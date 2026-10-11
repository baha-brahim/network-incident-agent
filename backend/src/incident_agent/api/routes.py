"""The endpoints."""

import asyncio
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from incident_agent.agent.tools.timeutil import as_utc
from incident_agent.api.bridge import sse_from_iterator
from incident_agent.api.datasets import list_alerts
from incident_agent.api.demos import replay_frames
from incident_agent.api.errors import ERRORS, ApiError
from incident_agent.api.kpis import KpiInputError, kpi_series
from incident_agent.api.live import live_events, live_remaining, seconds_to_next_day
from incident_agent.api.schemas import (
    AlertOut,
    DemoSummary,
    Health,
    InvestigationDetail,
    InvestigationSummary,
    KpiSeries,
    LiveRequest,
    Meta,
    Recording,
    Topology,
)
from incident_agent.api.services import Services
from incident_agent.api.topology import node_neighbourhood

router = APIRouter(prefix="/api")

STREAM_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
STREAM_DOC: dict[int | str, dict[str, object]] = {
    200: {
        "description": "Server-Sent Events. Each frame is `event: <type>` and one `data:` line "
        "holding a `RunEvent`. Comment lines (`: ...`) are keep-alives.",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }
}


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


Svc = Annotated[Services, Depends(get_services)]


# --- status -----------------------------------------------------------------------------------


@router.get("/health", response_model=Health, responses={503: {"model": Health}}, tags=["status"])
async def health(svc: Svc, response: Response) -> Health:
    """Liveness. Checks the database, giving up after 3 seconds."""

    def ping() -> None:
        with svc.engine().connect() as conn:
            conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(asyncio.to_thread(ping), 3.0)
        ok = True
    except Exception:
        ok = False
    if not ok:
        response.status_code = 503
    return Health(status="ok" if ok else "degraded", database=ok)


@router.get("/meta", response_model=Meta, responses=ERRORS, tags=["status"])
def meta(svc: Svc) -> Meta:
    """Facts about the dataset, and whether a live investigation can be started."""
    facts = svc.facts()
    settings = svc.settings
    return Meta(
        dataset_now=facts.now,
        window_start=facts.window_start,
        window_end=facts.window_end,
        step_minutes=facts.step_minutes,
        timezone=facts.timezone,
        regions=facts.regions,
        live_enabled=settings.live_enabled,
        live_daily_limit=settings.live_daily_limit,
        live_remaining=live_remaining(svc) if settings.live_enabled else 0,
        model=settings.agent_model,
    )


# --- recorded investigations ------------------------------------------------------------------


@router.get("/demos", response_model=list[DemoSummary], tags=["demos"])
def list_demos(svc: Svc) -> list[DemoSummary]:
    """The recorded investigations."""
    return [demo.summary for demo in svc.demos.all()]


@router.get("/demos/{demo_id}", response_model=Recording, responses=ERRORS, tags=["demos"])
def get_demo(demo_id: str, svc: Svc) -> Recording:
    """A whole recording, for an instant view without replay timing."""
    demo = svc.demos.get(demo_id)
    if demo is None:
        raise ApiError(404, "unknown_demo", f"No recorded investigation {demo_id!r}.")
    return demo.recording


@router.post(
    "/demos/{demo_id}/stream",
    responses={**ERRORS, **STREAM_DOC},
    response_class=StreamingResponse,
    tags=["demos"],
)
async def replay_demo(
    demo_id: str,
    svc: Svc,
    speed: Annotated[float, Query(ge=1, le=20, description="Replay speed, 1 to 20.")] = 1.0,
) -> StreamingResponse:
    """Replay a recording as events, paced by its recorded timing divided by `speed`."""
    demo = svc.demos.get(demo_id)
    if demo is None:
        raise ApiError(404, "unknown_demo", f"No recorded investigation {demo_id!r}.")
    frames = replay_frames(demo.events, speed, svc.sleep, svc.keepalive_seconds)
    return StreamingResponse(frames, media_type="text/event-stream", headers=STREAM_HEADERS)


# --- live investigations ----------------------------------------------------------------------


@router.post(
    "/investigations/stream",
    responses={**ERRORS, **STREAM_DOC},
    response_class=StreamingResponse,
    tags=["investigations"],
)
async def stream_investigation(body: LiveRequest, svc: Svc) -> StreamingResponse:
    """Run a live investigation and stream its events. Limited per day."""
    settings = svc.settings
    if not settings.live_enabled:
        raise ApiError(503, "live_disabled", "Live investigations are switched off.")

    def preflight() -> tuple[int, datetime]:
        return live_remaining(svc), svc.facts().now

    remaining, dataset_now = await asyncio.to_thread(preflight)
    if remaining <= 0:
        raise ApiError(
            429,
            "daily_limit_reached",
            "The daily limit of live investigations is reached. "
            "Replay a recorded one, or come back tomorrow (the limit resets at 00:00 UTC).",
            headers={"Retry-After": str(seconds_to_next_day(svc.clock()))},
            limit=settings.live_daily_limit,
            remaining=0,
        )
    now = as_utc(dataset_now)
    asked_at = as_utc(body.asked_at) if body.asked_at else now
    if asked_at > now:
        raise ApiError(
            422, "asked_at_in_future", f"asked_at cannot be later than {now.isoformat()}."
        )
    frames = sse_from_iterator(
        lambda: live_events(svc, body.question, asked_at), svc.keepalive_seconds
    )
    return StreamingResponse(frames, media_type="text/event-stream", headers=STREAM_HEADERS)


@router.get(
    "/investigations",
    response_model=list[InvestigationSummary],
    responses=ERRORS,
    tags=["investigations"],
)
def list_investigations(
    svc: Svc, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[InvestigationSummary]:
    """Past live runs, newest first."""
    return svc.runs.list_runs(limit)


@router.get(
    "/investigations/{run_id}",
    response_model=InvestigationDetail,
    responses=ERRORS,
    tags=["investigations"],
)
def get_investigation(run_id: str, svc: Svc) -> InvestigationDetail:
    """One past run with its event list, in the same form as a recording."""
    run = svc.runs.get_run(run_id)
    if run is None:
        raise ApiError(404, "unknown_run", f"No investigation {run_id!r}.")
    return run


# --- the network ------------------------------------------------------------------------------


@router.get("/alerts", response_model=list[AlertOut], responses=ERRORS, tags=["network"])
def alerts(svc: Svc, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[AlertOut]:
    """Detector alerts, newest first."""
    return list_alerts(svc.agent_engine(), svc.facts().now, limit)


@router.get("/kpis", response_model=KpiSeries, responses=ERRORS, tags=["network"])
def kpis(
    svc: Svc,
    entity_type: Literal["cell", "site", "region", "national", "core_node"],
    metric: str,
    entity_id: str | None = None,
    start: Annotated[
        datetime | None,
        Query(description="Default: 24 hours before `end`. No offset means Africa/Tunis."),
    ] = None,
    end: Annotated[
        datetime | None,
        Query(description="Default and maximum: the dataset's now."),
    ] = None,
) -> KpiSeries:
    """A KPI series with its baseline, cut at the dataset's now (7 days, 200 points at most)."""
    now = svc.facts().now
    end_at = as_utc(end) if end else now  # the window cuts it at `now` and says so
    start_at = as_utc(start) if start else min(end_at, now) - timedelta(days=1)
    if entity_type != "national" and not entity_id:
        raise ApiError(422, "entity_id_required", f"entity_id is required for {entity_type}.")
    try:
        found = kpi_series(
            svc.agent_engine(),
            entity_type=entity_type,
            entity_ids=[entity_id] if entity_id and entity_type != "national" else [],
            metrics=[metric],
            start=start_at.isoformat(),
            end=end_at.isoformat(),
            now=now,
        )
    except KpiInputError as exc:
        code = "unknown_entity" if exc.status == 404 else "invalid_kpi_request"
        raise ApiError(exc.status, code, exc.message) from exc
    if not found:
        raise ApiError(404, "no_series", "That entity has no such metric.")
    return next(iter(found.values()))


@router.get("/topology", response_model=Topology, responses=ERRORS, tags=["network"])
def topology(svc: Svc, node_id: str) -> Topology:
    """A node, its chain up to the core, and its siblings and children."""
    return node_neighbourhood(svc.agent_engine(), node_id)
