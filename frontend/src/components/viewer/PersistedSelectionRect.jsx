/**
 * PersistedSelectionRect — Displays the confirmed selection rectangle with resize handles.
 *
 * Responsibilities:
 * - Renders the selection rectangle that tracks viewport movement
 * - Shows dimension labels (width, height, area)
 * - Provides resize handles for adjusting selection
 */

import { useCallback } from 'react';
import { useViewerStore } from '../../stores/useViewerStore';
import { pxToUm, areaPxToMm2 } from '../../utils/coordinates';

export default function PersistedSelectionRect({ viewer, slideInfo }) {
  const {
    drawMode,
    selectedArea,
    selectionRect,
    setIsDragging,
    setResizeEdge,
    setDragStart,
  } = useViewerStore();

  const handleResizeMouseDown = useCallback(
    (e, edge) => {
      e.stopPropagation();
      e.preventDefault();
      setIsDragging(true);
      setResizeEdge(edge);
      const rect = viewer.container.getBoundingClientRect();
      setDragStart({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    },
    [viewer, setIsDragging, setResizeEdge, setDragStart],
  );

  // Don't show if draw mode is active or if there's no selection
  if (!selectionRect || drawMode || !selectedArea || !slideInfo) return null;

  // Calculate dimensions in mm
  const widthUm = pxToUm(selectedArea.width, slideInfo.mpp);
  const heightUm = pxToUm(selectedArea.height, slideInfo.mpp);
  const widthMm = widthUm / 1000;
  const heightMm = heightUm / 1000;
  const areaMm2 = areaPxToMm2(selectedArea.width * selectedArea.height, slideInfo.mpp);

  return (
    <div
      className="absolute z-30 border-2 border-cyan-400"
      style={{
        left: selectionRect.x,
        top: selectionRect.y,
        width: selectionRect.w,
        height: selectionRect.h,
        backgroundColor: 'rgba(34, 211, 238, 0.08)',
        pointerEvents: 'none',
      }}
    >
      {/* Animated corner markers */}
      <div className="absolute -top-0.5 -left-0.5 w-3 h-3 border-t-2 border-l-2 border-cyan-300" />
      <div className="absolute -top-0.5 -right-0.5 w-3 h-3 border-t-2 border-r-2 border-cyan-300" />
      <div className="absolute -bottom-0.5 -left-0.5 w-3 h-3 border-b-2 border-l-2 border-cyan-300" />
      <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 border-b-2 border-r-2 border-cyan-300" />

      {/* Resize handles */}
      <div
        className="absolute -top-1 left-0 right-0 h-3 cursor-ns-resize hover:bg-cyan-400/20"
        style={{ pointerEvents: 'auto' }}
        onMouseDown={(e) => handleResizeMouseDown(e, 'top')}
      />
      <div
        className="absolute -bottom-1 left-0 right-0 h-3 cursor-ns-resize hover:bg-cyan-400/20"
        style={{ pointerEvents: 'auto' }}
        onMouseDown={(e) => handleResizeMouseDown(e, 'bottom')}
      />
      <div
        className="absolute -left-1 top-0 bottom-0 w-3 cursor-ew-resize hover:bg-cyan-400/20"
        style={{ pointerEvents: 'auto' }}
        onMouseDown={(e) => handleResizeMouseDown(e, 'left')}
      />
      <div
        className="absolute -right-1 top-0 bottom-0 w-3 cursor-ew-resize hover:bg-cyan-400/20"
        style={{ pointerEvents: 'auto' }}
        onMouseDown={(e) => handleResizeMouseDown(e, 'right')}
      />

      {/* Dimension labels — match canvas-selected analysis box badges */}
      <div className="absolute -top-7 left-1/2 -translate-x-1/2 measurement-badge--small whitespace-nowrap">
        {widthMm.toFixed(3)} mm
      </div>

      <div className="absolute top-1/2 -left-16 -translate-y-1/2 measurement-badge--small whitespace-nowrap">
        {heightMm.toFixed(3)} mm
      </div>

      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 measurement-badge whitespace-nowrap">
        {areaMm2.toFixed(3)} mm²
      </div>
    </div>
  );
}
