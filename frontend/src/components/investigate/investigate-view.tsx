"use client";

import { Radio, Repeat } from "lucide-react";
import { useCallback, useState } from "react";
import { FailureNotice, FailureScreen } from "@/components/run/failure";
import { PlayerBar } from "@/components/run/run-bar";
import { RunPanel } from "@/components/run/run-panel";
import { Notice, buttonStyles } from "@/components/ui/notice";
import { useAsync } from "@/hooks/use-async";
import { useRunPlayer } from "@/hooks/use-run-player";
import { api, API_URL } from "@/lib/api";
import { cx } from "@/lib/cx";
import { DemoCards, DemoCardsSkeleton } from "./demo-cards";
import { LiveForm } from "./live-form";

type Mode = "replay" | "live";

const loadMeta = (signal: AbortSignal) => api.meta(signal);
const loadDemos = (signal: AbortSignal) => api.demos(signal);

export function InvestigateView() {
  const player = useRunPlayer();
  const meta = useAsync(loadMeta);
  const demos = useAsync(loadDemos);
  const [mode, setMode] = useState<Mode>("replay");

  const backToCases = useCallback(() => {
    player.reset();
    meta.reload();
  }, [player, meta]);

  const watchReplay = useCallback(() => {
    player.reset();
    setMode("replay");
  }, [player]);

  if (player.status !== "idle") {
    const silent = player.status === "failed" && player.view.steps.length === 0 && !player.view.runId;
    if (silent && player.failure) {
      return (
        <FailureScreen
          failure={player.failure}
          onBack={backToCases}
          onWatchReplay={watchReplay}
          onRetry={player.source?.kind === "demo" ? player.restart : undefined}
        />
      );
    }
    const source = player.source;
    const eyebrow = source?.kind === "demo" ? `Recorded replay · ${source.title}` : "Live investigation";
    return (
      <RunPanel
        view={player.view}
        eyebrow={eyebrow}
        animate={player.animate}
        onBack={backToCases}
        bar={<PlayerBar player={player} />}
        notice={
          player.failure ? (
            <FailureNotice
              failure={player.failure}
              actions={
                source?.kind === "demo" ? (
                  <button type="button" className={buttonStyles.secondary} onClick={player.restart}>
                    Replay again
                  </button>
                ) : (
                  <button type="button" className={buttonStyles.secondary} onClick={watchReplay}>
                    Watch a recorded replay
                  </button>
                )
              }
            />
          ) : null
        }
      />
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-4 pb-16 pt-8 sm:px-6 sm:pt-12">
      <p className="text-xs font-medium uppercase tracking-wider text-muted">Network operations · synthetic network</p>
      <h1 className="mt-2 max-w-3xl text-balance text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
        Watch an agent investigate a network incident
      </h1>
      <p className="mt-3 max-w-2xl text-pretty text-base leading-7 text-muted">
        It queries KPIs, alarms, topology, changes and runbooks, the way an engineer would, then writes a report where every claim points to its
        evidence. Pick a case to watch it work.
      </p>

      <div role="group" aria-label="Mode" className="mt-8 inline-flex gap-1 rounded-xl bg-surface-2 p-1">
        <ModeButton active={mode === "replay"} onClick={() => setMode("replay")} icon={<Repeat aria-hidden className="size-4" />}>
          Replay
        </ModeButton>
        <ModeButton active={mode === "live"} onClick={() => setMode("live")} icon={<Radio aria-hidden className="size-4" />}>
          Live
        </ModeButton>
      </div>

      <div className="mt-5">
        {mode === "replay" ? (
          <section aria-label="Recorded cases">
            <p className="mb-4 max-w-2xl text-sm text-muted">
              Recorded investigations, played back at their original pace. No model is called, so you can run as many as you like.
            </p>
            {demos.loading ? (
              <DemoCardsSkeleton />
            ) : demos.error || !demos.data ? (
              <Notice
                role="alert"
                tone="danger"
                title="The recorded cases could not be loaded"
                action={
                  <button type="button" className={buttonStyles.secondary} onClick={demos.reload}>
                    Try again
                  </button>
                }
              >
                The server did not answer.
                {process.env.NODE_ENV !== "production" ? (
                  <>
                    {" "}
                    Expected at <span className="font-mono">{API_URL}</span>.
                  </>
                ) : null}
              </Notice>
            ) : demos.data.length === 0 ? (
              <Notice title="No recorded cases yet">The server has no recordings to play.</Notice>
            ) : (
              <DemoCards demos={demos.data} onPick={player.startDemo} />
            )}
          </section>
        ) : (
          <section aria-label="Live investigation" className="max-w-2xl">
            <p className="mb-4 text-sm text-muted">
              Ask your own question. The agent runs for real on a free model tier, so the number of live runs per day is limited.
            </p>
            <LiveForm
              meta={meta.data}
              metaError={!!meta.error}
              examples={demos.data ?? []}
              onSubmit={player.startLive}
              onWatchReplay={() => setMode("replay")}
            />
          </section>
        )}
      </div>
    </div>
  );
}

function ModeButton({ active, onClick, icon, children }: { active: boolean; onClick(): void; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cx(
        "press inline-flex min-h-10 items-center gap-2 rounded-lg px-4 text-sm font-medium",
        active ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
      )}
    >
      {icon}
      {children}
    </button>
  );
}
