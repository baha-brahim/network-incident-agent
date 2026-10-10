import pytest

from incident_agent.db import check_connection


@pytest.mark.db
def test_check_connection() -> None:
    check_connection()
