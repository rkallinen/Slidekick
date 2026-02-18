/**
 * NucleusOverlay — Canvas2D layer for rendering nuclei on top of OpenSeadragon.
 *
 * Uses an HTML5 Canvas overlay aligned to the OSD viewport.
 * Nuclei are drawn as coloured circles at their Level-0 centroid
 * positions, transformed to viewport coordinates in real-time.
 *
 * Performance:  O(n) draw calls per frame. Canvas2D handles ~50k
 * circles at 60fps on modern hardware.
 */

import { useEffect, useRef } from "react";
import { CELL_TYPE_COLORS } from "../utils/coordinates.js";

const NUCLEUS_RADIUS_VP = 3; // Base radius in CSS pixels

/**
 * @param {{ viewer: OpenSeadragon.Viewer, nuclei: Array, visible: boolean }}
 */
export default function NucleusOverlay({ viewer, nuclei, visible = true }) {
  const canvasRef = useRef(null);
  const animFrameRef = useRef(null);

  useEffect(() => {
    if (!viewer || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");

    const draw = () => {
      if (!viewer.viewport || !visible) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        return;
      }

      // Match canvas size to the viewer container
      const container = viewer.container;
      const dpr = window.devicePixelRatio || 1;
      const w = container.clientWidth;
      const h = container.clientHeight;

      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;
        ctx.scale(dpr, dpr);
      }

      ctx.clearRect(0, 0, w, h);

      if (!nuclei || nuclei.length === 0) return;

      // Get current viewport transform
      const viewportBounds = viewer.viewport.getBounds(true);
      const containerSize = viewer.viewport.getContainerSize();

      // Batch draw by cell type for fewer state changes
      const grouped = {};
      for (const nuc of nuclei) {
        const key = nuc.cell_type;
        if (!grouped[key]) grouped[key] = [];
        grouped[key].push(nuc);
      }

      for (const [cellType, nucs] of Object.entries(grouped)) {
        const color = CELL_TYPE_COLORS[cellType] || "#ffffff";
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.7;
        ctx.beginPath();

        for (const nuc of nucs) {
          // Convert L0 pixel coords → OSD viewport → canvas pixels
          const vpPoint = viewer.viewport.imageToViewportCoordinates(
            nuc.x,
            nuc.y,
          );
          const screenPoint =
            viewer.viewport.viewportToViewerElementCoordinates(vpPoint);

          const sx = screenPoint.x;
          const sy = screenPoint.y;

          // Frustum cull
          if (sx < -10 || sx > w + 10 || sy < -10 || sy > h + 10) continue;

          ctx.moveTo(sx + NUCLEUS_RADIUS_VP, sy);
          ctx.arc(sx, sy, NUCLEUS_RADIUS_VP, 0, Math.PI * 2);
        }

        ctx.fill();
      }

      ctx.globalAlpha = 1.0;
    };

    // Redraw on every OSD animation frame
    const onAnimationFrame = () => {
      draw();
      animFrameRef.current = requestAnimationFrame(onAnimationFrame);
    };

    animFrameRef.current = requestAnimationFrame(onAnimationFrame);

    return () => {
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, [viewer, nuclei, visible]);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none z-10"
      aria-hidden="true"
      style={{ pointerEvents: 'none' }} // Redundant but explicit defense
    />
  );
}
