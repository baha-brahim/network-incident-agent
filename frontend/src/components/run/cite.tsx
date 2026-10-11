"use client";

import { HelpCircle } from "lucide-react";
import { Tip } from "@/components/ui/tip";
import { cx } from "@/lib/cx";
import { EVIDENCE_KINDS, toolLabel } from "@/lib/labels";
import { findStep } from "@/lib/investigation";
import { plainText } from "@/lib/steps";
import { useRunContext } from "./run-context";

/**
 * A citation chip. Hover or focus shows what the reference points to; a click selects the step
 * that produced it.
 */
export function Cite({ id, compact = false }: { id: string; compact?: boolean }) {
  const ctx = useRunContext();
  const entry = ctx?.view.evidence[id];
  const origin = ctx?.view.origins[id];
  const step = ctx && origin ? findStep(ctx.view, origin) : null;
  const chip = cx(
    "press inline-flex max-w-full items-center gap-1 rounded-md border px-1.5 align-baseline font-mono leading-5 break-anywhere",
    compact ? "text-[11px]" : "text-xs",
    entry
      ? "border-line bg-surface-2 text-fg hover:border-accent hover:text-accent"
      : "border-dashed border-warn/50 bg-warn-soft text-warn",
    origin ? "" : "cursor-help",
  );

  const isCall = !!step && step.kind === "tool" && step.id === id;
  const content = isCall && step.kind === "tool" ? (
    <span className="block">
      <span className="mb-1 flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-muted">
        Tool call
        <span className="font-mono normal-case tracking-normal">{id}</span>
      </span>
      <span className="block font-medium">{toolLabel(step.tool)}</span>
      <span className="block text-muted break-anywhere">
        {plainText(step.result?.error ?? step.result?.headline ?? "Waiting for the result")}
      </span>
      <span className="mt-1.5 block text-muted">Click to open that step.</span>
    </span>
  ) : entry ? (
    <span className="block">
      <span className="mb-1 flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-muted">
        {EVIDENCE_KINDS[entry.kind]?.label ?? entry.kind}
        <span className="font-mono normal-case tracking-normal">{id}</span>
      </span>
      <span className="block break-anywhere">{entry.summary}</span>
      {step?.kind === "tool" ? (
        <span className="mt-1.5 block text-muted">
          From {toolLabel(step.tool)} ({step.id}). Click to open that step.
        </span>
      ) : null}
    </span>
  ) : (
    <span className="block">
      <span className="font-mono">{id}</span> was not found among the evidence the agent collected.
    </span>
  );

  return (
    <Tip content={content}>
      <button
        type="button"
        className={chip}
        onClick={() => {
          if (origin) ctx?.selectStep(origin, { flash: true, ref: id });
        }}
      >
        {entry ? null : <HelpCircle aria-hidden className="size-3 shrink-0" />}
        {id}
      </button>
    </Tip>
  );
}

export function CiteList({ refs, compact }: { refs: readonly string[]; compact?: boolean }) {
  if (refs.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap gap-1" role="group" aria-label="Evidence">
      {refs.map((r) => (
        <Cite key={r} id={r} compact={compact} />
      ))}
    </span>
  );
}
