"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/lib/cx";

const LINKS = [
  { href: "/", label: "Investigate", match: (p: string) => p === "/" },
  { href: "/incidents", label: "Incidents", match: (p: string) => p.startsWith("/incidents") },
  { href: "/how-it-works", label: "How it works", match: (p: string) => p.startsWith("/how-it-works") },
];

export function SiteHeader() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-bg/90 pt-[env(safe-area-inset-top)] backdrop-blur">
      <div className="mx-auto flex h-[var(--header-h)] w-full max-w-[88rem] items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5 rounded-lg font-semibold tracking-tight">
          <svg aria-hidden viewBox="0 0 32 32" className="size-7 shrink-0">
            <rect width="32" height="32" rx="7" fill="var(--accent)" />
            <g stroke="var(--accent-fg)" strokeWidth="2" strokeLinecap="round" fill="none">
              <path d="M9 21l7-10 7 10" />
              <path d="M9 21h14" />
            </g>
            <g fill="var(--accent-fg)">
              <circle cx="16" cy="11" r="2.6" />
              <circle cx="9" cy="21" r="2.6" />
              <circle cx="23" cy="21" r="2.6" />
            </g>
          </svg>
          <span className="max-sm:sr-only">Network Incident Agent</span>
        </Link>
        <nav aria-label="Main" className="-mr-2 flex items-center gap-0.5">
          {LINKS.map((l) => {
            const active = l.match(pathname);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "press relative inline-flex min-h-10 items-center whitespace-nowrap rounded-lg px-2 text-sm font-medium sm:px-3",
                  active ? "text-fg" : "text-muted hover:text-fg",
                )}
              >
                {l.label}
                {active ? <span aria-hidden className="absolute inset-x-2 -bottom-[7px] sm:inset-x-3 h-0.5 rounded-full bg-accent" /> : null}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
