"""The recorded investigations: what each one asks, and the title and teaser the list shows.

Titles and teasers describe the situation, never the answer: the answer is the report.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoSpec:
    id: str
    title: str
    teaser: str
    question: str
    asked_at: str  # UTC


CATALOG: tuple[DemoSpec, ...] = (
    DemoSpec(
        "fiber-cut",
        "Three sites go dark",
        "Grand Tunis, a calm afternoon, then silence. Where did it start?",
        "Several sites in Grand Tunis went quiet yesterday afternoon. What happened?",
        "2026-09-22T07:38:00Z",
    ),
    DemoSpec(
        "planned-maintenance",
        "A quiet night in Tunis",
        "Traffic sags across the capital region after dark. Is something broken?",
        "Why did traffic drop in Grand Tunis last night?",
        "2026-09-07T07:08:00Z",
    ),
    DemoSpec(
        "power-outage",
        "The South goes quiet",
        "One afternoon, traffic in the South falls away. The clues are scattered.",
        "Why did traffic drop in the South yesterday afternoon?",
        "2026-10-01T07:41:00Z",
    ),
    DemoSpec(
        "config-push",
        "Calls that will not connect",
        "Connection attempts start failing across Sahel one morning.",
        "RRC success rate fell across several sites in Sahel yesterday morning. Why?",
        "2026-09-11T07:52:00Z",
    ),
    DemoSpec(
        "dns-degradation",
        "Everything feels slow",
        "Complaints arrive from every region at once, and nobody knows where to look.",
        "Latency complaints across the country yesterday afternoon, any idea?",
        "2026-09-21T08:09:00Z",
    ),
    DemoSpec(
        "stadium-event",
        "The evening surge",
        "Traffic climbs in Grand Tunis one evening. Good news or bad?",
        "Why did traffic jump in Grand Tunis yesterday evening?",
        "2026-09-26T07:33:00Z",
    ),
    DemoSpec(
        "alarm-storm",
        "A very noisy night",
        "One site would not stop alarming. Page someone, or go back to sleep?",
        "A lot of alarms came from S-SUD-007 last night. Should we worry?",
        "2026-09-17T08:52:00Z",
    ),
    DemoSpec(
        "congestion",
        "Too slow to stream",
        "An evening of complaints from one neighbourhood. What is slowing them down?",
        "Customers around S-TUN-004 complain about very slow speeds yesterday evening. Why?",
        "2026-09-27T07:06:00Z",
    ),
)

BY_ID: dict[str, DemoSpec] = {spec.id: spec for spec in CATALOG}
