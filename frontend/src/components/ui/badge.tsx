import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import type { Tone } from "@/lib/labels";

const TONES: Record<Tone, string> = {
  danger: "bg-danger-soft text-danger",
  warn: "bg-warn-soft text-warn",
  event: "bg-event-soft text-event",
  ok: "bg-ok-soft text-ok",
  neutral: "bg-surface-2 text-muted",
};

export const toneText: Record<Tone, string> = {
  danger: "text-danger",
  warn: "text-warn",
  event: "text-event",
  ok: "text-ok",
  neutral: "text-muted",
};

export function Badge({
  tone = "neutral",
  children,
  className,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-xs font-medium leading-4",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
