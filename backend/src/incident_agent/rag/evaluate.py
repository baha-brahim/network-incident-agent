"""Retrieval evaluation: recall@k, MRR and nDCG of each search mode against labelled queries.

Queries live in `evals/retrieval/queries.yaml`. Relevance is labelled per section id. A search
returns chunks; the ranking is reduced to sections (first occurrence wins) before scoring.
The tables are written between markers in `docs/results/retrieval.md`, so the prose around
them can be edited by hand and survives a re-run.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

import yaml
from sqlalchemy import Engine, text

from incident_agent.config import REPO_ROOT
from incident_agent.db.session import get_engine
from incident_agent.rag.embedder import Embedder, FastEmbedEmbedder, get_embedder
from incident_agent.rag.metrics import (
    dedupe_sections,
    mean_metrics,
    paired_bootstrap,
    query_metrics,
)
from incident_agent.rag.search import SearchMode, search_runbooks

QUERIES_PATH = REPO_ROOT / "evals" / "retrieval" / "queries.yaml"
RESULTS_DIR = REPO_ROOT / "docs" / "results"
DEPTH = 20  # chunks retrieved per query before reducing to sections
MODES: tuple[SearchMode, ...] = get_args(SearchMode)
METRIC_NAMES = ["hit@1", "hit@3", "hit@5", "recall@1", "recall@3", "recall@5", "mrr@10", "ndcg@5"]
BEGIN, END = "<!-- BEGIN GENERATED TABLES -->", "<!-- END GENERATED TABLES -->"


@dataclass(frozen=True)
class EvalQuery:
    id: str
    type: str
    query: str
    relevant: frozenset[str]


def load_queries(path: Path = QUERIES_PATH) -> list[EvalQuery]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    queries: list[EvalQuery] = []
    for item in raw["queries"]:
        relevant = item["relevant"]
        if not relevant:
            raise ValueError(f"query {item.get('id')}: no relevant sections")
        queries.append(EvalQuery(item["id"], item["type"], item["query"], frozenset(relevant)))
    ids = [q.id for q in queries]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate query ids")
    return queries


def evaluate(
    queries: list[EvalQuery],
    engine: Engine | None = None,
    embedder: Embedder | None = None,
) -> dict[str, Any]:
    engine = engine or get_engine()
    embedder = embedder or get_embedder()
    with engine.connect() as conn:
        n_chunks = conn.execute(text("SELECT count(*) FROM runbook_chunks")).scalar_one()
        n_sections = conn.execute(
            text("SELECT count(DISTINCT section_id) FROM runbook_chunks")
        ).scalar_one()
    if n_chunks == 0:
        raise RuntimeError(
            "no runbook chunks in the database; run `python -m incident_agent.rag ingest`"
        )

    # Load the model before timing any query.
    embedder.embed_query("warm up")
    results: dict[str, Any] = {
        "n_queries": len(queries),
        "n_chunks": n_chunks,
        "n_sections": n_sections,
        "depth": DEPTH,
        "embedder": embedder.name,
        "model_load_seconds": getattr(embedder, "load_seconds", None),
        "recall_ceiling": {
            f"recall@{k}": sum(min(k, len(q.relevant)) / len(q.relevant) for q in queries)
            / len(queries)
            for k in (1, 3, 5)
        },
        "modes": {},
    }
    for mode in MODES:
        per_query: list[dict[str, Any]] = []
        elapsed = 0.0
        for q in queries:
            t0 = time.perf_counter()
            hits = search_runbooks(q.query, k=DEPTH, mode=mode, engine=engine, embedder=embedder)
            elapsed += time.perf_counter() - t0
            ranked = dedupe_sections([h.section_id for h in hits])
            metrics = query_metrics(ranked, set(q.relevant))
            per_query.append({"id": q.id, "type": q.type, "metrics": metrics, "top5": ranked[:5]})
        by_type: dict[str, Any] = {}
        for qtype in sorted({q.type for q in queries}):
            rows = [p["metrics"] for p in per_query if p["type"] == qtype]
            by_type[qtype] = {"n": len(rows), **mean_metrics(rows)}
        results["modes"][mode] = {
            "overall": mean_metrics([p["metrics"] for p in per_query]),
            "by_type": by_type,
            "mean_query_ms": 1000 * elapsed / len(queries),
            "queries": per_query,
        }
    results["comparisons"] = _comparisons(results)
    return results


def _comparisons(results: dict[str, Any]) -> dict[str, Any]:
    """Is hybrid really better? Paired differences per query, with a bootstrap interval."""
    out: dict[str, Any] = {}
    hybrid = results["modes"]["hybrid"]["queries"]
    for other in ("vector", "keyword"):
        rival = results["modes"][other]["queries"]
        for metric in ("hit@5", "mrr@10", "recall@5"):
            diffs = [
                h["metrics"][metric] - r["metrics"][metric]
                for h, r in zip(hybrid, rival, strict=True)
            ]
            mean, lo, hi = paired_bootstrap(diffs)
            out[f"hybrid-{other}:{metric}"] = {"mean": mean, "low": lo, "high": hi}
    return out


def _row(label: str, values: dict[str, float], n: int | None = None) -> str:
    cells = " | ".join(f"{values[m]:.3f}" for m in METRIC_NAMES)
    prefix = f"| {label} | {n} | " if n is not None else f"| {label} | "
    return prefix + cells + " |"


def render_tables(results: dict[str, Any], queries: list[EvalQuery]) -> str:
    header = " | ".join(METRIC_NAMES)
    rule = "|".join("---:" for _ in METRIC_NAMES)
    lines = [
        f"{results['n_queries']} queries over {results['n_sections']} sections "
        f"({results['n_chunks']} chunks). Embedder: `{results['embedder']}`.",
        "",
        "### Overall",
        "",
        f"| mode | {header} | ms/query |",
        f"|---|{rule}|---:|",
    ]
    for mode, data in results["modes"].items():
        lines.append(_row(mode, data["overall"])[:-1] + f"| {data['mean_query_ms']:.0f} |")
    ceiling = results["recall_ceiling"]
    lines += [
        "",
        "Queries with several relevant sections cannot reach recall 1.0 at small k. "
        f"Best possible recall@1 is {ceiling['recall@1']:.3f}, "
        f"recall@3 is {ceiling['recall@3']:.3f}, recall@5 is {ceiling['recall@5']:.3f}.",
    ]
    types = sorted({q.type for q in queries})
    counts = {t: sum(1 for q in queries if q.type == t) for t in types}
    for metric in ("hit@5", "recall@5", "mrr@10"):
        lines += [
            "",
            f"### {metric} by query type",
            "",
            "| type | n | " + " | ".join(results["modes"]) + " |",
            "|---|---:|" + "|".join("---:" for _ in results["modes"]) + "|",
        ]
        for t in types:
            vals = " | ".join(f"{d['by_type'][t][metric]:.3f}" for d in results["modes"].values())
            lines.append(f"| {t} | {counts[t]} | {vals} |")
    lines += ["", "### Full metrics by query type", ""]
    for mode, data in results["modes"].items():
        lines += [
            f"**{mode}**",
            "",
            f"| type | n | {header} |",
            f"|---|---:|{rule}|",
        ]
        for t in types:
            lines.append(_row(t, data["by_type"][t], data["by_type"][t]["n"]))
        lines.append("")
    lines += ["### Hybrid minus the other modes, per query", ""]
    lines += ["| comparison | mean difference | 95% interval |", "|---|---:|---|"]
    for name, c in results["comparisons"].items():
        lines.append(f"| {name} | {c['mean']:+.3f} | {c['low']:+.3f} to {c['high']:+.3f} |")
    lines.append("")
    by_id = {q.id: q for q in queries}
    for mode in ("hybrid",):
        missed = [p for p in results["modes"][mode]["queries"] if p["metrics"]["hit@5"] == 0.0]
        lines += [f"### Misses at k=5 ({mode}): {len(missed)} of {results['n_queries']}", ""]
        for p in missed:
            q = by_id[p["id"]]
            lines.append(
                f'- `{q.id}` ({q.type}): "{q.query}" wanted {sorted(q.relevant)}, '
                f"got {p['top5'][:3]}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_results(results: dict[str, Any], queries: list[EvalQuery], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "retrieval.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    block = f"{BEGIN}\n{render_tables(results, queries)}{END}"
    md = out_dir / "retrieval.md"
    if md.exists() and BEGIN in (old := md.read_text(encoding="utf-8")) and END in old:
        head, rest = old.split(BEGIN, 1)
        tail = rest.split(END, 1)[1]
        md.write_text(head + block + tail, encoding="utf-8")
    else:
        md.write_text(f"# Runbook retrieval evaluation\n\n{block}\n", encoding="utf-8")


def run(out_dir: Path = RESULTS_DIR, queries_path: Path = QUERIES_PATH) -> dict[str, Any]:
    queries = load_queries(queries_path)
    embedder = FastEmbedEmbedder()
    results = evaluate(queries, embedder=embedder)
    write_results(results, queries, out_dir)
    return results
