/**
 * Deterministic layout of a derived network: where each node goes, and which nodes get a label.
 * A single region is drawn as a tree, one row per layer with children under their parent; a
 * nationwide picture groups the nodes by region. There is no physics: the same input gives the
 * same drawing.
 */
import { ALARM_TYPES } from "./labels";
import { humanize, severityRank, worstAlarm, type Layer, type MarkerKind, type NetNode, type Network } from "./network";

export const ROW_NAMES = ["Core", "Aggregation", "Transport", "Sites"] as const;
export const REGION_ORDER = ["TUN", "SAH", "SFX", "SUD"] as const;

/** Half the width, and the height above and below the centre, of each glyph at scale 1. */
export const GLYPH: Record<Layer, { up: number; down: number; half: number }> = {
  0: { up: 15, down: 15, half: 15 },
  1: { up: 13, down: 13, half: 13 },
  2: { up: 8, down: 8, half: 17 },
  3: { up: 17, down: 10, half: 10 },
};
export const DOT_RADIUS = 5;
/** Beyond this many nodes the ones with nothing to say shrink to dots. */
export const DENSE_AT = 24;

export const LINE_H = 16;
const BADGE_W = 12;

export interface NodePlace {
  x: number;
  y: number;
  scale: number;
  /** A node with nothing to report in a crowded diagram: drawn as a small dot, never labelled. */
  dot: boolean;
  up: number;
  down: number;
  half: number;
}

export interface RegionGroup {
  code: string;
  x: number;
  y: number;
  w: number;
  sites: number;
  others: number;
}

export interface Layout {
  mode: "tree" | "regions";
  w: number;
  h: number;
  places: Map<string, NodePlace>;
  rows: Array<{ layer: Layer; y: number }>;
  groups: RegionGroup[];
  showRowNames: boolean;
  /** Where the line from the core to the region groups runs. */
  busY: number;
  /** Nodes drawn with a short line up, because nothing above them has been looked up. */
  stubs: string[];
  /** The most lines a label beside a node may have. */
  maxLines: number;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function isRemarkable(n: NetNode): boolean {
  return n.flags.root || n.flags.affected || n.alarms.length > 0 || n.markers.length > 0 || n.probes.length > 0;
}

export const isDense = (net: Network): boolean => net.nodes.length > DENSE_AT;

/** A nationwide picture, or one that spans several regions, is drawn grouped by region. */
export const isMultiRegion = (net: Network): boolean => net.regionsInUse.length > 1 || !!net.scope?.nationwide;

export function layoutNetwork(net: Network, w: number, h: number): Layout {
  return isMultiRegion(net) ? layoutRegions(net, w, h) : layoutTree(net, w, h);
}

function placeOf(n: NetNode, x: number, y: number, scale: number, dot: boolean): NodePlace {
  if (dot) return { x, y, scale: 1, dot, up: DOT_RADIUS, down: DOT_RADIUS, half: DOT_RADIUS };
  const g = GLYPH[n.layer];
  return { x, y, scale, dot, up: g.up * scale, down: g.down * scale, half: g.half * scale };
}

function layoutTree(net: Network, w: number, h: number): Layout {
  const compact = w < 640;
  const showRowNames = !compact && w >= 720;
  const left = showRowNames ? 112 : 14;
  const right = 16;
  const dense = isDense(net);

  const layers = ([0, 1, 2, 3] as Layer[]).filter((l) => net.nodes.some((n) => n.layer === l));
  const topPad = 46;
  const bottomPad = layers.includes(3) ? (compact ? 56 : 76) : 24;
  const avail = Math.max(0, h - topPad - bottomPad);
  const steps = Math.max(1, layers.length - 1);
  const gap = layers.length > 1 ? Math.min(150, avail / steps) : 0;
  const y0 = topPad + Math.max(0, (avail - steps * gap) / 2);
  const rows = layers.map((layer, i) => ({ layer, y: y0 + i * gap }));
  const rowY = new Map(rows.map((r) => [r.layer, r.y]));

  const children = new Map<string, NetNode[]>();
  for (const n of net.nodes) {
    if (!n.parent) continue;
    const list = children.get(n.parent) ?? [];
    list.push(n);
    children.set(n.parent, list);
  }
  for (const list of children.values()) list.sort((a, b) => (a.id < b.id ? -1 : 1));

  const unitX = new Map<string, number>();
  let cursor = 0;
  const visiting = new Set<string>();
  const place = (n: NetNode): number => {
    const known = unitX.get(n.id);
    if (known !== undefined) return known;
    visiting.add(n.id);
    const kids = (children.get(n.id) ?? []).filter((k) => !visiting.has(k.id));
    let x: number;
    if (kids.length === 0) {
      x = cursor + 0.5;
      cursor += 1;
    } else {
      const xs = kids.map(place);
      x = (xs[0] + xs[xs.length - 1]) / 2;
    }
    unitX.set(n.id, x);
    return x;
  };
  const CLUSTER_GAP = 0.35;
  for (const n of net.nodes) {
    if (n.parent) continue;
    place(n);
    cursor += CLUSTER_GAP;
  }
  for (const n of net.nodes) {
    if (!unitX.has(n.id)) {
      place(n);
      cursor += CLUSTER_GAP;
    }
  }
  const units = Math.max(1, cursor - CLUSTER_GAP);

  const usableW = Math.max(120, w - left - right);
  const slotW = Math.min(usableW / units, 190);
  const originX = left + (usableW - units * slotW) / 2;
  const scale = clamp(Math.min(slotW / 84, gap > 0 ? gap / 62 : Infinity), 0.55, 1.6);

  const places = new Map<string, NodePlace>();
  for (const n of net.nodes) {
    const x = originX + (unitX.get(n.id) ?? 0) * slotW;
    const y = rowY.get(n.layer) ?? y0;
    places.set(n.id, placeOf(n, x, y, scale, dense && n.layer > 0 && !isRemarkable(n)));
  }
  const stubs = net.nodes.filter((n) => n.layer > 0 && !n.parent).map((n) => n.id);
  const maxLines = clamp(Math.floor((gap * 0.8 - 4) / LINE_H), 1, 3);
  return { mode: "tree", w, h, places, rows, groups: [], showRowNames, busY: 0, stubs, maxLines };
}

function layoutRegions(net: Network, w: number, h: number): Layout {
  const compact = w < 640;
  const pad = compact ? 10 : 20;
  const cols = compact ? 2 : 4;
  const groupRows = compact ? 2 : 1;
  const cores = net.nodes.filter((n) => n.layer === 0);
  const coreY = 30;
  const busY = coreY + (compact ? 28 : 38);
  const groupsTop = cores.length ? busY + (compact ? 14 : 22) : 10;
  const groupH = (h - groupsTop - 6) / groupRows;
  const gw = (w - pad * 2) / cols;

  const places = new Map<string, NodePlace>();
  cores.forEach((n, i) => {
    const x = w / 2 + (i - (cores.length - 1) / 2) * 190;
    places.set(n.id, placeOf(n, x, coreY, compact ? 0.8 : 1, false));
  });

  const groups: RegionGroup[] = [];
  REGION_ORDER.forEach((code, i) => {
    const gx = pad + (i % cols) * gw;
    const gy = groupsTop + Math.floor(i / cols) * groupH;
    const members = net.nodes
      .filter((n) => n.layer > 0 && n.region === code)
      .sort((a, b) => a.layer - b.layer || (a.id < b.id ? -1 : 1));
    groups.push({
      code,
      x: gx,
      y: gy,
      w: gw - 10,
      sites: members.filter((n) => n.layer === 3).length,
      others: members.filter((n) => n.layer !== 3).length,
    });
    const innerW = gw - 10 - 16;
    const innerH = groupH - 56 - (compact ? 6 : 0);
    const m = Math.max(1, members.length);
    let cell = clamp(Math.floor(Math.sqrt((innerW * innerH) / (m * 1.15))), 20, 56);
    const rowsNeeded = (c: number) => Math.ceil(m / Math.max(1, Math.floor(innerW / c)));
    while (cell > 18 && rowsNeeded(cell) * cell > innerH) cell -= 2;
    const perRow = Math.max(1, Math.floor(innerW / cell));
    const scale = clamp(cell / 46, 0.5, 1);
    members.forEach((n, k) => {
      places.set(
        n.id,
        placeOf(n, gx + 8 + cell / 2 + (k % perRow) * cell, gy + 54 + cell / 2 + Math.floor(k / perRow) * cell, scale, !isRemarkable(n)),
      );
    });
  });
  return { mode: "regions", w, h, places, rows: [], groups, showRowNames: false, busY, stubs: [], maxLines: 2 };
}

// ------------------------------------------------------------------------------------ labels

export type LabelSide = "right" | "left" | "below";

export interface LabelLine {
  kind: "id" | "root" | "alarm" | "marker";
  text: string;
  severity?: string;
  marker?: MarkerKind;
}

export interface LabelPlan {
  lines: LabelLine[];
  side: LabelSide;
  /** Top left corner of the label box, from the node's centre. */
  dx: number;
  dy: number;
  w: number;
  h: number;
}

interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

const touches = (a: Box, b: Box): boolean => a.x0 < b.x1 + 2 && a.x1 > b.x0 - 2 && a.y0 < b.y1 + 2 && a.y1 > b.y0 - 2;

/** The longest a node id is drawn in a label; the full id is in the node's name and its detail. */
export const LABEL_ID_MAX = 22;

/** An id cut in the middle when it is too long to label, keeping both the start and the end. */
export function clipId(id: string, max = LABEL_ID_MAX): string {
  if (id.length <= max) return id;
  const keep = max - 1;
  const head = Math.ceil(keep / 2);
  return `${id.slice(0, head)}…${id.slice(id.length - (keep - head))}`;
}

/** What a node is called when there is little room: the part that tells it apart from its neighbours. */
export function shortId(id: string): string {
  if (/^S-[A-Z]{3}-/.test(id)) return clipId(id.slice(6));
  const m = /^(AGG|LNK)-[A-Z]{3}-(.+)$/.exec(id);
  if (m) return clipId(`${m[1]}-${m[2]}`);
  return clipId(id.replace(/^CORE-/, ""));
}

function lineWidth(line: LabelLine): number {
  if (line.kind === "id") return line.text.length * 7.3 + 4;
  const icon = line.kind === "marker" ? 16 : 0;
  return line.text.length * (line.kind === "root" ? 6.9 : 6.4) + 4 + icon;
}

function flagLines(n: NetNode, net: Network): LabelLine[] {
  const out: LabelLine[] = [];
  if (n.flags.root && net.concluded) out.push({ kind: "root", text: net.rootLabel });
  const worst = worstAlarm(n);
  if (worst) out.push({ kind: "alarm", text: ALARM_TYPES[worst.type]?.label ?? humanize(worst.type), severity: worst.severity });
  const marker = n.markers[0];
  if (marker) out.push({ kind: "marker", text: marker.label + (n.markers.length > 1 ? ` +${n.markers.length - 1}` : ""), marker: marker.kind });
  return out;
}

function importance(n: NetNode, net: Network, mode: Layout["mode"], focus: ReadonlySet<string>): number {
  if (n.flags.root && net.concluded) return 100;
  if (focus.has(n.id)) return 90;
  if (n.flags.affected) return 60;
  const worst = worstAlarm(n);
  if (worst) return 40 + severityRank(worst.severity);
  if (n.markers.length) return 30;
  if (n.probes.length) return 20;
  const structural = !isDense(net) || n.layer === 0 || (mode === "tree" && n.layer < 3);
  return structural ? 5 : 0;
}

/**
 * Chooses a label for each node worth one, most important first, and keeps each label clear of
 * every glyph and every label already placed. A label that does not fit is first cut down to its
 * id, then to a short id, then dropped.
 */
export function planLabels(net: Network, layout: Layout, focus: ReadonlySet<string>): Map<string, LabelPlan> {
  const plans = new Map<string, LabelPlan>();
  const glyphs = new Map<string, Box>();
  const badge = (n: NetNode) => (n.alarms.length > 0 ? BADGE_W : 0);
  for (const n of net.nodes) {
    const p = layout.places.get(n.id);
    if (!p) continue;
    glyphs.set(n.id, { x0: p.x - p.half, x1: p.x + p.half + badge(n), y0: p.y - p.up - (n.alarms.length ? 8 : 0), y1: p.y + p.down });
  }
  const placed: Box[] = [];
  if (layout.showRowNames) for (const r of layout.rows) placed.push({ x0: 10, x1: 108, y0: r.y - 9, y1: r.y + 9 });
  for (const g of layout.groups) placed.push({ x0: g.x, x1: g.x + g.w, y0: g.y, y1: g.y + 46 });

  const ranked = net.nodes
    .map((n) => ({ n, rank: importance(n, net, layout.mode, focus) }))
    .filter((r) => r.rank > 0 && layout.places.has(r.n.id))
    .sort((a, b) => b.rank - a.rank || a.n.layer - b.n.layer || (a.n.id < b.n.id ? -1 : 1));

  for (const { n } of ranked) {
    const p = layout.places.get(n.id);
    if (!p) continue;
    const below = layout.mode === "tree" ? n.layer === 3 : n.layer > 0;
    const sides: LabelSide[] = below ? ["below"] : ["right", "left"];
    const room = below ? (layout.w < 640 ? 2 : 3) : layout.maxLines;
    const flags = flagLines(n, net);
    const variants: LabelLine[][] = [];
    for (let k = Math.min(flags.length, room - 1); k >= 0; k--) variants.push([{ kind: "id", text: clipId(n.id) }, ...flags.slice(0, k)]);
    const short = shortId(n.id);
    if (short !== clipId(n.id)) variants.push([{ kind: "id", text: short }]);

    const own = glyphs.get(n.id);
    if (!own) continue;
    search: for (const lines of variants) {
      const w = Math.max(...lines.map(lineWidth));
      const h = lines.length * LINE_H;
      for (const side of sides) {
        const x0 = side === "below" ? p.x - w / 2 : side === "right" ? own.x1 + 5 : own.x0 - 5 - w;
        const y0 = side === "below" ? p.y + p.down + 5 : p.y - h / 2;
        const box: Box = { x0, y0, x1: x0 + w, y1: y0 + h };
        if (x0 < 2 || y0 < 2 || box.x1 > layout.w - 2 || box.y1 > layout.h - 2) continue;
        if (placed.some((b) => touches(box, b))) continue;
        let blocked = false;
        for (const [id, g] of glyphs) {
          if (id !== n.id && touches(box, g)) {
            blocked = true;
            break;
          }
        }
        if (blocked) continue;
        placed.push(box);
        plans.set(n.id, { lines, side, dx: x0 - p.x, dy: y0 - p.y, w, h });
        break search;
      }
    }
  }
  return plans;
}
