/** True when the reader asked for less motion; scrolling then jumps instead of gliding. */
export function calmMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function scrollBehavior(): ScrollBehavior {
  return calmMotion() ? "auto" : "smooth";
}
