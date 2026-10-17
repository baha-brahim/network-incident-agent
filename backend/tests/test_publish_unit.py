"""The publish script's guards and error handling. Nothing here touches a database."""

import pytest

from incident_agent.db import publish
from incident_agent.db.publish import (
    PublishError,
    Roles,
    main,
    redact,
    same_database,
    secrets_of,
)

LOCAL = "postgresql+psycopg://incident:incident@localhost:5433/incident_agent"
HOSTED = "postgresql+psycopg://owner:s3cretpass@ep-quiet-sun-123456.eu-central-1.aws.neon.tech/db"
ROLES = Roles("agent_ro", "agent-pass", "api_rw", "api-pass")


def test_the_same_database_is_recognised_whatever_the_credentials() -> None:
    assert same_database(LOCAL, LOCAL.replace("incident:incident", "other:pw"))
    assert same_database(LOCAL, LOCAL + "?sslmode=disable")
    assert not same_database(LOCAL, LOCAL.replace("incident_agent", "incident_agent_test"))
    assert not same_database(LOCAL, HOSTED)


def test_the_source_database_cannot_be_the_target() -> None:
    with pytest.raises(PublishError, match="target is the source"):
        publish.publish(LOCAL, LOCAL, ROLES, dry_run=False)


def test_a_pooled_target_is_refused() -> None:
    pooled = HOSTED.replace("ep-quiet-sun-123456", "ep-quiet-sun-123456-pooler")
    with pytest.raises(PublishError, match="direct connection"):
        publish.publish(LOCAL, pooled, ROLES, dry_run=True)


def test_error_messages_hide_the_url_the_password_and_the_host() -> None:
    message = (
        "connection to server at ep-quiet-sun-123456.eu-central-1.aws.neon.tech failed for "
        f"{HOSTED} (password s3cretpass, role pw api-pass)"
    )
    shown = redact(message, [*secrets_of(LOCAL, HOSTED), "api-pass"])
    for secret in ("neon.tech", "s3cretpass", "api-pass", "owner:"):
        assert secret not in shown
    assert "failed for" in shown


def test_missing_settings_are_reported_without_touching_a_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(publish, "dotenv_values", lambda *_: {})
    for name in ("NO_SUCH_TARGET", "AGENT_RO_PASSWORD", "API_RW_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    assert main(["--target-env", "NO_SUCH_TARGET", "--dry-run"]) == 2
    err = capsys.readouterr().err
    assert "NO_SUCH_TARGET" in err and "AGENT_RO_PASSWORD" in err and "API_RW_PASSWORD" in err


def test_a_failure_is_reported_without_its_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(publish, "dotenv_values", lambda *_: {})
    monkeypatch.setenv("HOSTED_URL", HOSTED.replace("+psycopg", ""))
    monkeypatch.setenv("AGENT_RO_PASSWORD", "agent-pass")
    monkeypatch.setenv("API_RW_PASSWORD", "api-pass")

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError(f"cannot reach {HOSTED} with api-pass")

    monkeypatch.setattr(publish, "publish", boom)
    assert main(["--target-env", "HOSTED_URL"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("Publish failed: RuntimeError: cannot reach")
    for secret in ("neon.tech", "s3cretpass", "api-pass"):
        assert secret not in err
