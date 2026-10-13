"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Board } from "@/components/run/board";
import { api, isAbort } from "@/lib/api";
import { buildBoard } from "@/lib/board";
import { emptyView } from "@/lib/investigation";
import type { DemoSummary, Recording } from "@/lib/types";
import { previewFrames } from "./preview-frames";
import { IDLE_LINE, previewLine } from "./preview-line";
import { usePreview } from "./use-preview";

const NO_PREVIEW = "The preview could not be loaded. The recorded case still plays.";
const NO_STEPS = "This recording has no steps to preview.";
const ALT = "An evidence board with a lane for each place the agent looks. Marks appear as the agent checks each source in a recorded investigation.";

interface Loaded {
  id: string;
  recording: Recording | null;
}

/** The recording of a case; `failed` once it could not be loaded. A different case starts over. */
function useRecording(id: string | null): {
  recording: Recording | null;
  failed: boolean;
} {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    api.demo(id, controller.signal).then(
      (recording) => setLoaded({ id, recording }),
      (error: unknown) => {
        if (!isAbort(error)) setLoaded({ id, recording: null });
      },
    );
    return () => controller.abort();
  }, [id]);
  const current = loaded?.id === id ? loaded : null;
  return {
    recording: current?.recording ?? null,
    failed: !!current && current.recording === null,
  };
}

interface Props {
  demo: DemoSummary | null;
  /** Why there is no preview, when there is none. */
  unavailable: string | null;
  onWatch(demo: DemoSummary): void;
}

/** The first recorded case playing on an inert board, stopped before the answer. */
export function HomePreview({ demo, unavailable, onWatch }: Props) {
  const { recording, failed } = useRecording(demo?.id ?? null);
  const frames = useMemo(() => (recording ? previewFrames(Array.isArray(recording.events) ? recording.events : []) : null), [recording]);
  const target = useRef<HTMLDivElement>(null);
  const { index, reduced } = usePreview(frames, target);

  const view = frames && index >= 0 ? frames[index].view : emptyView;
  const model = useMemo(() => buildBoard(view), [view]);
  // The last frame is the tallest board. It is laid out invisibly under the live one so the space is held from the start.
  const tallest = useMemo(() => (frames && frames.length > 0 ? buildBoard(frames[frames.length - 1].view) : null), [frames]);
  const empty = !!frames && frames.length === 0;
  const line = frames && index >= 0 ? previewLine(view, model) : failed ? NO_PREVIEW : empty ? NO_STEPS : IDLE_LINE;

  return (
    <div className="home-hero">
      <p className="home-now" aria-hidden>
        {frames && index >= 0 ? <span className="here">{line}</span> : line}
      </p>
      <div ref={target} className="home-board" role="img" aria-label={ALT}>
        <div className="home-board-stack">
          {tallest ? (
            <div className="home-board-size" aria-hidden inert>
              <Board model={tallest} inert animate={false} />
            </div>
          ) : null}
          <Board model={model} inert animate={!reduced} />
        </div>
      </div>
      <p className="home-caption">
        {demo ? (
          <>
            Recorded case: {demo.title.trim()}.{" "}
            <button type="button" className="link" onClick={() => onWatch(demo)}>
              Watch the full investigation
            </button>
          </>
        ) : (
          (unavailable ?? "Loading the first recorded case.")
        )}
      </p>
    </div>
  );
}
