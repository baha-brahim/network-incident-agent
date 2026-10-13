"use client";

import { Define } from "@/components/ui/term";
import { nodeKind } from "@/lib/labels";
import { useRunCtx } from "./citations";

/** A node ID in running text, with its kind on hover. It points at the node on the network diagram. */
export function NodeChip({ id }: { id: string }) {
  const ctx = useRunCtx();
  const kind = nodeKind(id);
  const chip = <code className="id">{id}</code>;
  const inner = kind ? <Define term={{ label: id, definition: kind }}>{chip}</Define> : chip;
  const point = ctx?.pointAtNodes;
  if (!point) return inner;
  return (
    <span onMouseEnter={() => point([id])} onMouseLeave={() => point([])} onFocus={() => point([id])} onBlur={() => point([])}>
      {inner}
    </span>
  );
}
