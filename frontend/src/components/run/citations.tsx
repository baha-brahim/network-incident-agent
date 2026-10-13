"use client";

import { createContext, useContext, useEffect, useId, useLayoutEffect, useRef } from "react";
import type { RunView } from "@/lib/investigation";
import { EVIDENCE_KINDS, toolLabel } from "@/lib/labels";
import { plainText } from "@/lib/steps";

export interface OpenCite {
  /** Which button is open, so that two buttons for the same reference never open together. */
  key: string;
  ref: string;
}

export interface RunCtx {
  view: RunView;
  openCite: OpenCite | null;
  setOpenCite(open: OpenCite | null): void;
  /** Scroll the steps to the one that produced a reference and mark it for a moment. */
  goStep(stepId: string): void;
  /** Marks nodes on the network diagram while something in the text points at them. Absent when the diagram is not showing. */
  pointAtNodes?(ids: readonly string[]): void;
}

export const RunContext = createContext<RunCtx | null>(null);

export function useRunCtx(): RunCtx | null {
  return useContext(RunContext);
}

/** What a reference stands for, in a sentence. A tool call reads as its result, not as the call itself. */
export function evidenceText(view: RunView, ref: string): string | null {
  const entry = view.evidence[ref];
  if (!entry) return null;
  if (entry.kind !== "call") return plainText(entry.summary);
  const step = view.steps.find((s) => s.kind === "tool" && s.id === ref);
  const headline = step?.kind === "tool" ? step.result?.headline : undefined;
  return plainText(headline ?? entry.summary.replace(/^w+(.*?) -> /, ""));
}

/** Moves a floating box sideways to stay inside the viewport, and above its trigger when there is no room below. */
function keepInView(pop: HTMLElement, trigger: HTMLElement) {
  pop.style.removeProperty("--dx");
  pop.dataset.side = "below";
  // The box scales in, so its drawn size is smaller than its real size: measure the real one.
  const r = pop.getBoundingClientRect();
  const width = pop.offsetWidth;
  const height = pop.offsetHeight;
  const vw = document.documentElement.clientWidth;
  let dx = 0;
  if (r.left + width > vw - 8) dx = vw - 8 - (r.left + width);
  if (r.left + dx < 8) dx = 8 - r.left;
  if (dx) pop.style.setProperty("--dx", `${Math.round(dx)}px`);
  if (r.top + height > window.innerHeight - 8 && trigger.getBoundingClientRect().top - height - 6 > 8) pop.dataset.side = "above";
}

/** A reference as a small button. Activating it opens the evidence behind it. */
export function Cite({ id }: { id: string }) {
  const ctx = useRunCtx();
  const popId = useId();
  const key = useId();
  const wrap = useRef<HTMLSpanElement | null>(null);
  const button = useRef<HTMLButtonElement | null>(null);
  const pop = useRef<HTMLDivElement | null>(null);
  const open = ctx?.openCite?.key === key;
  const setOpenCite = ctx?.setOpenCite;

  useEffect(() => {
    if (!open || !setOpenCite) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpenCite(null);
      button.current?.focus();
    };
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpenCite(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open, setOpenCite]);

  useLayoutEffect(() => {
    if (open && pop.current && button.current) keepInView(pop.current, button.current);
  }, [open]);

  const entry = ctx?.view.evidence[id];
  const origin = ctx?.view.origins[id];
  if (!ctx || (!entry && !origin)) return <span className="cite-none">{id}</span>;

  const isCall = origin === id;
  const kindLabel = isCall ? "Tool call" : entry ? (EVIDENCE_KINDS[entry.kind]?.label ?? entry.kind) : "Evidence";
  const hasStep = !!origin && ctx.view.steps.some((s) => s.kind === "tool" && s.id === origin);
  const step = hasStep ? ctx.view.steps.find((s) => s.id === origin) : null;

  return (
    <span
      className="cite"
      ref={wrap}
      onBlur={(e) => {
        if (open && !e.currentTarget.contains(e.relatedTarget as Node | null)) ctx.setOpenCite(null);
      }}
    >
      <button
        ref={button}
        type="button"
        className="cite-btn"
        aria-expanded={open}
        aria-controls={open ? popId : undefined}
        onClick={() => ctx.setOpenCite(open ? null : { key, ref: id })}
      >
        {id}
      </button>
      {open ? (
        <div className="cite-pop" id={popId} role="group" aria-label={`Evidence ${id}`} ref={pop}>
          <p className="cite-kind">
            {kindLabel} <code>{id}</code>
          </p>
          <p>{evidenceText(ctx.view, id) ?? "The result of this call has not arrived yet."}</p>
          {origin && step?.kind === "tool" ? (
            <button type="button" className="link" onClick={() => ctx.goStep(origin)}>
              {isCall ? `Open step ${origin}` : `from step ${origin}`}
              <span className="sr-only">, {toolLabel(step.tool)}</span>
            </button>
          ) : null}
        </div>
      ) : null}
    </span>
  );
}

export function CiteList({ refs }: { refs: readonly string[] }) {
  if (refs.length === 0) return null;
  return (
    <span className="cites" role="group" aria-label="Evidence">
      {refs.map((r) => (
        <Cite key={r} id={r} />
      ))}
    </span>
  );
}
