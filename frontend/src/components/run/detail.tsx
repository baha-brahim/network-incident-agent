"use client";

import { X } from "lucide-react";
import { markTimes, type BoardModel, type KpiRow, type Mark } from "@/lib/board";
import type { RunView, ToolStep } from "@/lib/investigation";
import { EVIDENCE_KINDS, TOOLS, toolLabel } from "@/lib/labels";
import type { NetNode, Network } from "@/lib/network";
import { plainText } from "@/lib/steps";
import { evidenceText } from "./citations";
import { NodeDetail } from "./node-detail";
import { SeriesChart } from "./series-chart";

export type Selection = { kind: "mark"; mark: Mark } | { kind: "kpi"; row: KpiRow } | { kind: "node"; node: NetNode };

export type Stage = "timeline" | "network";

export function findSelection(model: BoardModel, id: string | null): Selection | null {
  if (!id) return null;
  for (const lane of model.lanes) {
    const mark = lane.marks.find((m) => m.id === id);
    if (mark) return { kind: "mark", mark };
    const row = lane.kpis.find((k) => k.id === id);
    if (row) return { kind: "kpi", row };
  }
  return null;
}

/** One plain line about what the agent is doing at the moment. */
export function nowText(view: RunView, stage: Stage = "timeline", stopped = false): string {
  if (stopped) return "This run was saved before it finished.";
  if (view.phase === "finished") return "The investigation is finished.";
  if (view.phase === "error") return "The investigation stopped before it could conclude.";
  const running = [...view.steps].reverse().find((s): s is ToolStep => s.kind === "tool" && s.status === "running");
  if (running) {
    const verb = TOOLS[running.tool]?.verb ?? `Running ${toolLabel(running.tool)}`;
    return stage === "network" ? `${verb}. The diagram grows with what it finds.` : `${verb}. That lane on the board is being filled in.`;
  }
  const last = [...view.steps].reverse().find((s) => s.kind !== "model");
  if (!last) return "Waiting for the agent to read the question.";
  if (last.kind === "gate") return "The completeness check found a gap. The agent is deciding where to look next.";
  if (last.kind === "note") return "The agent is weighing what it has found and choosing the next check.";
  if (view.report) return "Writing the report.";
  return "Choosing the next check.";
}

const REF_LIMIT = 6;

interface DetailProps {
  view: RunView;
  net: Network;
  stage: Stage;
  selection: Selection | null;
  /** A saved run that never finished: there is nothing the agent is doing now. */
  stopped?: boolean;
  onClose(): void;
  goStep(id: string): void;
}

/** What is selected on the board or the diagram and the evidence behind it; with nothing selected, what the agent is doing now. */
export function Detail({ view, net, stage, selection, stopped = false, onClose, goStep }: DetailProps) {
  if (selection?.kind === "node") return <NodeDetail node={selection.node} view={view} net={net} onClose={onClose} goStep={goStep} />;
  if (!selection) {
    return (
      <aside className="dt" aria-label="Selected evidence">
        <h2>Right now</h2>
        <p>{nowText(view, stage, stopped)}</p>
        <p className="dt-hint">
          {stage === "network" ? "Select a node on the diagram to see what is known about it." : "Select a mark or a KPI row on the board to see the evidence behind it."}
        </p>
      </aside>
    );
  }

  const isMark = selection.kind === "mark";
  const origin = isMark ? selection.mark.origin : selection.row.origin;
  const hasStep = view.steps.some((s) => s.id === origin);
  const title = isMark ? selection.mark.label : selection.row.title;
  const refs = isMark ? selection.mark.refs : [];
  const shown = refs.slice(0, REF_LIMIT);

  return (
    <aside className="dt" aria-label="Selected evidence" aria-live="polite">
      <div className="dt-head">
        <h2>{title}</h2>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Clear selection">
          <X aria-hidden size={16} />
        </button>
      </div>

      {isMark ? (
        <>
          <p className="dt-kind">{selection.mark.kindLabel}</p>
          <p className="dt-when">{markTimes(selection.mark)}</p>
          <dl className="dt-rows">
            {selection.mark.rows
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
          </dl>
          <h3>Evidence</h3>
          <ul className="dt-refs">
            {shown.map((r) => {
              const e = view.evidence[r];
              return (
                <li key={r}>
                  <code>{r}</code>
                  <span className="dt-ref-kind">{e ? (EVIDENCE_KINDS[e.kind]?.label ?? e.kind) : "Evidence"}</span>
                  <span>{e ? plainText(e.summary) : "Listed in the tool result."}</span>
                </li>
              );
            })}
          </ul>
          {refs.length > shown.length ? <p className="dt-hint">and {refs.length - shown.length} more with the same pattern.</p> : null}
        </>
      ) : (
        <>
          <p className="dt-kind">KPI series</p>
          <SeriesChart series={selection.row.series} deviationPct={selection.row.deviationPct} />
          <h3>Evidence</h3>
          <ul className="dt-refs">
            <li>
              <code>{origin}</code>
              <span className="dt-ref-kind">Tool call</span>
              <span>{evidenceText(view, origin) ?? "Result of the KPI query."}</span>
            </li>
          </ul>
        </>
      )}
      {hasStep ? (
        <button type="button" className="link" onClick={() => goStep(origin)}>
          from step {origin}
          <span className="sr-only">, show it in the steps</span>
        </button>
      ) : null}
    </aside>
  );
}
