"use client";

import { useLayoutEffect, useState, type RefObject } from "react";

export interface Size {
  w: number;
  h: number;
}

/** The size of an element, kept up to date. An element that is not laid out keeps its last size. */
export function useElementSize(ref: RefObject<HTMLElement | null>): Size {
  const [size, setSize] = useState<Size>({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = () => {
      const r = el.getBoundingClientRect();
      const w = Math.round(r.width);
      const h = Math.round(r.height);
      if (w < 1 || h < 1) return;
      setSize((s) => (s.w === w && s.h === h ? s : { w, h }));
    };
    read();
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}
