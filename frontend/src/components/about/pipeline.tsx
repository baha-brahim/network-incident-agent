type Actor = "model" | "code" | "both";

interface Stage {
  name: string;
  actor: Actor;
  text: string;
  repeats?: boolean;
}

const ACTOR_LABEL: Record<Actor, string> = { model: "Model", code: "Code", both: "Model and code" };

const STAGES: Stage[] = [
  { name: "intake", actor: "model", text: "Reads the question and turns it into a scope: the symptom, a time window, a region or nodes." },
  { name: "orient", actor: "code", text: "Runs the first lookups itself, such as the detector's alerts for that scope, so the model starts with facts." },
  {
    name: "investigate",
    actor: "both",
    repeats: true,
    text: "The model picks a tool, reads the result and writes a note. Code runs the tools and checks nothing was skipped.",
  },
  { name: "conclude", actor: "model", text: "Writes the report as a structured document: cause, confidence, timeline, findings, and what was ruled out." },
  { name: "verify", actor: "code", text: "Checks every cited reference, time and node ID against the evidence, and asks for a repair if something is off." },
];

/** Model is an open circle, code a solid square, both a solid square inside a circle. */
export function ActorMark({ actor, className }: { actor: Actor; className?: string }) {
  return (
    <svg className={className} width="22" height="22" viewBox="0 0 22 22" aria-hidden focusable="false">
      {actor === "code" ? (
        <rect x="4" y="4" width="14" height="14" fill="currentColor" />
      ) : (
        <>
          <circle cx="11" cy="11" r="9" fill="var(--paper)" stroke="currentColor" strokeWidth="2" />
          {actor === "both" ? <rect x="6.5" y="6.5" width="9" height="9" fill="currentColor" /> : null}
        </>
      )}
    </svg>
  );
}

export function Pipeline() {
  return (
    <figure className="hw-pipeline">
      <ol className="hw-stages" aria-label="The five stages of one investigation, in order">
        {STAGES.map((stage) => (
          <li key={stage.name} className="hw-stage">
            <span className="hw-line" aria-hidden />
            {stage.repeats ? (
              <>
                <svg className="hw-loop hw-loop-wide" aria-hidden focusable="false" width="100%" height="60">
                  <rect x="11" y="1" height="120" rx="22" style={{ width: "calc(100% - 34px)" }} fill="none" stroke="currentColor" strokeWidth="2" />
                  <polygon points="11,50 6,40 16,40" fill="currentColor" />
                </svg>
                <svg className="hw-loop hw-loop-tall" aria-hidden focusable="false" width="40" height="100%">
                  <rect x="-60" y="11" width="92" rx="18" style={{ height: "calc(100% - 52px)" }} fill="none" stroke="currentColor" strokeWidth="2" />
                  <polygon points="11,11 21,6 21,16" fill="currentColor" />
                </svg>
              </>
            ) : null}
            <ActorMark actor={stage.actor} className="hw-mark" />
            <h3 className="hw-name">{stage.name}</h3>
            <p className="hw-who">
              {ACTOR_LABEL[stage.actor]}
              {stage.repeats ? <span className="hw-repeats">Repeats</span> : null}
            </p>
            <p className="hw-text">{stage.text}</p>
          </li>
        ))}
      </ol>

      <figcaption className="hw-pipeline-caption">
        <ul className="hw-legend" aria-label="What the marks on the line mean">
          {(Object.keys(ACTOR_LABEL) as Actor[]).map((actor) => (
            <li key={actor}>
              <ActorMark actor={actor} />
              {ACTOR_LABEL[actor]}
            </li>
          ))}
        </ul>
        <p>Stage three repeats: ask for a tool, read the result, write a note.</p>
      </figcaption>
    </figure>
  );
}
