import { ArrowRight, ExternalLink } from "lucide-react";
import Link from "next/link";
import { RESULTS } from "@/lib/results";
import { Pipeline } from "./pipeline";
import { ResultBlock } from "./result-block";
import "./about.css";

const REPO_URL = process.env.NEXT_PUBLIC_REPO_URL;

const IDEAS = [
  {
    title: "A case file, not a transcript",
    text: "Everything the agent learns goes into a compact case file of one-line headlines and evidence IDs, not raw tables. Old tool output is trimmed once used, so each model call stays small.",
  },
  {
    title: "Checked citations",
    text: "Every claim in the report cites evidence IDs that came from a tool result. A verification step then checks that each reference exists, that times are in range and that node IDs are real.",
  },
  {
    title: "No looking into the future",
    text: "Every query stops at the moment the question was asked, and baselines use only earlier data. The agent cannot use hindsight to reach its answer.",
  },
  {
    title: "Guardrails in code",
    text: "The tools are read-only, and the SQL tool has allow-lists and limits. A completeness gate sends the agent back if it has not looked at maintenance, changes and events, and code can lower a confidence the model claimed.",
  },
];

export function AboutView() {
  return (
    <div className="page hw">
      <header className="hw-intro">
        <h1>How it works</h1>
        <p>
          The network here is synthetic, with incidents planted at known places and times. That means the agent&apos;s answers can be checked against the
          truth, not only judged by how convincing they sound.
        </p>
      </header>

      <section aria-labelledby="pipeline" className="hw-section">
        <h2 id="pipeline">One investigation, five stages</h2>
        <Pipeline />
      </section>

      <section aria-labelledby="ideas" className="hw-section hw-ideas">
        <h2 id="ideas">Four design ideas</h2>
        <div className="hw-ideas-list">
          {IDEAS.map((idea) => (
            <div key={idea.title} className="hw-idea">
              <h3>{idea.title}</h3>
              <p>{idea.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="results" className="hw-section">
        <h2 id="results">What has been measured</h2>
        <p className="hw-results-intro">
          Read each block with the dataset it comes from. Every figure here comes from worlds that were not looked at while the agent was written; the
          hard world is built so that the obvious explanation is often the wrong one.
        </p>
        <div className="hw-blocks">
          {RESULTS.map((block) => (
            <ResultBlock key={block.id} block={block} />
          ))}
        </div>
      </section>

      <section aria-labelledby="next" className="hw-next">
        <h2 id="next">See an investigation</h2>
        <p>Open a recorded case to watch an investigation run.</p>
        <div className="hw-next-actions">
          <Link href="/" className="btn is-primary">
            Open a recorded case
            <ArrowRight aria-hidden className="size-4" />
          </Link>
          {REPO_URL ? (
            <a href={REPO_URL} target="_blank" rel="noreferrer noopener" className="btn">
              Full results and source code
              <ExternalLink aria-hidden className="size-3.5" />
            </a>
          ) : null}
        </div>
      </section>
    </div>
  );
}
