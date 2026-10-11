"use client";

import { createContext, useContext } from "react";
import type { RunView } from "@/lib/investigation";

export interface RunContextValue {
  view: RunView;
  selectedId: string | null;
  /** The citation that sent the reader to the selected step, so its evidence row can be marked. */
  focusRef: string | null;
  /** Select a step (shows it in the detail panel). `flash` also draws the eye to it in the timeline. */
  selectStep(id: string, options?: { flash?: boolean; ref?: string }): void;
}

export const RunContext = createContext<RunContextValue | null>(null);

export function useRunContext(): RunContextValue | null {
  return useContext(RunContext);
}
