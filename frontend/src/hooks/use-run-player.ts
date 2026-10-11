"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { PlayerEngine, initialState, type PlayerState, type Speed } from "@/lib/player";

export { SPEEDS } from "@/lib/player";
export type { Failure, PlayerStatus, RunSource, Speed } from "@/lib/player";

export interface RunPlayer extends PlayerState {
  startDemo(demo: { id: string; title: string; question: string }): void;
  startLive(question: string): void;
  pause(): void;
  resume(): void;
  setSpeed(speed: Speed): void;
  skip(): void;
  restart(): void;
  reset(): void;
}

export function useRunPlayer(): RunPlayer {
  const [engine] = useState(() => new PlayerEngine());
  const state = useSyncExternalStore(engine.subscribe, engine.getSnapshot, () => initialState);
  useEffect(() => () => engine.stop(), [engine]);
  const [actions] = useState(() => ({
    startDemo: engine.startDemo.bind(engine),
    startLive: engine.startLive.bind(engine),
    pause: engine.pause.bind(engine),
    resume: engine.resume.bind(engine),
    setSpeed: engine.setSpeed.bind(engine),
    skip: engine.skip.bind(engine),
    restart: engine.restart.bind(engine),
    reset: engine.reset.bind(engine),
  }));
  return { ...state, ...actions };
}
