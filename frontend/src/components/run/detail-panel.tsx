"use client";

import { AlertTriangle, Brain, Compass, MousePointerClick, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { buttonStyles } from "@/components/ui/notice";
import { RichText } from "@/components/ui/rich-text";
import { Define } from "@/components/ui/term";
import { argRows, listValueLabel } from "@/lib/args";
import { extractChart, extractDeviationPct } from "@/lib/chart";
import { cx } from "@/lib/cx";
import { fmtIso } from "@/lib/format";
import type { RunView, Step, ToolStep } from "@/lib/investigation";
import { EVIDENCE_KINDS, METRICS, TOOLS, nodeKind, toolLabel } from "@/lib/labels";
import { missingSentence, regionNames } from "@/lib/steps";
import { ToolIcon } from "./tool-icon";
import { KpiChart } from "./kpi-chart";
import { useRunContext } from "./run-context";

export function DetailPanel({ step, view }: { step: Step | null; view: RunView }) {
  if (!step) {
    return (
      <div className="grid min-h-48 place-items-center rounded-xl border border-dashed border-line-strong p-6 text-center">
        <div className="max-w-xs">
          <MousePointerClick aria-hidden className="mx-auto mb-2 size-5 text-muted" />
          <p className="text-sm font-medium">Pick a step</p>
          <p className="mt-1 text-sm text-muted">
            Select a step in the timeline to see what the agent asked, what came back, and the evidence behind it.
          </p>
        </div>
      </div>
    );
  }
  switch (step.kind) {
    case "tool":
      return <ToolDetail step={step} />;
    case "scope":
      return <ScopeDetail step={step} />;
    case "note":
      return (
        <Panel icon={<Brain aria-hidden className="size-4 text-accent" />} title="Reasoning" subtitle="The agent's notes to itself between tool calls">
          <p className="whitespace-pre-wrap text-sm leading-relaxed break-anywhere">
            <RichText text={step.text} />
          </p>
        </Panel>
      );
    case "gate":
      return (
        <Panel icon={<ShieldCheck aria-hidden className="size-4 text-warn" />} title="Completeness check" subtitle="A rule in code, not a model decision">
          <p className="text-sm">
            The agent started to conclude, but had not yet checked: <strong>{missingSentence(step.data.missing)}</strong>. It was sent back to look before
            writing the report.
          </p>
          <p className="mt-3 text-xs text-muted">Message sent to the agent</p>
          <p className="mt-1 rounded-lg bg-surface-2 p-2.5 font-mono text-xs leading-relaxed break-anywhere">{step.data.message}</p>
        </Panel>
      );
    case "error":
      return (
        <Panel icon={<AlertTriangle aria-hidden className="size-4 text-danger" />} title="The run hit an error" subtitle={step.where ? `While: ${step.where}` : undefined}>
          <p className="rounded-lg bg-danger-soft p-3 text-sm text-danger break-anywhere">{step.message}</p>
          <p className="mt-3 text-sm text-muted">
            The investigation stopped here. Anything the agent had found before this point is in the timeline.
          </p>
        </Panel>
      );
    case "model":
      return null;
  }
  void view;
}

function Panel({
  icon,
  title,
  subtitle,
  aside,
  children,
}: {
  icon: ReactNode;
  title: string;
  subtitle?: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-label={`Step detail: ${title}`} className="space-y-4">
      <header className="flex items-start gap-3">
        <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2">{icon}</span>
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold leading-6">{title}</h3>
          {subtitle ? <p className="text-sm text-muted break-anywhere">{subtitle}</p> : null}
        </div>
        {aside}
      </header>
      {children}
    </section>
  );
}

function Label({ children }: { children: ReactNode }) {
  return <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">{children}</h4>;
}

function ScopeDetail({ step }: { step: Extract<Step, { kind: "scope" }> }) {
  const d = step.data;
  const rows: Array<[string, ReactNode]> = [
    ["Symptom", d.symptom],
    ["From", fmtIso(d.window_start)],
    ["To", fmtIso(d.window_end)],
    ["Where", d.nationwide ? "Nationwide" : regionNames(d.region_ids).join(", ") || "Not narrowed to a region"],
    ["Nodes", d.node_ids.length ? <IdChips ids={d.node_ids} /> : "None named"],
    ["Still going", d.ongoing ? "Yes" : "No"],
  ];
  return (
    <Panel
      icon={<Compass aria-hidden className="size-4" />}
      title="Scope understood"
      subtitle="How the agent read the question, before looking at any data"
    >
      <dl className="grid grid-cols-[5.5rem_1fr] sm:grid-cols-[7rem_1fr] gap-x-3 gap-y-2 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted">{k}</dt>
            <dd className="break-anywhere">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-muted">All times are Africa/Tunis (UTC+1).</p>
      {d.source === "default" ? (
        <p className="rounded-lg bg-warn-soft p-2.5 text-sm text-warn">
          The question was too vague to read a window from, so a default window was used.
        </p>
      ) : null}
      {d.unknown_ids.length ? (
        <p className="rounded-lg bg-warn-soft p-2.5 text-sm text-warn">
          Not found in the network: <span className="font-mono">{d.unknown_ids.join(", ")}</span>
        </p>
      ) : null}
    </Panel>
  );
}

const CHIP_LIMIT = 12;

function IdChips({ ids, metrics = false }: { ids: readonly string[]; metrics?: boolean }) {
  const [all, setAll] = useState(false);
  const shown = all ? ids : ids.slice(0, CHIP_LIMIT);
  return (
    <span className="flex flex-wrap items-center gap-1">
      {shown.map((id) => {
        const kind = metrics ? null : nodeKind(id);
        const metric = metrics ? METRICS[id] : null;
        const chip = <span className="inline-block rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs break-anywhere">{metrics ? listValueLabel("metrics", id) : id}</span>;
        if (metric) {
          return (
            <Define key={id} term={{ label: `${metric.label} (${id})`, definition: metric.definition }} className="no-underline">
              {chip}
            </Define>
          );
        }
        return kind ? (
          <Define key={id} term={{ label: id, definition: kind }} className="no-underline">
            {chip}
          </Define>
        ) : (
          <span key={id}>{chip}</span>
        );
      })}
      {ids.length > CHIP_LIMIT ? (
        <button type="button" onClick={() => setAll((v) => !v)} className="press rounded px-1.5 py-0.5 text-xs text-accent hover:underline">
          {all ? "Show fewer" : `+${ids.length - CHIP_LIMIT} more`}
        </button>
      ) : null}
    </span>
  );
}

function ToolDetail({ step }: { step: ToolStep }) {
  const ctx = useRunContext();
  const result = step.result;
  const rows = argRows(step.args);
  const series = extractChart(result?.data);
  const pct = extractDeviationPct(result?.data);
  const [showAllCharts, setShowAllCharts] = useState(false);
  const [showAllRefs, setShowAllRefs] = useState(false);
  const refs = result?.refs ?? [];
  const focusRef = ctx?.focusRef ?? null;
  const focusIndex = focusRef ? refs.findIndex((r) => r.ref === focusRef) : -1;
  const shownRefs = showAllRefs || refs.length <= 8 ? refs : refs.filter((_, i) => i < 8 || i === focusIndex);
  const rowRef = useRef<HTMLLIElement>(null);

  useEffect(() => {
    rowRef.current?.scrollIntoView({ block: "nearest" });
  }, [focusRef, step.id]);

  const sorted = [...series].sort((a, b) => Number(!!b.deviation) - Number(!!a.deviation));
  const charts = showAllCharts ? sorted : sorted.slice(0, 6);

  const status =
    step.status === "running" ? (
      <Badge tone="neutral">Running</Badge>
    ) : step.status === "skipped" ? (
      <Badge>Skipped</Badge>
    ) : step.status === "error" ? (
      <Badge tone="danger">Error</Badge>
    ) : null;

  return (
    <Panel
      icon={<ToolIcon tool={step.tool} className="size-4" />}
      title={toolLabel(step.tool)}
      subtitle={TOOLS[step.tool]?.definition}
      aside={
        <div className="flex shrink-0 flex-col items-end gap-1">
          <span className="font-mono text-xs text-muted">{step.id}</span>
          {status}
        </div>
      }
    >
      {result ? (
        <p className={cx("rounded-lg px-3 py-2 text-sm break-anywhere", result.error ? "bg-danger-soft text-danger" : "bg-surface-2")}>
          {result.error ? result.error : <RichText text={result.headline} />}
        </p>
      ) : (
        <p className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2 text-sm text-muted">
          <span aria-hidden className="spinner inline-block size-3 rounded-full border-2 border-accent border-t-transparent" />
          Waiting for the result…
        </p>
      )}

      {step.status === "skipped" ? (
        <p className="text-sm text-muted">
          This call repeated an earlier one{result?.duplicate_of ? ` (${result.duplicate_of})` : ""}, so it was not run again and nothing new came back.
        </p>
      ) : null}

      <div>
        <Label>What the agent asked</Label>
        {rows.length ? (
          <dl className="grid grid-cols-[5.5rem_1fr] sm:grid-cols-[7.5rem_1fr] gap-x-3 gap-y-1.5 text-sm">
            {rows.map((row) => (
              <div key={row.key} className="contents">
                <dt className="text-muted">{row.label}</dt>
                <dd className="min-w-0 break-anywhere">
                  {row.kind === "list" ? (
                    <IdChips ids={row.value as string[]} metrics={row.key === "metrics"} />
                  ) : row.kind === "time" ? (
                    <span className="font-mono text-[13px]">{row.value as string}</span>
                  ) : row.kind === "code" ? (
                    <pre className="whitespace-pre-wrap rounded bg-surface-2 p-2 font-mono text-xs">{row.value as string}</pre>
                  ) : row.kind === "text" && nodeKind(String(row.value)) ? (
                    <IdChips ids={[String(row.value)]} />
                  ) : (
                    String(row.value)
                  )}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-sm text-muted">No arguments.</p>
        )}
        {rows.some((r) => r.kind === "time") ? <p className="mt-1.5 text-xs text-muted">Times are Africa/Tunis.</p> : null}
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-xs text-muted hover:text-fg">Raw arguments</summary>
          <pre className="scroll-thin mt-1.5 overflow-x-auto rounded-lg bg-surface-2 p-2.5 font-mono text-xs leading-relaxed">
            {JSON.stringify(step.args, null, 2)}
          </pre>
        </details>
      </div>

      {sorted.length > 0 ? (
        <div>
          <Label>KPI series against their usual level</Label>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,17rem),1fr))] gap-3">
            {charts.map((s) => (
              <KpiChart key={`${s.entity_id}|${s.metric}`} series={s} deviationPct={pct.get(`${s.entity_id}|${s.metric}`)} />
            ))}
          </div>
          {sorted.length > 6 ? (
            <button type="button" className={cx(buttonStyles.secondary, "mt-3")} onClick={() => setShowAllCharts((v) => !v)}>
              {showAllCharts ? "Show fewer charts" : `Show all ${sorted.length} charts`}
            </button>
          ) : null}
        </div>
      ) : null}

      {result && !result.error && step.status !== "skipped" ? (
        <div>
          <Label>Output the agent read</Label>
          <pre className="scroll-thin max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-surface-2 p-3 font-mono text-xs leading-relaxed break-anywhere">
            {result.body || "(empty)"}
          </pre>
          {result.truncated || result.data_truncated ? (
            <p className="mt-1.5 text-xs text-muted">Long output was cut short before the agent saw it.</p>
          ) : null}
        </div>
      ) : null}

      {refs.length > 0 ? (
        <div>
          <Label>Evidence this step produced ({refs.length})</Label>
          <ul className="divide-y divide-line rounded-lg border border-line">
            {shownRefs.map((r) => {
              const focused = r.ref === focusRef;
              return (
                <li
                  key={r.ref}
                  ref={focused ? rowRef : undefined}
                  className={cx("grid gap-x-3 gap-y-0.5 px-3 py-2 text-sm sm:grid-cols-[minmax(0,9rem)_1fr]", focused && "bg-accent-soft")}
                >
                  <span className="min-w-0">
                    <span className="block font-mono text-xs break-anywhere">{r.ref}</span>
                    <span className="block text-[11px] text-muted">{EVIDENCE_KINDS[r.kind]?.label ?? r.kind}</span>
                  </span>
                  <span className="min-w-0 text-muted break-anywhere">{r.summary}</span>
                </li>
              );
            })}
          </ul>
          {refs.length > 8 ? (
            <button type="button" className={cx(buttonStyles.secondary, "mt-3")} onClick={() => setShowAllRefs((v) => !v)}>
              {showAllRefs ? "Show fewer" : `Show all ${refs.length}`}
            </button>
          ) : null}
        </div>
      ) : null}

      {result ? (
        <p className="text-xs text-muted">
          Tool time {result.wall_ms} ms · {result.n_refs} reference{result.n_refs === 1 ? "" : "s"}
        </p>
      ) : null}
    </Panel>
  );
}
