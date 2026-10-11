import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MAX_GAP_MS, Pacer } from "./pacer";
import type { RunEvent } from "./types";

const ev = (seq: number, t_ms: number) => ({ seq, t_ms, type: "note", run_id: "R", data: {} }) as unknown as RunEvent;

describe("Pacer", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("releases events as they arrive while running", () => {
    const seen: number[] = [];
    const p = new Pacer((e) => seen.push(e.seq));
    p.push(ev(0, 0));
    p.push(ev(1, 5000));
    expect(seen).toEqual([0, 1]);
  });

  it("holds events while paused and plays them out with their recorded gaps on resume", () => {
    const seen: number[] = [];
    const p = new Pacer((e) => seen.push(e.seq), () => 2);
    p.push(ev(0, 0));
    p.pause();
    p.push(ev(1, 1000));
    p.push(ev(2, 2000));
    p.push(ev(3, 2400));
    expect(seen).toEqual([0]);
    expect(p.size).toBe(3);

    p.resume();
    expect(seen).toEqual([0, 1]);
    vi.advanceTimersByTime(499);
    expect(seen).toEqual([0, 1]);
    vi.advanceTimersByTime(1);
    expect(seen).toEqual([0, 1, 2]);
    vi.advanceTimersByTime(200);
    expect(seen).toEqual([0, 1, 2, 3]);
  });

  it("caps long gaps", () => {
    const seen: number[] = [];
    const p = new Pacer((e) => seen.push(e.seq));
    p.pause();
    p.push(ev(0, 0));
    p.push(ev(1, 60_000));
    p.resume();
    expect(seen).toEqual([0]);
    vi.advanceTimersByTime(MAX_GAP_MS);
    expect(seen).toEqual([0, 1]);
  });

  it("drops events it has already received", () => {
    const seen: number[] = [];
    const p = new Pacer((e) => seen.push(e.seq));
    p.push(ev(0, 0));
    p.push(ev(1, 10));
    p.push(ev(0, 0));
    p.push(ev(1, 10));
    p.push(ev(2, 20));
    expect(seen).toEqual([0, 1, 2]);
    expect(p.lastSeq).toBe(2);
  });

  it("flushes the backlog at once and reports idle", () => {
    const seen: number[] = [];
    const idle = vi.fn();
    const p = new Pacer((e) => seen.push(e.seq), () => 1, idle);
    p.pause();
    p.push(ev(0, 0));
    p.push(ev(1, 500));
    expect(p.flush()).toBe(2);
    expect(seen).toEqual([0, 1]);
    expect(idle).toHaveBeenCalled();
  });

  it("stops releasing when paused in the middle of a backlog", () => {
    const seen: number[] = [];
    const p = new Pacer((e) => seen.push(e.seq));
    p.pause();
    for (let i = 0; i < 4; i++) p.push(ev(i, i * 400));
    p.resume();
    expect(seen).toEqual([0]);
    p.pause();
    vi.advanceTimersByTime(5000);
    expect(seen).toEqual([0]);
    p.resume();
    expect(seen).toEqual([0, 1]);
  });
});
