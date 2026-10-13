import type { BoardModel, LaneId } from "@/lib/board";
import { TOOL_LANE } from "@/lib/board";
import type { RunView } from "@/lib/investigation";
import { TOOLS } from "@/lib/labels";

export const IDLE_LINE = "Six places to look, all blank. The agent fills them in as it checks.";

const WHERE: Record<LaneId, string> = {
  alerts: "the detector alerts",
  alarms: "the alarms",
  kpis: "the KPIs",
  changes: "the change log",
  maintenance: "the maintenance calendar",
  events: "external events",
};

/** One plain sentence about the latest step of the preview. */
export function previewLine(view: RunView, model: BoardModel): string {
  const last = [...view.steps].reverse().find((s) => s.kind !== "model");
  if (!last) return view.phase === "running" ? "Reading the question." : IDLE_LINE;

  switch (last.kind) {
    case "scope":
      return "The question is understood and the time window is set.";
    case "note":
      return "The agent writes down what it has found so far.";
    case "gate":
      return last.data.missing.length > 0
        ? `Not yet checked: ${last.data.missing.join(" and ")}. The agent is sent back.`
        : "The completeness check found a gap. The agent is sent back.";
    case "error":
      return "The investigation stopped.";
    case "tool": {
      const verb = TOOLS[last.tool]?.verb ?? "Running a check";
      if (last.status === "running") return `${verb}…`;
      if (last.status === "skipped") return "Skipped a repeated check.";
      if (last.status === "error") return "A check failed.";
      const laneId = TOOL_LANE[last.tool];
      const lane = laneId ? model.lanes.find((l) => l.def.id === laneId) : undefined;
      if (laneId && lane?.state === "clear") return `Nothing in ${WHERE[laneId]}.`;
      if (laneId && lane?.state === "found") return `Found ${lane.marks.length + lane.kpis.length} in ${WHERE[laneId]}.`;
      return `${verb}.`;
    }
    default:
      return IDLE_LINE;
  }
}
