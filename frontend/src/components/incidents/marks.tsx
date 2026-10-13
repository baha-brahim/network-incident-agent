import { humanize, sentenceCase } from "./text";

const LEVELS: Record<string, number> = { low: 1, medium: 2, high: 3 };

/** Three rising bars; how many are filled is the severity, so it reads without colour. A severity the page does not know shows no bar filled. */
export function SeverityMark({ severity }: { severity: string }) {
  const known = Object.hasOwn(LEVELS, severity);
  const level = known ? LEVELS[severity] : 0;
  const label = known ? sentenceCase(severity) : humanize(severity) ? sentenceCase(humanize(severity)) : "Severity unknown";
  return (
    <span className={`sev is-${known ? severity : "unknown"}`}>
      <svg aria-hidden width="14" height="12" viewBox="0 0 14 12">
        {[0, 1, 2].map((i) => (
          <rect key={i} x={i * 5} y={12 - (i + 1) * 4} width="4" height={(i + 1) * 4} className={i < level ? "sev-on" : "sev-off"} />
        ))}
      </svg>
      {label}
    </span>
  );
}

const KNOWN_VERDICTS = new Set(["incident", "planned_maintenance", "expected_event", "no_impact", "inconclusive"]);

/** A small mark whose outline differs per verdict, next to the verdict's name. */
export function VerdictMark({ verdict }: { verdict: string }) {
  return (
    <svg aria-hidden className={`vmark is-${KNOWN_VERDICTS.has(verdict) ? verdict : "inconclusive"}`} width="12" height="12" viewBox="0 0 12 12">
      {verdict === "expected_event" ? (
        <path d="M6 0.8 11.2 6 6 11.2 0.8 6Z" />
      ) : verdict === "no_impact" ? (
        <circle cx="6" cy="6" r="4.6" />
      ) : (
        <rect x="1" y="1" width="10" height="10" />
      )}
    </svg>
  );
}
