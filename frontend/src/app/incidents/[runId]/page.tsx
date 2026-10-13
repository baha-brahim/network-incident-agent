import type { Metadata } from "next";
import { StoredRun } from "@/components/incidents/stored-run";

export async function generateMetadata({ params }: { params: Promise<{ runId: string }> }): Promise<Metadata> {
  const { runId } = await params;
  let id = runId;
  try {
    id = decodeURIComponent(runId);
  } catch {
    // A malformed escape in the address: show it as it came.
  }
  return { title: `Saved run ${id.slice(0, 40)}` };
}

export default async function Page({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <StoredRun runId={runId} />;
}
