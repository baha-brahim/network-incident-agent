"use client";

import { useMemo, type ReactNode } from "react";
import { Cite, useRunCtx } from "@/components/run/citations";
import { NodeChip } from "@/components/run/node-chip";
import { Define } from "./term";
import { ALARM_TYPES, CATEGORIES, METRICS, NODE_ID_PATTERN, lookupTerm } from "@/lib/labels";

const EVIDENCE_ID = String.raw`(?:ALM|ALR|ANM|CHG|MW|EVT)-[0-9A-Z-]+|RB-[A-Z-]+#\d+|T\d{1,3}`;
// Category names are matched only in their snake_case form, so ordinary words like "capacity" stay plain.
const TERMS = [
  ...Object.keys(ALARM_TYPES),
  ...Object.keys(METRICS),
  ...Object.keys(CATEGORIES).filter((k) => k.includes("_")),
].join("|");
const NODE_ONLY = new RegExp(`^(?:${NODE_ID_PATTERN.source})$`);
const TOKEN = new RegExp(`\`?(\\b(?:${NODE_ID_PATTERN.source}|${EVIDENCE_ID}|${TERMS})\\b)\`?`, "g");

/**
 * Prose from the agent, with the things a reader may want explained marked up: node IDs and jargon
 * in monospace with a definition, and evidence references as citation buttons.
 */
export function RichText({ text }: { text: string }) {
  const ctx = useRunCtx();
  const view = ctx?.view;
  const parts = useMemo(() => {
    const out: ReactNode[] = [];
    let last = 0;
    for (const match of text.matchAll(TOKEN)) {
      const token = match[1];
      const index = match.index ?? 0;
      if (index > last) out.push(text.slice(last, index));
      last = index + match[0].length;
      const key = `${index}`;

      if (NODE_ONLY.test(token)) {
        out.push(<NodeChip key={key} id={token} />);
        continue;
      }
      const term = lookupTerm(token);
      if (term) {
        out.push(
          <Define key={key} term={{ label: token, definition: term.definition }}>
            <code className="id">{token}</code>
          </Define>,
        );
        continue;
      }
      if (view && (view.evidence[token] || view.origins[token])) out.push(<Cite key={key} id={token} />);
      else out.push(match[0]);
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }, [text, view]);

  return <>{parts}</>;
}
