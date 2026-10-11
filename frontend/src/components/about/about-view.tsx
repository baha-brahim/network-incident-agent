import { ArrowRight, ExternalLink } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { buttonStyles } from "@/components/ui/notice";
import { RESULTS } from "@/lib/results";

const REPO_URL = process.env.NEXT_PUBLIC_REPO_URL;

const PIPELINE = [
  { name: "intake", who: "Model", text: "Reads the question and turns it into a scope: the symptom, a time window, a region or nodes." },
  { name: "orient", who: "Code", text: "Runs the first lookups itself, such as the detector's alerts for that scope, so the model starts with facts." },
  { name: "investigate", who: "Model + code", text: "The model picks a tool, reads the result and writes a note. Code runs the tools and checks nothing was skipped." },
  { name: "conclude", who: "Model", text: "Writes the report as a structured document: cause, confidence, timeline, findings, and what was ruled out." },
  { name: "verify", who: "Code", text: "Checks every cited reference, time and node ID against the evidence, and asks for a repair if something is off." },
];

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
    <div className="mx-auto w-full max-w-5xl px-4 pb-20 pt-8 sm:px-6 sm:pt-10">
      <h1 className="text-balance text-3xl font-semibold tracking-tight">How it works</h1>
      <p className="mt-3 max-w-2xl text-base leading-7 text-muted">
        The network here is synthetic, with incidents planted at known places and times. That means the agent&apos;s answers can be checked against the
        truth, not only judged by how convincing they sound.
      </p>

      <section aria-labelledby="pipeline" className="mt-12">
        <h2 id="pipeline" className="text-xl font-semibold tracking-tight">
          One investigation, five stages
        </h2>
        <ol className="mt-5 grid gap-3 md:grid-cols-5 md:gap-5">
          {PIPELINE.map((stage, i) => (
            <li key={stage.name} className="relative rounded-xl border border-line bg-surface p-4">
              <span className="font-mono text-sm font-semibold">{stage.name}</span>
              <div className="mt-1.5">
                <Badge tone={stage.who === "Code" ? "neutral" : "event"}>{stage.who}</Badge>
              </div>
              <p className="mt-2 text-sm leading-6 text-muted">{stage.text}</p>
              {i < PIPELINE.length - 1 ? (
                <ArrowRight aria-hidden className="absolute -right-[18px] top-6 hidden size-4 text-muted md:block" />
              ) : null}
            </li>
          ))}
        </ol>
        <p className="mt-3 text-sm text-muted">
          Stage three repeats: ask for a tool, read the result, write a note. Open a{" "}
          <Link href="/" className="text-accent underline underline-offset-2">
            replay
          </Link>{" "}
          to watch it happen.
        </p>
      </section>

      <section aria-labelledby="ideas" className="mt-14">
        <h2 id="ideas" className="text-xl font-semibold tracking-tight">
          Four design ideas
        </h2>
        <ul className="mt-5 grid gap-4 sm:grid-cols-2">
          {IDEAS.map((idea, i) => (
            <li key={idea.title} className="rounded-xl border border-line bg-surface p-5">
              <p className="font-mono text-xs text-muted">{String(i + 1).padStart(2, "0")}</p>
              <h3 className="mt-1 text-base font-semibold">{idea.title}</h3>
              <p className="mt-2 text-sm leading-6 text-muted">{idea.text}</p>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="results" className="mt-14">
        <h2 id="results" className="text-xl font-semibold tracking-tight">
          What has been measured
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
          Read each block with the dataset it comes from. The agent&apos;s figures are from the world its prompts were written on, so they are the optimistic
          case.
        </p>
        <div className="mt-5 space-y-6">
          {RESULTS.map((block) => (
            <article key={block.id} className="rounded-xl border border-line bg-surface">
              <header className="border-b border-line p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-base font-semibold">{block.title}</h3>
                  <Badge tone={block.datasetTone === "caution" ? "warn" : "ok"}>
                    {block.datasetTone === "caution" ? "Development data: optimistic" : "Held-out data"}
                  </Badge>
                </div>
                <p className="mt-1.5 text-sm text-muted">{block.dataset}</p>
              </header>
              <dl className="divide-y divide-line">
                {block.rows.map((row) => (
                  <div key={row.metric} className="grid gap-x-6 gap-y-0.5 px-5 py-3 sm:grid-cols-[1fr_auto]">
                    <dt className="text-sm">{row.metric}</dt>
                    <dd className="font-mono text-sm font-medium sm:text-right">{row.value}</dd>
                    {row.note ? <p className="text-xs text-muted sm:col-span-2">{row.note}</p> : null}
                  </div>
                ))}
              </dl>
              <footer className="border-t border-line bg-surface-2/60 p-5">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Caveats</p>
                <ul className="mt-2 list-disc space-y-1.5 pl-4 text-sm leading-6 text-muted">
                  {block.caveats.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </footer>
            </article>
          ))}
        </div>
        {REPO_URL ? (
          <p className="mt-6">
            <a href={REPO_URL} target="_blank" rel="noreferrer noopener" className={buttonStyles.secondary}>
              Full results and source code
              <ExternalLink aria-hidden className="size-3.5" />
            </a>
          </p>
        ) : null}
      </section>
    </div>
  );
}
