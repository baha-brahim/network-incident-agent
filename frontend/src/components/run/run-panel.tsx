"use client";

import { ArrowLeft, FileText, ListTree, MousePointerClick } from "lucide-react";
import { useCallback, useMemo, useState, type ReactNode } from "react";
import { cx } from "@/lib/cx";
import { findStep, isSelectable, type RunView, type Step } from "@/lib/investigation";
import { announce } from "@/lib/steps";
import { DetailPanel } from "./detail-panel";
import { CostLine, ReportView } from "./report";
import { RunContext, type RunContextValue } from "./run-context";
import { Timeline } from "./timeline";

type Tab = "timeline" | "step" | "report";

interface Props {
  view: RunView;
  eyebrow: string;
  /** The status line and controls, shown in a bar that stays under the site header. */
  bar: ReactNode;
  /** Shown above the panels: a failure or a notice about the run. */
  notice?: ReactNode;
  animate: boolean;
  onBack?: () => void;
  backLabel?: string;
}

export function RunPanel({ view, eyebrow, bar, notice, animate, onBack, backLabel = "All cases" }: Props) {
  const [pinned, setPinned] = useState<string | null>(null);
  const [focusRef, setFocusRef] = useState<string | null>(null);
  const [flash, setFlash] = useState<{ id: string; n: number } | null>(null);
  // The reader's own choice of tab counts only until the report appears; then the report is shown.
  const [chosen, setChosen] = useState<{ tab: Tab; hadReport: boolean } | null>(null);
  const [showFullQuestion, setShowFullQuestion] = useState(false);

  const hasReport = !!view.report;
  const auto: Tab = hasReport ? "report" : "timeline";
  const tab: Tab = chosen && chosen.hadReport === hasReport ? chosen.tab : auto;
  const running = view.phase === "running";

  const latest = useMemo(() => {
    for (let i = view.steps.length - 1; i >= 0; i--) {
      const s = view.steps[i];
      if (s.kind === "tool" || s.kind === "scope") return s;
    }
    return null;
  }, [view.steps]);

  const selectedStep: Step | null = (pinned ? findStep(view, pinned) : null) ?? latest;
  const selectedId = selectedStep && isSelectable(selectedStep) ? selectedStep.id : null;

  const choose = useCallback(
    (next: Tab) => setChosen({ tab: next, hadReport: hasReport }),
    [hasReport],
  );

  const selectStep = useCallback(
    (id: string, options?: { flash?: boolean; ref?: string }) => {
      setPinned(id);
      setFocusRef(options?.ref ?? null);
      if (options?.flash) setFlash((f) => ({ id, n: (f?.n ?? 0) + 1 }));
      setChosen({ tab: "step", hadReport: hasReport });
    },
    [hasReport],
  );

  const context = useMemo<RunContextValue>(
    () => ({ view, selectedId, focusRef, selectStep }),
    [view, selectedId, focusRef, selectStep],
  );

  const lastStep = view.steps.at(-1);
  const spoken = announce(lastStep, view);
  const question = view.question;
  const longQuestion = question.length > 180;

  return (
    <RunContext.Provider value={context}>
      <div className="mx-auto w-full max-w-[88rem] px-4 pb-24 pt-4 sm:px-6 lg:pb-10">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {onBack ? (
            <button
              type="button"
              onClick={onBack}
              className="press hover-surface -ml-2 inline-flex min-h-9 items-center gap-1.5 rounded-lg px-2 text-sm text-muted hover:text-fg"
            >
              <ArrowLeft aria-hidden className="size-4" />
              {backLabel}
            </button>
          ) : null}
          <p className="text-xs font-medium uppercase tracking-wider text-muted">{eyebrow}</p>
        </div>

        <h1 className="max-w-[60rem] text-balance text-xl font-semibold leading-snug tracking-tight sm:text-2xl">
          <span className={cx("break-anywhere", longQuestion && !showFullQuestion && "line-clamp-3")}>{question || "Starting…"}</span>
        </h1>
        {longQuestion ? (
          <button type="button" className="mt-1 text-xs text-accent underline-offset-2 hover:underline" onClick={() => setShowFullQuestion((v) => !v)}>
            {showFullQuestion ? "Show less" : "Show the whole question"}
          </button>
        ) : null}

        <div className="sticky top-[var(--header-h)] z-20 -mx-4 mt-3 border-b border-line bg-bg/95 px-4 py-2 backdrop-blur sm:-mx-6 sm:px-6">
          {bar}
        </div>

        {notice ? <div className="mt-4">{notice}</div> : null}

        <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,23rem)_minmax(0,1fr)] xl:grid-cols-[minmax(0,25rem)_minmax(0,1fr)]">
          <section aria-label="Timeline" className={cx("min-w-0 lg:sticky lg:top-[calc(var(--header-h)+4.25rem)] lg:self-start", tab === "timeline" ? "block" : "max-lg:hidden")}>
            <h2 className="mb-2 hidden text-xs font-semibold uppercase tracking-wider text-muted lg:block">Timeline</h2>
            <Timeline
              view={view}
              selectedId={selectedId}
              flashId={flash}
              animate={animate}
              running={running}
              onSelect={(id) => selectStep(id)}
              onOpenReport={() => choose("report")}
            />
          </section>

          <section aria-label="Details" className={cx("min-w-0", tab === "timeline" ? "max-lg:hidden" : "block")}>
            <div role="group" aria-label="Show" className="mb-4 hidden gap-1 rounded-lg bg-surface-2 p-1 lg:inline-flex">
              <Segment active={tab !== "report"} onClick={() => choose("step")} icon={<MousePointerClick aria-hidden className="size-4" />}>
                Step
              </Segment>
              <Segment active={tab === "report"} disabled={!hasReport} onClick={() => choose("report")} icon={<FileText aria-hidden className="size-4" />}>
                Report
              </Segment>
            </div>

            {tab === "report" ? (
              <ReportView view={view} animate={animate} />
            ) : (
              <>
                {hasReport ? (
                  <button
                    type="button"
                    onClick={() => choose("report")}
                    className="press hover-surface -ml-2 mb-3 inline-flex min-h-9 items-center gap-1.5 rounded-lg px-2 text-sm text-accent"
                  >
                    <ArrowLeft aria-hidden className="size-4" />
                    Back to the report
                  </button>
                ) : null}
                <DetailPanel step={selectedStep} view={view} />
              </>
            )}
          </section>
        </div>

        {view.finished ? (
          <footer className="mt-8 border-t border-line pt-4">
            <CostLine view={view} />
          </footer>
        ) : null}

        <p role="status" aria-live="polite" className="sr-only">
          {spoken}
        </p>

        <nav
          aria-label="Views"
          className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-3 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
        >
          <BottomTab active={tab === "timeline"} onClick={() => choose("timeline")} icon={<ListTree aria-hidden className="size-5" />}>
            Timeline
          </BottomTab>
          <BottomTab active={tab === "step"} onClick={() => choose("step")} icon={<MousePointerClick aria-hidden className="size-5" />}>
            Step
          </BottomTab>
          <BottomTab active={tab === "report"} disabled={!hasReport} onClick={() => choose("report")} icon={<FileText aria-hidden className="size-5" />}>
            Report
          </BottomTab>
        </nav>
      </div>
    </RunContext.Provider>
  );
}

function Segment({
  active,
  disabled,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick(): void;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={cx(
        "press inline-flex min-h-8 items-center gap-1.5 rounded-md px-3 text-sm font-medium disabled:opacity-45",
        active ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
      )}
    >
      {icon}
      {children}
    </button>
  );
}

function BottomTab({
  active,
  disabled,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick(): void;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      aria-label={typeof children === "string" ? children : undefined}
      disabled={disabled}
      onClick={onClick}
      className={cx(
        "press flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium disabled:opacity-40",
        active ? "text-accent" : "text-muted",
      )}
    >
      {icon}
      {children}
    </button>
  );
}
