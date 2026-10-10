"""Ranking metrics for the retrieval evaluation. Pure functions, no database."""

import math
import random


def dedupe_sections(section_ids: list[str]) -> list[str]:
    """Keep the first occurrence of each section. Relevance is labelled per section, so a second
    chunk of an already-seen section adds no information to the ranking."""
    return list(dict.fromkeys(section_ids))


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Share of the relevant sections that appear in the top k."""
    if not relevant:
        raise ValueError("a query needs at least one relevant section")
    return len(relevant & set(ranked[:k])) / len(relevant)


def hit_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """1.0 if at least one relevant section is in the top k, else 0.0 (success@k)."""
    return 1.0 if relevant & set(ranked[:k]) else 0.0


def first_relevant_rank(ranked: list[str], relevant: set[str]) -> int | None:
    """1-based rank of the first relevant section, or None."""
    for i, item in enumerate(ranked, start=1):
        if item in relevant:
            return i
    return None


def reciprocal_rank(ranked: list[str], relevant: set[str], k: int = 10) -> float:
    """1 / rank of the first relevant section within the top k, else 0."""
    rank = first_relevant_rank(ranked[:k], relevant)
    return 0.0 if rank is None else 1.0 / rank


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Binary-gain nDCG: DCG of the ranking divided by the DCG of a perfect one."""
    dcg = sum(
        1.0 / math.log2(i + 1) for i, item in enumerate(ranked[:k], start=1) if item in relevant
    )
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def query_metrics(ranked: list[str], relevant: set[str]) -> dict[str, float]:
    return {
        "hit@1": hit_at_k(ranked, relevant, 1),
        "hit@3": hit_at_k(ranked, relevant, 3),
        "hit@5": hit_at_k(ranked, relevant, 5),
        "recall@1": recall_at_k(ranked, relevant, 1),
        "recall@3": recall_at_k(ranked, relevant, 3),
        "recall@5": recall_at_k(ranked, relevant, 5),
        "mrr@10": reciprocal_rank(ranked, relevant, 10),
        "ndcg@5": ndcg_at_k(ranked, relevant, 5),
    }


def mean_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    return {name: sum(r[name] for r in rows) / len(rows) for name in rows[0]}


def paired_bootstrap(
    diffs: list[float], resamples: int = 2000, seed: int = 0
) -> tuple[float, float, float]:
    """Mean of per-query differences with a 95% bootstrap interval (seeded, so repeatable)."""
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(resamples))
    return sum(diffs) / n, means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]
