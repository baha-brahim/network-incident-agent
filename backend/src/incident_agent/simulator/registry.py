"""Which scenario kinds a profile can use."""

from incident_agent.simulator.config import SimConfig
from incident_agent.simulator.drafts import ScenarioKind
from incident_agent.simulator.scenarios import SCENARIO_KINDS


def scenario_kinds(cfg: SimConfig) -> dict[str, ScenarioKind]:
    """The default kinds, plus the trap scenarios of the hard profile."""
    if cfg.profile == "hard":
        from incident_agent.simulator.hard import HARD_KINDS

        return {**SCENARIO_KINDS, **HARD_KINDS}
    return SCENARIO_KINDS
