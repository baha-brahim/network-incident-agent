"use client";

import type { ReactNode } from "react";
import { Tip } from "./tip";
import { cx } from "@/lib/cx";
import type { Term as TermData } from "@/lib/labels";

/** A word with a plain-language definition on hover, focus or tap. */
export function Define({
  term,
  children,
  className,
}: {
  term: Pick<TermData, "label" | "definition">;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Tip
      content={
        <span className="block">
          <span className="block font-medium">{term.label}</span>
          <span className="block text-muted">{term.definition}</span>
        </span>
      }
    >
      <span
        tabIndex={0}
        className={cx("cursor-help underline decoration-muted/60 decoration-dotted underline-offset-[3px]", className)}
      >
        {children}
      </span>
    </Tip>
  );
}
