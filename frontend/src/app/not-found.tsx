import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <div className="page py-14 sm:py-20">
      <div className="max-w-xl border-t-2 border-ink pt-5">
        <h1 className="text-3xl font-bold leading-tight tracking-tight">There is no page here</h1>
        <p className="mt-3 text-base leading-relaxed">The link may be wrong or out of date.</p>
        <div className="mt-6 flex flex-wrap gap-2">
          <Link href="/" className="btn is-primary">
            Back to the cases
          </Link>
          <Link href="/incidents" className="btn">
            See all incidents
          </Link>
        </div>
      </div>
    </div>
  );
}
