import { describe, expect, it } from "vitest";
import fiberCut from "./__fixtures__/fiber-cut.json";
import { reduceEvents } from "./investigation";
import { deriveNetwork } from "./network";
import { clipId, LABEL_ID_MAX, layoutNetwork, planLabels, shortId } from "./network-layout";
import type { Recording, RunEvent } from "./types";

const fiber = fiberCut as unknown as Recording;

describe("clipId", () => {
  it("leaves a normal id alone and cuts a long one in the middle", () => {
    expect(clipId("S-TUN-012")).toBe("S-TUN-012");
    const long = "S-TUN-" + "0".repeat(60) + "123456789-EXTREMELY-LONG-NODE-IDENTIFIER";
    const clipped = clipId(long);
    expect(clipped).toHaveLength(LABEL_ID_MAX);
    expect(clipped.startsWith("S-TUN-")).toBe(true);
    expect(clipped.endsWith("IDENTIFIER")).toBe(true);
    expect(shortId(long).length).toBeLessThanOrEqual(LABEL_ID_MAX);
  });
});

describe("labels in a nationwide picture", () => {
  it("names the root cause, not just its id", () => {
    const events = fiber.events.map((e) => {
      if (e.type === "scope") return { ...e, data: { ...e.data, nationwide: true, region_ids: [], node_ids: ["CORE-DNS-01"] } };
      if (e.type === "report" || e.type === "run_finished") {
        return { ...e, data: { ...e.data, report: { ...(e.data as { report: object }).report, root_cause_node_id: "CORE-DNS-01", classification: "incident" } } };
      }
      return e;
    }) as RunEvent[];
    const net = deriveNetwork(reduceEvents(events));
    const layout = layoutNetwork(net, 1200, 440);
    expect(layout.mode).toBe("regions");
    const plan = planLabels(net, layout, new Set()).get("CORE-DNS-01");
    expect(plan?.lines.map((l) => l.text)).toEqual(["CORE-DNS-01", "Root cause"]);
  });

  it("labels a node with a very long id with a clipped id", () => {
    const long = "S-TUN-" + "0".repeat(80) + "-X";
    const events = fiber.events.slice(0, 3).map((e) => (e.type === "scope" ? { ...e, data: { ...e.data, node_ids: [long] } } : e)) as RunEvent[];
    const net = deriveNetwork(reduceEvents(events));
    const layout = layoutNetwork(net, 900, 440);
    const plan = planLabels(net, layout, new Set([long])).get(long);
    expect(plan).toBeDefined();
    for (const line of plan?.lines ?? []) expect(line.text.length).toBeLessThanOrEqual(LABEL_ID_MAX);
  });
});
