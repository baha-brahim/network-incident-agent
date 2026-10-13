import type { Layer } from "@/lib/network";

/** Glyph geometry is drawn in a 56 unit box centred on the node. */
export const BOX = 56;

/** Core: a double circle. Router: a square. Link: a lozenge on the line. Site: a circle with a mast. */
export function GlyphShape({ layer }: { layer: Layer }) {
  switch (layer) {
    case 0:
      return (
        <g>
          <circle className="nws-shape" r="15" />
          <circle className="nws-inner" r="9" />
        </g>
      );
    case 1:
      return <rect className="nws-shape" x="-13" y="-13" width="26" height="26" />;
    case 2:
      return <path className="nws-shape" d="M-17 0 L0 -8 L17 0 L0 8 Z" />;
    default:
      return (
        <g>
          <path className="nws-mast" d="M0 -10 V-17 M-4 -17 H4" />
          <circle className="nws-shape" r="10" />
        </g>
      );
  }
}

export function LegendGlyph({ layer }: { layer: Layer }) {
  return (
    <svg className="nws-legend-glyph" width="22" height="22" viewBox="-20 -20 40 40" aria-hidden="true">
      <GlyphShape layer={layer} />
    </svg>
  );
}
