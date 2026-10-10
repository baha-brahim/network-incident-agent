"""Time parsing and formatting shared by every tool. Local time is Africa/Tunis."""

from datetime import UTC, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

STEP = timedelta(minutes=15)  # KPI granularity


def _load_tz() -> tzinfo:
    try:
        return ZoneInfo("Africa/Tunis")
    except ZoneInfoNotFoundError:  # no tz database on this host: Tunisia has been UTC+1 all year
        return timezone(timedelta(hours=1), "Africa/Tunis")


LOCAL_TZ: tzinfo = _load_tz()
LOCAL_TZ_NAME = "Africa/Tunis"


class TimeParseError(ValueError):
    """Raised for an unusable time argument; tools turn it into a ToolResult error."""


def parse_time(value: str, *, name: str = "time") -> datetime:
    """Parse an ISO 8601 string. Without an offset the value is Africa/Tunis local time."""
    text = value.strip() if isinstance(value, str) else ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise TimeParseError(
            f"Cannot parse {name}={value!r}. Use ISO 8601, e.g. '2026-09-21 16:50' "
            "(Africa/Tunis local time) or '2026-09-21T15:50Z'."
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(UTC)


def as_utc(dt: datetime) -> datetime:
    """UTC version of `dt`; a naive value is taken as Africa/Tunis local time."""
    return (dt if dt.tzinfo else dt.replace(tzinfo=LOCAL_TZ)).astimezone(UTC)


def to_local(dt: datetime) -> datetime:
    return dt.astimezone(LOCAL_TZ)


def fmt(dt: datetime | None) -> str:
    """Local time as shown to the model: '2026-09-21 16:50'."""
    return "-" if dt is None else to_local(dt).strftime("%Y-%m-%d %H:%M")


def fmt_hm(dt: datetime) -> str:
    return to_local(dt).strftime("%H:%M")


def iso(dt: datetime | None) -> str | None:
    """UTC ISO string for the structured `data` payload."""
    return None if dt is None else dt.astimezone(UTC).isoformat()


def fmt_duration(delta: timedelta) -> str:
    minutes = round(delta.total_seconds() / 60)
    if minutes < 90:
        return f"{minutes} min"
    hours = minutes / 60
    return f"{hours:.1f} h" if hours < 48 else f"{hours / 24:.1f} d"


def fmt_window(start: datetime, end: datetime) -> str:
    return f"{fmt(start)} to {fmt(end)}"


class Window:
    """A requested time range clamped to `asked_at`."""

    def __init__(self, start: datetime, end: datetime, asked_at: datetime) -> None:
        self.asked_at = as_utc(asked_at)
        self.start = start
        self.requested_end = end
        self.end = min(end, self.asked_at)
        self.clamped = end > self.asked_at
        self.empty = start > self.end

    def notes(self) -> list[str]:
        """Sentences to put in the body when the window was cut or lies in the future."""
        if self.empty:
            return [
                f"Window starts after asked_at ({fmt(self.asked_at)}); nothing is visible there."
            ]
        if self.clamped:
            return [
                f"Window cut at asked_at ({fmt(self.asked_at)}); "
                f"requested end {fmt(self.requested_end)} is not visible."
            ]
        return []


def make_window(start: str, end: str, asked_at: datetime) -> Window:
    s, e = parse_time(start, name="start"), parse_time(end, name="end")
    if e < s:
        raise TimeParseError(f"end ({fmt(e)}) is before start ({fmt(s)}).")
    return Window(s, e, asked_at)
