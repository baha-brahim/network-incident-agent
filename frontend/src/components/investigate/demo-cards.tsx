"use client";

import { Play } from "lucide-react";
import { cx } from "@/lib/cx";
import { Skeleton } from "@/components/ui/notice";
import type { DemoSummary } from "@/lib/types";

export function DemoCards({ demos, onPick }: { demos: DemoSummary[]; onPick(demo: DemoSummary): void }) {
  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {demos.map((demo, i) => {
        const first = i === 0;
        return (
          <li key={demo.id} className={cx(first && "lg:col-span-2")}>
            <button
              type="button"
              onClick={() => onPick(demo)}
              className={cx(
                "press hover-border group flex h-full w-full flex-col gap-3 rounded-xl border bg-surface p-4 text-left",
                first ? "border-accent/50 bg-accent-soft/50" : "border-line",
              )}
            >
              <span className="flex items-start justify-between gap-3">
                <span className="min-w-0">
                  {first ? (
                    <span className="mb-1.5 inline-block rounded-md bg-accent px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-accent-fg">
                      Start here
                    </span>
                  ) : null}
                  <span className={cx("block font-semibold leading-snug break-anywhere", first ? "text-lg" : "text-base")}>{demo.title}</span>
                </span>
                <span
                  aria-hidden
                  className={cx(
                    "mt-0.5 grid size-8 shrink-0 place-items-center rounded-full",
                    first ? "bg-accent text-accent-fg" : "bg-surface-2 text-muted group-hover:bg-accent group-hover:text-accent-fg",
                  )}
                >
                  <Play className="size-3.5 translate-x-px fill-current" />
                </span>
              </span>
              <span className="text-sm text-muted break-anywhere">{demo.teaser}</span>
              <span className="mt-auto flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-line pt-3 text-xs text-muted">
                <span className="line-clamp-2 italic break-anywhere">“{demo.question}”</span>
                <span className="whitespace-nowrap font-mono">
                  {demo.counts.tool_calls} tool calls · ~{Math.round(demo.duration_ms / 1000)} s
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function DemoCardsSkeleton() {
  return (
    <ul aria-hidden className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 8 }, (_, i) => (
        <li key={i} className={cx(i === 0 && "lg:col-span-2")}>
          <Skeleton className="h-36 w-full rounded-xl" />
        </li>
      ))}
    </ul>
  );
}
