"use client";

import { AlertTriangle, Brain, Check, Compass, FileText, Gauge, ShieldCheck, ArrowDown } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { CLASSIFICATIONS, CONFIDENCE, TOOLS, toolLabel } from "@/lib/labels";
import { argSummary } from "@/lib/args";
import { cx } from "@/lib/cx";
import { compact, fmtSeconds } from "@/lib/format";
import { isPartialReport, type ModelStep, type NoteStep, type RunView, type ScopeStep, type Step, type ToolStep } from "@/lib/investigation";
import { missingSentence, plainText, regionNames, windowText } from "@/lib/steps";
import { ToolIcon } from "./tool-icon";

export const REPORT_STEP_ID = "report";

interface Props {
  view: RunView;
  selectedId: string | null;
  flashId: { id: string; n: number } | null;
  animate: boolean;
  running: boolean;
  onSelect(id: string): void;
  onOpenReport(): void;
}

export function Timeline({ view, selectedId, flashId, animate, running, onSelect, onOpenReport }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const count = view.steps.length;

  const toBottom = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, []);

  useEffect(() => {
    if (following && running) toBottom();
  }, [count, following, running, toBottom, view.report]);

  // Bring a step that was selected from a citation into view.
  useEffect(() => {
    if (!flashId) return;
    const el = scroller.current?.querySelector<HTMLElement>(`[data-step="${CSS.escape(flashId.id)}"]`);
    el?.scrollIntoView({ block: "nearest", behavior: "auto" });
  }, [flashId]);

  function onScroll() {
    const el = scroller.current;
    if (!el) return;
    setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight < 48);
  }

  function onKeyDown(e: KeyboardEvent<HTMLOListElement>) {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const items = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>("button[data-step]"));
    if (items.length === 0) return;
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    let next = current;
    if (e.key === "ArrowDown") next = Math.min(items.length - 1, current + 1);
    if (e.key === "ArrowUp") next = Math.max(0, current <= 0 ? 0 : current - 1);
    if (e.key === "Home") next = 0;
    if (e.key === "End") next = items.length - 1;
    e.preventDefault();
    items[next]?.focus();
    const id = items[next]?.dataset.step;
    if (id && id !== REPORT_STEP_ID) onSelect(id);
  }

  const enter = animate ? "step-enter" : "";

  return (
    <div className="relative flex min-h-0 flex-col">
      <div
        ref={scroller}
        onScroll={onScroll}
        className="scroll-thin max-h-[calc(100dvh-var(--header-h)-9.5rem)] min-h-40 overflow-y-auto overscroll-contain pr-1 lg:max-h-[calc(100dvh-var(--header-h)-9rem)]"
        tabIndex={-1}
      >
        <ol
          aria-label="Investigation steps"
          aria-live="polite"
          aria-relevant="additions"
          onKeyDown={onKeyDown}
          className="space-y-1 pb-1"
        >
          {view.steps.length === 0 ? (
            <li className="px-2.5 py-3 text-sm text-muted">Waiting for the first step…</li>
          ) : null}
          {view.steps.map((step) => (
            <li key={step.id} className={enter}>
              <StepRow
                step={step}
                selected={selectedId === step.id}
                flash={flashId?.id === step.id ? flashId.n : null}
                onSelect={onSelect}
              />
            </li>
          ))}
          {view.report ? (
            <li className={enter}>
              <button
                type="button"
                data-step={REPORT_STEP_ID}
                onClick={onOpenReport}
                className="press-row hover-surface flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left"
              >
                <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-accent text-accent-fg">
                  <FileText aria-hidden className="size-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{isPartialReport(view) ? "Incomplete report" : "Report written"}</span>
                  <span className="block text-xs text-muted">
                    {CLASSIFICATIONS[view.report.classification].label} · {CONFIDENCE[view.report.confidence].label.toLowerCase()}
                  </span>
                </span>
              </button>
            </li>
          ) : null}
        </ol>
      </div>
      {!following && running ? (
        <button
          type="button"
          onClick={() => {
            setFollowing(true);
            toBottom();
          }}
          className="press absolute bottom-2 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3 py-1.5 text-xs font-medium shadow-pop"
        >
          <ArrowDown aria-hidden className="size-3.5" />
          Jump to latest
        </button>
      ) : null}
    </div>
  );
}

function rowClass(selected: boolean, flash: number | null) {
  return cx(
    "press-row hover-surface relative flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left",
    selected && "bg-accent-soft shadow-[inset_2px_0_0_var(--accent)]",
    flash !== null && "flash",
  );
}

function StepRow({
  step,
  selected,
  flash,
  onSelect,
}: {
  step: Step;
  selected: boolean;
  flash: number | null;
  onSelect(id: string): void;
}) {
  switch (step.kind) {
    case "scope":
      return <ScopeRow step={step} selected={selected} flash={flash} onSelect={onSelect} />;
    case "tool":
      return <ToolRow step={step} selected={selected} flash={flash} onSelect={onSelect} />;
    case "note":
      return <NoteRow step={step} selected={selected} flash={flash} onSelect={onSelect} />;
    case "gate":
      return (
        <button
          type="button"
          data-step={step.id}
          aria-current={selected || undefined}
          onClick={() => onSelect(step.id)}
          key={flash ?? "x"}
          className={cx(
            "press relative flex w-full items-start gap-3 rounded-lg border border-warn/30 bg-warn-soft px-2.5 py-2 text-left",
            selected && "ring-2 ring-accent",
            flash !== null && "flash",
          )}
        >
          <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-warn" />
          <span className="min-w-0 text-sm">
            <span className="block font-medium text-warn">Completeness check</span>
            <span className="block text-muted">
              Before concluding, the agent was asked to go back and check what it had skipped: {missingSentence(step.data.missing)}.
            </span>
          </span>
        </button>
      );
    case "error":
      return (
        <button
          type="button"
          data-step={step.id}
          aria-current={selected || undefined}
          onClick={() => onSelect(step.id)}
          className={cx(
            "press relative flex w-full items-start gap-3 rounded-lg border border-danger/30 bg-danger-soft px-2.5 py-2 text-left",
            selected && "ring-2 ring-accent",
          )}
        >
          <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
          <span className="min-w-0 text-sm">
            <span className="block font-medium text-danger">The run hit an error</span>
            <span className="line-clamp-3 text-muted break-anywhere">{step.message}</span>
          </span>
        </button>
      );
    case "model":
      return <ModelLine step={step} />;
  }
}

type RowProps<T> = { step: T; selected: boolean; flash: number | null; onSelect(id: string): void };

function ScopeRow({ step, selected, flash, onSelect }: RowProps<ScopeStep>) {
  const d = step.data;
  const nodes = d.node_ids.length > 3 ? `${d.node_ids.slice(0, 3).join(", ")} and ${d.node_ids.length - 3} more` : d.node_ids.join(", ");
  const where = d.nationwide ? "nationwide" : [...regionNames(d.region_ids), nodes].filter(Boolean).join(", ") || "whole network";
  return (
    <button type="button" data-step={step.id} aria-current={selected || undefined} onClick={() => onSelect(step.id)} className={rowClass(selected, flash)} key={flash ?? "x"}>
      <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
        <Compass aria-hidden className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">Scope understood</span>
        <span className="block text-sm text-muted break-anywhere">
          “{d.symptom}” · {where}
        </span>
        <span className="block text-xs text-muted">{windowText(d.window_start, d.window_end)}{d.ongoing ? " · ongoing" : ""}</span>
      </span>
    </button>
  );
}

function ToolRow({ step, selected, flash, onSelect }: RowProps<ToolStep>) {
  const running = step.status === "running";
  const skipped = step.status === "skipped";
  const failed = step.status === "error";
  const verb = TOOLS[step.tool]?.verb ?? "Running a tool";
  const summary = argSummary(step.args);
  return (
    <button
      type="button"
      data-step={step.id}
      aria-current={selected || undefined}
      onClick={() => onSelect(step.id)}
      className={rowClass(selected, flash)}
      key={flash ?? "x"}
    >
      <span
        className={cx(
          "mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg",
          failed ? "bg-danger-soft text-danger" : running ? "bg-accent-soft text-accent" : "bg-surface-2 text-muted",
          skipped && "opacity-60",
        )}
      >
        <ToolIcon tool={step.tool} className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span className={cx("text-sm font-medium", skipped && "text-muted")}>{toolLabel(step.tool)}</span>
          <span className="font-mono text-[11px] text-muted">{step.id}</span>
          {skipped ? (
            <span className="rounded bg-surface-2 px-1.5 text-[11px] text-muted">skipped</span>
          ) : null}
        </span>
        {running ? (
          <span className="mt-0.5 flex items-center gap-2 text-sm text-muted">
            <span aria-hidden className="spinner inline-block size-3 shrink-0 rounded-full border-2 border-accent border-t-transparent" />
            <span className="min-w-0 break-anywhere">
              {verb}
              {summary ? <span className="text-muted"> · {summary}</span> : null}…
            </span>
          </span>
        ) : skipped ? (
          <span className="block text-sm text-muted">
            Repeated an earlier call{step.result?.duplicate_of ? ` (${step.result.duplicate_of})`  : ""}, so it was not run again.
          </span>
        ) : failed ? (
          <span className="line-clamp-2 text-sm text-danger break-anywhere">{plainText(step.result?.error ?? "The tool returned an error.")}</span>
        ) : (
          <span className="line-clamp-2 text-sm text-muted break-anywhere">{plainText(step.result?.headline ?? "")}</span>
        )}
      </span>
      {!running && !skipped && step.result ? (
        <span className="mt-1 flex shrink-0 items-center gap-1 font-mono text-[11px] text-muted">
          {failed ? null : <Check aria-hidden className="size-3 text-ok" />}
          {step.result.wall_ms} ms
        </span>
      ) : null}
    </button>
  );
}

function NoteRow({ step, selected, flash, onSelect }: RowProps<NoteStep>) {
  return (
    <button type="button" data-step={step.id} aria-current={selected || undefined} onClick={() => onSelect(step.id)} className={rowClass(selected, flash)} key={flash ?? "x"}>
      <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
        <Brain aria-hidden className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-accent">Reasoning</span>
        <span className="line-clamp-3 text-sm italic text-muted break-anywhere">{plainText(step.text)}</span>
      </span>
    </button>
  );
}

function ModelLine({ step }: { step: ModelStep }) {
  const d = step.data;
  return (
    <p aria-hidden className="flex items-center gap-1.5 py-0.5 pl-[2.9rem] font-mono text-[11px] leading-4 text-muted/90">
      <Gauge className="size-3 shrink-0" />
      <span className="min-w-0 truncate">
        {d.purpose} ·{" "}
        {d.error ? "failed" : `${compact(d.input_tokens)} in · ${compact(d.output_tokens)} out · ${fmtSeconds(d.latency_ms)}`}
        {d.fell_back ? " · fallback model" : ""}
      </span>
    </p>
  );
}
