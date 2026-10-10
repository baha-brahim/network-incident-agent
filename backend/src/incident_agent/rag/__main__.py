"""CLI: python -m incident_agent.rag {ingest,search,evaluate}."""

import argparse
import statistics
import time

from incident_agent.rag.search import DEFAULT_MODE, search_runbooks


def _cmd_ingest(_args: argparse.Namespace) -> None:
    from incident_agent.rag.embedder import get_embedder
    from incident_agent.rag.ingest import ingest

    embedder = get_embedder()
    report = ingest(embedder=embedder)
    print(f"docs: {report.n_docs}  chunks: {report.n_chunks}")
    print(f"ingested: {len(report.ingested)}  skipped (unchanged): {len(report.skipped)}", end="")
    print(f"  removed: {len(report.removed)}")
    if embedder.load_seconds is not None:
        print(f"model load: {embedder.load_seconds:.1f}s")
    print(f"embedding: {report.embed_seconds:.1f}s  total: {report.total_seconds:.1f}s")
    if report.token_counts:
        t = sorted(report.token_counts)
        q = statistics.quantiles(t, n=10) if len(t) > 1 else t
        print(
            f"chunk tokens (this run, n={len(t)}): min {t[0]}  median {statistics.median(t):.0f}"
            f"  p90 {q[-1]:.0f}  max {t[-1]}"
        )


def _cmd_search(args: argparse.Namespace) -> None:
    t0 = time.perf_counter()
    hits = search_runbooks(args.query, k=args.k, mode=args.mode)
    elapsed = time.perf_counter() - t0
    for rank, hit in enumerate(hits, start=1):
        snippet = " ".join(hit.content.split())[:160]
        print(f"{rank}. {hit.chunk_id}  score={hit.score:.4f}  [{hit.heading_path}]")
        print(f"   {snippet}...")
    print(f"({len(hits)} hits, mode={args.mode}, {elapsed:.2f}s incl. model load)")


def _cmd_evaluate(_args: argparse.Namespace) -> None:
    from incident_agent.rag.evaluate import METRIC_NAMES, RESULTS_DIR, run

    results = run()
    print(f"{results['n_queries']} queries, {results['n_chunks']} chunks")
    print(f"{'mode':9s} " + " ".join(f"{m:>9s}" for m in METRIC_NAMES))
    for mode, data in results["modes"].items():
        print(f"{mode:9s} " + " ".join(f"{data['overall'][m]:9.3f}" for m in METRIC_NAMES))
    print(f"written to {RESULTS_DIR}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m incident_agent.rag")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest", help="chunk, embed and store the runbooks").set_defaults(
        func=_cmd_ingest
    )
    s = sub.add_parser("search", help="search the stored runbooks")
    s.add_argument("query")
    s.add_argument("--mode", choices=["hybrid", "vector", "keyword"], default=DEFAULT_MODE)
    s.add_argument("-k", type=int, default=5)
    s.set_defaults(func=_cmd_search)
    sub.add_parser("evaluate", help="score the search modes on the labelled queries").set_defaults(
        func=_cmd_evaluate
    )
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
