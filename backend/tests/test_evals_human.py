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
from incident_agent.evals.human_labels import GLOSSARY, describe_call
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


def test_a_smaller_sample_is_a_subset_of_a_larger_one() -> None:
    cases = make_cases(dict.fromkeys("abcdefghij", (4, 2)))
    small = {a.case.case_id for a in human.select_cases(cases, 10, seed=0)}
    large = {a.case.case_id for a in human.select_cases(cases, 20, seed=0)}
    assert len(small) == 10 and small < large


def test_the_default_pack_has_ten_reports() -> None:
    import argparse

    from incident_agent.evals import cli_grading

    parser = argparse.ArgumentParser()
    cli_grading.add_commands(parser.add_subparsers())
    assert parser.parse_args(["human-pack", "--run", "x"]).n == 10


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


def test_every_box_has_a_plain_header_and_a_type() -> None:
    [report] = human.build_pack([make_artifact()])["reports"]
    boxes = {e["ref"]: e for item in report["items"] for e in item["evidence"]}
    assert boxes["T1"]["type"] == "call" and boxes["T1"]["tool"] == "get_alarms"
    assert boxes["T1"]["label"].startswith("Alarms on S-TUN-012")
    assert boxes["ALM-000472"]["type"] == "alarm"
    assert boxes["ALM-000472"]["label"] == "One alarm: ALM-000472"
    assert boxes["S-TUN-012"]["label"] == "One network node: S-TUN-012"
    assert "tool" not in boxes["ALM-000472"]


def test_a_missing_reference_is_labelled_as_such() -> None:
    report = make_report([Finding(claim="X.", basis="observed", refs=["ALM-999999"])])
    [view] = human.build_pack([make_artifact(result=make_result(report))])["reports"]
    box = view["items"][1]["evidence"][0]
    assert box["type"] == "missing" and box["label"].startswith("Not among the report's evidence")


def test_every_verdict_has_a_plain_paraphrase_beside_the_graders_wording() -> None:
    verdicts = human.build_pack([make_artifact()])["rubric"]["verdicts"]
    assert [v["key"] for v in verdicts] == list(VERDICT_DEFINITIONS)
    assert all(v["plain"] and v["plain"] != v["definition"] for v in verdicts)


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
            for k, v in value.items():
                if k != "args":  # the arguments of a tool call: free-form names of the tool
                    walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(data["reports"])
    assert not keys & {"verdict", "reason", "grader", "truth", "kind", "difficulty", "correct"}
    assert keys <= {"case_id", "question", "title", "chips", "summary", "items", "index", "basis",
                    "claim", "evidence", "ref", "text", "shortened", "found", "type", "tool",
                    "args", "label"}  # fmt: skip


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


# --- plain-English headers and glossary ----------------------------------------------------


def test_call_headers_say_what_was_asked() -> None:
    alarms = describe_call(
        "get_alarms",
        {
            "start": "2026-09-21 15:00",
            "end": "2026-09-21 19:00",
            "node_ids": ["S-TUN-012", "S-TUN-014", "S-TUN-015"],
            "include_descendants": True,
        },
    )
    assert alarms == (
        "Alarms on S-TUN-012, S-TUN-014, S-TUN-015 and nodes below them, 21 Sep 15:00 to 19:00"
    )
    kpis = describe_call(
        "query_kpis",
        {
            "entity_type": "site",
            "entity_ids": ["S-SUD-006"],
            "metrics": ["availability_pct", "dl_volume_mb"],
            "start": "2026-09-30 12:00",
            "end": "2026-09-30 17:00",
        },
    )
    assert kpis == (
        "KPI measurements for site S-SUD-006 (availability, downlink traffic volume), "
        "30 Sep 12:00 to 17:00"
    )
    changes = describe_call(
        "get_changes",
        {"node_ids": ["AGG-TUN-02"], "start": "2026-09-29 18:00", "end": "2026-09-30 09:59"},
    )
    assert changes == "Changes on AGG-TUN-02, 29 Sep 18:00 to 30 Sep 09:59"
    assert describe_call("search_runbooks", {"query": "bad change", "k": 4}) == (
        "Runbook excerpts for the query 'bad change'"
    )
    assert describe_call("get_maintenance", {"region_id": "TUN", "start": "x", "end": "y"}) == (
        "Maintenance calendar for region TUN, x to y"
    )
    assert describe_call("get_anomalies", {"entity_id": "S-TUN-004", "start": "2026-09-29 16:00",
                                           "end": "2026-09-29 20:00"}).startswith(
        "Detector alerts in S-TUN-004"
    )  # fmt: skip
    assert describe_call("get_topology", {"node_id": "S-TUN-004", "include": "all"}).startswith(
        "Network map around S-TUN-004"
    )
    assert describe_call("something_new", {}) == "Something new"


def test_long_node_lists_are_shortened_in_the_header() -> None:
    ids = [f"S-TUN-{n:03d}" for n in range(1, 8)]
    text = describe_call("get_changes", {"node_ids": ids, "start": "2026-09-29 18:00",
                                         "end": "2026-09-29 19:00"})  # fmt: skip
    assert "S-TUN-004 and 3 more" in text and "S-TUN-005" not in text


def test_the_glossary_covers_every_alarm_type_of_the_network() -> None:
    from incident_agent.config import REPO_ROOT
    from incident_agent.simulator.noise import _ALARM_KINDS

    reference = (REPO_ROOT / "runbooks" / "RB-ALARM-REFERENCE.md").read_text(encoding="utf-8")
    types = set(re.findall(r"\*\*`([A-Z_]+)`", reference)) | {k[0] for k in _ALARM_KINDS}
    assert len(types) >= 14
    assert types <= {term for term, *_ in GLOSSARY}


def test_the_glossary_defines_the_prefixes_the_evidence_uses() -> None:
    terms = {term for term, *_ in GLOSSARY}
    for needed in ("S-", "LNK-", "AGG-", "CORE-", "T", "ALM", "CHG", "MW", "EVT", "ALR", "ANM",
                   "RB", "baseline", "onset", "active", "cleared", "z-score", "availability",
                   "dl volume", "RRC success", "drop rate", "latency",
                   "PRB utilisation"):  # fmt: skip
        assert needed in terms
    for regexes in (m for *_, m in GLOSSARY):
        for source in regexes:
            re.compile(source)


def test_the_pack_carries_the_glossary() -> None:
    pack = human.build_pack([make_artifact()])
    assert [g["term"] for g in pack["glossary"]] == [term for term, *_ in GLOSSARY]
    assert all(g["text"] for g in pack["glossary"])
