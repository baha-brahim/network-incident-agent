import type { Network } from "@/lib/network";
import type { Layout } from "@/lib/network-layout";
import { LegendGlyph } from "./glyphs";
import type { Probe } from "./use-probe";

/** One line on what the agent is doing, and the key to the glyphs. */
export function StageFoot({ net, layout, probe }: { net: Network; layout: Layout | null; probe: Probe }) {
  const hasStubs = !!layout && layout.stubs.length > 0;
  const showConclusion = net.concluded && net.rootId !== null && net.verdict !== "inconclusive";
  const anyAffected = net.nodes.some((n) => n.flags.affected);
  return (
    <footer className="nws-foot">
      <p className="nws-readout">
        <span className={probe.busy ? "here" : undefined}>{probe.text}</span>
      </p>
      <ul className="nws-legend" aria-label="Key">
        <li>
          <LegendGlyph layer={0} />
          Core
        </li>
        <li>
          <LegendGlyph layer={1} />
          Router
        </li>
        <li>
          <LegendGlyph layer={2} />
          Link
        </li>
        <li>
          <LegendGlyph layer={3} />
          Site
        </li>
        {hasStubs ? (
          <li>
            <svg className="nws-legend-glyph" width="22" height="22" viewBox="-11 -11 22 22" aria-hidden="true">
              <path className="nws-stub" d="M0 8V-8" />
            </svg>
            Upstream unknown
          </li>
        ) : null}
        {showConclusion ? (
          <li>
            <svg className="nws-legend-glyph" width="22" height="22" viewBox="-11 -11 22 22" aria-hidden="true">
              <circle className="nws-key-ring" r="8" />
            </svg>
            {net.rootLabel}
          </li>
        ) : null}
        {net.concluded && anyAffected ? (
          <li>
            <svg className="nws-legend-glyph" width="22" height="22" viewBox="-11 -11 22 22" aria-hidden="true">
              <circle className="nws-key-tint" r="6" />
            </svg>
            Affected
          </li>
        ) : null}
      </ul>
    </footer>
  );
}
