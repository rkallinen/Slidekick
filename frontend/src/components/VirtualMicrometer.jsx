/**
 * VirtualMicrometer — Scale bar overlay for physical distance reference.
 *
 * Converts pixel distance to μm using WSI metadata (MPP).
 * Automatically selects an appropriate scale (50μm, 100μm, 200μm, 500μm, 1mm)
 * based on the current zoom level so the bar is always legible.
 *
 * Mathematical relationship:
 *   bar_css_px = (target_μm / MPP) × (containerWidth × zoom / slideWidth)
 */

import { useState, useEffect, useRef } from "react";
import { scaleBarPixels } from "../utils/coordinates.js";

// Candidate scale bar lengths in μm
const SCALE_TARGETS = [10, 25, 50, 100, 200, 500, 1000, 2000, 5000];

// Preferred on-screen width range (CSS pixels)
const MIN_BAR_PX = 60;
const MAX_BAR_PX = 200;

function formatLength(um) {
  if (um >= 1000) return `${(um / 1000).toFixed(um % 1000 === 0 ? 0 : 1)} mm`;
  return `${um} μm`;
}

/**
 * @param {{ viewer: OpenSeadragon.Viewer, slideInfo: { width_px, height_px, mpp } }}
 */
export default function VirtualMicrometer({ viewer, slideInfo }) {
  const [barWidth, setBarWidth] = useState(100);
  const [barLabel, setBarLabel] = useState("100 μm");
  const rafRef = useRef(null);

  useEffect(() => {
    if (!viewer || !slideInfo) return;

    const update = () => {
      if (!viewer.viewport) return;

      const zoom = viewer.viewport.getZoom(true);
      const containerWidth = viewer.viewport.getContainerSize().x;
      const { width_px, mpp } = slideInfo;

      // Find the best target length that fits our preferred pixel range
      let bestTarget = SCALE_TARGETS[0];
      let bestWidth = 0;

      for (const target of SCALE_TARGETS) {
        const px = scaleBarPixels(target, mpp, zoom, width_px, containerWidth);
        if (px >= MIN_BAR_PX && px <= MAX_BAR_PX) {
          bestTarget = target;
          bestWidth = px;
          break;
        }
        if (px < MIN_BAR_PX) {
          bestTarget = target;
          bestWidth = px;
        }
      }

      // If nothing fit, use the last candidate that was too small
      if (bestWidth < MIN_BAR_PX) {
        bestWidth = scaleBarPixels(
          bestTarget,
          mpp,
          zoom,
          width_px,
          containerWidth,
        );
      }

      setBarWidth(Math.max(20, Math.round(bestWidth)));
      setBarLabel(formatLength(bestTarget));
    };

    // Update on every viewport change
    const handler = () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(update);
    };

    viewer.addHandler("zoom", handler);
    viewer.addHandler("animation-finish", handler);
    viewer.addHandler("open", handler);

    // Initial computation
    handler();

    return () => {
      viewer.removeHandler("zoom", handler);
      viewer.removeHandler("animation-finish", handler);
      viewer.removeHandler("open", handler);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [viewer, slideInfo]);

  return (
    <div className="absolute bottom-10 left-4 z-20 flex flex-col items-start bg-white/70 rounded-md px-2 py-1 backdrop-blur-sm">
      {/* Scale bar */}
      <div
        className="h-1 bg-black shadow-md"
        style={{ width: `${barWidth}px` }}
      />
      {/* Ticks at endpoints */}
      <div className="flex justify-between" style={{ width: `${barWidth}px` }}>
        <div className="h-2 w-px bg-black" />
        <div className="h-2 w-px bg-black" />
      </div>
      {/* Label */}
      <span className="mt-0.5 text-[20px] font-mono text-black">
        {barLabel}
      </span>
    </div>
  );
}
