/**
 * DrawModeOverlay — Interactive overlay for area selection in draw mode.
 *
 * Responsibilities:
 * - Captures mouse events for drawing selection rectangles
 * - Displays the banner instructing users to drag
 * - Manages drag state and converts screen coordinates to L0 pixel coordinates
 */

import { useCallback } from 'react';
import OpenSeadragon from 'openseadragon';
import { useViewerStore } from '../../stores/useViewerStore';

export default function DrawModeOverlay({ viewer, slideInfo }) {
  const {
    drawMode,
    isDragging,
    dragStart,
    resizeEdge,
    setIsDragging,
    setDragStart,
    setDragEnd,
    setSelectedArea,
    setSelectionRect,
    setDrawMode,
  } = useViewerStore();

  const handleMouseDown = useCallback(
    (e) => {
      if (e.button !== 0) return; // only left click
      const rect = e.currentTarget.getBoundingClientRect();
      const point = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      setIsDragging(true);
      setDragStart(point);
      setDragEnd(point);
      setSelectedArea(null);
      setSelectionRect(null);
    },
    [setIsDragging, setDragStart, setDragEnd, setSelectedArea, setSelectionRect],
  );

  const handleMouseMove = useCallback(
    (e) => {
      if (!isDragging || resizeEdge) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const point = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      setDragEnd(point);
    },
    [isDragging, resizeEdge, setDragEnd],
  );

  const handleMouseUp = useCallback(
    (e) => {
      if (!isDragging || !dragStart || resizeEdge) return;
      setIsDragging(false);

      const rect = e.currentTarget.getBoundingClientRect();
      const endPoint = { x: e.clientX - rect.left, y: e.clientY - rect.top };

      const sx = Math.min(dragStart.x, endPoint.x);
      const sy = Math.min(dragStart.y, endPoint.y);
      const sw = Math.abs(endPoint.x - dragStart.x);
      const sh = Math.abs(endPoint.y - dragStart.y);

      // Ignore tiny drags
      if (sw < 10 || sh < 10) {
        setDragStart(null);
        setDragEnd(null);
        return;
      }

      // Convert screen corners to L0 pixel coordinates
      if (viewer && viewer.viewport && slideInfo) {
        const topLeftVP = viewer.viewport.viewerElementToViewportCoordinates(
          new OpenSeadragon.Point(sx, sy),
        );
        const bottomRightVP = viewer.viewport.viewerElementToViewportCoordinates(
          new OpenSeadragon.Point(sx + sw, sy + sh),
        );

        const topLeftImg = viewer.viewport.viewportToImageCoordinates(topLeftVP);
        const bottomRightImg = viewer.viewport.viewportToImageCoordinates(bottomRightVP);

        const xMin = Math.max(0, Math.round(topLeftImg.x));
        const yMin = Math.max(0, Math.round(topLeftImg.y));
        const xMax = Math.min(slideInfo.width_px, Math.round(bottomRightImg.x));
        const yMax = Math.min(slideInfo.height_px, Math.round(bottomRightImg.y));

        setSelectedArea({
          x: xMin,
          y: yMin,
          width: xMax - xMin,
          height: yMax - yMin,
          xMin,
          yMin,
          xMax,
          yMax,
        });

        setSelectionRect({ x: sx, y: sy, w: sw, h: sh });
      }

      setDragStart(null);
      setDragEnd(null);
      // Exit draw mode once the area is drawn
      setDrawMode(false);
    },
    [
      isDragging,
      dragStart,
      viewer,
      slideInfo,
      resizeEdge,
      setIsDragging,
      setDragStart,
      setDragEnd,
      setSelectedArea,
      setSelectionRect,
      setDrawMode,
    ],
  );

  if (!drawMode) return null;

  return (
    <>
      {/* Transparent overlay for capturing mouse events */}
      <div
        className="absolute inset-0 z-40"
        style={{ cursor: 'crosshair' }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
      />

      {/* Banner instructing user */}
      {!isDragging && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-50 pointer-events-none">
          <div className="rounded-lg bg-cyan-600/90 px-4 py-2 text-sm font-medium text-white shadow-lg backdrop-blur-sm">
            Click and drag to select an area
          </div>
        </div>
      )}
    </>
  );
}
