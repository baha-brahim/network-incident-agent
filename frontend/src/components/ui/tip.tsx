"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import { useRef, useState, type ReactNode } from "react";

export function TipProvider({ children }: { children: ReactNode }) {
  return (
    <Tooltip.Provider delayDuration={300} skipDelayDuration={500}>
      {children}
    </Tooltip.Provider>
  );
}

/**
 * A tooltip that opens on hover and on focus, and on tap for touch screens (where hover does not exist).
 * `children` must be a single focusable element.
 */
export function Tip({
  content,
  children,
  side = "top",
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const touch = useRef(false);
  return (
    <Tooltip.Root open={open} onOpenChange={setOpen}>
      <Tooltip.Trigger
        asChild
        onPointerDown={(e) => {
          touch.current = e.pointerType === "touch";
        }}
        onClick={(e) => {
          if (touch.current) {
            e.preventDefault();
            setOpen((o) => !o);
          }
        }}
      >
        {children}
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side={side}
          sideOffset={6}
          collisionPadding={12}
          className="tip z-50 max-w-[min(22rem,calc(100vw-1.5rem))] rounded-lg border border-line bg-surface px-3 py-2 text-xs leading-relaxed text-fg shadow-pop"
        >
          {content}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
