from pathlib import Path

from incident_agent.simulator.plots import make_plots
from tests.fixtures_world import make_fixture_world


def test_make_plots_writes_one_file_per_scenario_and_region(tmp_path: Path) -> None:
    world = make_fixture_world()
    paths = make_plots(world, tmp_path / "plots")

    expected = {f"{s}.png" for s in world.scenarios["scenario_id"]} | {
        f"overview_{r}.png" for r in world.regions["region_id"]
    }
    assert {p.name for p in paths} == expected
    for path in paths:
        assert path.parent == tmp_path / "plots"
        assert path.read_bytes().startswith(b"\x89PNG")
        assert path.stat().st_size > 5_000
