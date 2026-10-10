"""Run the agent on cases: variants, one case with quota handling, and a resumable batch.

A case that fails for a reason outside the agent (quota, outage, crash) is saved with
`CaseArtifact.error` and is not scored. When the daily quota is gone the run stops, saves
nothing for the case in flight, and the next invocation picks it up again.
"""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Engine, create_engine

from incident_agent.agent.config import AgentConfig
from incident_agent.agent.graph import investigate
from incident_agent.agent.nodes import ToolExecutor
from incident_agent.agent.reference import Reference
from incident_agent.agent.state import RunResult
from incident_agent.agent.tools import execute_tool
from incident_agent.agent.tools.common import error_result
from incident_agent.agent.types import ToolContext, ToolResult
from incident_agent.config import get_settings
from incident_agent.evals.cases import (
    PlannedCase,
    QuestionMode,
    load_planned_cases,
    load_topology,
    select_cases,
    stratified,
)
from incident_agent.evals.prepare import loaded_seed, resolve_targets
from incident_agent.evals.rundir import RunDir, RunMeta
from incident_agent.evals.scoring import CaseScore, Topology, score_case
from incident_agent.evals.types import CaseArtifact
from incident_agent.llm.errors import DAILY_QUOTA_COOLDOWN, classify
from incident_agent.llm.runner import LLMRunner, Runner

# --- variants ---------------------------------------------------------------------------------


class VariantUnavailable(RuntimeError):
    """A variant needs a switch that the agent does not have."""


@dataclass(frozen=True)
class Variant:
    name: str
    description: str
    config: Mapping[str, Any] = field(default_factory=dict)  # AgentConfig overrides
    disabled_tools: tuple[str, ...] = ()  # tools the model is not told about


VARIANTS: dict[str, Variant] = {
    v.name: v
    for v in (
        Variant("default", "The agent as designed."),
        Variant(
            "no-gate",
            "The completeness gate is off: the model may stop without the nudge to check "
            "maintenance, changes and external events.",
            {"completeness_gate": False},
        ),
        Variant(
            "no-runbooks",
            "The search_runbooks tool is removed from the tool list.",
            disabled_tools=("search_runbooks",),
        ),
    )
}


def get_variant(name: str) -> Variant:
    try:
        return VARIANTS[name]
    except KeyError:
        raise ValueError(f"unknown variant {name!r}; choose from {', '.join(VARIANTS)}") from None


def agent_config_for(variant: Variant) -> AgentConfig:
    """The agent configuration of a variant. Tool removal needs `AgentConfig.disabled_tools`."""
    values: dict[str, Any] = dict(variant.config)
    if variant.disabled_tools:
        if "disabled_tools" not in AgentConfig.model_fields:
            raise VariantUnavailable(
                f"variant {variant.name!r} removes tools from the model's tool list, which "
                "needs an AgentConfig.disabled_tools setting that this agent does not have yet."
            )
        values["disabled_tools"] = variant.disabled_tools
    return AgentConfig(**values)


def executor_for(variant: Variant) -> ToolExecutor | None:
    """Refuses a disabled tool should the model call it anyway; None when nothing is disabled."""
    if not variant.disabled_tools:
        return None
    disabled = set(variant.disabled_tools)

    def execute(name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if name in disabled:
            return error_result(name, args, f"Unknown tool {name!r}.")
        return execute_tool(name, args, ctx)

    return execute


# --- failures that are not the agent's -------------------------------------------------------

FailureKind = Literal["daily_quota", "rate_limit", "transient", "cache_miss", "crash"]
_SEVERITY: tuple[FailureKind, ...] = (
    "daily_quota",
    "rate_limit",
    "transient",
    "cache_miss",
    "crash",
)
DEFAULT_WAIT_SECONDS = 60.0


@dataclass(frozen=True)
class InfraFailure:
    kind: FailureKind
    message: str
    wait_seconds: float = 0.0


class QuotaExhausted(RuntimeError):
    """The model provider will not answer any more today (or for too long to wait)."""


def _classify_text(text: str) -> tuple[FailureKind, float] | None:
    if "CacheMiss" in text:
        return "cache_miss", 0.0
    info = classify(Exception(text))
    if info.kind == "other" and "cooling down" in text:
        return "rate_limit", DEFAULT_WAIT_SECONDS  # the runner is already waiting out a limit
    if info.kind == "rate_limit":
        return (
            "daily_quota" if info.cooldown >= DAILY_QUOTA_COOLDOWN else "rate_limit"
        ), info.cooldown
    if info.kind == "transient":
        return "transient", info.cooldown
    return None


def infra_failure(result: RunResult) -> InfraFailure | None:
    """Why a finished run says nothing about the agent, or None if it is a real answer.

    The graph turns a failed model call into a step with `error`. A rate limit, an outage or a
    missing recording is not the agent's fault; a malformed or empty model answer is (it leads to
    an inconclusive report, which is scored as such).
    """
    found: list[InfraFailure] = []
    for step in result.steps:
        if step.error:
            kind = _classify_text(step.error + " " + " ".join(step.attempts))
            if kind is not None:
                found.append(InfraFailure(kind[0], step.error[:300], kind[1]))
    if result.error and not result.error.startswith("conclude failed"):
        found.append(InfraFailure("crash", result.error[:300]))
    if not found:
        return None
    return min(found, key=lambda f: _SEVERITY.index(f.kind))


# --- one case ---------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def run_case(
    planned: PlannedCase,
    *,
    runner: Runner,
    engine: Engine,
    variant: Variant,
    run_name: str,
    agent_model: str,
    reference: Reference | None = None,
    tool_executor: ToolExecutor | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_waits: int = 3,
    max_wait_seconds: float = 180.0,
) -> CaseArtifact:
    """Investigate one case. Waits out per-minute limits; raises `QuotaExhausted` otherwise.

    Steps that already succeeded are in the response cache, so a retry repeats only the call
    that failed.
    """
    case = planned.case
    config = agent_config_for(variant)
    executor = tool_executor or executor_for(variant)

    def artifact(result: RunResult | None, error: str | None) -> CaseArtifact:
        return CaseArtifact(
            case=case,
            truth=planned.truth,
            run_name=run_name,
            variant=variant.name,
            agent_model=agent_model,
            result=result,
            error=error,
            created_at=_now(),
        )

    waits = 0
    while True:
        try:
            result = investigate(
                case.question,
                case.asked_at,
                runner=runner,
                ctx=ToolContext(engine=engine, asked_at=case.asked_at),
                store=None,
                config=config,
                reference=reference,
                tool_executor=executor,
            )
        except Exception as exc:
            return artifact(None, f"crash: {type(exc).__name__}: {str(exc)[:300]}")
        failure = infra_failure(result)
        if failure is None:
            return artifact(result, None)
        waitable = failure.kind in ("rate_limit", "transient")
        if failure.kind == "daily_quota" or (
            failure.kind == "rate_limit"
            and (waits >= max_waits or failure.wait_seconds > max_wait_seconds)
        ):
            raise QuotaExhausted(f"{failure.kind}: {failure.message}")
        if waitable and waits < max_waits:
            waits += 1
            sleep(max(failure.wait_seconds, 1.0))
            continue
        return artifact(result, f"{failure.kind}: {failure.message}")


# --- a batch ----------------------------------------------------------------------------------


@dataclass
class BatchResult:
    executed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # executed, but saved with an error
    skipped_done: list[str] = field(default_factory=list)
    skipped_errors: list[str] = field(default_factory=list)  # earlier errors left alone
    not_run: int = 0  # pending cases left because of --max-cases or a stop
    stopped: str | None = None  # why the run stopped early (quota)


ProgressFn = Callable[[int, int, CaseArtifact], None]


def run_batch(
    run: RunDir,
    cases: Sequence[PlannedCase],
    run_one: Callable[[PlannedCase], CaseArtifact],
    *,
    retry_errors: bool = False,
    max_cases: int | None = None,
    progress: ProgressFn | None = None,
) -> BatchResult:
    """Run the cases that are not done, in order, saving each artifact as soon as it exists."""
    out = BatchResult()
    pending: list[PlannedCase] = []
    for planned in cases:
        state = run.case_state(planned.case_id)
        if state == "done":
            out.skipped_done.append(planned.case_id)
        elif state == "error" and not retry_errors:
            out.skipped_errors.append(planned.case_id)
        else:
            pending.append(planned)
    todo = pending if max_cases is None else pending[: max(max_cases, 0)]
    out.not_run = len(pending) - len(todo)
    for n, planned in enumerate(todo, 1):
        try:
            artifact = run_one(planned)
        except QuotaExhausted as exc:
            out.stopped = str(exc)
            out.not_run += len(todo) - n + 1
            break
        run.save_artifact(artifact)
        out.executed.append(planned.case_id)
        if artifact.error is not None:
            out.errors.append(planned.case_id)
        if progress:
            progress(n, len(todo), artifact)
    return out


def progress_line(n: int, total: int, artifact: CaseArtifact, topology: Topology) -> str:
    """One line per case: id, verdict, calls, tokens, seconds."""
    head = f"[{n}/{total}] {artifact.case.case_id:<20}"
    score: CaseScore = score_case(artifact, topology)
    if score.status == "error":
        return f"{head} ERROR  {score.error}"
    assert artifact.result is not None
    usage = artifact.result.usage
    mark = "ok" if score.rca_lenient else "WRONG"
    cached = f" ({usage.cached_calls} cached)" if usage.cached_calls else ""
    return (
        f"{head} {score.kind}/{score.difficulty}  verdict={score.report_classification}/"
        f"{score.report_category}@{score.report_node} {mark}  "
        f"calls llm={usage.llm_calls}{cached} tool={usage.tool_calls}  "
        f"tokens={score.total_tokens}  {score.wall_seconds:.1f}s"
    )


# --- a whole run ------------------------------------------------------------------------------


@dataclass
class RunOptions:
    name: str
    seed: int
    variant: str = "default"
    questions: QuestionMode = "first"
    only: list[str] | None = None
    max_cases: int | None = None
    retry_errors: bool = False
    cache_mode: Literal["readwrite", "replay"] = "readwrite"
    model: str | None = None  # "provider:model"; default is the configured agent model
    database: str | None = None
    runs_dir: Path | None = None


def _check_or_create_meta(
    run: RunDir, opts: RunOptions, model: str, total: int, database: str
) -> RunMeta:
    existing = run.read_meta()
    now = _now().isoformat(timespec="seconds")
    if existing is None:
        from incident_agent.evals.cases import split_of

        return RunMeta(
            name=opts.name,
            seed=opts.seed,
            split=split_of(opts.seed),
            variant=opts.variant,
            agent_model=model,
            questions=opts.questions,
            cases_total=total,
            database=database,
            created_at=now,
            updated_at=now,
        )
    mismatch = [
        f"{what} is {have!r} in the run, {want!r} now"
        for what, have, want in (
            ("seed", existing.seed, opts.seed),
            ("variant", existing.variant, opts.variant),
            ("model", existing.agent_model, model),
            ("questions", existing.questions, opts.questions),
        )
        if have != want
    ]
    if mismatch:
        raise ValueError(
            f"run {opts.name!r} already exists with other settings ({'; '.join(mismatch)}). "
            "Use a new --name: one run is one seed, variant and model."
        )
    return existing.model_copy(update={"cases_total": total, "updated_at": now})


def execute_run(
    opts: RunOptions,
    *,
    runner: Runner | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> BatchResult:
    """Run (or resume) `opts.name` against the seed's evaluation database."""
    settings = get_settings()
    variant = get_variant(opts.variant)
    agent_config_for(variant)  # fail early when the variant cannot run
    model = opts.model or settings.agent_model
    targets = resolve_targets(opts.seed, database=opts.database, settings=settings)
    owner = create_engine(targets.owner_url)
    agent = create_engine(targets.agent_url)
    try:
        if loaded_seed(owner) != str(opts.seed):
            raise RuntimeError(
                f"{targets.name} does not hold the world of seed {opts.seed}; "
                f"run `evals prepare --seed {opts.seed}` first."
            )
        everything = load_planned_cases(owner, opts.seed, opts.questions)
        topology = load_topology(owner)
        chosen = select_cases(stratified(everything), opts.only)
        run = RunDir(opts.name, opts.runs_dir)
        meta = _check_or_create_meta(run, opts, model, len(everything), targets.name)
        run.write_topology(topology)
        reference = Reference.load(agent)
        llm = runner or LLMRunner(
            "agent", chain=[model], cache_mode=opts.cache_mode, settings=settings
        )
        log(
            f"run {opts.name}: seed {opts.seed}, variant {opts.variant}, model {model}, "
            f"cache {opts.cache_mode}, {len(chosen)} of {len(everything)} cases selected"
        )

        def run_one(planned: PlannedCase) -> CaseArtifact:
            return run_case(
                planned,
                runner=llm,
                engine=agent,
                variant=variant,
                run_name=opts.name,
                agent_model=model,
                reference=reference,
                sleep=sleep,
            )

        def show(n: int, total: int, artifact: CaseArtifact) -> None:
            log(progress_line(n, total, artifact, topology))

        result = run_batch(
            run,
            chosen,
            run_one,
            retry_errors=opts.retry_errors,
            max_cases=opts.max_cases,
            progress=show,
        )
        meta.invocations.append(
            {
                "at": _now().isoformat(timespec="seconds"),
                "cache_mode": opts.cache_mode,
                "only": opts.only,
                "max_cases": opts.max_cases,
                "retry_errors": opts.retry_errors,
                "executed": len(result.executed),
                "errors": len(result.errors),
                "skipped": len(result.skipped_done) + len(result.skipped_errors),
                "stopped": result.stopped,
            }
        )
        run.write_meta(meta.model_copy(update={"updated_at": _now().isoformat(timespec="seconds")}))
        return result
    finally:
        owner.dispose()
        agent.dispose()
