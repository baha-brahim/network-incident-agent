"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FailureNotice, FailureScreen } from "@/components/run/failure";
import { RunScreen } from "@/components/run/run-screen";
import { buttonStyles } from "@/components/ui/notice";
import { useAsync } from "@/hooks/use-async";
import { useRunPlayer } from "@/hooks/use-run-player";
import { api } from "@/lib/api";
import { Home } from "./home";
import type { Mode } from "./cases";

const loadMeta = (signal: AbortSignal) => api.meta(signal);
const loadDemos = (signal: AbortSignal) => api.demos(signal);

export function InvestigateView() {
  const player = useRunPlayer();
  const meta = useAsync(loadMeta);
  const demos = useAsync(loadDemos);
  const [mode, setMode] = useState<Mode>("recorded");

  // /?case=<id> starts that recorded case once, and is then dropped from the address.
  const wantedCase = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (wantedCase.current === undefined) wantedCase.current = new URLSearchParams(window.location.search).get("case");
    const id = wantedCase.current;
    if (!id || !demos.data) return;
    wantedCase.current = null;
    window.history.replaceState(null, "", window.location.pathname);
    const demo = demos.data.find((d) => d.id === id);
    if (demo) player.startDemo(demo);
  }, [demos.data, player]);

  const backToCases = useCallback(() => {
    player.reset();
    meta.reload();
  }, [player, meta]);

  const watchReplay = useCallback(() => {
    player.reset();
    setMode("recorded");
  }, [player]);

  if (player.status !== "idle") {
    const silent = player.status === "failed" && player.view.steps.length === 0 && !player.view.runId;
    if (silent && player.failure) {
      const source = player.source;
      const failure = player.failure;
      // A live question is worth asking again after a dropped connection or a server error, not after a refusal.
      const retry =
        source?.kind === "demo"
          ? player.restart
          : source?.kind === "live" && (failure.kind === "unreachable" || failure.kind === "server")
            ? () => player.startLive(source.question)
            : undefined;
      return <FailureScreen failure={failure} onBack={backToCases} onWatchReplay={watchReplay} onRetry={retry} />;
    }
    const source = player.source;
    const label = source?.kind === "demo" ? `Recorded case · ${source.title}` : "Live investigation";
    return (
      <RunScreen
        view={player.view}
        animate={player.animate}
        source={label}
        player={player}
        onBack={backToCases}
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

  return <Home mode={mode} onMode={setMode} demos={demos} meta={meta} onStartDemo={player.startDemo} onStartLive={player.startLive} />;
}
