/**
 * AnalysisBoxOverlay — Canvas2D layer for rendering analysis box outlines.
 *
 * Draws clickable rectangular outlines for each AnalysisBox.
 * The selected box is highlighted with a thicker, brighter border.
 * Clicking a box calls `onSelectBox(boxId)`.
 */

import { useEffect, useRef } from "react";
import { pxToUm, areaPxToMm2 } from "../utils/coordinates.js";


const BOX_STROKE_COLOR = "rgba(59, 130, 246, 0.95)";     
const BOX_STROKE_SELECTED = "rgba(250, 204, 21, 0.95)";  
const BOX_FILL = "rgba(59, 130, 246, 0.2)";           
const BOX_FILL_SELECTED = "rgba(3, 3, 2, 0.08)";
const BOX_LABEL_BG = "rgba(15, 23, 42, 0.85)";

/**
 * @param {{
 *   viewer: OpenSeadragon.Viewer,
 *   boxes: Array<{ id, x_min, y_min, x_max, y_max, total_nuclei, label }>,
 *   selectedBoxId: string | null,
 *   onSelectBox: (boxId: string) => void,
 *   visible: boolean,
 *   slideInfo: object,
 * }}
 */
export default function AnalysisBoxOverlay({
  viewer,
  boxes,
  selectedBoxId,
  onSelectBox,
  visible = true,
  slideInfo,
}) {
  const canvasRef = useRef(null);
  const animFrameRef = useRef(null);
  // Store box screen rects for hit testing
  const boxRectsRef = useRef([]);

  useEffect(() => {
    if (!viewer || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");

    const draw = () => {
      if (!viewer.viewport || !visible) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        boxRectsRef.current = [];
        return;
      }

      const container = viewer.container;
      const dpr = window.devicePixelRatio || 1;
      const w = container.clientWidth;
      const h = container.clientHeight;

      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;
      }

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      if (!boxes || boxes.length === 0) {
        boxRectsRef.current = [];
        return;
      }

      const rects = [];

      for (const box of boxes) {
        const isSelected = box.id === selectedBoxId;

        // Convert L0 pixel corners → screen coordinates
        const topLeftVP = viewer.viewport.imageToViewportCoordinates(box.x_min, box.y_min);
        const bottomRightVP = viewer.viewport.imageToViewportCoordinates(box.x_max, box.y_max);

        const topLeftScreen = viewer.viewport.viewportToViewerElementCoordinates(topLeftVP);
        const bottomRightScreen = viewer.viewport.viewportToViewerElementCoordinates(bottomRightVP);

        const sx = topLeftScreen.x;
        const sy = topLeftScreen.y;
        const sw = bottomRightScreen.x - topLeftScreen.x;
        const sh = bottomRightScreen.y - topLeftScreen.y;

        // Skip if completely offscreen
        if (sx + sw < -50 || sx > w + 50 || sy + sh < -50 || sy > h + 50) continue;

        // Store for hit testing
        rects.push({ id: box.id, x: sx, y: sy, w: sw, h: sh });

        // Fill
        ctx.fillStyle = isSelected ? BOX_FILL_SELECTED : BOX_FILL;
        ctx.fillRect(sx, sy, sw, sh);

        // Stroke
        ctx.strokeStyle = isSelected ? BOX_STROKE_SELECTED : BOX_STROKE_COLOR;
        ctx.lineWidth = isSelected ? 3 : 1.5;
        ctx.setLineDash(isSelected ? [] : [6, 4]);
        ctx.strokeRect(sx, sy, sw, sh);
        ctx.setLineDash([]);

        // Label badge (top-left corner)
        const labelText = `${box.total_nuclei} nuclei`;
        ctx.font = "bold 11px Inter, system-ui, sans-serif";
        const textWidth = ctx.measureText(labelText).width;
        const badgePadX = 6;
        const badgePadY = 3;
        const badgeH = 18;
        const badgeW = textWidth + badgePadX * 2;

        // Position badge at top-left of box
        const bx = sx;
        const by = sy - badgeH - 2;

        ctx.fillStyle = BOX_LABEL_BG;
        ctx.beginPath();
        ctx.roundRect(bx, by, badgeW, badgeH, 3);
        ctx.fill();

        ctx.fillStyle = isSelected ? BOX_STROKE_SELECTED : "#94a3b8";
        ctx.fillText(labelText, bx + badgePadX, by + badgeH - badgePadY - 1);

        // Calculate dimensions if slideInfo is available
        if (slideInfo && isSelected) {
          const widthPx = box.x_max - box.x_min;
          const heightPx = box.y_max - box.y_min;
          const widthUm = pxToUm(widthPx, slideInfo.mpp);
          const heightUm = pxToUm(heightPx, slideInfo.mpp);
          const widthMm = widthUm / 1000;
          const heightMm = heightUm / 1000;
          const areaMm2 = areaPxToMm2(widthPx * heightPx, slideInfo.mpp);

          ctx.font = "bold 10px Inter, system-ui, sans-serif";

          // Width label (top, centered) - only if box is tall enough
          if (sh > 60) {
            const widthText = `${widthMm.toFixed(3)} mm`;
            const widthTextWidth = ctx.measureText(widthText).width;
            const widthLabelX = sx + sw / 2 - widthTextWidth / 2 - badgePadX;
            const widthLabelY = sy - 26;
            const widthLabelW = widthTextWidth + badgePadX * 2;

            ctx.fillStyle = "rgba(250, 204, 21, 0.95)";
            ctx.beginPath();
            ctx.roundRect(widthLabelX, widthLabelY, widthLabelW, 16, 3);
            ctx.fill();

            ctx.fillStyle = "#000";
            ctx.fillText(widthText, widthLabelX + badgePadX, widthLabelY + 12);
          }

          // Height label (left side, centered) - only if box is wide enough
          if (sw > 80) {
            const heightText = `${heightMm.toFixed(3)} mm`;
            const heightTextWidth = ctx.measureText(heightText).width;
            const heightLabelX = sx - heightTextWidth - badgePadX * 2 - 8;
            const heightLabelY = sy + sh / 2 - 8;
            const heightLabelW = heightTextWidth + badgePadX * 2;

            ctx.fillStyle = "rgba(250, 204, 21, 0.95)";
            ctx.beginPath();
            ctx.roundRect(heightLabelX, heightLabelY, heightLabelW, 16, 3);
            ctx.fill();

            ctx.fillStyle = "#000";
            ctx.fillText(heightText, heightLabelX + badgePadX, heightLabelY + 12);
          }

          // Area label (center) - only if box is large enough
          if (sw > 100 && sh > 100) {
            const areaText = `${areaMm2.toFixed(3)} mm²`;
            const areaTextWidth = ctx.measureText(areaText).width;
            const areaLabelX = sx + sw / 2 - areaTextWidth / 2 - badgePadX;
            const areaLabelY = sy + sh / 2 - 10;
            const areaLabelW = areaTextWidth + badgePadX * 2;

            ctx.fillStyle = "rgba(250, 204, 21, 0.95)";
            ctx.beginPath();
            ctx.roundRect(areaLabelX, areaLabelY, areaLabelW, 20, 4);
            ctx.fill();

            ctx.fillStyle = "#000";
            ctx.font = "bold 11px Inter, system-ui, sans-serif";
            ctx.fillText(areaText, areaLabelX + badgePadX, areaLabelY + 14);
          }
        }
      }

      boxRectsRef.current = rects;
    };

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
  }, [viewer, boxes, selectedBoxId, visible, slideInfo]);

  // Click handler — hit test against stored box rects
  // We listen on the viewer's container so pointer-events: none on the
  // canvas doesn't block OSD pan/zoom. Only box-hits trigger selection.
  useEffect(() => {
    if (!viewer || !onSelectBox || !visible) return;

    const container = viewer.container;
    if (!container) return;

    const handleClick = (e) => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      // Check boxes in reverse order (top-most drawn last)
      const rects = boxRectsRef.current;
      for (let i = rects.length - 1; i >= 0; i--) {
        const r = rects[i];
        if (mx >= r.x && mx <= r.x + r.w && my >= r.y && my <= r.y + r.h) {
          onSelectBox(r.id);
          return;
        }
      }
    };

    // Use capture phase so we see clicks before OSD swallows them
    container.addEventListener("click", handleClick, true);
    return () => container.removeEventListener("click", handleClick, true);
  }, [viewer, onSelectBox, visible]);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 z-20"
      style={{ pointerEvents: "none" }}
      aria-label="Analysis box overlay"
    />
  );
}
