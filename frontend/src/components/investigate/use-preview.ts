"use client";

import { useEffect, useState, useSyncExternalStore, type RefObject } from "react";
import type { PreviewFrame } from "./preview-frames";

/** How long the last frame stays before the preview starts again from an empty board. */
export const HOLD_MS = 4000;

const REDUCED = "(prefers-reduced-motion: reduce)";

function subscribeReduced(onChange: () => void) {
  const query = window.matchMedia(REDUCED);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function subscribeVisibility(onChange: () => void) {
  document.addEventListener("visibilitychange", onChange);
  return () => document.removeEventListener("visibilitychange", onChange);
}

function useReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReduced,
    () => window.matchMedia(REDUCED).matches,
    () => false,
  );
}

/** True while the tab is showing and the element is on screen. */
function useWatched(target: RefObject<Element | null>): boolean {
  const tabShown = useSyncExternalStore(
    subscribeVisibility,
    () => !document.hidden,
    () => true,
  );
  const [onScreen, setOnScreen] = useState(true);
  useEffect(() => {
    const el = target.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) => setOnScreen(entry.isIntersecting), { threshold: 0.1 });
    observer.observe(el);
    return () => observer.disconnect();
  }, [target]);
  return tabShown && onScreen;
}

export interface PreviewState {
  /** The frame to show; -1 is the empty board. */
  index: number;
  reduced: boolean;
}

/**
 * Steps through the frames on the recorded gaps, holds the last one, then starts over. It waits while
 * the tab is hidden or the target is off screen. With reduced motion it shows the last frame and stays.
 */
export function usePreview(frames: readonly PreviewFrame[] | null, target: RefObject<Element | null>): PreviewState {
  const reduced = useReducedMotion();
  const watched = useWatched(target);
  const [index, setIndex] = useState(-1);
  const count = frames?.length ?? 0;

  useEffect(() => {
    if (!frames || count === 0 || reduced || !watched) return;
    const atEnd = index >= count - 1;
    const wait = atEnd ? HOLD_MS : frames[index + 1].delay;
    const timer = setTimeout(() => setIndex(atEnd ? -1 : index + 1), wait);
    return () => clearTimeout(timer);
  }, [frames, count, index, reduced, watched]);

  if (count === 0) return { index: -1, reduced };
  return { index: reduced ? count - 1 : Math.min(index, count - 1), reduced };
}
