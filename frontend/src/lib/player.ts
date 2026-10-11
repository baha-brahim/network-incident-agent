/**
 * The playback engine behind a replay or a live run: it reads the event stream, holds events back
 * while paused, and keeps the view state. It is a plain store (subscribe / snapshot) so React can
 * read it with `useSyncExternalStore`.
 */
import { api, ApiError, isAbort, replayDemo, runLive, type ApiErrorKind } from "./api";
import { emptyView, reduce, startingView, type RunView } from "./investigation";
import { Pacer, type Clock } from "./pacer";
import type { Recording, RunEvent } from "./types";

export type PlayerStatus = "idle" | "connecting" | "playing" | "paused" | "done" | "failed";
export const SPEEDS = [1, 2, 4] as const;
export type Speed = (typeof SPEEDS)[number];

export type RunSource =
  | { kind: "demo"; id: string; title: string; question: string }
  | { kind: "live"; question: string };

export interface Failure {
  kind: ApiErrorKind | "dropped";
  message: string;
  retryAfter?: number;
  remaining?: number;
  limit?: number;
}

export interface PlayerState {
  view: RunView;
  status: PlayerStatus;
  speed: Speed;
  source: RunSource | null;
  failure: Failure | null;
  /** False after "skip to report", so a whole run does not animate in at once. */
  animate: boolean;
}

export interface Transport {
  replay(id: string, speed: number, signal: AbortSignal): Promise<AsyncIterable<RunEvent>>;
  live(question: string, signal: AbortSignal): Promise<AsyncIterable<RunEvent>>;
  recording(id: string, signal: AbortSignal): Promise<Pick<Recording, "events">>;
}

const defaultTransport: Transport = {
  replay: replayDemo,
  live: runLive,
  recording: (id, signal) => api.demo(id, signal),
};

export const initialState: PlayerState = {
  view: emptyView,
  status: "idle",
  speed: 1,
  source: null,
  failure: null,
  animate: true,
};

export function describeFailure(error: unknown, gotEvents: boolean): Failure {
  if (error instanceof ApiError) {
    if (error.kind === "unreachable" && gotEvents) {
      return { kind: "dropped", message: "The connection was lost before the investigation finished." };
    }
    return {
      kind: error.kind,
      message: error.message,
      retryAfter: error.extra.retryAfter,
      remaining: error.extra.remaining,
      limit: error.extra.limit,
    };
  }
  return { kind: "server", message: "Something went wrong while reading the investigation." };
}

export class PlayerEngine {
  private state: PlayerState = initialState;
  private listeners = new Set<() => void>();
  private controller: AbortController | null = null;
  private token = 0;
  private streamEnded = false;
  private sawFinished = false;
  private gotEvents = false;
  private speed: Speed = 1;
  private readonly pacer: Pacer;

  constructor(
    private readonly transport: Transport = defaultTransport,
    clock?: Clock,
  ) {
    this.pacer = new Pacer(
      (event) => {
        if (event.type === "run_finished") this.sawFinished = true;
        this.update({ view: reduce(this.state.view, event) });
      },
      () => this.speed,
      () => this.finishIfDrained(),
      clock,
    );
  }

  // --- store ---------------------------------------------------------------------------------

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): PlayerState => this.state;

  private update(patch: Partial<PlayerState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }

  // --- commands ------------------------------------------------------------------------------

  startDemo(demo: { id: string; title: string; question: string }): void {
    this.begin({ kind: "demo", id: demo.id, title: demo.title, question: demo.question });
  }

  startLive(question: string): void {
    this.begin({ kind: "live", question });
  }

  pause(): void {
    this.pacer.pause();
    this.setStatus("paused");
  }

  resume(): void {
    this.setStatus(this.gotEvents ? "playing" : "connecting");
    this.pacer.resume();
  }

  setSpeed(speed: Speed): void {
    this.speed = speed;
    this.update({ speed });
    const { source, status } = this.state;
    const active = status === "playing" || status === "paused" || status === "connecting";
    // The stream is paced by the server, so a new speed needs a new stream. Events already
    // received are dropped by sequence number when it replays them.
    if (source?.kind === "demo" && !this.streamEnded && active) this.connect(source, speed);
  }

  skip(): void {
    const { source } = this.state;
    if (source?.kind === "live") {
      this.update({ animate: false });
      this.pacer.flush();
      return;
    }
    if (source?.kind !== "demo") return;
    this.controller?.abort();
    const mine = ++this.token;
    const controller = new AbortController();
    this.controller = controller;
    this.pacer.pause();
    this.transport
      .recording(source.id, controller.signal)
      .then((recording) => {
        if (mine !== this.token) return;
        this.pacer.reset();
        this.sawFinished = true;
        this.streamEnded = true;
        let view = this.state.view;
        for (const event of recording.events) view = reduce(view, event);
        this.update({ view, animate: false, status: "done" });
      })
      .catch((error: unknown) => {
        if (isAbort(error) || mine !== this.token) return;
        this.fail(describeFailure(error, false));
      });
  }

  restart(): void {
    const { source } = this.state;
    if (source?.kind === "demo") this.begin(source);
  }

  reset(): void {
    this.stop();
    this.update({ ...initialState, speed: this.speed });
  }

  /** Stops reading and drops anything queued. Safe to call more than once. */
  stop(): void {
    this.controller?.abort();
    this.token++;
    this.pacer.reset();
  }

  // --- internals -----------------------------------------------------------------------------

  private begin(source: RunSource): void {
    this.stop();
    this.sawFinished = false;
    this.gotEvents = false;
    this.streamEnded = false;
    const speed = source.kind === "demo" ? this.speed : 1;
    this.state = {
      view: startingView(source.question),
      status: "connecting",
      speed: this.speed,
      source,
      failure: null,
      animate: true,
    };
    this.update({});
    this.connect(source, speed);
  }

  private connect(source: RunSource, speed: number): void {
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;
    const mine = ++this.token;
    this.streamEnded = false;

    void (async () => {
      try {
        const stream =
          source.kind === "demo"
            ? await this.transport.replay(source.id, speed, controller.signal)
            : await this.transport.live(source.question, controller.signal);
        for await (const event of stream) {
          if (mine !== this.token) return;
          if (!this.gotEvents) {
            this.gotEvents = true;
            this.setStatus(this.pacer.paused ? "paused" : "playing");
          }
          this.pacer.push(event);
        }
        if (mine !== this.token) return;
        this.streamEnded = true;
        this.finishIfDrained();
      } catch (error) {
        if (isAbort(error) || mine !== this.token) return;
        this.fail(describeFailure(error, this.gotEvents));
      }
    })();
  }

  private finishIfDrained(): void {
    if (!this.streamEnded || this.pacer.size > 0) return;
    if (this.sawFinished) this.setStatus("done");
    else if (this.state.status !== "failed") this.fail(describeFailure(new ApiError(0, "unreachable", ""), true));
  }

  private setStatus(status: PlayerStatus): void {
    if (this.state.status === "failed" || this.state.status === status) return;
    this.update({ status });
  }

  private fail(failure: Failure): void {
    this.update({ status: "failed", failure });
  }
}
