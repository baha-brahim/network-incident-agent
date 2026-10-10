"""Every tunable of the synthetic network in one frozen dataclass."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegionSpec:
    region_id: str
    name: str
    lat: float
    lon: float
    n_sites: int
    n_links: int
    upf_id: str
    urban_frac: float
    suburban_frac: float
    localities: tuple[str, ...]


@dataclass(frozen=True)
class ScenarioSpec:
    """One planned scenario.

    `overlap_group` pairs two scenarios (an anchor, listed first, and a follower) that must
    overlap in time in different regions. `start_hours` overrides the kind's usual local start
    window; hi may exceed 24 to wrap past midnight.
    """

    kind: str
    difficulty: str
    overlap_group: str | None = None
    start_hours: tuple[float, float] | None = None


DEFAULT_REGIONS: tuple[RegionSpec, ...] = (
    RegionSpec(
        "TUN",
        "Grand Tunis",
        36.80,
        10.18,
        18,
        6,
        "CORE-UPF-01",
        0.50,
        0.35,
        (
            "Ariana",
            "La Marsa",
            "Carthage",
            "Bardo",
            "Manouba",
            "Ben Arous",
            "Rades",
            "La Goulette",
            "Megrine",
            "Ezzahra",
            "Hammam-Lif",
            "El Menzah",
            "Lac 1",
            "Lac 2",
            "Le Kram",
            "Soukra",
            "Mornag",
            "Mohamedia",
        ),
    ),
    RegionSpec(
        "SAH",
        "Sahel",
        35.83,
        10.60,
        12,
        4,
        "CORE-UPF-01",
        0.35,
        0.40,
        (
            "Sousse Centre",
            "Hammam Sousse",
            "Kantaoui",
            "Monastir",
            "Mahdia",
            "Msaken",
            "Kalaa Kebira",
            "Ksar Hellal",
            "Moknine",
            "Jemmal",
            "Khenis",
            "Bekalta",
        ),
    ),
    RegionSpec(
        "SFX",
        "Sfax",
        34.74,
        10.76,
        10,
        4,
        "CORE-UPF-02",
        0.40,
        0.35,
        (
            "Sfax Centre",
            "Sfax Sud",
            "Sakiet Ezzit",
            "Sakiet Eddaier",
            "Thyna",
            "Gremda",
            "Mahres",
            "Jebeniana",
            "El Hencha",
            "Agareb",
        ),
    ),
    RegionSpec(
        "SUD",
        "South",
        33.60,
        10.40,
        8,
        4,
        "CORE-UPF-02",
        0.20,
        0.35,
        (
            "Gabes",
            "Medenine",
            "Houmt Souk",
            "Zarzis",
            "Tataouine",
            "Mareth",
            "Matmata",
            "Ben Gardane",
        ),
    ),
)


def _spec(
    kind: str,
    difficulty: str,
    group: str | None = None,
    hours: tuple[float, float] | None = None,
) -> ScenarioSpec:
    return ScenarioSpec(kind, difficulty, group, hours)


# 24 incidents (10 easy / 9 medium / 5 hard) and 10 red herrings (4 / 4 / 2).
DEFAULT_PLAN: tuple[ScenarioSpec, ...] = (
    _spec("fiber_cut", "easy"),
    _spec("power_outage", "medium", "night", (22.0, 25.0)),
    _spec("fiber_cut", "medium", "night"),
    _spec("fiber_cut", "medium"),
    _spec("fiber_cut", "hard"),
    _spec("power_outage", "easy"),
    _spec("power_outage", "easy"),
    _spec("power_outage", "hard"),
    _spec("config_push", "easy"),
    _spec("config_push", "easy"),
    _spec("config_push", "medium"),
    _spec("config_push", "medium"),
    _spec("config_push", "hard"),
    _spec("dns_degradation", "easy"),
    _spec("dns_degradation", "medium"),
    _spec("dns_degradation", "hard"),
    _spec("congestion", "easy"),
    _spec("congestion", "medium", "evening"),
    _spec("congestion", "easy"),
    _spec("congestion", "hard"),
    _spec("link_degradation", "easy"),
    _spec("link_degradation", "medium", "evening"),
    _spec("link_degradation", "medium"),
    _spec("link_degradation", "easy"),
    _spec("planned_maintenance", "easy"),
    _spec("planned_maintenance", "medium"),
    _spec("planned_maintenance", "hard"),
    _spec("stadium_event", "easy"),
    _spec("stadium_event", "medium"),
    _spec("stadium_event", "hard"),
    _spec("public_holiday", "medium"),
    _spec("alarm_storm", "easy"),
    _spec("alarm_storm", "medium"),
    _spec("alarm_storm", "easy"),
)

# Peak (diurnal = 1, weekly = 1) active users of a typical cell, keyed "<tech>:<area_type>".
DEFAULT_PEAK_USERS: dict[str, float] = {
    "4G:urban": 85.0,
    "4G:suburban": 55.0,
    "4G:rural": 25.0,
    "5G:urban": 150.0,
    "5G:suburban": 100.0,
    "5G:rural": 45.0,
}


@dataclass(frozen=True)
class SimConfig:
    # Time (all local clock strings are Africa/Tunis, a fixed UTC+1).
    window_start_local: str = "2026-09-01T00:00"
    days: int = 30
    step_minutes: int = 15
    utc_offset_hours: int = 1
    now_local: str = "2026-10-01T09:00"
    timezone_name: str = "Africa/Tunis"

    # Topology.
    regions: tuple[RegionSpec, ...] = DEFAULT_REGIONS
    cells_per_site: int = 3
    microwave_links: int = 5
    near_venue_sites: int = 3
    venue_region: str = "TUN"
    venue_lat: float = 36.7476
    venue_lon: float = 10.2748
    venue_capacity_boost: float = 1.5

    # Normal behaviour.
    peak_users: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_PEAK_USERS))
    per_user_mbps_4g: float = 0.65
    per_user_mbps_5g: float = 1.5
    capacity_mbps_4g: float = 110.0
    capacity_mbps_5g: float = 420.0
    users_noise_sigma: float = 0.06
    regional_noise_sigma: float = 0.04
    noise_rho: float = 0.7
    micro_outage_prob: float = 1.0e-4

    # Background clutter.
    alarm_episodes_per_day: float = 6.5
    changes_per_day: float = 2.0
    noise_maintenance_windows: int = 6
    future_maintenance_windows: int = 2

    # Scenarios.
    scenario_plan: tuple[ScenarioSpec, ...] = DEFAULT_PLAN
    first_scenario_day: int = 2  # local day index; scenarios start on or after 3 Sept
    latest_scenario_end_local: str = "2026-09-30T20:00"
    scenario_margin_minutes: int = 60
    placement_attempts: int = 2000
    same_kind_gap_days: float = 5.0  # preferred spacing between scenarios of one kind
    holiday_urban_drop: float = 0.33
    holiday_residential_boost: float = 0.10
