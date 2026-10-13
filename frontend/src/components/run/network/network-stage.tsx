"use client";

import { useId, useMemo, useRef } from "react";
import { REGIONS } from "@/lib/labels";
import { networkSummary, windowText, type Network } from "@/lib/network";
import { isMultiRegion, layoutNetwork, planLabels } from "@/lib/network-layout";
import { joinWords, regionNames } from "@/lib/steps";
import { DiagramLines } from "./diagram-lines";
import { NodeView } from "./node-view";
import { StageFoot } from "./stage-foot";
import type { Probe } from "./use-probe";
import { useElementSize } from "./use-element-size";
import { useTweenedPositions, type Point } from "./use-tween";
import "./network.css";

export interface NetworkStageProps {
  net: Network;
  probe: Probe;
  /** Switches the motion on: nodes grow in, lines draw, the conclusion is marked step by step. */
  animate?: boolean;
  selectedId?: string | null;
  onSelect?(id: string | null): void;
  /** Nodes outlined because something else on the page points at them. */
  highlightIds?: ReadonlySet<string>;
}

const NO_IDS: ReadonlySet<string> = new Set();
const noop = () => {};

function whereText(net: Network): string {
  const scope = net.scope;
  if (!scope) return "";
  if (scope.nationwide) return "Nationwide";
  const names = regionNames(scope.region_ids.filter((r) => r in REGIONS));
  return names.length ? joinWords(names) : "";
}

/** A diagram of the part of the network under investigation, drawn as the agent learns it. */
export function NetworkStage({ net, probe, animate = true, selectedId = null, onSelect = noop, highlightIds = NO_IDS }: NetworkStageProps) {
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const summaryId = useId();
  const size = useElementSize(canvasRef);
  const layout = useMemo(() => (size.w > 0 ? layoutNetwork(net, size.w, size.h) : null), [net, size.w, size.h]);

  const focus = useMemo(() => {
    const ids = new Set<string>([...probe.ids, ...highlightIds]);
    if (selectedId) ids.add(selectedId);
    return ids;
  }, [probe.ids, highlightIds, selectedId]);
  const labels = useMemo(() => (layout ? planLabels(net, layout, focus) : null), [net, layout, focus]);

  const target = useMemo(() => {
    const m = new Map<string, Point>();
    if (layout) for (const [id, p] of layout.places) m.set(id, { x: p.x, y: p.y });
    return m;
  }, [layout]);
  const shown = useTweenedPositions(target, animate);
  const posOf = (id: string): Point | null => shown.get(id) ?? target.get(id) ?? null;

  const where = whereText(net);
  const title = where || (net.scope ? "Network" : "Network under investigation");
  const when = windowText(net.scope);
  const summary = networkSummary(net, where || "the network under investigation");
  const fade = net.concluded && net.verdict !== "inconclusive" && net.rootId !== null;

  return (
    <section
      className="nws"
      aria-label="Network diagram"
      data-animate={animate ? "" : undefined}
      data-regions={isMultiRegion(net) ? "" : undefined}
      data-concluded={net.concluded ? "" : undefined}
      data-verdict={net.verdict ?? undefined}
    >
      <header className="nws-head">
        <strong>{title}</strong>
        {when ? (
          <>
            <span aria-hidden="true"> · </span>
            <span className="mono">{when}</span>
            <span>, Africa/Tunis</span>
          </>
        ) : (
          <span> · The scope is not set yet</span>
        )}
      </header>

      <div ref={canvasRef} className="nws-canvas" role="group" aria-label="Nodes" aria-describedby={summaryId}>
        <p id={summaryId} className="sr-only">
          {summary}
        </p>
        {layout && labels ? (
          <>
            <DiagramLines net={net} layout={layout} posOf={posOf} highlight={highlightIds} fade={fade} />
            {net.nodes.map((node) => {
              const place = layout.places.get(node.id);
              const pos = posOf(node.id);
              if (!place || !pos) return null;
              return (
                <NodeView
                  key={node.id}
                  node={node}
                  net={net}
                  place={place}
                  pos={pos}
                  label={labels.get(node.id)}
                  probing={probe.ids.has(node.id)}
                  highlighted={highlightIds.has(node.id)}
                  selected={selectedId === node.id}
                  dimmed={fade && !node.flags.root && !node.flags.affected}
                  onSelect={onSelect}
                />
              );
            })}
          </>
        ) : null}
        {net.nodes.length === 0 ? <p className="nws-empty">Nothing located yet. Nodes appear as the agent finds them.</p> : null}
      </div>

      <StageFoot net={net} layout={layout} probe={probe} />
    </section>
  );
}
