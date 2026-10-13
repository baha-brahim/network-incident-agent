import { REGIONS } from "@/lib/labels";
import { plural } from "@/lib/format";
import type { Network } from "@/lib/network";
import { ROW_NAMES, type Layout, type NodePlace, type RegionGroup } from "@/lib/network-layout";
import type { Point } from "./use-tween";

interface LinesProps {
  net: Network;
  layout: Layout;
  posOf(id: string): Point | null;
  highlight: ReadonlySet<string>;
  /** Everything outside the conclusion is faded. */
  fade: boolean;
}

function edgePath(c: Point, cp: NodePlace, p: Point, pp: NodePlace): string {
  const y1 = c.y - cp.up;
  const y2 = p.y + pp.down;
  if (Math.abs(c.x - p.x) < 0.5) return `M${c.x.toFixed(1)} ${y1.toFixed(1)}V${y2.toFixed(1)}`;
  const bus = y1 - Math.min(20, Math.max(6, (y1 - y2) / 2));
  return `M${c.x.toFixed(1)} ${y1.toFixed(1)}V${bus.toFixed(1)}H${p.x.toFixed(1)}V${y2.toFixed(1)}`;
}

function groupCount(g: RegionGroup, compact: boolean): string {
  if (g.sites + g.others === 0) return "Nothing seen yet";
  if (compact) return [g.sites ? plural(g.sites, "site") : "", g.others ? `${g.others} other` : ""].filter(Boolean).join(", ");
  if (g.others === 0) return `${plural(g.sites, "site")} seen`;
  if (g.sites === 0) return `${plural(g.others, "link or router", "links and routers")} seen`;
  return `${plural(g.sites, "site")}, ${plural(g.others, "link or router", "links and routers")} seen`;
}

/** The drawn lines under the nodes: row names, the links between nodes, and the region frames. */
export function DiagramLines({ net, layout, posOf, highlight, fade }: LinesProps) {
  const { places } = layout;
  return (
    <svg className="nws-svg" width={layout.w} height={layout.h} aria-hidden="true">
      {layout.showRowNames
        ? layout.rows.map((r) => (
            <text key={r.layer} className="nws-rowname" x={14} y={r.y + 4}>
              {ROW_NAMES[r.layer]}
            </text>
          ))
        : null}

      {layout.mode === "regions" ? <RegionFrames net={net} layout={layout} /> : null}

      {layout.stubs.map((id) => {
        const p = posOf(id);
        const pl = places.get(id);
        if (!p || !pl) return null;
        const y = p.y - pl.up;
        return <path key={`stub-${id}`} className="nws-stub" d={`M${p.x.toFixed(1)} ${y.toFixed(1)}V${(y - 20).toFixed(1)}`} />;
      })}

      {layout.mode === "tree"
        ? net.edges.map((e) => {
            const c = net.byId.get(e.child);
            const p = net.byId.get(e.parent);
            const cPos = c && posOf(c.id);
            const pPos = p && posOf(p.id);
            const cPlace = c && places.get(c.id);
            const pPlace = p && places.get(p.id);
            if (!c || !p || !cPos || !pPos || !cPlace || !pPlace) return null;
            const fault = net.concluded && (c.flags.root || c.flags.affected) && (p.flags.root || p.flags.affected);
            const lit = highlight.has(c.id) || highlight.has(p.id);
            return (
              <path
                key={`${e.child}>${e.parent}`}
                className="nws-edge"
                pathLength={1}
                d={edgePath(cPos, cPlace, pPos, pPlace)}
                data-fault={fault ? "" : undefined}
                data-dim={fade && !fault && !lit ? "" : undefined}
                data-lit={lit ? "" : undefined}
              />
            );
          })
        : null}
    </svg>
  );
}

function RegionFrames({ net, layout }: { net: Network; layout: Layout }) {
  const core = net.nodes.find((n) => n.layer === 0);
  const corePlace = core ? layout.places.get(core.id) : undefined;
  const mids = layout.groups.map((g) => g.x + g.w / 2);
  const bus = layout.busY;
  // Groups stacked in a second row hang below the first; a line down to them would run through it.
  const firstRow = Math.min(...layout.groups.map((g) => g.y));
  const compact = layout.w < 640;
  return (
    <g>
      {corePlace && mids.length ? (
        <>
          <path className="nws-hair" d={`M${Math.min(...mids, corePlace.x)} ${bus}H${Math.max(...mids, corePlace.x)}`} />
          <path className="nws-hair" d={`M${corePlace.x} ${corePlace.y + corePlace.down}V${bus}`} />
        </>
      ) : null}
      {layout.groups.map((g) => (
        <g key={g.code}>
          {corePlace && g.y > bus && g.y <= firstRow + 1 ? <path className="nws-hair" d={`M${g.x + g.w / 2} ${bus}V${g.y}`} /> : null}
          <path className="nws-frame" d={`M${g.x} ${g.y + 8}V${g.y}H${g.x + g.w}V${g.y + 8}`} />
          <text className="nws-region-name" x={g.x + 2} y={g.y + 25}>
            {REGIONS[g.code] ?? g.code}
          </text>
          <text className="nws-region-count" x={g.x + 2} y={g.y + 42}>
            {groupCount(g, compact)}
          </text>
        </g>
      ))}
    </g>
  );
}
