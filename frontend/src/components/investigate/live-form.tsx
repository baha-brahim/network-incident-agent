"use client";

import { Send } from "lucide-react";
import { useState } from "react";
import { Notice, buttonStyles } from "@/components/ui/notice";
import { cx } from "@/lib/cx";
import { fmtIso } from "@/lib/format";
import type { DemoSummary, Meta } from "@/lib/types";

const MIN = 8;
const MAX = 300;

export function LiveForm({
  meta,
  metaError,
  examples,
  onSubmit,
  onWatchReplay,
}: {
  meta: Meta | null;
  metaError: boolean;
  examples: DemoSummary[];
  onSubmit(question: string): void;
  onWatchReplay(): void;
}) {
  const [text, setText] = useState("");
  const question = text.replace(/\s+/g, " ").trim();
  const long = question.length > MAX;
  const valid = question.length >= MIN && !long;
  const out = meta ? !meta.live_enabled : false;
  const used = meta ? meta.live_remaining <= 0 : false;
  const blocked = metaError || out || used;
  const hint =
    question.length === 0
      ? `Between ${MIN} and ${MAX} characters.`
      : question.length < MIN
        ? `A little more detail, please (at least ${MIN} characters).`
        : long
          ? `${question.length - MAX} characters too many.`
          : `${question.length} of ${MAX}`;

  function submit() {
    if (valid && !blocked) onSubmit(question);
  }

  return (
    <div className="space-y-4">
      {metaError ? (
        <Notice tone="warn" title="Live mode is not available right now">
          The server did not answer, so the number of remaining runs is unknown. Recorded replays may still work once the server is back.
        </Notice>
      ) : out ? (
        <Notice
          tone="neutral"
          title="Live mode is switched off"
          action={
            <button type="button" className={buttonStyles.secondary} onClick={onWatchReplay}>
              Watch a recorded replay
            </button>
          }
        >
          Live investigations are disabled on this server. Recorded replays show the same thing and use no model.
        </Notice>
      ) : used ? (
        <Notice
          tone="warn"
          title="Today's live runs are used up"
          action={
            <button type="button" className={buttonStyles.secondary} onClick={onWatchReplay}>
              Watch a recorded replay
            </button>
          }
        >
          Live runs use a free model tier, so only {meta?.live_daily_limit} are allowed per day. The count resets at midnight UTC. Replays don&apos;t count against it.
        </Notice>
      ) : null}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="space-y-3"
      >
        <label htmlFor="question" className="block text-sm font-medium">
          Ask about the network
        </label>
        <textarea
          id="question"
          name="question"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              submit();
            }
          }}
          rows={3}
          disabled={blocked}
          placeholder="Why did traffic drop in Sfax yesterday evening?"
          aria-describedby="question-hint"
          aria-invalid={long || undefined}
          autoCapitalize="sentences"
          enterKeyHint="send"
          className={cx(
            "block w-full resize-y rounded-xl border bg-surface p-3 text-base leading-6 placeholder:text-muted/70 disabled:opacity-60",
            long ? "border-danger" : "border-line-strong",
          )}
        />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p id="question-hint" className={cx("text-xs", long ? "text-danger" : "text-muted")}>
            {hint}
          </p>
          <div className="flex items-center gap-3">
            {meta ? (
              <p className="text-xs text-muted">
                <span className="font-mono text-fg">{meta.live_remaining}</span> of {meta.live_daily_limit} live runs left today
              </p>
            ) : null}
            <button type="submit" disabled={!valid || blocked} className={buttonStyles.primary}>
              <Send aria-hidden className="size-4" />
              Investigate
            </button>
          </div>
        </div>
      </form>

      {examples.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">Questions to start from</p>
          <ul className="flex flex-wrap gap-2">
            {examples.slice(0, 4).map((d) => (
              <li key={d.id} className="min-w-0 max-w-full">
                <button
                  type="button"
                  disabled={blocked}
                  onClick={() => setText(d.question)}
                  className="press hover-surface max-w-full rounded-full border border-line px-3 py-1.5 text-left text-xs text-muted hover:text-fg disabled:opacity-50"
                >
                  <span className="line-clamp-2 break-anywhere">{d.question}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="text-xs text-muted">
        A live run calls a model for each step, so it takes 10 to 30 seconds. The data is a synthetic network{meta ? <> that ends on {fmtIso(meta.dataset_now)} (Tunis time)</> : null}.
        {meta ? <> Model: <span className="font-mono">{meta.model.split(":").slice(1).join(":") || meta.model}</span>.</> : null}
      </p>
    </div>
  );
}
