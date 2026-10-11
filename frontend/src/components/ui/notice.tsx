import { AlertTriangle, Info } from "lucide-react";
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import type { Tone } from "@/lib/labels";

const STYLES: Record<Tone, string> = {
  danger: "border-danger/30 bg-danger-soft",
  warn: "border-warn/30 bg-warn-soft",
  event: "border-event/30 bg-event-soft",
  ok: "border-ok/30 bg-ok-soft",
  neutral: "border-line bg-surface-2",
};
const ICON: Record<Tone, string> = {
  danger: "text-danger",
  warn: "text-warn",
  event: "text-event",
  ok: "text-ok",
  neutral: "text-muted",
};

export function Notice({
  tone = "neutral",
  title,
  children,
  action,
  role,
  className,
}: {
  tone?: Tone;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  role?: "alert" | "status";
  className?: string;
}) {
  const Icon = tone === "danger" || tone === "warn" ? AlertTriangle : Info;
  return (
    <div role={role} className={cx("flex gap-3 rounded-xl border p-3.5 text-sm", STYLES[tone], className)}>
      <Icon aria-hidden className={cx("mt-0.5 size-4 shrink-0", ICON[tone])} />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{title}</p>
        {children ? <div className="mt-1 text-muted break-anywhere">{children}</div> : null}
        {action ? <div className="mt-3 flex flex-wrap gap-2">{action}</div> : null}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cx("skeleton", className)} />;
}

const BUTTON =
  "press inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-medium disabled:opacity-50 disabled:active:scale-100";
export const buttonStyles = {
  primary: `${BUTTON} bg-accent text-accent-fg hover:opacity-90`,
  secondary: `${BUTTON} border border-line-strong bg-surface hover-surface`,
  ghost: `${BUTTON} text-muted hover-surface hover:text-fg`,
};
