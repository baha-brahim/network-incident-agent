import type { Metadata } from "next";
import { StoredRun } from "@/components/incidents/stored-run";

export const metadata: Metadata = { title: "Saved run" };

export default async function Page({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <StoredRun runId={runId} />;
}
