"""Alert-triggered investigations without a database: the question builder and the webhook."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from incident_agent.api.alert_runs import (
    AlertQuestion,
    VisibleAnomaly,
    alert_asked_at,
    question_text,
)
from incident_agent.api.app import create_app
from incident_agent.api.live import live_events
from incident_agent.api.schemas import AlertOut
from incident_agent.api.services import Services
from incident_agent.llm.testing import ScriptedRunner
from tests.api_support import DATASET_NOW, MemoryRunRepository, make_services

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ASKED = datetime.fromisoformat(DATASET_NOW)
NAMES = {"TUN": "Grand Tunis", "SFX": "Sfax", "SOU": "Sousse"}

# --- the question -------------------------------------------------------------------------------


def anomaly(
    entity: str, metric: str = "dl_volume_mb", direction: str = "drop", region: str | None = "TUN"
) -> VisibleAnomaly:
    kind = "core_node" if entity.startswith("CORE") else "region" if entity in NAMES else "site"
    return VisibleAnomaly(kind, entity, region, metric, direction)


def sites(*numbers: int, **kw: Any) -> list[VisibleAnomaly]:
    return [anomaly(f"S-TUN-{n:03d}", **kw) for n in numbers]


def ask(anomalies: list[VisibleAnomaly], **kw: Any) -> str:
    return question_text(
        "ALR-0019", datetime(2026, 9, 22, 13, 45, tzinfo=UTC), anomalies, NAMES, **kw
    )


def test_the_alert_is_asked_one_hour_after_it_starts_and_never_after_now() -> None:
    start = datetime(2026, 9, 22, 12, 45, tzinfo=UTC)
    now = datetime(2026, 9, 25, tzinfo=UTC)
    assert alert_asked_at(start, now) == datetime(2026, 9, 22, 13, 45, tzinfo=UTC)
    near = start + timedelta(minutes=20)
    assert alert_asked_at(start, near) == near  # an alert that just started: cut at now


def test_the_question_names_what_is_visible() -> None:
    anomalies = [
        *sites(4, 6, 9),
        *sites(4, 6, 9, metric="active_users"),
    ]
    assert ask(anomalies) == (
        "Detector alert ALR-0019 at 14:45: traffic and active users dropping at "
        "S-TUN-004, S-TUN-006 and S-TUN-009 (Grand Tunis). What is causing it?"
    )


def test_a_long_entity_list_is_cut_after_four() -> None:
    text = ask(sites(*range(1, 8)))
    assert "at S-TUN-001, S-TUN-002, S-TUN-003, S-TUN-004 and 3 more (Grand Tunis)." in text


def test_both_directions_regions_and_core_nodes() -> None:
    mixed = [*sites(1, 2), *sites(1, metric="latency_ms", direction="spike")]
    assert "traffic dropping and latency spiking at S-TUN-001 and S-TUN-002" in ask(mixed)
    two_regions = [anomaly("S-TUN-001"), anomaly("S-SFX-001", region="SFX")]
    assert "(Sfax and Grand Tunis)" in ask(two_regions)
    core = [anomaly("CORE-DNS-01", "query_success_pct", region=None)]
    assert ask(core).endswith("DNS query success dropping at CORE-DNS-01. What is causing it?")
    regional = [anomaly("TUN", "availability_pct", region="TUN")]
    assert ask(regional).endswith("availability dropping in Grand Tunis. What is causing it?")


def test_the_question_stays_between_8_and_300_characters() -> None:
    long_names = {
        f"R{i}": f"Region with a very long descriptive name number {i} " * 2 for i in range(6)
    }
    anomalies = [
        VisibleAnomaly("site", f"S-R{i}-001", f"R{i}", m, "drop")
        for i in range(6)
        for m in ("dl_volume_mb", "active_users", "availability_pct")
    ]
    text = question_text("ALR-0019", ASKED, anomalies, long_names)
    assert 8 <= len(text) <= 300
    assert text.startswith("Detector alert ALR-0019 at ") and "S-R0-001" in text


def test_with_no_visible_anomaly_the_alerts_regions_and_metrics_stand_in() -> None:
    assert ask(
        [], alert_region_ids=["TUN"], alert_metrics=["availability_pct", "dl_volume_mb"]
    ) == (
        "Detector alert ALR-0019 at 14:45: abnormal traffic and availability in Grand Tunis. "
        "What is causing it?"
    )
    assert ask([], alert_metrics=["resolution_ms"]).endswith(
        "abnormal DNS resolution nationwide. What is causing it?"
    )


# --- live_events -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [({}, ("user", None)), ({"trigger": "alert", "alert_id": "ALR-0001"}, ("alert", "ALR-0001"))],
)
def test_live_events_passes_the_trigger_to_the_agent(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any], expected: tuple[str, str | None]
) -> None:
    seen: dict[str, Any] = {}

    def spy(*args: Any, **kw: Any) -> Any:
        seen.update(kw)
        return iter(())

    monkeypatch.setattr("incident_agent.api.live.stream", spy)
    list(live_events(make_services(), "Why did traffic drop?", ASKED, **kwargs))
    assert (seen["trigger"], seen["alert_id"]) == expected


# --- the webhook --------------------------------------------------------------------------------

QUESTIONS = {
    alert_id: AlertQuestion(
        alert_id, f"Detector alert {alert_id} at 09:00: traffic dropping.", ASKED
    )
    for alert_id in ("ALR-0001", "ALR-0002")
}


@pytest.fixture(autouse=True)
def known_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "incident_agent.api.alert_runs.alert_question",
        lambda engine, alert_id, now: QUESTIONS.get(alert_id),
    )


class Hook:
    """A client for the webhook that counts how often a model was asked for."""

    def __init__(self, **settings: Any) -> None:
        self.repo = MemoryRunRepository()
        settings = {"alert_webhook_token": TOKEN, **settings}
        self.services: Services = make_services(repo=self.repo, **settings)
        make_runner = self.services.runner_factory
        self.runners = 0

        def counted() -> Any:
            self.runners += 1
            return make_runner()

        self.services.runner_factory = counted
        self.client = TestClient(create_app(self.services))

    def post(self, alert_id: str = "ALR-0001", headers: dict[str, str] | None = AUTH) -> Any:
        return self.client.post(f"/api/alerts/{alert_id}/investigate", headers=headers)


def test_the_webhook_is_off_without_a_token() -> None:
    hook = Hook(alert_webhook_token=None)
    r = hook.post()
    assert r.status_code == 503 and r.json()["error"]["code"] == "alert_hooks_disabled"
    assert hook.runners == 0


@pytest.mark.parametrize(
    "headers",
    [
        None,
        {"Authorization": "Bearer nope"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": ""},
    ],
)
def test_a_missing_or_wrong_token_is_refused(headers: dict[str, str] | None) -> None:
    hook = Hook()
    r = hook.post(headers=headers)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert TOKEN not in r.text and "nope" not in r.text
    assert hook.runners == 0


def test_an_unknown_alert_is_a_404() -> None:
    hook = Hook()
    r = hook.post("ALR-9999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "unknown_alert"
    assert hook.runners == 0


def test_an_alert_is_investigated_and_the_run_is_stored_like_a_live_run() -> None:
    hook = Hook()
    r = hook.post()

    assert r.status_code == 200, r.text
    body = r.json()
    run = body["run"]
    assert body["created"] is True
    assert run["trigger"] == "alert" and run["alert_id"] == "ALR-0001"
    assert run["status"] == "finished" and run["cause"] == "transport_failure"
    assert run["question"] == QUESTIONS["ALR-0001"].question

    stored = hook.client.get(f"/api/investigations/{run['run_id']}").json()
    assert stored["events"][0]["type"] == "run_started"
    assert stored["events"][0]["data"]["trigger"] == "alert"
    assert stored["events"][-1]["type"] == "run_finished" and stored["alert_id"] == "ALR-0001"
    listed = hook.client.get("/api/investigations").json()
    assert [(row["run_id"], row["alert_id"]) for row in listed] == [(run["run_id"], "ALR-0001")]
    # the live limit is not used up by alert runs
    assert hook.client.get("/api/meta").json()["live_remaining"] == 20


def test_a_second_call_returns_the_same_run_without_a_model_call() -> None:
    hook = Hook()
    first = hook.post().json()
    assert hook.runners == 1
    again = hook.post()
    assert again.status_code == 200
    assert again.json() == {"created": False, "run": first["run"]}
    assert hook.runners == 1


def test_a_run_in_progress_blocks_a_new_one_only_for_fifteen_minutes() -> None:
    hook = Hook()
    now = datetime.now(UTC)

    def running(started_at: datetime) -> dict[str, Any]:
        return {
            "question": "q", "asked_at": ASKED, "started_at": started_at,
            "trigger": "alert", "alert_id": "ALR-0001", "status": "running",
        }  # fmt: skip

    hook.repo.runs["RUN-live"] = running(now - timedelta(minutes=5))
    blocked = hook.post().json()
    assert blocked["created"] is False and blocked["run"]["run_id"] == "RUN-live"
    assert hook.runners == 0

    hook.repo.runs["RUN-live"] = running(now - timedelta(minutes=20))
    retried = hook.post().json()
    assert retried["created"] is True and retried["run"]["run_id"] != "RUN-live"
    assert hook.runners == 1


def test_a_failed_run_does_not_block_a_retry() -> None:
    hook = Hook()
    hook.repo.runs["RUN-failed"] = {
        "question": "q", "asked_at": ASKED, "started_at": datetime.now(UTC),
        "trigger": "alert", "alert_id": "ALR-0001", "status": "error",
    }  # fmt: skip
    assert hook.post().json()["created"] is True


def test_the_daily_limit_gives_429_before_any_model_call() -> None:
    hook = Hook(alert_daily_limit=1)
    assert hook.post("ALR-0001").json()["created"] is True
    r = hook.post("ALR-0002")
    assert r.status_code == 429
    error = r.json()["error"]
    assert (
        error["code"] == "alert_limit_reached" and error["limit"] == 1 and error["remaining"] == 0
    )
    assert 0 < int(r.headers["retry-after"]) <= 86_401
    assert hook.runners == 1
    # an alert that is already investigated is still answered at the limit
    assert hook.post("ALR-0001").json()["created"] is False

    assert Hook(alert_daily_limit=0).post().status_code == 429


def test_runs_of_earlier_days_do_not_count_against_the_limit() -> None:
    hook = Hook(alert_daily_limit=1)
    hook.repo.alert_runs = [datetime(2020, 1, 1, tzinfo=UTC)] * 5
    assert hook.post().json()["created"] is True


def test_switching_live_investigations_off_disables_the_webhook() -> None:
    hook = Hook(live_enabled=False)
    r = hook.post()
    assert r.status_code == 503 and r.json()["error"]["code"] == "live_disabled"
    assert hook.runners == 0


def test_a_run_that_ends_in_an_error_is_still_a_200() -> None:
    hook = Hook()

    def broken() -> ScriptedRunner:
        raise RuntimeError("no model")

    hook.services.runner_factory = broken
    r = hook.post()
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True and body["run"]["status"] == "error"
    assert body["run"]["alert_id"] == "ALR-0001" and body["run"]["trigger"] == "alert"


# --- the contract -------------------------------------------------------------------------------


def test_alerts_carry_the_id_of_their_newest_stored_run(monkeypatch: pytest.MonkeyPatch) -> None:
    hook = Hook()
    run_id = hook.post("ALR-0002").json()["run"]["run_id"]

    def alert(alert_id: str) -> AlertOut:
        return AlertOut(
            id=alert_id, start_at=ASKED, end_at=ASKED, severity="high", score=1.0, summary="s",
            region_ids=[], entity_ids=[], metrics=[], n_anomalies=1, status="new",
        )  # fmt: skip

    monkeypatch.setattr(
        "incident_agent.api.routes.list_alerts",
        lambda engine, now, limit: [alert("ALR-0001"), alert("ALR-0002")],
    )
    rows = hook.client.get("/api/alerts").json()
    assert [(row["id"], row["run_id"]) for row in rows] == [
        ("ALR-0001", None),
        ("ALR-0002", run_id),
    ]
    json.dumps(rows)
