"""The FastAPI application. `app` is what uvicorn serves; nothing connects until a request needs it.

uv run uvicorn incident_agent.api.app:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from incident_agent.api.errors import install_handlers
from incident_agent.api.limits import BodyLimitMiddleware
from incident_agent.api.routes import router
from incident_agent.api.services import Services
from incident_agent.config import Settings, get_settings

DESCRIPTION = (
    "Investigations of network incidents, streamed as Server-Sent Events, with recorded replays, "
    "the detector's alerts, KPI series and the topology."
)


def create_app(services: Services | None = None, settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass `services` with their own runner, engines and clock."""
    services = services or Services(settings=settings or get_settings())
    app = FastAPI(title="Network Incident Agent API", version="0.1.0", description=DESCRIPTION)
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=services.settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        max_age=600,
    )
    app.add_middleware(BodyLimitMiddleware)
    install_handlers(app)
    app.include_router(router)
    return app


def __getattr__(name: str) -> FastAPI:
    """`app` is built on first access, so importing this module reads no settings."""
    if name == "app":
        built = create_app()
        globals()["app"] = built
        return built
    raise AttributeError(name)
