"""Runbook parsing and heading-aware chunking.

A runbook is a markdown file with YAML front matter. Each `##` section is one retrieval unit
(its `section_id`). Sections longer than `max_tokens` are split at `###` headings, then at
paragraph boundaries; every piece keeps the section's id. Sections shorter than `min_tokens` are
folded into a neighbour.

Token counts are a cheap proxy (words and punctuation marks), not the model's tokenizer. Word
pieces make the real count a little higher, and the model's limit is 512, so the default target
of 300 leaves ample room.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Bump when chunking changes, so ingest re-embeds documents that would be chunked differently.
CHUNKER_VERSION = "2"
MAX_TOKENS = 300
MIN_TOKENS = 25

_DOC_ID = re.compile(r"^RB-[A-Z0-9]+(-[A-Z0-9]+)*$")
_TOKEN = re.compile(r"\w+|[^\w\s]")
_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$")


@dataclass(frozen=True)
class Runbook:
    doc_id: str
    title: str
    tags: list[str]
    categories: list[str]
    body: str
    path: str  # repo-relative, forward slashes
    text: str  # the whole file, front matter included (used for the content hash)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    ordinal: int
    section_id: str
    heading_path: str
    content: str
    n_tokens: int

    @property
    def embed_text(self) -> str:
        return f"{self.heading_path}\n{self.content}"


def count_tokens(text: str) -> int:
    return len(_TOKEN.findall(text))


def slugify(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def _string_list(meta: dict[str, Any], key: str, where: str) -> list[str]:
    value = meta.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{where}: front matter '{key}' must be a list of strings")
    return list(value)


def parse_runbook(text: str, path: str) -> Runbook:
    """Split front matter from the body and validate it."""
    parts = text.split("---", 2)
    if len(parts) < 3 or parts[0].strip():
        raise ValueError(f"{path}: missing YAML front matter")
    meta = yaml.safe_load(parts[1])
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: front matter is not a mapping")
    doc_id, title = meta.get("id"), meta.get("title")
    if not isinstance(doc_id, str) or not _DOC_ID.match(doc_id):
        raise ValueError(f"{path}: front matter 'id' must look like RB-FIBER-CUT")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"{path}: front matter 'title' is required")
    return Runbook(
        doc_id=doc_id,
        title=title.strip(),
        tags=_string_list(meta, "tags", path),
        categories=_string_list(meta, "categories", path),
        body=parts[2].strip("\n"),
        path=path,
        text=text,
    )


def load_runbooks(directory: Path, repo_root: Path) -> list[Runbook]:
    runbooks: list[Runbook] = []
    for file in sorted(directory.glob("*.md")):
        resolved = file.resolve()
        rel = (
            resolved.relative_to(repo_root.resolve()).as_posix()
            if resolved.is_relative_to(repo_root.resolve())
            else resolved.as_posix()
        )
        runbooks.append(parse_runbook(file.read_text(encoding="utf-8"), rel))
    ids = [r.doc_id for r in runbooks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate runbook ids: {sorted(duplicates)}")
    return runbooks


@dataclass
class _Unit:
    """A piece of a section: its intro text, or one `###` subsection."""

    suffix: str | None  # the `###` heading, None for the intro
    text: str

    @property
    def tokens(self) -> int:
        return count_tokens(self.text)


@dataclass
class _Section:
    title: str
    slug: str
    units: list[_Unit]


def _split_sections(body: str) -> list[_Section]:
    """Group the body into `##` sections, each split into intro and `###` units."""
    sections: list[_Section] = []
    h3: str | None = None
    lines: list[str] = []
    in_code = False

    def flush_unit() -> None:
        text = "\n".join(lines).strip("\n")
        lines.clear()
        if not text.strip() or not sections:
            return
        sections[-1].units.append(_Unit(h3, text))

    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        m = None if in_code else _HEADING.match(line)
        if m is None:
            lines.append(line)
            continue
        level, heading = len(m.group(1)), m.group(2)
        if level == 1:
            continue
        flush_unit()
        if level == 2:
            sections.append(_Section(heading, slugify(heading), []))
            h3 = None
        else:
            h3 = heading
            lines.append(line)
    flush_unit()
    return [s for s in sections if s.units]


def _paragraphs(text: str) -> list[str]:
    """Blank-line separated blocks, keeping fenced code blocks whole."""
    blocks: list[str] = []
    current: list[str] = []
    in_code = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if not line.strip() and not in_code:
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _split_unit(unit: _Unit, max_tokens: int) -> list[_Unit]:
    """Cut an oversized unit at paragraph boundaries, falling back to single lines."""
    pieces: list[str] = []
    for block in _paragraphs(unit.text):
        if count_tokens(block) <= max_tokens:
            pieces.append(block)
        else:
            pieces.extend(block.split("\n"))
    out: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if current and count_tokens(candidate) > max_tokens:
            out.append(current)
            current = piece
        else:
            current = candidate
    if current:
        out.append(current)
    return [_Unit(unit.suffix, t) for t in out]


@dataclass
class _Draft:
    suffix: str | None
    text: str

    @property
    def tokens(self) -> int:
        return count_tokens(self.text)


def _pack_section(section: _Section, max_tokens: int, min_tokens: int) -> list[_Draft]:
    units: list[_Unit] = []
    for unit in section.units:
        units.extend(_split_unit(unit, max_tokens) if unit.tokens > max_tokens else [unit])
    drafts: list[_Draft] = []
    for unit in units:
        if drafts and drafts[-1].tokens + unit.tokens <= max_tokens:
            drafts[-1].text += "\n\n" + unit.text
            drafts[-1].suffix = None  # several subsections: the section heading is enough
        else:
            drafts.append(_Draft(unit.suffix, unit.text))
    # Fold small remainders into the previous piece of the same section.
    merged: list[_Draft] = []
    for draft in drafts:
        if merged and draft.tokens < min_tokens:
            merged[-1].text += "\n\n" + draft.text
        else:
            merged.append(draft)
    if len(merged) > 1 and merged[0].tokens < min_tokens:
        second = merged.pop(1)
        merged[0].text += "\n\n" + second.text
    return merged


def chunk_runbook(
    runbook: Runbook, max_tokens: int = MAX_TOKENS, min_tokens: int = MIN_TOKENS
) -> list[Chunk]:
    """Chunk one runbook. Chunk ids are `<doc id>#NN`, numbered from 1 in document order."""
    sections = _split_sections(runbook.body)
    slugs = [s.slug for s in sections]
    if len(set(slugs)) != len(slugs):
        raise ValueError(f"{runbook.doc_id}: duplicate section headings")

    entries: list[tuple[str, str, str]] = []  # (section_id, heading_path, content)
    for section in sections:
        section_id = f"{runbook.doc_id}/{section.slug}"
        base = f"{runbook.title} > {section.title}"
        drafts = _pack_section(section, max_tokens, min_tokens)
        if len(drafts) == 1 and drafts[0].tokens < min_tokens and entries:
            # A tiny section on its own: fold it into the previous chunk if that stays small.
            prev_id, prev_path, prev_text = entries[-1]
            folded = f"{prev_text}\n\n{section.title}\n{drafts[0].text}"
            if count_tokens(folded) <= max_tokens:
                entries[-1] = (prev_id, prev_path, folded)
                continue
        for draft in drafts:
            path = f"{base} > {draft.suffix}" if draft.suffix else base
            entries.append((section_id, path, draft.text))

    return [
        Chunk(
            chunk_id=f"{runbook.doc_id}#{i:02d}",
            doc_id=runbook.doc_id,
            ordinal=i,
            section_id=section_id,
            heading_path=path,
            content=content,
            n_tokens=count_tokens(f"{path}\n{content}"),
        )
        for i, (section_id, path, content) in enumerate(entries, start=1)
    ]


def section_ids(runbooks: list[Runbook]) -> set[str]:
    """Every section id the chunker produces, for validating the evaluation queries."""
    return {c.section_id for r in runbooks for c in chunk_runbook(r)}
