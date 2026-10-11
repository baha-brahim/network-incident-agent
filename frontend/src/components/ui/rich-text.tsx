"use client";

import { Fragment, useMemo, type ReactNode } from "react";
import { Cite } from "@/components/run/cite";
import { useRunContext } from "@/components/run/run-context";
import { Define } from "./term";
import { ALARM_TYPES, CATEGORIES, METRICS, NODE_ID_PATTERN, lookupTerm, nodeKind } from "@/lib/labels";

const EVIDENCE_ID = String.raw`(?:ALM|ALR|ANM|CHG|MW|EVT)-[0-9A-Z-]+|RB-[A-Z-]+#\d+|T\d{1,3}`;
// Category names are matched only in their snake_case form, so ordinary words like "capacity" stay plain.
const TERMS = [
  ...Object.keys(ALARM_TYPES),
  ...Object.keys(METRICS),
  ...Object.keys(CATEGORIES).filter((k) => k.includes("_")),
].join("|");
const NODE_ONLY = new RegExp(`^(?:${NODE_ID_PATTERN.source})$`);
const TOKEN = new RegExp(`\`?(\\b(?:${NODE_ID_PATTERN.source}|${EVIDENCE_ID}|${TERMS})\\b)\`?`, "g");

const mono = "font-mono text-[0.92em]";

/**
 * Prose from the agent, with the things a reader may want explained marked up: node IDs in
 * monospace, jargon with a definition on its first mention, and references as citation chips.
 */
export function RichText({ text }: { text: string }) {
  const ctx = useRunContext();
  const parts = useMemo(() => {
    const out: ReactNode[] = [];
    const seen = new Set<string>();
    let last = 0;
    for (const match of text.matchAll(TOKEN)) {
      const token = match[1];
      const index = match.index ?? 0;
      if (index > last) out.push(text.slice(last, index));
      last = index + match[0].length;
      const key = `${index}`;

      if (NODE_ONLY.test(token)) {
        const kind = nodeKind(token);
        const chip = <span className={`rounded bg-surface-2 px-0.5 break-anywhere ${mono}`}>{token}</span>;
        out.push(
          kind ? (
            <Define key={key} term={{ label: token, definition: kind }} className="no-underline">
              {chip}
            </Define>
          ) : (
            <Fragment key={key}>{chip}</Fragment>
          ),
        );
        continue;
      }
      const term = lookupTerm(token);
      if (term) {
        if (seen.has(token)) {
          out.push(
            <span key={key} className={mono}>
              {token}
            </span>,
          );
        } else {
          seen.add(token);
          out.push(
            <Define key={key} term={term}>
              <span className={mono}>{token}</span>
            </Define>,
          );
        }
        continue;
      }
      // An evidence reference: a chip when the run really has it, plain text otherwise.
      if (ctx && (ctx.view.evidence[token] || ctx.view.origins[token])) {
        out.push(<Cite key={key} id={token} compact />);
      } else {
        out.push(match[0]);
      }
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }, [text, ctx]);

  return <>{parts}</>;
}
