"use client";

import { useEffect, useRef, useState } from "react";

export interface Point {
  x: number;
  y: number;
}

const easeOut = (t: number) => 1 - Math.pow(1 - t, 5);

function calm(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Eases node positions toward their targets so a growing diagram moves instead of jumping. Lines
 * and nodes read the same positions, so they stay attached while they move.
 */
export function useTweenedPositions(target: Map<string, Point>, enabled: boolean, duration = 400): Map<string, Point> {
  const [shown, setShown] = useState<Map<string, Point> | null>(null);
  const shownRef = useRef<Map<string, Point> | null>(null);

  useEffect(() => {
    shownRef.current = shown;
  });

  useEffect(() => {
    if (!enabled || calm()) return;
    const from = shownRef.current ?? target;
    let moving = false;
    for (const [id, p] of target) {
      const f = from.get(id);
      if (f && (Math.abs(f.x - p.x) > 0.5 || Math.abs(f.y - p.y) > 0.5)) moving = true;
    }
    let raf = 0;
    if (!moving) {
      raf = requestAnimationFrame(() => setShown(target));
      return () => cancelAnimationFrame(raf);
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const k = easeOut(t);
      const next = new Map<string, Point>();
      for (const [id, p] of target) {
        const f = from.get(id) ?? p;
        next.set(id, { x: f.x + (p.x - f.x) * k, y: f.y + (p.y - f.y) * k });
      }
      setShown(t >= 1 ? target : next);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, enabled, duration]);

  if (!enabled || !shown) return target;
  return shown;
}
