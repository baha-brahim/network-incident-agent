"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { RunPlayer } from "@/hooks/use-run-player";
import { buildBoard, type LaneId } from "@/lib/board";
import { findStep, type RunView } from "@/lib/investigation";
import { deriveNetwork, nodesForRef, nodesTouchedBy } from "@/lib/network";
import { announce, reportRowText } from "@/lib/steps";
import { Board } from "./board";
import { ContextRows } from "./board-legend";
import { RunContext, type OpenCite, type RunCtx } from "./citations";
import { Detail, findSelection, type Selection, type Stage } from "./detail";
import { Feed, stepDomId, stepLanes } from "./feed";
import { calmMotion, scrollBehavior } from "./motion";
import { NetworkStage } from "./network/network-stage";
import { useProbe } from "./network/use-probe";
import { ReportView } from "./report-view";
import { RunControls, runCounts } from "./run-controls";
import "./run-screen.css";

export interface RunScreenProps {
  view: RunView;
  /** False when the whole run is shown at once (a saved run, or after "skip to report"). */
  animate: boolean;
  /** Where the run comes from: "Recorded case · Three sites go dark", "Live investigation", "Saved run · RUN-1a2b". */
  source: string;
  /** Playback state and controls. Leave out for a run that is not playing, such as a saved run. */
  player?: RunPlayer;
  /** One line under the title for a run that is not playing, for example when it was asked. */
  note?: string;
  /** A failure or a warning about the run, shown above the board. */
  notice?: ReactNode;
  onBack(): void;
  backLabel?: string;
}

/** How much of the report should show below the board when it arrives. */
const REPORT_PEEK = 200;
const FLASH_MS = 1800;
const NO_LANES: readonly LaneId[] = [];
const NO_NODES: readonly string[] = [];
const NO_NODE_SET: ReadonlySet<string> = new Set();

const STAGE_NOTE: Record<Stage, string> = {
  timeline: "When things happened, by source",
  network: "Where things happened, on the part of the network involved",
};

function activeElement(): HTMLElement | null {
  const el = document.activeElement;
  return el instanceof HTMLElement && el !== document.body ? el : null;
}

/** What the live region says: the last step that finished, and once it is there, the report. */
function spokenText(view: RunView): string {
  if (view.phase === "finished" && view.report) return `Investigation finished. The report is ready: ${reportRowText(view)}.`;
  if (view.phase === "error") return `The investigation stopped before it could conclude.${view.report ? " A partial report is shown." : ""}`;
  for (let i = view.steps.length - 1; i >= 0; i--) {
    const text = announce(view.steps[i], view);
    if (text) return text;
  }
  return "";
}

/** One investigation: the question, the controls, the evidence board, the steps and the report. */
export function RunScreen({ view, animate, source, player, note, notice, onBack, backLabel = "All cases" }: RunScreenProps) {
  const model = useMemo(() => buildBoard(view), [view]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("timeline");
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [hoverStepId, setHoverStepId] = useState<string | null>(null);
  const [textNodes, setTextNodes] = useState<readonly string[]>(NO_NODES);
  const [hoverPin, setHoverPin] = useState<number | null>(null);
  const [openCite, setOpenCite] = useState<OpenCite | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const flashTimer = useRef<number | undefined>(undefined);
  /** Where the reader was before a selection opened the detail, so closing it puts them back. */
  const returnTo = useRef<HTMLElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const barRef = useRef<HTMLDivElement | null>(null);
  const boardRef = useRef<HTMLDivElement | null>(null);

  const hasReport = !!view.report;
  const hasSteps = view.steps.length > 0;
  const net = useMemo(() => deriveNetwork(view), [view]);
  const probe = useProbe(view, net, { animate, playing: player?.status === "playing", speed: player?.speed ?? 1 });
  const selectedNetNode = selectedNode ? (net.byId.get(selectedNode) ?? null) : null;
  const selection = useMemo<Selection | null>(
    () => (selectedNetNode ? { kind: "node", node: selectedNetNode } : findSelection(model, selectedId)),
    [model, selectedId, selectedNetNode],
  );
  const highlightRefs = useMemo<ReadonlySet<string>>(() => new Set(openCite ? [openCite.ref] : []), [openCite]);
  const hoverStep = findStep(view, hoverStepId);
  const hoverLanes = useMemo(() => (hoverStep ? stepLanes(hoverStep) : NO_LANES), [hoverStep]);
  const highlightNodes = useMemo<ReadonlySet<string>>(() => {
    const fromStep = hoverStepId ? nodesTouchedBy(net, hoverStepId) : NO_NODES;
    const fromCite = openCite ? nodesForRef(view, net, openCite.ref) : NO_NODES;
    if (fromStep.length + fromCite.length + textNodes.length === 0) return NO_NODE_SET;
    return new Set([...fromStep, ...fromCite, ...textNodes]);
  }, [net, view, hoverStepId, openCite, textNodes]);
  const question = view.question || player?.source?.question || "";

  // A new run starts with no steps: forget the selection of the last one.
  if (view.steps.length === 0 && (selectedId !== null || selectedNode !== null || openCite !== null)) {
    setSelectedId(null);
    setSelectedNode(null);
    setOpenCite(null);
  }

  const selectMark = useCallback((id: string | null) => {
    if (id) returnTo.current = activeElement();
    setSelectedId(id);
    setSelectedNode(null);
  }, []);
  const selectNode = useCallback((id: string | null) => {
    if (id) returnTo.current = activeElement();
    setSelectedNode(id);
    setSelectedId(null);
  }, []);
  const closeDetail = useCallback(() => {
    setSelectedId(null);
    setSelectedNode(null);
    const back = returnTo.current;
    returnTo.current = null;
    if (back) window.requestAnimationFrame(() => (back.isConnected ? back.focus({ preventScroll: true }) : undefined));
  }, []);
  const chooseStage = useCallback((next: Stage) => {
    setStage(next);
    if (next === "network") setSelectedId(null);
    else setSelectedNode(null);
    setTextNodes(NO_NODES);
  }, []);
  const pointAtNodes = useCallback((ids: readonly string[]) => setTextNodes(ids.length ? ids : NO_NODES), []);

  const goStep = useCallback((id: string) => {
    setOpenCite(null);
    const el = document.getElementById(stepDomId(id));
    if (!el) return;
    el.scrollIntoView({ block: "start", behavior: scrollBehavior() });
    el.focus({ preventScroll: true });
    setFlash(null);
    window.requestAnimationFrame(() => setFlash(id));
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlash(null), FLASH_MS);
  }, []);

  useEffect(() => () => window.clearTimeout(flashTimer.current), []);

  // Anything scrolled into view clears the sticky controls; their height changes with the width.
  useEffect(() => {
    const root = rootRef.current;
    const bar = barRef.current;
    if (!root || !bar) return;
    const measure = () => root.style.setProperty("--bar-h", `${bar.offsetHeight}px`);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(bar);
    return () => observer.disconnect();
  }, []);

  // When the report lands while watching, bring the board with its conclusion and the top of the report into view.
  useEffect(() => {
    if (!hasReport || !animate) return;
    const timer = window.setTimeout(() => {
      const board = boardRef.current;
      if (!board) return;
      const bar = barRef.current?.offsetHeight ?? 0;
      const rect = board.getBoundingClientRect();
      const top = window.scrollY + rect.top - bar - 8;
      const wanted = window.scrollY + rect.bottom + REPORT_PEEK - window.innerHeight;
      window.scrollTo({ top: Math.max(top, wanted), behavior: calmMotion() ? "auto" : "smooth" });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [hasReport, animate]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || openCite) return;
      setSelectedId(null);
      setSelectedNode(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openCite]);

  const ctx = useMemo<RunCtx>(
    () => ({ view, openCite, setOpenCite, goStep, pointAtNodes: stage === "network" ? pointAtNodes : undefined }),
    [view, openCite, goStep, stage, pointAtNodes],
  );
  const spoken = useMemo(() => spokenText(view), [view]);
  const savedWithoutSteps = !hasSteps && hasReport && !player;
  const stopped = !player && view.phase !== "finished" && view.phase !== "error";
  const detail = <Detail view={view} net={net} stage={stage} selection={selection} stopped={stopped} onClose={closeDetail} goStep={goStep} />;
  const feed = <Feed view={view} flashStep={flash} stopped={stopped} onHover={setHoverStepId} />;

  return (
    <RunContext.Provider value={ctx}>
      <div ref={rootRef} className={`run${hasReport ? " has-report" : ""}`} data-animate={animate ? "" : undefined}>
        <div className="page run-head">
          <h1 className={question.length > 140 ? "is-long" : undefined}>{question || "Starting…"}</h1>
          <p className="run-source">
            {source}
            <span className="run-source-extra">
              {" · "}
              {runCounts(view)}
              {note ? ` · ${note}` : ""}
            </span>
          </p>
        </div>

        <div className="run-bar" ref={barRef}>
          <div className="page">
            <RunControls view={view} player={player} note={note} onBack={onBack} backLabel={backLabel} />
          </div>
        </div>

        <div className="page run-body">
          {notice ? <div className="run-notice">{notice}</div> : null}

          {savedWithoutSteps ? (
            <p className="run-nosteps">The steps of this run were not saved. Only its report is shown.</p>
          ) : (
            <div className="run-board" ref={boardRef}>
              <div className="run-viewbar">
                <div className="seg is-text" role="group" aria-label="What the stage shows">
                  <button type="button" aria-pressed={stage === "timeline"} onClick={() => chooseStage("timeline")}>
                    Timeline
                  </button>
                  <button type="button" aria-pressed={stage === "network"} onClick={() => chooseStage("network")}>
                    Network
                  </button>
                </div>
                <p className="run-viewnote">{STAGE_NOTE[stage]}</p>
              </div>
              <div className="run-view" data-off={stage !== "timeline" ? "" : undefined} inert={stage !== "timeline"}>
                <Board
                  model={model}
                  animate={animate}
                  selectedId={selectedId}
                  onSelect={selectMark}
                  highlightRefs={highlightRefs}
                  hoverLanes={hoverLanes}
                  hoverPin={hoverPin}
                  onHoverPin={setHoverPin}
                >
                  <ContextRows lines={model.context} />
                </Board>
              </div>
              <div className="run-view" data-off={stage !== "network" ? "" : undefined} inert={stage !== "network"}>
                <NetworkStage net={net} probe={probe} animate={animate} selectedId={selectedNode} onSelect={selectNode} highlightIds={highlightNodes} />
              </div>
            </div>
          )}

          {savedWithoutSteps ? (
            <div className="run-cols is-single">
              <div className="col-main">
                <ReportView view={view} hoverPin={hoverPin} onHoverPin={setHoverPin} />
              </div>
            </div>
          ) : (
            <div className="run-cols">
              {hasReport ? (
                <>
                  <div className="col-main">
                    <ReportView view={view} hoverPin={hoverPin} onHoverPin={setHoverPin} />
                  </div>
                  <div className="col-side">
                    {selection ? detail : null}
                    {feed}
                  </div>
                </>
              ) : (
                <>
                  <div className="col-main">{feed}</div>
                  <div className="col-side">{detail}</div>
                </>
              )}
            </div>
          )}
        </div>

        <p role="status" className="sr-only">
          {spoken}
        </p>
      </div>
    </RunContext.Provider>
  );
}
