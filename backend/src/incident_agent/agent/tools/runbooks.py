"""search_runbooks: hybrid search over the runbooks, with excerpts that fit the budget."""

import re

from pydantic import Field

from incident_agent.agent.tools.common import BODY_CHARS, error_result, hard_cap, trim
from incident_agent.agent.tools.schema import ToolArgs
from incident_agent.agent.types import EvidenceRef, ToolContext, ToolResult
from incident_agent.rag.search import RunbookHit, search_runbooks

MAX_K = 6
_WORD = re.compile(r"[a-z0-9_]{3,}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "not", "but",
    "has", "have", "its", "into", "than", "then", "when", "what", "why", "how", "does", "did",
}  # fmt: skip


class SearchRunbooksArgs(ToolArgs):
    query: str = Field(
        min_length=2,
        max_length=300,
        description="What to look up: symptoms, alarm names, a suspected cause, a diagnostic step.",
    )
    k: int = Field(default=4, ge=1, le=MAX_K, description="Number of chunks, at most 6.")


def _terms(query: str) -> set[str]:
    return {w for w in _WORD.findall(query.lower()) if w not in _STOP}


def excerpt(content: str, query: str, limit: int) -> tuple[str, bool]:
    """The sentences of `content` that best match `query`, in original order, within `limit`.

    Returns the text and whether anything was left out.
    """
    flat = content.strip()
    if len(flat) <= limit:
        return " ".join(flat.split()), False
    flat = flat.replace("**", "")
    parts = [p.strip(" -*#>") for p in _SENTENCE.split(flat) if p and p.strip(" -*#>")]
    terms = _terms(query)

    def score(i: int, part: str) -> tuple[float, int]:
        words = set(_WORD.findall(part.lower()))
        hit = len(words & terms) / (1 + 0.02 * len(words))
        return (hit + (0.5 if i == 0 else 0.0), -i)

    ranked = sorted(range(len(parts)), key=lambda i: score(i, parts[i]), reverse=True)
    chosen: list[int] = []
    used = 0
    for i in ranked:
        cost = len(parts[i]) + 1
        if used + cost > limit and chosen:
            continue
        if used + cost > limit:
            chosen.append(i)
            used = limit
            break
        chosen.append(i)
        used += cost
    chosen.sort()
    out: list[str] = []
    prev = -1
    for i in chosen:
        if i != prev + 1:
            out.append("...")
        out.append(parts[i])
        prev = i
    if chosen and chosen[-1] != len(parts) - 1:
        out.append("...")
    text_ = " ".join(out)
    return (text_ if len(text_) <= limit + 8 else trim(text_, limit)), True


def search_runbooks_tool(ctx: ToolContext, args: SearchRunbooksArgs) -> ToolResult:
    query = args.query.strip()
    try:
        hits: list[RunbookHit] = search_runbooks(
            query, k=args.k, mode="hybrid", engine=ctx.engine, embedder=ctx.embedder
        )
    except Exception as exc:  # embedding model missing, database error: let the model react
        return error_result(
            "search_runbooks", args, f"Runbook search failed: {trim(str(exc), 200)}"
        )
    if not hits:
        body = f"No runbook chunk matches {query!r}. Try the alarm name or a plainer description."
        return ToolResult(
            tool="search_runbooks",
            args=args.model_dump(),
            headline=body[:200],
            body=body,
            data={"hits": []},
        )

    lead = f"{len(hits)} runbook chunk(s) for {trim(query, 80)!r}, best first (excerpts):"
    overhead = sum(len(h.chunk_id) + len(h.heading_path) + 12 for h in hits)
    per_chunk = max(150, (BODY_CHARS - 60 - len(lead) - overhead) // len(hits))
    lines = [lead]
    refs: list[EvidenceRef] = []
    cut = False
    for h in hits:
        text_, was_cut = excerpt(h.content, query, per_chunk)
        cut = cut or was_cut
        lines.append(f"[{h.chunk_id}] {h.heading_path}: {text_}")
        refs.append(
            EvidenceRef(
                ref=h.chunk_id,
                kind="runbook",
                summary=trim(f"{h.heading_path}: {h.content}", 160),
            )
        )
    if cut:
        lines.append("Excerpts are cut; search again with a narrower query for the rest.")
    return ToolResult(
        tool="search_runbooks",
        args=args.model_dump(),
        headline=lead[:200],
        body=hard_cap("\n".join(lines)),
        refs=refs,
        data={
            "hits": [
                {"chunk_id": h.chunk_id, "heading_path": h.heading_path, "score": h.score}
                for h in hits
            ]
        },
        truncated=cut,
    )
