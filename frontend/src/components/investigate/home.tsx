"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import type { AsyncState } from "@/hooks/use-async";
import { RESULTS } from "@/lib/results";
import type { DemoSummary, Meta } from "@/lib/types";
import { Cases, type Mode } from "./cases";
import { aboutSeconds } from "./demo-text";
import { measured } from "./measured";
import { HomePreview } from "./home-preview";
import "./home.css";

interface Props {
  mode: Mode;
  onMode(mode: Mode): void;
  demos: AsyncState<DemoSummary[]>;
  meta: AsyncState<Meta>;
  onStartDemo(demo: DemoSummary): void;
  onStartLive(question: string): void;
}

export function Home({ mode, onMode, demos, meta, onStartDemo, onStartLive }: Props) {
  const first = demos.data?.[0] ?? null;
  const unreachable = !demos.loading && (!!demos.error || !demos.data);
  const score = measured(RESULTS);
  const reason = unreachable ? "The server is not answering." : demos.loading ? "Loading the cases." : !first ? "There are no recorded cases yet." : null;

  return (
    <div className="page home">
      <div className="home-top">
        <h1 className="home-title">Several sites went quiet. Watch an agent find out why.</h1>
        <p className="home-pitch">
          The agent investigates a synthetic Tunisian mobile network the way an engineer would: it reads alarms, KPIs, the change log and the maintenance
          calendar, takes notes, then writes a report in which every claim points to evidence you can open.
        </p>

        <div className="home-go">
          <button type="button" className="btn is-primary" disabled={!first} onClick={() => first && onStartDemo(first)}>
            Watch it investigate
            <ArrowRight aria-hidden size={18} strokeWidth={2} />
          </button>
          <span className="home-go-note">{first ? <span className="mono">{aboutSeconds(first)}</span> : reason}</span>
        </div>

        {score ? (
          <p className="home-measure">
            On development data: right verdict in {score.verdict} planted scenarios, right cause and node in {score.cause}.{" "}
            <Link href="/how-it-works" className="link">
              How it was measured
            </Link>
          </p>
        ) : null}

        <HomePreview
          demo={first}
          unavailable={unreachable ? "The preview needs the server, which is not answering." : demos.loading ? null : "There is no recorded case to preview."}
          onWatch={onStartDemo}
        />
      </div>

      <Cases mode={mode} onMode={onMode} demos={demos} meta={meta} onStartDemo={onStartDemo} onStartLive={onStartLive} />
    </div>
  );
}
