import type { Metadata } from "next";
import { IncidentsView } from "@/components/incidents/incidents-view";

export const metadata: Metadata = { title: "Incidents" };

export default function Page() {
  return <IncidentsView />;
}
