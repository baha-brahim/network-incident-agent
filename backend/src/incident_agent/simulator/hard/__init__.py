"""The hard profile: scenarios built around a trap that a hasty investigator falls into.

Each trap scenario has a known correct answer that a careful investigator can derive from the
data with the documented method (timeline, scope, topology, calendar). Its `notes` start with
`trap=<name>;` and say what the trap is and which observation settles it.
"""

from functools import partial

from incident_agent.simulator.drafts import ScenarioKind
from incident_agent.simulator.hard.bad_change import apply_bad_change, sample_bad_change
from incident_agent.simulator.hard.match_day import (
    apply_match_day,
    apply_venue_noise,
    sample_match_day,
    sample_venue_noise,
)
from incident_agent.simulator.hard.missing_alarm import (
    apply_missing_fiber,
    apply_missing_power,
    sample_missing_fiber,
    sample_missing_power,
)
from incident_agent.simulator.hard.near_miss import apply_near_miss, sample_near_miss
from incident_agent.simulator.hard.pairs import apply_pair, sample_pair
from incident_agent.simulator.hard.root_change import apply_root_change, sample_root_change
from incident_agent.simulator.hard.scary_change import apply_scary, sample_scary

_ROOT = ["dns_upgrade", "dns_upgrade_silent", "power_param", "fiber_router"]
_ROOT += ["congestion_batch", "linkdeg_router"]
_BAD = ["maint_sibling", "flapping_link", "stadium_region"]
_NEAR = ["other_link", "starts_before", "overrun", "none_expected_power", "none_expected_fiber"]
_PAIR = ["power_fiber", "fiber_config", "linkdeg_power"]

HARD_KINDS: dict[str, ScenarioKind] = {}
for _v in _ROOT:
    HARD_KINDS[f"root_change_{_v}"] = ScenarioKind(
        f"root_change_{_v}", True, partial(sample_root_change, variant=_v), apply_root_change
    )
for _v in _BAD:
    HARD_KINDS[f"bad_change_{_v}"] = ScenarioKind(
        f"bad_change_{_v}", True, partial(sample_bad_change, variant=_v), apply_bad_change
    )
for _v in _NEAR:
    HARD_KINDS[f"near_miss_{_v}"] = ScenarioKind(
        f"near_miss_{_v}", True, partial(sample_near_miss, variant=_v), apply_near_miss
    )
for _v in _PAIR:
    HARD_KINDS[f"pair_{_v}"] = ScenarioKind(
        f"pair_{_v}", True, partial(sample_pair, variant=_v), apply_pair
    )
for _v in ("link", "site"):
    HARD_KINDS[f"scary_change_{_v}"] = ScenarioKind(
        f"scary_change_{_v}", False, partial(sample_scary, variant=_v), apply_scary
    )
HARD_KINDS["match_day_congestion"] = ScenarioKind(
    "match_day_congestion", True, sample_match_day, apply_match_day
)
HARD_KINDS["venue_noise"] = ScenarioKind(
    "venue_noise", False, sample_venue_noise, apply_venue_noise
)
HARD_KINDS["missing_alarm_fiber"] = ScenarioKind(
    "missing_alarm_fiber", True, sample_missing_fiber, apply_missing_fiber
)
HARD_KINDS["missing_alarm_power"] = ScenarioKind(
    "missing_alarm_power", True, sample_missing_power, apply_missing_power
)
