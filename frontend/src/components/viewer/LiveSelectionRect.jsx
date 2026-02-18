/**
 * LiveSelectionRect — Visual feedback during area selection drag.
 *
 * Responsibilities:
 * - Displays the dragging rectangle in real-time
 * - Shows dimension labels (width, height, area) during drag
 * - Calculates measurements from pixel coordinates using slide MPP
 */

import { useViewerStore } from '../../stores/useViewerStore';
import { pxToUm, areaPxToMm2 } from '../../utils/coordinates';
import OpenSeadragon from 'openseadragon';

export default function LiveSelectionRect({ viewer, slideInfo }) {
  const { isDragging, dragStart, dragEnd, resizeEdge } = useViewerStore();

  // Compute the live drag rectangle for rendering
  const liveDragRect =
    isDragging && dragStart && dragEnd
      ? {
          x: Math.min(dragStart.x, dragEnd.x),
          y: Math.min(dragStart.y, dragEnd.y),
          w: Math.abs(dragEnd.x - dragStart.x),
          h: Math.abs(dragEnd.y - dragStart.y),
        }
      : null;

  // Calculate live measurements during drag
  const liveMeasurements = (() => {
    if (!liveDragRect || !viewer || !slideInfo || resizeEdge) return null;

    // Convert screen corners to L0 pixel coordinates
    const topLeftVP = viewer.viewport.viewerElementToViewportCoordinates(
      new OpenSeadragon.Point(liveDragRect.x, liveDragRect.y),
    );
    const bottomRightVP = viewer.viewport.viewerElementToViewportCoordinates(
      new OpenSeadragon.Point(liveDragRect.x + liveDragRect.w, liveDragRect.y + liveDragRect.h),
    );

    const topLeftImg = viewer.viewport.viewportToImageCoordinates(topLeftVP);
    const bottomRightImg = viewer.viewport.viewportToImageCoordinates(bottomRightVP);

    const widthPx = Math.abs(bottomRightImg.x - topLeftImg.x);
    const heightPx = Math.abs(bottomRightImg.y - topLeftImg.y);

    const widthUm = pxToUm(widthPx, slideInfo.mpp);
    const heightUm = pxToUm(heightPx, slideInfo.mpp);
    const widthMm = widthUm / 1000;
    const heightMm = heightUm / 1000;
    const areaMm2 = areaPxToMm2(widthPx * heightPx, slideInfo.mpp);

    return { widthMm, heightMm, areaMm2 };
  })();

  if (!liveDragRect || liveDragRect.w <= 10 || liveDragRect.h <= 10) return null;

  return (
    <div
      className="absolute z-50 pointer-events-none border-2 border-dashed border-cyan-400"
      style={{
        left: liveDragRect.x,
        top: liveDragRect.y,
        width: liveDragRect.w,
        height: liveDragRect.h,
        backgroundColor: 'rgba(34, 211, 238, 0.1)',
      }}
    >
      {liveMeasurements && (
        <>
          {/* Width label (top, centered) */}
          <div className="absolute -top-7 left-1/2 -translate-x-1/2 measurement-badge--small whitespace-nowrap">
            {liveMeasurements.widthMm.toFixed(3)} mm
          </div>

          {/* Height label (left side, centered) */}
          <div className="absolute top-1/2 -left-16 -translate-y-1/2 measurement-badge--small whitespace-nowrap">
            {liveMeasurements.heightMm.toFixed(3)} mm
          </div>

          {/* Area label (center) */}
          {liveDragRect.w > 80 && liveDragRect.h > 80 && (
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 measurement-badge whitespace-nowrap">
              {liveMeasurements.areaMm2.toFixed(3)} mm²
            </div>
          )}
        </>
      )}
    </div>
  );
}
