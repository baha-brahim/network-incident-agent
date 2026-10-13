"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import "./shell.css";

const LINKS = [
  { href: "/", label: "Investigate", match: (p: string) => p === "/" },
  { href: "/incidents", label: "Incidents", match: (p: string) => p.startsWith("/incidents") },
  { href: "/how-it-works", label: "How it works", match: (p: string) => p.startsWith("/how-it-works") },
];

export function SiteHeader() {
  const pathname = usePathname();
  return (
    <header className="site-header">
      <div className="page site-header-row">
        <Link href="/" className="site-brand">
          Network Incident Agent
        </Link>
        <nav aria-label="Main" className="site-nav">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} aria-current={l.match(pathname) ? "page" : undefined}>
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
