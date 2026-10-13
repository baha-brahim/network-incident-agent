"use client";

import { useEffect, useMemo, useState } from "react";
import { argSummary } from "@/lib/args";
import type { RunView, ToolStep } from "@/lib/investigation";
import { TOOLS, toolLabel } from "@/lib/labels";
import { argNodeIds, type Network } from "@/lib/network";

/** The nodes the agent is asking about right now, and a line saying so. */
export interface Probe {
  ids: ReadonlySet<string>;
  text: string;
  busy: boolean;
}

/** Recorded calls resolve in a moment; the probe is held this long, at normal speed, so it can be seen. */
const HOLD_MS = 1500;
const NO_IDS: ReadonlySet<string> = new Set();

interface ProbeOptions {
  animate: boolean;
  playing: boolean;
  speed: number;
}

const lowerFirst = (s: string): string => (/^[A-Z][a-z]/.test(s) ? s[0].toLowerCase() + s.slice(1) : s);

function listIds(ids: string[]): string {
  return ids.length > 3 ? `${ids.slice(0, 3).join(", ")} and ${ids.length - 3} more` : ids.join(", ");
}

export function useProbe(view: RunView, net: Network, { animate, playing, speed }: ProbeOptions): Probe {
  let last: ToolStep | null = null;
  for (let i = view.steps.length - 1; i >= 0 && !last; i--) {
    const s = view.steps[i];
    if (s.kind === "tool") last = s;
  }
  const lastId = last?.id ?? null;
  const [expired, setExpired] = useState<string | null>(null);
  if (lastId === null && expired !== null) setExpired(null);

  useEffect(() => {
    if (!animate || !playing || !lastId) return;
    const timer = window.setTimeout(() => setExpired(lastId), HOLD_MS / speed);
    return () => window.clearTimeout(timer);
  }, [lastId, animate, playing, speed]);

  const busy = !!last && animate && playing && !view.report && (last.status === "running" || expired !== lastId);

  return useMemo<Probe>(() => {
    const named = busy && last ? argNodeIds(last.args).filter((id) => net.byId.has(id)) : [];
    const what = last ? argSummary(last.args) : "";
    let text = "Waiting for the first tool call.";
    if (view.report) {
      text = net.rootId ? `${net.rootLabel}: ${net.rootId}.` : "Report ready. No single node is named as the cause.";
    } else if (last && busy) {
      text = named.length
        ? `Probing ${listIds(named)}: ${lowerFirst(toolLabel(last.tool))}`
        : `${TOOLS[last.tool]?.verb ?? toolLabel(last.tool)}${what ? ` · ${what}` : ""}`;
    } else if (last) {
      text = `Last call: ${toolLabel(last.tool)}${what ? ` · ${what}` : ""}`;
    }
    return { ids: named.length ? new Set(named) : NO_IDS, text, busy };
  }, [busy, last, net, view.report]);
}
