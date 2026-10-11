"""The API contract as a file: `docs/api/openapi.json`, for typing the web interface.

uv run python -m incident_agent.api.openapi            # write it
uv run python -m incident_agent.api.openapi --check    # fail if the file is out of date
"""

import argparse
import json
from typing import Any

from incident_agent.api.app import create_app
from incident_agent.api.services import Services
from incident_agent.config import REPO_ROOT, Settings

OPENAPI_PATH = REPO_ROOT / "docs" / "api" / "openapi.json"


def render() -> str:
    """The schema of the API with default settings, as the text of the committed file."""
    app = create_app(Services(settings=Settings(_env_file=None)))
    spec: dict[str, Any] = app.openapi()
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m incident_agent.api.openapi")
    parser.add_argument("--check", action="store_true", help="do not write; fail if out of date")
    args = parser.parse_args(argv)
    text = render()
    current = (
        OPENAPI_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
        if OPENAPI_PATH.exists()
        else ""
    )
    if args.check:
        if current != text:
            print(f"{OPENAPI_PATH} is out of date; run python -m incident_agent.api.openapi")
            return 1
        return 0
    OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI_PATH.write_bytes(text.encode("utf-8"))
    print(f"wrote {OPENAPI_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
