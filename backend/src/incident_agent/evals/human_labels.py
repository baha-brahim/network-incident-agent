# ruff: noqa: E501
"""Plain-English headers and the glossary of the grading page.

These are reading aids. A header is built only from the tool name and arguments of a call (or from
the kind of a cited row), so it says what the evidence box is about without changing the text the
grader model reads. The glossary explains the terms that occur in that text.
"""

from datetime import datetime
from typing import Any

MAX_NAMES = 4
MAX_QUERY = 70

KPI_NAMES = {
    "availability_pct": "availability",
    "dl_volume_mb": "downlink traffic volume",
    "ul_volume_mb": "uplink traffic volume",
    "active_users": "active users",
    "rrc_success_pct": "connection success (RRC)",
    "drop_rate_pct": "drop rate",
    "latency_ms": "latency",
    "prb_util_pct": "radio load (PRB utilisation)",
    "cells_down": "cells down",
}

ROW_LABELS = {
    "alarm": "One alarm",
    "change": "One configuration change",
    "maintenance": "One maintenance window",
    "event": "One external event",
    "alert": "One detector alert",
    "anomaly": "One detected anomaly",
    "runbook": "One runbook excerpt",
    "node": "One network node",
}

RELATIVES = {
    "ancestors": "what it depends on",
    "descendants": "what is below it",
    "siblings": "its neighbours",
    "all": "what it depends on, what is below it and its neighbours",
}


def _moment(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).strip())
    except ValueError:
        return None


def _day(moment: datetime) -> str:
    return f"{moment.day} {moment:%b}"


def window(start: Any, end: Any) -> str:
    """'21 Sep 15:00 to 19:00', or both dates when the window spans days."""
    a, b = _moment(start), _moment(end)
    if a is None or b is None:
        return f"{start} to {end}"
    if a.date() == b.date():
        return f"{_day(a)} {a:%H:%M} to {b:%H:%M}"
    return f"{_day(a)} {a:%H:%M} to {_day(b)} {b:%H:%M}"


def _names(ids: list[str]) -> str:
    shown = ", ".join(ids[:MAX_NAMES])
    return shown if len(ids) <= MAX_NAMES else f"{shown} and {len(ids) - MAX_NAMES} more"


def _scope(args: dict[str, Any], *, below: bool = False, above: bool = False) -> str:
    """Where a call looked: the named nodes (and their relatives), a region, or everywhere."""
    ids = [str(n) for n in args.get("node_ids") or []]
    if ids:
        text = _names(ids)
        if below and args.get("include_descendants"):
            text += " and nodes below them"
        if above and args.get("include_ancestors"):
            text += " and the nodes above them"
        return text
    if args.get("region_id"):
        return f"region {args['region_id']}"
    return "the whole network"


def describe_call(tool: str, args: dict[str, Any]) -> str:
    when = window(args.get("start"), args.get("end")) if args.get("start") else ""
    tail = f", {when}" if when else ""
    if tool == "get_alarms":
        extra = ""
        if args.get("alarm_types"):
            extra = f" ({', '.join(args['alarm_types'])} only)"
        elif args.get("min_severity"):
            extra = f" ({args['min_severity']} or worse)"
        return f"Alarms on {_scope(args, below=True)}{extra}{tail}"
    if tool == "get_changes":
        return f"Changes on {_scope(args, above=True)}{tail}"
    if tool == "get_maintenance":
        return f"Maintenance calendar for {_scope(args, above=True)}{tail}"
    if tool == "get_anomalies":
        where = args.get("entity_id") or args.get("region_id") or "the whole network"
        return f"Detector alerts in {where}{tail}"
    if tool == "get_external_events":
        where = f"region {args['region_id']}" if args.get("region_id") else "the whole network"
        return f"External events (holidays, stadium events) in {where}{tail}"
    if tool == "query_kpis":
        ids = [str(n) for n in args.get("entity_ids") or []]
        kind = str(args.get("entity_type") or "entity")
        target = f"{kind} {_names(ids)}" if ids else f"the {kind}"
        metrics = ", ".join(
            KPI_NAMES.get(m, m.replace("_", " ")) for m in args.get("metrics") or []
        )
        return f"KPI measurements for {target} ({metrics}){tail}"
    if tool == "get_topology":
        node = args.get("node_id", "?")
        return (
            f"Network map around {node}: {RELATIVES.get(str(args.get('include')), 'its relatives')}"
        )
    if tool == "search_runbooks":
        return f"Runbook excerpts for the query '{args.get('query', '')}'"
    if tool == "run_sql":
        query = " ".join(str(args.get("query", "")).split())
        if len(query) > MAX_QUERY:
            query = query[: MAX_QUERY - 3] + "..."
        return f"Database query: {query}"
    return tool.replace("_", " ").capitalize() + (f"{tail}" if tail else "")


def describe_row(ref: str, kind: str | None) -> str:
    if kind is None:
        return f"Not among the report's evidence: {ref}"
    return f"{ROW_LABELS.get(kind, 'One item')}: {ref}"


# --- glossary -------------------------------------------------------------------------------

# (term, group, one-line definition, regexes of the words in the text that this term explains).
# A node or reference ID is explained through its prefix, so those entries have no regexes.
GLOSSARY: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "LINK_LOS",
        "Alarm type",
        "Loss of signal on a transport link: nothing arrives, the sites behind it go down.",
        (r"\bLINK_LOS\b",),
    ),
    (
        "LINK_DEGRADED",
        "Alarm type",
        "A transport link works but poorly (reduced capacity or errors).",
        (r"\bLINK_DEGRADED\b",),
    ),
    (
        "SITE_DOWN",
        "Alarm type",
        "A radio site cannot be reached. A symptom: the cause is elsewhere.",
        (r"\bSITE_DOWN\b",),
    ),
    (
        "MAINS_FAILURE",
        "Alarm type",
        "A site lost mains electricity and runs on its battery.",
        (r"\bMAINS_FAILURE\b",),
    ),
    (
        "BATTERY_LOW",
        "Alarm type",
        "A site's battery is nearly empty (about 15 minutes left).",
        (r"\bBATTERY_LOW\b",),
    ),
    (
        "RECTIFIER_FAULT",
        "Alarm type",
        "A power module in a site cabinet is faulty.",
        (r"\bRECTIFIER_FAULT\b",),
    ),
    (
        "HIGH_PRB",
        "Alarm type",
        "Radio capacity of a site is almost fully used (PRB utilisation above 85-90 %).",
        (r"\bHIGH_PRB\b",),
    ),
    (
        "RRC_FAILURE_RATE_HIGH",
        "Alarm type",
        "Many phones fail to set up a connection on a site.",
        (r"\bRRC_FAILURE_RATE_HIGH\b",),
    ),
    (
        "DNS_TIMEOUT_RATE",
        "Alarm type",
        "The DNS service (name lookup) times out too often.",
        (r"\bDNS_TIMEOUT_RATE\b",),
    ),
    (
        "TEMP_HIGH",
        "Alarm type",
        "Cabinet temperature is high. Common and usually harmless.",
        (r"\bTEMP_HIGH\b",),
    ),
    (
        "VSWR_HIGH",
        "Alarm type",
        "Signal reflection on an antenna cable. Frequent and usually harmless.",
        (r"\bVSWR_HIGH\b",),
    ),
    ("FAN_FAILURE", "Alarm type", "A cabinet cooling fan runs slowly.", (r"\bFAN_FAILURE\b",)),
    (
        "DOOR_OPEN",
        "Alarm type",
        "A cabinet door is open, usually a technician visit.",
        (r"\bDOOR_OPEN\b",),
    ),
    (
        "CPU_HIGH",
        "Alarm type",
        "A router's processor load is high. Brief spikes are normal.",
        (r"\bCPU_HIGH\b",),
    ),
    (
        "availability",
        "KPI",
        "Share of time a cell was in service. Normal is 100 %.",
        (r"\bavailability(?:_pct)?\b",),
    ),
    (
        "dl volume",
        "KPI",
        "Downlink data volume delivered to users, in megabytes per 15 minutes.",
        (r"\bdl[_ ]volume(?:_mb)?\b", r"\bdownlink (?:traffic |data )?volume\b"),
    ),
    (
        "RRC success",
        "KPI",
        "Share of connection set-ups that succeed. Normal is about 99-99.7 %.",
        (r"\brrc[_ ]success(?:_pct)?\b",),
    ),
    (
        "drop rate",
        "KPI",
        "Share of sessions that end abnormally. Normal is 0.4-0.8 %.",
        (r"\bdrop[_ ]rate(?:_pct)?\b",),
    ),
    (
        "latency",
        "KPI",
        "Average round-trip time in milliseconds. Normal is about 20-40 ms.",
        (r"\blatency(?:_ms)?\b",),
    ),
    (
        "PRB utilisation",
        "KPI",
        "Share of radio resource blocks in use, i.e. how full the cell is.",
        (r"\bprb[_ ]util(?:isation|ization|_pct)?\b", r"\bPRB\b"),
    ),
    ("active users", "KPI", "Number of phones connected to a cell.", (r"\bactive[_ ]users\b",)),
    (
        "baseline",
        "Term",
        "What a value normally is at the same time of day on earlier days of the same type.",
        (r"\bbaseline\b",),
    ),
    ("onset", "Term", "The first time step at which a value left its baseline.", (r"\bonset\b",)),
    ("active", "Term", "An alarm that has been raised and not yet cleared.", (r"\bactive\b",)),
    ("cleared", "Term", "An alarm that has ended.", (r"\bcleared\b",)),
    (
        "z-score",
        "Term",
        "How many typical deviations a value is from its baseline. Above about 3.5 counts as unusual.",
        (r"\bz[- ]score\b", r"\bz(?= -?\d)"),
    ),
    ("S-", "Node ID", "A radio site, e.g. S-TUN-004 (TUN, SAH, SFX, SUD are regions).", ()),
    ("C-", "Node ID", "One cell (sector) of a site, e.g. C-SAH-007-1.", ()),
    (
        "LNK-",
        "Node ID",
        "A transport link (fiber or microwave) that connects sites to the network.",
        (),
    ),
    ("AGG-", "Node ID", "An aggregation router that gathers several links.", ()),
    ("CORE-", "Node ID", "A core network node (UPF, DNS, AMF).", ()),
    (
        "T",
        "Reference",
        "T1, T2, ...: a tool call the agent made; its output is the evidence.",
        (r"\bT\d+\b",),
    ),
    ("ALM", "Reference", "ALM-000472: one alarm.", ()),
    ("CHG", "Reference", "CHG-2026-0044: one configuration change.", ()),
    ("MW", "Reference", "MW-0003: one planned maintenance window.", ()),
    ("EVT", "Reference", "EVT-004: one external event (holiday, stadium event).", ()),
    ("ALR", "Reference", "ALR-0037: one detector alert, a group of related anomalies.", ()),
    ("ANM", "Reference", "ANM-000163: one detected anomaly on one KPI of one node.", ()),
    ("RB", "Reference", "RB-BAD-CHANGE#02: an excerpt of an operations runbook.", ()),
)
