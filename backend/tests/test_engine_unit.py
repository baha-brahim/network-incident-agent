"""Engine settings that matter on Lambda and behind Neon's pooler. No connection is made."""

from typing import Any

import pytest

from incident_agent.db import session
from incident_agent.db.session import MAX_OVERFLOW, POOL_SIZE, build_engine, is_pooled_host

DIRECT = (
    "postgresql+psycopg://u:p@ep-quiet-sun-123456.eu-central-1.aws.neon.tech/db?sslmode=require"
)
POOLED = DIRECT.replace("ep-quiet-sun-123456", "ep-quiet-sun-123456-pooler")


def test_only_the_pooler_host_is_recognised() -> None:
    assert is_pooled_host(POOLED)
    assert not is_pooled_host(DIRECT)
    assert not is_pooled_host(
        "postgresql+psycopg://incident:incident@localhost:5433/incident_agent"
    )
    assert not is_pooled_host("postgresql+psycopg:///db")  # no host at all


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake(url: str, **kwargs: Any) -> object:
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(session, "create_engine", fake)
    return seen


def test_pools_are_small_and_checked(captured: dict[str, Any]) -> None:
    build_engine(DIRECT)
    assert captured["pool_size"] == POOL_SIZE == 2
    assert captured["max_overflow"] == MAX_OVERFLOW == 2
    assert captured["pool_pre_ping"] is True
    assert captured["pool_recycle"] == 300


def test_prepared_statements_are_off_behind_the_pooler(captured: dict[str, Any]) -> None:
    build_engine(POOLED)
    assert captured["connect_args"] == {"prepare_threshold": None}


def test_prepared_statements_stay_on_for_a_direct_connection(captured: dict[str, Any]) -> None:
    build_engine(DIRECT)
    assert captured["connect_args"] == {}
