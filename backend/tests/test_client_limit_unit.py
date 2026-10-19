"""The per-client cap on live investigations: client keys, the cap itself, and what is stored."""

import json
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from incident_agent.api.app import create_app
from incident_agent.api.clients import (
    client_address,
    context_source_ip,
    hash_address,
    last_forwarded_address,
)
from incident_agent.config import Settings
from tests.api_support import QUESTION, MemoryRunRepository, make_services

STREAM = "/api/investigations/stream"


def forwarded(address: str) -> dict[str, str]:
    return {"X-Forwarded-For": address}


def post(c: TestClient, address: str | None = None) -> Any:
    headers = forwarded(address) if address else {}
    return c.post(STREAM, json={"question": QUESTION}, headers=headers)


def meta(c: TestClient, address: str | None = None) -> dict[str, Any]:
    headers = forwarded(address) if address else {}
    body: dict[str, Any] = c.get("/api/meta", headers=headers).json()
    return body


# --- client keys ------------------------------------------------------------------------------


def request_with(headers: dict[str, str], client: tuple[str, int] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": client})


def lambda_context(source_ip: object) -> str:
    return json.dumps({"requestId": "r-1", "http": {"method": "GET", "sourceIp": source_ip}})


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("  203.0.113.7  ", "203.0.113.7"),
        ("198.51.100.1, 10.0.0.1, 203.0.113.7", "203.0.113.7"),
        ("10.0.0.1 ,203.0.113.7", "203.0.113.7"),
        ("10.0.0.1, 2001:db8::1", "2001:db8::1"),
        ("", None),
        ("   ", None),
        ("10.0.0.1, ", None),
        (None, None),
    ],
)
def test_last_forwarded_address_is_the_nearest_proxys(
    header: str | None, expected: str | None
) -> None:
    assert last_forwarded_address(header) == expected


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (lambda_context("203.0.113.7"), "203.0.113.7"),
        (lambda_context(" 2001:db8::1 "), "2001:db8::1"),
        (lambda_context(""), None),
        (lambda_context(7), None),
        (lambda_context(None), None),
        ('{"http": {}}', None),
        ('{"http": "203.0.113.7"}', None),
        ('{"sourceIp": "203.0.113.7"}', None),
        ("[]", None),
        ('"203.0.113.7"', None),
        ("null", None),
        ("not json", None),
        ("", None),
        (None, None),
    ],
)
def test_context_source_ip_ignores_anything_but_a_string_there(
    header: str | None, expected: str | None
) -> None:
    assert context_source_ip(header) == expected


def test_the_aws_source_ip_beats_a_spoofed_forwarded_for() -> None:
    request = request_with(
        {
            "x-amzn-request-context": lambda_context("203.0.113.7"),
            "x-forwarded-for": "6.6.6.6, 203.0.113.7",
        },
        ("127.0.0.1", 5000),
    )
    assert client_address(request) == "203.0.113.7"


@pytest.mark.parametrize("context", ["not json", "[]", '{"http": {"sourceIp": 7}}', ""])
def test_a_bad_context_falls_back_to_the_last_forwarded_address(context: str) -> None:
    headers = {"x-amzn-request-context": context, "x-forwarded-for": "6.6.6.6, 203.0.113.7"}
    assert client_address(request_with(headers, ("127.0.0.1", 5000))) == "203.0.113.7"


def test_the_last_forwarded_address_is_used_without_a_context() -> None:
    request = request_with({"x-forwarded-for": "6.6.6.6, 10.0.0.1, 203.0.113.7"})
    assert client_address(request) == "203.0.113.7"


def test_without_either_header_the_socket_address_is_used() -> None:
    assert client_address(request_with({}, ("198.51.100.4", 5000))) == "198.51.100.4"
    assert client_address(request_with({"x-forwarded-for": " "}, ("198.51.100.4", 5000))) == (
        "198.51.100.4"
    )
    assert client_address(request_with({})) == "unknown"


def test_the_hash_is_short_stable_and_salted() -> None:
    plain = Settings(_env_file=None)
    salted = Settings(_env_file=None, client_hash_salt="pepper")
    other = Settings(_env_file=None, client_hash_salt="paprika")
    a = hash_address("203.0.113.7", salted)
    assert re.fullmatch(r"[0-9a-f]{16}", a)
    assert hash_address("203.0.113.7", salted) == a
    assert hash_address("203.0.113.8", salted) != a
    assert hash_address("203.0.113.7", other) != a
    assert hash_address("203.0.113.7", plain) != a
    assert "203" not in a


# --- the cap ----------------------------------------------------------------------------------


def test_a_client_is_stopped_at_its_cap_and_others_are_not() -> None:
    repo = MemoryRunRepository()
    c = TestClient(create_app(make_services(repo=repo, live_per_client_daily_limit=2)))
    assert post(c, "203.0.113.7").status_code == 200
    assert post(c, "203.0.113.7").status_code == 200

    r = post(c, "203.0.113.7")
    assert r.status_code == 429
    assert r.json()["error"] == {
        "code": "client_limit_reached",
        "message": r.json()["error"]["message"],
        "limit": 2,
        "remaining": 0,
    }
    assert 0 < int(r.headers["retry-after"]) <= 86_401
    assert len(repo.runs) == 2  # the refused request started nothing

    assert post(c, "203.0.113.8").status_code == 200  # another client is independent
    assert post(c).status_code == 200  # so is a request with no forwarded address


def test_hops_before_the_last_do_not_change_the_client() -> None:
    c = TestClient(create_app(make_services(live_per_client_daily_limit=1)))
    assert post(c, "10.0.0.1, 203.0.113.7").status_code == 200
    assert post(c, "10.9.9.9, 203.0.113.7").status_code == 429


def test_the_client_message_comes_before_the_global_one() -> None:
    repo = MemoryRunRepository()
    repo.user_runs = [datetime.now(UTC)] * 5
    c = TestClient(create_app(make_services(repo=repo, live_daily_limit=5)))
    assert post(c, "203.0.113.7").json()["error"]["code"] == "daily_limit_reached"

    zero = TestClient(create_app(make_services(repo=repo, live_per_client_daily_limit=0)))
    assert post(zero, "203.0.113.7").json()["error"]["code"] == "client_limit_reached"


def test_meta_reports_what_is_left_for_the_asking_client() -> None:
    c = TestClient(create_app(make_services(live_daily_limit=10)))
    first = meta(c, "203.0.113.7")
    assert (first["live_remaining"], first["live_client_limit"]) == (10, 3)
    assert first["live_client_remaining"] == 3

    post(c, "203.0.113.7")
    mine, other = meta(c, "203.0.113.7"), meta(c, "203.0.113.8")
    assert (mine["live_remaining"], mine["live_client_remaining"]) == (9, 2)
    assert (other["live_remaining"], other["live_client_remaining"]) == (9, 3)


def test_meta_shows_no_client_runs_when_live_is_off() -> None:
    off = meta(TestClient(create_app(make_services(live_enabled=False))))
    assert off["live_remaining"] == 0 and off["live_client_remaining"] == 0


# --- what is stored ---------------------------------------------------------------------------


def test_only_the_hash_of_the_address_reaches_the_repository() -> None:
    repo = MemoryRunRepository()
    settings: dict[str, Any] = {"client_hash_salt": "pepper"}
    c = TestClient(create_app(make_services(repo=repo, **settings)))
    post(c, "203.0.113.7")

    expected = hash_address("203.0.113.7", Settings(_env_file=None, **settings))
    assert [h for h, _ in repo.client_runs] == [expected]
    assert "203.0.113.7" not in repr(repo.runs) + repr(repo.client_runs) + repr(repo.events)


def test_alert_runs_carry_no_client() -> None:
    repo = MemoryRunRepository()
    store = repo.trace_store()
    assert store is not None
    store.start_run("RUN-A", "q", datetime.now(UTC), trigger="alert", alert_id="ALR-0001")
    assert repo.client_runs == []
