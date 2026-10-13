"use client";

import { ArrowRight, X } from "lucide-react";
import { fmtIso } from "@/lib/format";
import type { RunView } from "@/lib/investigation";
import { ALARM_TYPES, EVIDENCE_KINDS, nodeKind } from "@/lib/labels";
import { chainOf, humanize, nodeEvidence, type NetNode, type Network } from "@/lib/network";
import { plainText } from "@/lib/steps";

const REF_LIMIT = 6;

interface NodeDetailProps {
  node: NetNode;
  view: RunView;
  net: Network;
  onClose(): void;
  goStep(id: string): void;
}

/** What the run knows about one node of the network diagram, and the steps it comes from. */
export function NodeDetail({ node, view, net, onClose, goStep }: NodeDetailProps) {
  const chain = chainOf(net, node.id);
  const evidence = nodeEvidence(view, node.id);
  const shown = evidence.slice(0, REF_LIMIT);
  const hasStep = (id: string) => view.steps.some((s) => s.id === id);
  const calls = view.steps.filter((s) => s.kind === "tool" && node.touchedBy.includes(s.id));
  const verdict = net.concluded && node.flags.root ? net.rootLabel : net.concluded && node.flags.affected ? "Affected" : null;

  return (
    <aside className="dt" aria-label="Selected node" aria-live="polite">
      <div className="dt-head">
        <h2 className="dt-id">{node.id}</h2>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Clear selection">
          <X aria-hidden size={16} />
        </button>
      </div>
      <p className="dt-kind">
        {nodeKind(node.id) ?? "Node"}
        {verdict ? ` · ${verdict}` : ""}
      </p>

      {chain.length > 0 ? (
        <p className="dt-chain">
          <span className="dt-chain-lead">Sits under</span>
          {chain.map((id, i) => (
            <span key={id} className="dt-chain-step">
              <code className="id">{id}</code>
              {i < chain.length - 1 ? <ArrowRight aria-hidden size={13} strokeWidth={2} /> : null}
            </span>
          ))}
        </p>
      ) : node.layer > 0 ? (
        <p className="dt-hint">Nothing above it has been looked up yet.</p>
      ) : null}

      <h3>Alarms</h3>
      {node.alarms.length === 0 ? (
        <p className="dt-hint">None read for this node.</p>
      ) : (
        <ul className="dt-facts">
          {node.alarms.map((a) => (
            <li key={a.id}>
              <strong>{ALARM_TYPES[a.type]?.label ?? humanize(a.type)}</strong>
              <span className="dt-ref-kind">
                {a.severity}
                {a.count > 1 ? `, ${a.count} raised` : ""} · <code>{a.id}</code>
              </span>
              <span>
                {fmtIso(a.raisedAt)} to {a.clearedAt ? fmtIso(a.clearedAt) : "still active"}
              </span>
            </li>
          ))}
        </ul>
      )}

      {node.markers.length > 0 ? (
        <>
          <h3>Changes, maintenance and events</h3>
          <ul className="dt-facts">
            {node.markers.map((m) => (
              <li key={m.id}>
                <strong>{m.label}</strong>
                <span className="dt-ref-kind">
                  {m.kind === "change" ? "Change" : m.kind === "maintenance" ? "Maintenance window" : "External event"} · <code>{m.id}</code>
                </span>
                <span>
                  {fmtIso(m.at)}
                  {m.until ? ` to ${fmtIso(m.until)}` : ""}
                </span>
                {m.description ? <span>{plainText(m.description)}</span> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {shown.length > 0 ? (
        <>
          <h3>Evidence that mentions it</h3>
          <ul className="dt-refs">
            {shown.map(([ref, e]) => {
              const origin = view.origins[ref] ?? ref;
              return (
                <li key={ref}>
                  <code>{ref}</code>
                  <span className="dt-ref-kind">{EVIDENCE_KINDS[e.kind]?.label ?? e.kind}</span>
                  <span>{plainText(e.summary)}</span>
                  {hasStep(origin) ? (
                    <button type="button" className="link" onClick={() => goStep(origin)}>
                      from step {origin}
                      <span className="sr-only">, show it in the steps</span>
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
          {evidence.length > shown.length ? <p className="dt-hint">and {evidence.length - shown.length} more.</p> : null}
        </>
      ) : null}

      {calls.length > 0 ? (
        <p className="dt-calls">
          <span className="dt-chain-lead">Asked about in</span>
          {calls.slice(0, REF_LIMIT).map((s) => (
            <button key={s.id} type="button" className="link" onClick={() => goStep(s.id)}>
              {s.id}
            </button>
          ))}
        </p>
      ) : null}
      <p className="dt-hint">Times are Africa/Tunis.</p>
    </aside>
  );
}
