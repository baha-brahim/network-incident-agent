"use client";

import { useRef, type KeyboardEvent } from "react";
import { Notice, buttonStyles } from "@/components/ui/notice";
import type { AsyncState } from "@/hooks/use-async";
import { API_URL } from "@/lib/api";
import type { DemoSummary, Meta } from "@/lib/types";
import { AskLive } from "./ask-live";
import { CaseList, CaseListSkeleton } from "./case-list";

export type Mode = "recorded" | "live";

const TABS: ReadonlyArray<readonly [Mode, string]> = [
  ["recorded", "Recorded cases"],
  ["live", "Ask live"],
];

interface Props {
  mode: Mode;
  onMode(mode: Mode): void;
  demos: AsyncState<DemoSummary[]>;
  meta: AsyncState<Meta>;
  onStartDemo(demo: DemoSummary): void;
  onStartLive(question: string): void;
}

export function Cases({ mode, onMode, demos, meta, onStartDemo, onStartLive }: Props) {
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const current = TABS.findIndex(([m]) => m === mode);
    const target =
      e.key === "ArrowRight"
        ? (current + 1) % TABS.length
        : e.key === "ArrowLeft"
          ? (current - 1 + TABS.length) % TABS.length
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? TABS.length - 1
              : -1;
    if (target < 0) return;
    e.preventDefault();
    onMode(TABS[target][0]);
    tabs.current[target]?.focus();
  }

  return (
    <section className="cases" aria-labelledby="cases-title">
      <div className="cases-head">
        <h2 id="cases-title">Choose a case</h2>
        <div className="switch" role="tablist" aria-label="Where the question comes from" onKeyDown={onKeyDown}>
          {TABS.map(([m, label], i) => (
            <button
              key={m}
              ref={(el) => {
                tabs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={`cases-tab-${m}`}
              aria-selected={mode === m}
              aria-controls={mode === m ? `cases-panel-${m}` : undefined}
              tabIndex={mode === m ? 0 : -1}
              onClick={() => onMode(m)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div role="tabpanel" id={`cases-panel-${mode}`} aria-labelledby={`cases-tab-${mode}`}>
        {mode === "recorded" ? (
          demos.loading ? (
            <CaseListSkeleton />
          ) : demos.error || !demos.data ? (
            <Notice
              role="alert"
              tone="danger"
              title="The recorded cases could not be loaded"
              action={
                <button
                  type="button"
                  className={buttonStyles.secondary}
                  onClick={() => {
                    demos.reload();
                    meta.reload();
                  }}
                >
                  Try again
                </button>
              }
            >
              The server did not answer.
              {process.env.NODE_ENV !== "production" ? (
                <>
                  {" "}
                  Expected at <span className="mono">{API_URL}</span>.
                </>
              ) : null}
            </Notice>
          ) : demos.data.length === 0 ? (
            <Notice
              title="There are no recorded cases yet"
              action={
                <button type="button" className={buttonStyles.secondary} onClick={() => onMode("live")}>
                  Ask live
                </button>
              }
            >
              The server has no recordings to play. You can still ask your own question.
            </Notice>
          ) : (
            <CaseList demos={demos.data} onPick={onStartDemo} />
          )
        ) : (
          <AskLive meta={meta.data} metaError={!!meta.error} examples={demos.data ?? []} onSubmit={onStartLive} onWatchRecorded={() => onMode("recorded")} />
        )}
      </div>
    </section>
  );
}
