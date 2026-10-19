import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import fiberCut from "./__fixtures__/fiber-cut.json";
import stadiumEvent from "./__fixtures__/stadium-event.json";
import { emptyView, reduceEvents, type RunView } from "./investigation";
import { layoutNetwork, planLabels, shortId } from "./network-layout";
import { deriveNetwork, nodesForRef, nodesTouchedBy, windowText, worstAlarm } from "./network";
import type { Recording, RunEvent } from "./types";

const fiber = fiberCut as unknown as Recording;
const stadium = stadiumEvent as unknown as Recording;

const full = (r: Recording): RunView => reduceEvents(r.events);
const indexOfEvent = (r: Recording, type: string, ref?: string): number =>
  r.events.findIndex((e) => e.type === type && (ref === undefined || (e.data as { ref?: string }).ref === ref));
const viewThrough = (r: Recording, index: number): RunView => reduceEvents(r.events.slice(0, index + 1));
const demoDir = fileURLToPath(new URL("../../../backend/src/incident_agent/api/demos/", import.meta.url));
const demo = (name: string): Recording => JSON.parse(readFileSync(`${demoDir}${name}.json`, "utf8")) as Recording;
const withAffected = (r: Recording, extra: string[]): RunEvent[] =>
  r.events.map((e) =>
    e.type === "report" || e.type === "run_finished"
      ? ({ ...e, data: { ...e.data, report: { ...(e.data as { report: { affected_node_ids: string[] } }).report, affected_node_ids: [...(e.data as { report: { affected_node_ids: string[] } }).report.affected_node_ids, ...extra] } } } as RunEvent)
      : e,
  );
const without = (r: Recording, tool: string): RunEvent[] => r.events.filter((e) => !("tool" in e.data && e.data.tool === tool));

describe("deriveNetwork", () => {
  it("finds the three sites, the link, the router and the core in the fibre cut", () => {
    const net = deriveNetwork(full(fiber));
    for (const id of ["S-TUN-012", "S-TUN-014", "S-TUN-015", "LNK-TUN-02-C", "AGG-TUN-02", "CORE-UPF-01"]) expect(net.byId.has(id)).toBe(true);
    expect(net.nodes.filter((n) => n.layer < 3)).toHaveLength(3);
  });

  it("shows a site the detector named for an unrelated reason, unconnected and not affected", () => {
    const net = deriveNetwork(full(fiber));
    const decoy = net.byId.get("S-TUN-011");
    expect(decoy?.flags.detector).toBe(true);
    expect(decoy?.parent).toBeNull();
    expect(decoy?.flags.affected).toBe(false);
    expect(net.nodes.filter((n) => n.layer === 3)).toHaveLength(4);
  });

  it("chains each site to the link, the link to the router and the router to the core", () => {
    const net = deriveNetwork(full(fiber));
    for (const site of ["S-TUN-012", "S-TUN-014", "S-TUN-015"]) expect(net.byId.get(site)?.parent).toBe("LNK-TUN-02-C");
    expect(net.byId.get("LNK-TUN-02-C")?.parent).toBe("AGG-TUN-02");
    expect(net.byId.get("AGG-TUN-02")?.parent).toBe("CORE-UPF-01");
    expect(net.byId.get("CORE-UPF-01")?.parent).toBeNull();
    expect(net.edges).toHaveLength(5);
  });

  it("attaches each alarm to the node it was raised on", () => {
    const net = deriveNetwork(full(fiber));
    expect(net.byId.get("LNK-TUN-02-C")?.alarms.map((a) => a.type)).toEqual(["LINK_LOS"]);
    expect(net.byId.get("S-TUN-014")?.alarms.map((a) => a.type)).toEqual(["SITE_DOWN"]);
    const noisy = net.byId.get("S-TUN-012");
    expect(noisy?.alarms.map((a) => a.type).sort()).toEqual(["SITE_DOWN", "VSWR_HIGH"]);
    expect(noisy && worstAlarm(noisy)?.severity).toBe("critical");
    expect(net.byId.get("AGG-TUN-02")?.alarms).toEqual([]);
  });

  it("flags the root cause and the affected nodes only once the report is in", () => {
    const beforeReport = deriveNetwork(viewThrough(fiber, indexOfEvent(fiber, "report") - 1));
    expect(beforeReport.concluded).toBe(false);
    expect(beforeReport.rootId).toBeNull();
    expect(beforeReport.nodes.some((n) => n.flags.root || n.flags.affected)).toBe(false);

    const done = deriveNetwork(full(fiber));
    expect(done.concluded).toBe(true);
    expect(done.rootId).toBe("LNK-TUN-02-C");
    expect(done.rootLabel).toBe("Root cause");
    expect(done.byId.get("LNK-TUN-02-C")?.flags.root).toBe(true);
    expect(done.nodes.filter((n) => n.flags.affected).map((n) => n.id).sort()).toEqual(["LNK-TUN-02-C", "S-TUN-012", "S-TUN-014", "S-TUN-015"]);
  });

  it("words the root cause after the verdict", () => {
    const net = deriveNetwork(full(stadium));
    expect(net.verdict).toBe("expected_event");
    expect(net.rootLabel).toBe("Expected event");
  });

  it("records a probe on the nodes a tool call names, from the moment it is sent", () => {
    const call = indexOfEvent(fiber, "tool_call", "T2");
    const net = deriveNetwork(viewThrough(fiber, call));
    const asked = (fiber.events[call].data as unknown as { args: { node_ids: string[] } }).args.node_ids;
    expect(asked.length).toBeGreaterThan(0);
    for (const id of asked) {
      const node = net.byId.get(id);
      expect(node?.probes).toHaveLength(1);
      expect(node?.touchedBy).toContain("T2");
    }
    expect(nodesTouchedBy(net, "T2").sort()).toEqual([...asked].sort());
  });

  it("starts empty and gains the sites when the detector names them", () => {
    expect(deriveNetwork(emptyView).nodes).toEqual([]);
    const afterAnomalies = deriveNetwork(viewThrough(fiber, indexOfEvent(fiber, "tool_result", "T1")));
    expect(afterAnomalies.nodes.filter((n) => n.layer === 3 && n.flags.detector).length).toBeGreaterThanOrEqual(3);
    expect(afterAnomalies.edges).toEqual([]);
  });

  it("leaves nodes unconnected when the topology was never looked up", () => {
    const net = deriveNetwork(reduceEvents(without(fiber, "get_topology")));
    expect(net.edges).toEqual([]);
    expect(net.nodes.length).toBeGreaterThan(0);
    expect(net.nodes.every((n) => n.parent === null)).toBe(true);
  });

  it("maps evidence to the nodes it concerns", () => {
    const view = full(fiber);
    const net = deriveNetwork(view);
    expect(nodesForRef(view, net, "ALM-000472")).toEqual(["LNK-TUN-02-C"]);
    expect(nodesForRef(view, net, "ALR-0022").sort()).toEqual(["S-TUN-012", "S-TUN-014", "S-TUN-015"]);
    expect(nodesForRef(view, net, "T3")).toContain("S-TUN-012");
    expect(nodesForRef(view, net, "NOPE-1")).toEqual([]);
  });
});

describe("windowText", () => {
  it("writes a same-day window with the date once", () => {
    expect(windowText(deriveNetwork(full(fiber)).scope)).toBe("21 Sep, 12:00 to 18:00");
    expect(windowText(null)).toBeNull();
  });
});

describe("layoutNetwork", () => {
  const net = deriveNetwork(full(fiber));

  it("is deterministic", () => {
    const a = layoutNetwork(net, 900, 420);
    const b = layoutNetwork(net, 900, 420);
    expect([...a.places]).toEqual([...b.places]);
    expect([...planLabels(net, a, new Set())]).toEqual([...planLabels(net, b, new Set())]);
  });

  it.each([
    [1200, 440],
    [900, 420],
    [390, 262],
  ])("keeps every node inside a %i by %i stage, none on top of another", (w, h) => {
    for (const source of [full(fiber), full(stadium)]) {
      const n = deriveNetwork(source);
      const layout = layoutNetwork(n, w, h);
      const seen = new Set<string>();
      for (const node of n.nodes) {
        const p = layout.places.get(node.id);
        expect(p).toBeDefined();
        if (!p) continue;
        expect(p.x - p.half).toBeGreaterThanOrEqual(0);
        expect(p.x + p.half).toBeLessThanOrEqual(w);
        expect(p.y - p.up).toBeGreaterThanOrEqual(0);
        expect(p.y + p.down).toBeLessThanOrEqual(h);
        const key = `${Math.round(p.x)},${Math.round(p.y)}`;
        expect(seen.has(key)).toBe(false);
        seen.add(key);
      }
    }
  });

  it("stacks the layers from the core down and puts children under their parent", () => {
    const layout = layoutNetwork(net, 900, 420);
    const y = (id: string) => layout.places.get(id)?.y ?? NaN;
    expect(y("CORE-UPF-01")).toBeLessThan(y("AGG-TUN-02"));
    expect(y("AGG-TUN-02")).toBeLessThan(y("LNK-TUN-02-C"));
    expect(y("LNK-TUN-02-C")).toBeLessThan(y("S-TUN-012"));
    const xs = ["S-TUN-012", "S-TUN-014", "S-TUN-015"].map((id) => layout.places.get(id)?.x ?? NaN);
    expect(layout.places.get("LNK-TUN-02-C")?.x).toBeCloseTo((xs[0] + xs[2]) / 2, 5);
  });

  it("labels every node of a small run, and never lets two labels or a glyph overlap", () => {
    const layout = layoutNetwork(net, 900, 440);
    const plans = planLabels(net, layout, new Set());
    for (const node of net.nodes) expect(plans.has(node.id)).toBe(true);
    const boxes = [...plans].map(([id, plan]) => {
      const p = layout.places.get(id)!;
      return { id, x0: p.x + plan.dx, y0: p.y + plan.dy, x1: p.x + plan.dx + plan.w, y1: p.y + plan.dy + plan.h };
    });
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i];
        const b = boxes[j];
        expect(a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0).toBe(false);
      }
    }
  });

  it("leaves a node with nothing to say as a small unlabelled dot in a crowded run", () => {
    const sites = Array.from({ length: 30 }, (_, i) => `S-TUN-${String(100 + i)}`);
    const events = fiber.events.slice(0, 3).map((e) => (e.type === "scope" ? { ...e, data: { ...e.data, node_ids: sites } } : e)) as RunEvent[];
    const crowded = deriveNetwork(reduceEvents(events));
    const layout = layoutNetwork(crowded, 1200, 440);
    const plans = planLabels(crowded, layout, new Set());
    expect(crowded.nodes.every((n) => layout.places.get(n.id)?.dot)).toBe(true);
    expect(plans.size).toBe(0);
    const focused = planLabels(crowded, layout, new Set(["S-TUN-110"]));
    expect(focused.has("S-TUN-110")).toBe(true);
  });
});

describe("shortId", () => {
  it("keeps what tells nodes in one region apart", () => {
    expect(shortId("S-SAH-014")).toBe("014");
    expect(shortId("LNK-TUN-02-C")).toBe("LNK-02-C");
    expect(shortId("AGG-TUN-02")).toBe("AGG-02");
    expect(shortId("CORE-DNS-01")).toBe("DNS-01");
  });
});

describe("nodes known only as siblings", () => {
  const cut = demo("fiber-cut");

  it("do not make a single-region run span several regions, and are not drawn", () => {
    const view = full(cut);
    const siblings = (view.steps.flatMap((s) => (s.kind === "tool" && s.tool === "get_topology" ? [s.result?.data] : [])) as Array<{ siblings?: string[] }>).flatMap(
      (d) => d?.siblings ?? [],
    );
    expect(siblings).toContain("AGG-SAH-01");
    const net = deriveNetwork(view);
    expect(net.regionsInUse).toEqual(["TUN"]);
    expect(net.byId.has("AGG-SAH-01")).toBe(false);
    expect(net.edges.every((e) => net.byId.has(e.child) && net.byId.has(e.parent))).toBe(true);
    expect(layoutNetwork(net, 1200, 440).mode).toBe("tree");
  });

  it("keep their place when another node of the same region is looked up", () => {
    const net = deriveNetwork(full(cut));
    expect(net.byId.get("AGG-TUN-01")?.parent).toBe("CORE-UPF-01");
  });

  it("count once something else names them, and the run is then drawn by region", () => {
    const net = deriveNetwork(reduceEvents(withAffected(cut, ["AGG-SAH-01"])));
    expect(net.regionsInUse.sort()).toEqual(["SAH", "TUN"]);
    expect(net.byId.has("AGG-SAH-01")).toBe(true);
    expect(layoutNetwork(net, 1200, 440).mode).toBe("regions");
  });

  it("stay drawn in a nationwide run", () => {
    const events = cut.events.map((e) => (e.type === "scope" ? { ...e, data: { ...e.data, nationwide: true } } : e)) as RunEvent[];
    const net = deriveNetwork(reduceEvents(events));
    expect(net.byId.has("AGG-SAH-01")).toBe(true);
    expect(layoutNetwork(net, 1200, 440).mode).toBe("regions");
  });
});

describe("recorded cases", () => {
  const names = readdirSync(demoDir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => f.replace(/\.json$/, ""));

  it.each(names)("%s is drawn in the layout its scope calls for", (name) => {
    const r = demo(name);
    const net = deriveNetwork(full(r));
    const scope = r.events.find((e) => e.type === "scope")?.data as { nationwide?: boolean; region_ids?: string[] } | undefined;
    const expected = scope?.nationwide ? "regions" : "tree";
    expect(layoutNetwork(net, 1200, 440).mode).toBe(expected);
  });
});
