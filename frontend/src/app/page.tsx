import type { Metadata } from "next";
import { InvestigateView } from "@/components/investigate/investigate-view";

export const metadata: Metadata = { title: "Investigate" };

export default function Page() {
  return <InvestigateView />;
}
