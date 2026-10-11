import type { Metadata } from "next";
import { AboutView } from "@/components/about/about-view";

export const metadata: Metadata = { title: "How it works" };

export default function Page() {
  return <AboutView />;
}
