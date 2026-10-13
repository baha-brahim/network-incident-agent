"use client";

import { CalendarDays, FileCog, Wrench } from "lucide-react";
import { nodeKind } from "@/lib/labels";
import { alarmTotal, kindWord, worstAlarm, type MarkerKind, type NetNode, type Network } from "@/lib/network";
import type { LabelLine, LabelPlan, NodePlace } from "@/lib/network-layout";
import { BOX, GlyphShape } from "./glyphs";
import type { Point } from "./use-tween";

interface NodeViewProps {
  node: NetNode;
  net: Network;
  place: NodePlace;
  pos: Point;
  label: LabelPlan | undefined;
  probing: boolean;
  highlighted: boolean;
  selected: boolean;
  /** The conclusion is drawn and this node is not part of it. */
  dimmed: boolean;
  onSelect(id: string | null): void;
}

function MarkerIcon({ kind }: { kind: MarkerKind }) {
  const props = { size: 12, strokeWidth: 2, "aria-hidden": true } as const;
  if (kind === "maintenance") return <Wrench {...props} />;
  if (kind === "change") return <FileCog {...props} />;
  return <CalendarDays {...props} />;
}

function Line({ line }: { line: LabelLine }) {
  return (
    <span className="nws-l" data-kind={line.kind} data-sev={line.severity} data-marker={line.marker}>
      <span className="nws-t">
        {line.kind === "marker" && line.marker ? <MarkerIcon kind={line.marker} /> : null}
        {line.text}
      </span>
    </span>
  );
}

function accessibleName(node: NetNode, net: Network): string {
  const worst = worstAlarm(node);
  const total = alarmTotal(node);
  return [
    node.id,
    nodeKind(node.id)?.toLowerCase() ?? kindWord(node.layer),
    worst ? `${total} ${total === 1 ? "alarm" : "alarms"}` : null,
    node.markers.length ? `${node.markers.length} ${node.markers.length === 1 ? "change, maintenance or event" : "changes, maintenance or events"}` : null,
    net.concluded && node.flags.root ? net.rootLabel.toLowerCase() : null,
    net.concluded && node.flags.affected ? "affected" : null,
  ]
    .filter(Boolean)
    .join(", ");
}

export function NodeView({ node, net, place, pos, label, probing, highlighted, selected, dimmed, onSelect }: NodeViewProps) {
  const s = place.scale;
  const hit = Math.max(24, Math.max(place.up, place.down, place.half) * 2 + 8);
  const total = alarmTotal(node);
  const worst = worstAlarm(node);
  const showRoot = net.concluded && node.flags.root && net.verdict !== "inconclusive";

  return (
    <div
      className="nws-node"
      style={{ transform: `translate(${pos.x.toFixed(1)}px, ${pos.y.toFixed(1)}px)` }}
      data-layer={node.layer}
      data-dot={place.dot ? "" : undefined}
      data-probe={probing ? "" : undefined}
      data-hl={highlighted ? "" : undefined}
      data-selected={selected ? "" : undefined}
      data-dim={dimmed && !highlighted && !selected ? "" : undefined}
      data-root={net.concluded && node.flags.root ? "" : undefined}
      data-affected={net.concluded && node.flags.affected ? "" : undefined}
    >
      <button
        type="button"
        className="nws-btn"
        aria-label={accessibleName(node, net)}
        aria-pressed={selected}
        style={{ width: hit, height: hit, marginLeft: -hit / 2, marginTop: -hit / 2 }}
        onClick={() => onSelect(selected ? null : node.id)}
      >
        <svg
          className="nws-glyph"
          width={BOX * s}
          height={BOX * s}
          viewBox={`${-BOX / 2} ${-BOX / 2} ${BOX} ${BOX}`}
          style={{ ["--k" as string]: 1 / s, marginLeft: (-BOX * s) / 2, marginTop: (-BOX * s) / 2 }}
          aria-hidden="true"
        >
          <circle className="nws-disc" r={place.dot ? 12 : 22} />
          <circle className="nws-ring-probe" r={place.dot ? 11 : 21} />
          <circle className="nws-ring-hl" r={place.dot ? 11 : 22} />
          {showRoot ? <circle className="nws-ring-root" r="23" pathLength={1} /> : null}
          <g className="nws-body">{place.dot ? <circle className="nws-shape" r="5" /> : <GlyphShape layer={node.layer} />}</g>
        </svg>
        {worst ? (
          <span className="nws-badge" data-sev={worst.severity} style={{ left: `calc(50% + ${place.half + 3 - 8}px)`, top: `calc(50% - ${place.up * 0.65 + 9}px)` }} aria-hidden="true">
            {total > 99 ? "99+" : total}
          </span>
        ) : null}
        {label ? (
          <span
            className="nws-lab"
            data-side={label.side}
            style={{ left: `calc(50% + ${label.dx.toFixed(1)}px)`, top: `calc(50% + ${label.dy.toFixed(1)}px)`, width: label.w }}
            aria-hidden="true"
          >
            {label.lines.map((line, i) => (
              <Line key={i} line={line} />
            ))}
          </span>
        ) : null}
      </button>
    </div>
  );
}
