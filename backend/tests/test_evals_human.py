"""The human grading page: sampling, content, the rubric, isolation from verdicts and truth."""

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from incident_agent.agent.report import Finding
from incident_agent.evals import human
from incident_agent.evals.grader import (
    RULES,
    VERDICT_DEFINITIONS,
    build_items,
    evidence_text,
)
from incident_agent.evals.human_template import PAGE
from incident_agent.evals.types import ReportGrade
from tests.grading_support import (
    TRUTH_KIND,
    TRUTH_NOTES,
    make_artifact,
    make_report,
    make_result,
    make_truth,
)

# --- sampling ------------------------------------------------------------------------------


def make_cases(spec: dict[str, tuple[int, int]]) -> list:
    """kind -> (right, wrong) counts. A wrong report names the wrong category."""
    out = []
    for kind, (right, wrong) in spec.items():
        for n in range(right + wrong):
            ok = n < right
            report = make_report(
                root_cause_category="transport_failure" if ok else "power_failure",
                classification="incident",
            )
            truth = make_truth(kind=kind, root_cause_category="transport_failure")
            out.append(
                make_artifact(f"s42-{kind}-{n:02d}-q0", result=make_result(report), truth=truth)
            )
    return out


def test_selection_spreads_over_kinds_and_mixes_right_and_wrong() -> None:
    cases = make_cases({"fiber": (6, 2), "power": (6, 2), "dns": (6, 2), "event": (6, 2)})
    chosen = human.select_cases(cases, 8, seed=1)
    assert len(chosen) == 8
    kinds = [a.truth.kind for a in chosen]
    assert {k: kinds.count(k) for k in set(kinds)} == {"fiber": 2, "power": 2, "dns": 2, "event": 2}
    assert sum(human.is_correct(a) for a in chosen) == 4  # incorrect first within each kind


def test_selection_is_deterministic_and_depends_on_the_seed() -> None:
    cases = make_cases({"a": (5, 3), "b": (5, 3)})
    ids = lambda seed: [a.case.case_id for a in human.select_cases(cases, 6, seed)]  # noqa: E731
    assert ids(0) == ids(0)
    assert ids(0) != ids(1)
    assert ids(0) == [a.case.case_id for a in human.select_cases(list(reversed(cases)), 6, 0)]


def test_selection_does_not_group_by_kind() -> None:
    cases = make_cases({"a": (4, 0), "b": (4, 0), "c": (4, 0)})
    kinds = [a.truth.kind for a in human.select_cases(cases, 12, seed=3)]
    assert kinds != sorted(kinds)


def test_selection_takes_what_exists_when_asked_for_more() -> None:
    cases = make_cases({"a": (1, 0), "b": (2, 1)})
    assert len(human.select_cases(cases, 20)) == 4


def test_selection_skips_crashed_cases() -> None:
    good = make_artifact("s42-X-q0")
    crashed = make_artifact("s42-Y-q0", error="quota")
    assert [a.case.case_id for a in human.select_cases([good, crashed], 5)] == ["s42-X-q0"]


def test_a_red_herring_is_right_when_it_is_named_as_such() -> None:
    truth = make_truth(is_incident=False, root_cause_category="planned_maintenance")
    report = make_report(classification="planned_maintenance",
                         root_cause_category="planned_maintenance")  # fmt: skip
    assert human.is_correct(make_artifact(result=make_result(report), truth=truth))
    wrong = make_report(classification="incident", root_cause_category="transport_failure")
    assert not human.is_correct(make_artifact(result=make_result(wrong), truth=truth))


# --- pack content --------------------------------------------------------------------------


def test_the_pack_has_every_item_with_the_evidence_the_grader_reads() -> None:
    artifact = make_artifact()
    pack = human.build_pack([artifact])
    [report] = pack["reports"]
    assert artifact.result is not None
    items = build_items(artifact.result.report)
    assert [i["index"] for i in report["items"]] == [i.index for i in items]
    assert [i["claim"] for i in report["items"]] == [i.claim for i in items]
    for shown, item in zip(report["items"], items, strict=True):
        assert [e["ref"] for e in shown["evidence"]] == list(item.refs)
    first = report["items"][1]["evidence"][0]
    assert first["text"] == evidence_text("T1", artifact.result).text
    assert report["question"] == artifact.case.question


def test_a_large_report_keeps_all_its_items_in_the_pack() -> None:
    findings = [
        Finding(claim=f"Claim {n}.", basis="observed", refs=["T1", "T2"]) for n in range(40)
    ]
    artifact = make_artifact(result=make_result(make_report(findings)))
    [report] = human.build_pack([artifact])["reports"]
    assert len(report["items"]) == 41


def test_the_pack_id_follows_the_content() -> None:
    a, b = make_artifact("s42-A-q0"), make_artifact("s42-B-q0")
    assert human.build_pack([a])["pack_id"] == human.build_pack([a])["pack_id"]
    assert human.build_pack([a])["pack_id"] != human.build_pack([b])["pack_id"]


# --- the page ------------------------------------------------------------------------------


class Scripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str | None]] = []
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self._in = False
        self.bodies: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))
        if tag == "script":
            self.scripts.append(dict(attrs))
            self._in = True
            self.bodies.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in = False

    def handle_data(self, data: str) -> None:
        if self._in:
            self.bodies[-1] += data


def parse(page: str) -> Scripts:
    parser = Scripts()
    parser.feed(page)
    return parser


def test_the_page_makes_no_requests_and_loads_nothing() -> None:
    page = human.render_page(human.build_pack([make_artifact()]))
    parsed = parse(page)
    for tag, attrs in parsed.tags:
        assert tag not in {"link", "img", "iframe", "audio", "video", "embed", "object", "form"}
        assert "src" not in attrs, f"<{tag}> loads {attrs.get('src')}"
        assert "href" not in attrs
    for forbidden in ("http://", "https://", "fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon",
                      "import(", "importScripts", "@import", "url("):  # fmt: skip
        assert forbidden not in page, forbidden


def test_the_page_has_exactly_two_inline_scripts_one_of_them_data() -> None:
    parsed = parse(human.render_page(human.build_pack([make_artifact()])))
    assert [s.get("type") for s in parsed.scripts] == ["application/json", None]
    assert all("src" not in s for s in parsed.scripts)


def test_the_embedded_data_is_the_pack() -> None:
    artifact = make_artifact()
    pack = human.build_pack([artifact])
    parsed = parse(human.render_page(pack))
    assert json.loads(parsed.bodies[0]) == pack


def test_text_that_looks_like_markup_cannot_break_out_of_the_data() -> None:
    nasty = "</script><script>alert(1)</script><!-- & <b>"
    report = make_report([Finding(claim=nasty, basis="observed", refs=["T2"])])
    artifact = make_artifact(result=make_result(report))
    pack = human.build_pack([artifact])
    page = human.render_page(pack)
    parsed = parse(page)
    assert len(parsed.scripts) == 2  # no extra script was opened
    assert json.loads(parsed.bodies[0]) == pack  # and the text survives intact
    assert nasty in json.dumps(pack)


def test_the_page_defines_the_verdicts_in_the_graders_words() -> None:
    page = human.render_page(human.build_pack([make_artifact()]))
    data = json.loads(parse(page).bodies[0])
    shown = {v["key"]: v["definition"] for v in data["rubric"]["verdicts"]}
    assert shown == VERDICT_DEFINITIONS
    assert data["rubric"]["rules"] == list(RULES)
    from incident_agent.evals.grader import SYSTEM_PROMPT

    for text in [*shown.values(), *RULES]:
        assert text in SYSTEM_PROMPT


def test_the_page_follows_the_system_theme() -> None:
    assert "prefers-color-scheme: dark" in PAGE
    assert "color-scheme: light dark" in PAGE
    assert 'name="viewport"' in PAGE


def test_the_page_has_the_controls_a_grader_needs() -> None:
    for needle in (
        "localStorage",
        "ArrowRight",
        "ArrowDown",
        "human_grades.json",
        "FileReader",
        "createObjectURL",
        "radiogroup",
    ):
        assert needle in PAGE


def test_the_page_holds_no_grader_verdicts_and_no_truth() -> None:
    artifact = make_artifact()
    page = human.render_page(human.build_pack([artifact]))
    assert TRUTH_NOTES not in page and TRUTH_KIND not in page
    data = json.loads(parse(page).bodies[0])
    # the data has no key that could carry a verdict, a reason or a truth field
    keys: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            keys.update(value)
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(data["reports"])
    assert not keys & {"verdict", "reason", "grader", "truth", "kind", "difficulty", "correct"}
    assert keys <= {"case_id", "question", "title", "chips", "summary", "items", "index", "basis",
                    "claim", "evidence", "ref", "text", "shortened", "found"}  # fmt: skip


def test_build_pack_takes_no_grades_so_none_can_leak() -> None:
    import inspect

    params = inspect.signature(human.build_pack).parameters
    assert set(params) == {"artifacts", "title"}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_script_is_valid_javascript(tmp_path: Path) -> None:
    parsed = parse(human.render_page(human.build_pack([make_artifact()])))
    script = tmp_path / "page.js"
    script.write_text(parsed.bodies[1], encoding="utf-8")
    done = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


# --- files ---------------------------------------------------------------------------------


def test_write_pack_writes_the_page_and_the_data(tmp_path: Path) -> None:
    pack = human.build_pack([make_artifact()])
    page, items = human.write_pack(pack, tmp_path / "out")
    assert page.name == "grading.html" and items.name == "items.json"
    assert json.loads(items.read_text(encoding="utf-8")) == pack
    assert b"\r\n" not in page.read_bytes()
    assert re.search(r"<title>Report grading</title>", page.read_text(encoding="utf-8"))


def test_exported_grades_load_as_report_grades(tmp_path: Path) -> None:
    exported = [
        {"case_id": "s42-X-q0", "grader": "human:Sam",
         "findings": [{"index": -1, "verdict": "supported", "reason": ""},
                      {"index": 0, "verdict": "unsupported", "reason": "wrong node"}],
         "comments": "note", "extra": {"complete": True, "pack_id": "abc"}},
    ]  # fmt: skip
    path = tmp_path / "human_grades.json"
    path.write_text(json.dumps(exported), encoding="utf-8")
    [grade] = human.read_human_grades(path)
    assert isinstance(grade, ReportGrade) and grade.grader == "human:Sam"
    assert [f.verdict for f in grade.findings] == ["supported", "unsupported"]
