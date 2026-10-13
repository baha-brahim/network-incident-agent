import { ArrowRight } from "lucide-react";
import { Skeleton, SlowNote } from "@/components/ui/notice";
import { cx } from "@/lib/cx";
import type { DemoSummary } from "@/lib/types";
import { demoMeta } from "./demo-text";

export function CaseList({ demos, onPick }: { demos: readonly DemoSummary[]; onPick(demo: DemoSummary): void }) {
  return (
    <ul className="case-list">
      {demos.map((demo, i) => (
        <li key={demo.id}>
          <button type="button" className={cx("case", i === 0 && "is-first")} onClick={() => onPick(demo)}>
            <span className="case-main">
              <span className="case-title" dir="auto">
                {demo.title}
                {i === 0 ? <span className="tag">Start here</span> : null}
              </span>
              {demo.teaser.trim() ? (
                <span className="case-teaser" dir="auto">
                  {demo.teaser}
                </span>
              ) : null}
            </span>
            {demo.question.trim() ? (
              <span className="case-q" dir="auto">
                “{demo.question}”
              </span>
            ) : (
              <span aria-hidden />
            )}
            <span className="case-meta">
              <span className="mono">{demoMeta(demo)}</span>
              <ArrowRight aria-hidden size={18} strokeWidth={2} />
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function CaseListSkeleton() {
  return (
    <>
      <p className="sr-only" role="status">
        Loading the recorded cases
      </p>
      <ul aria-hidden className="case-list">
        {Array.from({ length: 5 }, (_, i) => (
          <li key={i} className={cx("case-skeleton", i === 0 && "is-first")}>
            <span className="case-main">
              <Skeleton className="sk-title" />
              <Skeleton className="sk-line" />
            </span>
            <Skeleton className="sk-line sk-q" />
            <Skeleton className="sk-line sk-meta" />
          </li>
        ))}
      </ul>
      <SlowNote />
    </>
  );
}
