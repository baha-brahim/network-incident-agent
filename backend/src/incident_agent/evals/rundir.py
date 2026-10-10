"""The files of one run: `evals/runs/<name>/`.

    run.json                what the run is (seed, variant, model) and the invocations so far
    topology.json           node -> parent, so scoring needs no database
    cases/<case_id>.json    one `CaseArtifact` per case
    grades/<case_id>.json   one `ReportGrade` per case (written by the grading commands)
    summary.json            scores and aggregates (written by `score`)

JSON is written with sorted keys, two-space indent, UTF-8 and LF endings, so that a re-run
shows up as a small diff.
"""

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from incident_agent.config import REPO_ROOT
from incident_agent.evals.scoring import Topology
from incident_agent.evals.types import CaseArtifact, ReportGrade, Split

RUNS_DIR = REPO_ROOT / "evals" / "runs"
CaseState = Literal["done", "error", "missing"]


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_text(path: Path, content: str) -> None:
    """Atomic write with LF endings on every platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(content.encode("utf-8"))
    os.replace(tmp, path)


class RunMeta(BaseModel):
    name: str
    seed: int
    split: Split
    variant: str
    agent_model: str
    questions: str  # first | all
    cases_total: int  # cases in the whole world for this question mode
    database: str
    created_at: str
    updated_at: str
    invocations: list[dict[str, Any]] = Field(default_factory=list)


class RunDir:
    def __init__(self, name: str, root: Path | None = None) -> None:
        self.name = name
        self.path = (root or RUNS_DIR) / name

    @property
    def meta_path(self) -> Path:
        return self.path / "run.json"

    @property
    def cases_dir(self) -> Path:
        return self.path / "cases"

    @property
    def grades_dir(self) -> Path:
        return self.path / "grades"

    @property
    def summary_path(self) -> Path:
        return self.path / "summary.json"

    @property
    def topology_path(self) -> Path:
        return self.path / "topology.json"

    def exists(self) -> bool:
        return self.meta_path.exists()

    # --- run.json / topology.json
    def read_meta(self) -> RunMeta | None:
        if not self.meta_path.exists():
            return None
        return RunMeta.model_validate_json(self.meta_path.read_text(encoding="utf-8"))

    def write_meta(self, meta: RunMeta) -> None:
        write_text(self.meta_path, dumps(meta.model_dump(mode="json")))

    def write_topology(self, topology: Topology) -> None:
        write_text(self.topology_path, dumps(topology.parents))

    def read_topology(self) -> Topology:
        parents = json.loads(self.topology_path.read_text(encoding="utf-8"))
        return Topology(parents=parents)

    # --- artifacts
    def artifact_path(self, case_id: str) -> Path:
        return self.cases_dir / f"{case_id}.json"

    def save_artifact(self, artifact: CaseArtifact) -> None:
        write_text(
            self.artifact_path(artifact.case.case_id), dumps(artifact.model_dump(mode="json"))
        )

    def load_artifact(self, case_id: str) -> CaseArtifact | None:
        path = self.artifact_path(case_id)
        if not path.exists():
            return None
        return CaseArtifact.model_validate_json(path.read_text(encoding="utf-8"))

    def load_artifacts(self) -> list[CaseArtifact]:
        if not self.cases_dir.exists():
            return []
        files = sorted(self.cases_dir.glob("*.json"))
        return [CaseArtifact.model_validate_json(f.read_text(encoding="utf-8")) for f in files]

    def case_state(self, case_id: str) -> CaseState:
        artifact = self.load_artifact(case_id)
        if artifact is None:
            return "missing"
        return "error" if artifact.error is not None or artifact.result is None else "done"

    # --- grades
    def load_grades(self) -> dict[str, ReportGrade]:
        if not self.grades_dir.exists():
            return {}
        grades = [
            ReportGrade.model_validate_json(f.read_text(encoding="utf-8"))
            for f in sorted(self.grades_dir.glob("*.json"))
        ]
        return {g.case_id: g for g in grades}

    def write_summary(self, summary: dict[str, Any]) -> None:
        write_text(self.summary_path, dumps(summary))
