import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fiberCut from "./__fixtures__/fiber-cut.json";
import { ApiError } from "./api";
import { PlayerEngine, type Transport } from "./player";
import type { Recording, RunEvent } from "./types";

const events = (fiberCut as unknown as Recording).events;
const demo = { id: "fiber-cut", title: "Three sites go dark", question: events[0].type === "run_started" ? events[0].data.question : "" };

/** A stream the test feeds by hand. */
function channel() {
  const queue: RunEvent[] = [];
  let wake: (() => void) | null = null;
  let closed = false;
  let failure: unknown = null;
  const iterable: AsyncIterable<RunEvent> = {
    async *[Symbol.asyncIterator]() {
      for (;;) {
        if (queue.length) yield queue.shift()!;
        else if (failure) throw failure;
        else if (closed) return;
        else await new Promise<void>((r) => (wake = r));
      }
    },
  };
  const poke = () => wake?.();
  return {
    iterable,
    send(...e: RunEvent[]) {
      queue.push(...e);
      poke();
    },
    close() {
      closed = true;
      poke();
    },
    fail(error: unknown) {
      failure = error;
      poke();
    },
  };
}

function setup() {
  const streams: Array<{ speed: number; ch: ReturnType<typeof channel> }> = [];
  const transport: Transport = {
    replay: vi.fn(async (_id, speed) => {
      const ch = channel();
      streams.push({ speed, ch });
      return ch.iterable;
    }),
    live: vi.fn(async () => {
      const ch = channel();
      streams.push({ speed: 1, ch });
      return ch.iterable;
    }),
    recording: vi.fn(async () => ({ events })),
  };
  return { engine: new PlayerEngine(transport), streams, transport };
}

const tick = () => vi.advanceTimersByTimeAsync(0);

describe("PlayerEngine", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("plays a stream through to the report", async () => {
    const { engine, streams } = setup();
    engine.startDemo(demo);
    expect(engine.getSnapshot().status).toBe("connecting");
    expect(engine.getSnapshot().view.question).toBe(demo.question);
    await tick();
    streams[0].ch.send(...events);
    streams[0].ch.close();
    await tick();
    const s = engine.getSnapshot();
    expect(s.status).toBe("done");
    expect(s.view.phase).toBe("finished");
    expect(s.view.report?.classification).toBe("incident");
  });

  it("holds events while paused and releases them on resume", async () => {
    const { engine, streams } = setup();
    engine.startDemo(demo);
    await tick();
    streams[0].ch.send(...events.slice(0, 4));
    await tick();
    const before = engine.getSnapshot().view.steps.length;
    expect(before).toBeGreaterThan(0);

    engine.pause();
    expect(engine.getSnapshot().status).toBe("paused");
    streams[0].ch.send(...events.slice(4, 12));
    await tick();
    expect(engine.getSnapshot().view.steps.length).toBe(before);

    engine.resume();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(engine.getSnapshot().view.steps.length).toBeGreaterThan(before);
    expect(engine.getSnapshot().status).toBe("playing");
  });

  it("reconnects at the new speed and ignores events it already has", async () => {
    const { engine, streams, transport } = setup();
    engine.startDemo(demo);
    await tick();
    streams[0].ch.send(...events.slice(0, 6));
    await tick();
    const seen = engine.getSnapshot().view.lastSeq;

    engine.setSpeed(4);
    await tick();
    expect(transport.replay).toHaveBeenLastCalledWith("fiber-cut", 4, expect.any(AbortSignal));
    streams[1].ch.send(...events);
    streams[1].ch.close();
    await vi.advanceTimersByTimeAsync(10_000);
    const s = engine.getSnapshot();
    expect(seen).toBeGreaterThan(0);
    expect(s.status).toBe("done");
    expect(s.speed).toBe(4);
    const ids = s.view.steps.map((x) => x.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("jumps to the report with the whole recording", async () => {
    const { engine, streams, transport } = setup();
    engine.startDemo(demo);
    await tick();
    streams[0].ch.send(...events.slice(0, 3));
    await tick();
    engine.skip();
    await tick();
    const s = engine.getSnapshot();
    expect(transport.recording).toHaveBeenCalledWith("fiber-cut", expect.any(AbortSignal));
    expect(s.status).toBe("done");
    expect(s.animate).toBe(false);
    expect(s.view.report).not.toBeNull();
  });

  it("reports a stream that ends early as a lost connection", async () => {
    const { engine, streams } = setup();
    engine.startDemo(demo);
    await tick();
    streams[0].ch.send(...events.slice(0, 5));
    streams[0].ch.close();
    await tick();
    expect(engine.getSnapshot().status).toBe("failed");
    expect(engine.getSnapshot().failure?.kind).toBe("dropped");
  });

  it("reports a daily limit with nothing received", async () => {
    const { engine, transport } = setup();
    (transport.live as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new ApiError(429, "daily_limit", "limit reached", { retryAfter: 3600, limit: 20, remaining: 0 }),
    );
    engine.startLive("Why did traffic drop in Sfax?");
    await tick();
    const s = engine.getSnapshot();
    expect(s.status).toBe("failed");
    expect(s.failure).toMatchObject({ kind: "limit", retryAfter: 3600, limit: 20 });
    expect(s.view.steps).toHaveLength(0);
  });

  it("reports an unreachable server", async () => {
    const { engine, transport } = setup();
    (transport.replay as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new ApiError(0, "unreachable", "down"));
    engine.startDemo(demo);
    await tick();
    expect(engine.getSnapshot().failure?.kind).toBe("unreachable");
  });

  it("goes back to idle on reset, and stops listening to the old stream", async () => {
    const { engine, streams } = setup();
    engine.startDemo(demo);
    await tick();
    engine.reset();
    streams[0].ch.send(...events);
    await tick();
    expect(engine.getSnapshot().status).toBe("idle");
    expect(engine.getSnapshot().view.steps).toHaveLength(0);
  });
});
