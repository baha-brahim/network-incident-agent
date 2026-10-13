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
        <>
          <strong>{term.label}</strong>
          {term.definition}
        </>
      }
    >
      <span tabIndex={0} className={cx("def", className)}>
        {children}
      </span>
    </Tip>
  );
}
