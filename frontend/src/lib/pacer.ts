import type { RunEvent } from "./types";

export interface Clock {
  set(fn: () => void, ms: number): unknown;
  clear(handle: unknown): void;
}

const realClock: Clock = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** The longest pause between two released events when a backlog is being played out. */
export const MAX_GAP_MS = 1500;

/**
 * Releases events to the view. While running, an event is released the moment it arrives, so the
 * stream's own timing is what the viewer sees. After a pause, the queued events are released with
 * the gaps they were recorded with (divided by the speed), not all at once.
 */
export class Pacer {
  private queue: RunEvent[] = [];
  private timer: unknown = null;
  private held = false;
  private lastT = 0;
  private maxSeq = -1;

  constructor(
    private readonly emit: (event: RunEvent) => void,
    private readonly speed: () => number = () => 1,
    private readonly onIdle: () => void = () => {},
    private readonly clock: Clock = realClock,
  ) {}

  get paused(): boolean {
    return this.held;
  }

  get size(): number {
    return this.queue.length;
  }

  /** The highest sequence number received so far (released or queued). */
  get lastSeq(): number {
    return this.maxSeq;
  }

  /** Queues an event. One already received (for example after reconnecting at another speed) is dropped. */
  push(event: RunEvent): void {
    if (event.seq <= this.maxSeq) return;
    this.maxSeq = event.seq;
    this.queue.push(event);
    this.pump();
  }

  pause(): void {
    this.held = true;
    this.stopTimer();
  }

  resume(): void {
    if (!this.held) return;
    this.held = false;
    this.pump();
  }

  /** Releases everything queued at once and returns how many events that was. */
  flush(): number {
    this.stopTimer();
    const events = this.queue.splice(0);
    for (const event of events) this.release(event);
    this.onIdle();
    return events.length;
  }

  /** Forgets the queue and the sequence history. */
  reset(): void {
    this.stopTimer();
    this.queue = [];
    this.held = false;
    this.lastT = 0;
    this.maxSeq = -1;
  }

  private release(event: RunEvent): void {
    this.lastT = event.t_ms;
    this.emit(event);
  }

  private pump(): void {
    if (this.held || this.timer !== null) return;
    const event = this.queue.shift();
    if (!event) return;
    this.release(event);
    const next = this.queue[0];
    if (next) {
      const gap = Math.min(MAX_GAP_MS, Math.max(0, next.t_ms - this.lastT) / Math.max(1, this.speed()));
      this.timer = this.clock.set(() => {
        this.timer = null;
        this.pump();
      }, gap);
    } else {
      this.onIdle();
    }
  }

  private stopTimer(): void {
    if (this.timer !== null) this.clock.clear(this.timer);
    this.timer = null;
  }
}
