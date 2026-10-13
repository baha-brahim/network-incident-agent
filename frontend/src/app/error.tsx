"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

/** Shown when a screen fails while drawing, so the person is never left with a blank page. */
export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus({ preventScroll: true }), []);
  return (
    <div className="page py-14 sm:py-20">
      <div className="max-w-xl border-t-2 border-ink pt-5">
        <h1 ref={heading} tabIndex={-1} className="text-3xl font-bold leading-tight tracking-tight outline-none">
          Something went wrong on this page
        </h1>
        <p className="mt-3 text-base leading-relaxed">The page could not be drawn. Trying again often fixes it.</p>
        <div className="mt-6 flex flex-wrap gap-2">
          <button type="button" className="btn is-primary" onClick={reset}>
            Try again
          </button>
          <Link href="/" className="btn">
            Back to the cases
          </Link>
        </div>
      </div>
    </div>
  );
}
