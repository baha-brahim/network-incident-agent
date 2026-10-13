"use client";

import { AlertTriangle, Info } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { cx } from "@/lib/cx";

export type NoticeTone = "danger" | "warn" | "neutral" | "event" | "ok";

export function Notice({
  tone = "neutral",
  title,
  children,
  action,
  role,
  className,
}: {
  tone?: NoticeTone;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  role?: "alert" | "status";
  className?: string;
}) {
  const alarming = tone === "danger" || tone === "warn";
  const Icon = alarming ? AlertTriangle : Info;
  return (
    <div role={role} className={cx("notice", alarming && `is-${tone}`, className)}>
      <Icon aria-hidden size={16} />
      <div className="min-w-0 flex-1">
        <p className="notice-title">{title}</p>
        {children ? <div className="notice-body">{children}</div> : null}
        {action ? <div className="notice-actions">{action}</div> : null}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cx("skeleton", className)} />;
}

/** Said once a wait has gone on for a while, so a slow server does not look like a frozen page. */
export function SlowNote({ after = 6000 }: { after?: number }) {
  const [late, setLate] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setLate(true), after);
    return () => clearTimeout(timer);
  }, [after]);
  return late ? (
    <p role="status" className="slow-note">
      Still waiting for the server. It may be starting up.
    </p>
  ) : null;
}

export const buttonStyles = {
  primary: "btn is-primary",
  secondary: "btn",
  ghost: "link",
};
