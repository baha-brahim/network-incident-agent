"use client";

import { useId, useState } from "react";
import { Notice, buttonStyles } from "@/components/ui/notice";
import { cx } from "@/lib/cx";
import { fmtIso, fmtNumber } from "@/lib/format";
import { liveQuota } from "@/lib/quota";
import type { DemoSummary, Meta } from "@/lib/types";

const MIN = 8;
const MAX = 300;

interface Props {
  meta: Meta | null;
  metaError: boolean;
  examples: readonly DemoSummary[];
  onSubmit(question: string): void;
  onWatchRecorded(): void;
}

export function AskLive({ meta, metaError, examples, onSubmit, onWatchRecorded }: Props) {
  const id = useId();
  const [text, setText] = useState("");
  const question = text.replace(/\s+/g, " ").trim();
  const long = question.length > MAX;
  const valid = question.length >= MIN && !long;
  const switchedOff = meta ? !meta.live_enabled : false;
  const quota = meta ? liveQuota(meta) : null;
  const usedUp = quota ? quota.left <= 0 : false;
  const blocked = metaError || switchedOff || usedUp;
  const hint =
    question.length === 0
      ? `Between ${MIN} and ${MAX} characters.`
      : question.length < MIN
        ? `A little more detail, please: at least ${MIN} characters.`
        : long
          ? `${question.length - MAX} characters too many.`
          : `${question.length} of ${MAX} characters`;

  const toRecorded = (
    <button type="button" className={buttonStyles.secondary} onClick={onWatchRecorded}>
      Watch a recorded case
    </button>
  );

  function submit() {
    if (valid && !blocked) onSubmit(question);
  }

  return (
    <div className="live">
      {metaError ? (
        <Notice tone="warn" title="Live mode is not available right now" action={toRecorded}>
          The server did not answer, so the number of runs left is unknown. Recorded cases may work again once the server is back.
        </Notice>
      ) : switchedOff ? (
        <Notice title="Live mode is switched off" action={toRecorded}>
          Live investigations are disabled on this server. Recorded cases show the same thing and use no model.
        </Notice>
      ) : usedUp ? (
        <Notice tone="warn" title="Today's live runs are used up" action={toRecorded}>
          Live runs use a free model tier, so only {quota ? fmtNumber(quota.limit) : "a few"} are allowed per day. The count resets at midnight UTC.
          Recorded cases do not count against it.
        </Notice>
      ) : null}

      <div className="live-main">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <label htmlFor={`${id}-q`} className="live-label">
            Ask about the network
          </label>
          <textarea
            id={`${id}-q`}
            name="question"
            rows={2}
            value={text}
            disabled={blocked}
            placeholder="Why did traffic drop in Sfax yesterday evening?"
            aria-describedby={`${id}-hint`}
            aria-invalid={long || undefined}
            enterKeyHint="send"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className="live-foot">
            <p id={`${id}-hint`} className={cx("live-hint", long && "is-over")}>
              {hint}
            </p>
            <button type="submit" className={buttonStyles.primary} disabled={!valid || blocked}>
              Investigate
            </button>
          </div>
        </form>

        {examples.length > 0 ? (
          <div className="live-examples">
            <p>Or start from one of these questions:</p>
            <ul>
              {examples.slice(0, 4).map((demo) => (
                <li key={demo.id}>
                  <button type="button" disabled={blocked} onClick={() => setText(demo.question)}>
                    {demo.question}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      <div className="live-aside">
        {quota ? (
          <p className="live-left">
            <span className="mono">{fmtNumber(quota.left)}</span> of {fmtNumber(quota.limit)} live runs left today
          </p>
        ) : null}
        <p className="live-note">
          A live run calls a model for each step, so it takes 10 to 30 seconds. The data is a synthetic network
          {meta ? <> that ends on {fmtIso(meta.dataset_now)} (Tunis time)</> : null}.
          {meta ? (
            <>
              {" "}
              Model: <span className="mono">{meta.model.split(":").slice(1).join(":") || meta.model}</span>.
            </>
          ) : null}
        </p>
      </div>
    </div>
  );
}
