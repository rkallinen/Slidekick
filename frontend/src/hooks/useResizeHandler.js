/**
 * useResizeHandler — Hook to manage selection rectangle resizing.
 *
 * Responsibilities:
 * - Handles global mouse events during resize operations
 * - Updates the selected area based on which edge is being dragged
 * - Converts mouse coordinates to L0 pixel coordinates
 */

import { useEffect, useCallback } from 'react';
import OpenSeadragon from 'openseadragon';
import { useViewerStore } from '../stores/useViewerStore';

export function useResizeHandler(viewer, slideInfo) {
  const {
    isDragging,
    resizeEdge,
    selectedArea,
    setSelectedArea,
    setSelectionRect,
    setIsDragging,
    setResizeEdge,
    setDragStart,
  } = useViewerStore();

  const handleResizeMouseMove = useCallback(
    (e) => {
      if (!isDragging || !resizeEdge || !selectedArea || !viewer || !slideInfo) return;

      const rect = viewer.container.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      // Convert mouse position to L0 coordinates
      const mouseVP = viewer.viewport.viewerElementToViewportCoordinates(
        new OpenSeadragon.Point(mx, my),
      );
      const mouseImg = viewer.viewport.viewportToImageCoordinates(mouseVP);
      const mousePx = {
        x: Math.max(0, Math.min(slideInfo.width_px, Math.round(mouseImg.x))),
        y: Math.max(0, Math.min(slideInfo.height_px, Math.round(mouseImg.y))),
      };

      // Update selected area based on which edge is being dragged
      let newArea = { ...selectedArea };

      if (resizeEdge === 'left') {
        const newXMin = Math.min(mousePx.x, selectedArea.xMax - 10);
        newArea = {
          ...newArea,
          xMin: newXMin,
          x: newXMin,
          width: selectedArea.xMax - newXMin,
        };
      } else if (resizeEdge === 'right') {
        const newXMax = Math.max(mousePx.x, selectedArea.xMin + 10);
        newArea = {
          ...newArea,
          xMax: newXMax,
          width: newXMax - selectedArea.xMin,
        };
      } else if (resizeEdge === 'top') {
        const newYMin = Math.min(mousePx.y, selectedArea.yMax - 10);
        newArea = {
          ...newArea,
          yMin: newYMin,
          y: newYMin,
          height: selectedArea.yMax - newYMin,
        };
      } else if (resizeEdge === 'bottom') {
        const newYMax = Math.max(mousePx.y, selectedArea.yMin + 10);
        newArea = {
          ...newArea,
          yMax: newYMax,
          height: newYMax - selectedArea.yMin,
        };
      }

      setSelectedArea(newArea);

      // Update screen rect
      const topLeftVP = viewer.viewport.imageToViewportCoordinates(newArea.xMin, newArea.yMin);
      const bottomRightVP = viewer.viewport.imageToViewportCoordinates(newArea.xMax, newArea.yMax);
      const topLeftScreen = viewer.viewport.viewportToViewerElementCoordinates(topLeftVP);
      const bottomRightScreen = viewer.viewport.viewportToViewerElementCoordinates(bottomRightVP);

      setSelectionRect({
        x: topLeftScreen.x,
        y: topLeftScreen.y,
        w: bottomRightScreen.x - topLeftScreen.x,
        h: bottomRightScreen.y - topLeftScreen.y,
      });
    },
    [isDragging, resizeEdge, selectedArea, viewer, slideInfo, setSelectedArea, setSelectionRect],
  );

  const handleResizeMouseUp = useCallback(() => {
    setIsDragging(false);
    setResizeEdge(null);
    setDragStart(null);
  }, [setIsDragging, setResizeEdge, setDragStart]);

  // Global mouse event listeners for resizing
  useEffect(() => {
    if (!resizeEdge) return;

    const handleGlobalMouseMove = (e) => {
      if (!viewer || !viewer.container) return;
      handleResizeMouseMove({
        clientX: e.clientX,
        clientY: e.clientY,
      });
    };

    const handleGlobalMouseUp = () => {
      handleResizeMouseUp();
    };

    document.addEventListener('mousemove', handleGlobalMouseMove);
    document.addEventListener('mouseup', handleGlobalMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleGlobalMouseMove);
      document.removeEventListener('mouseup', handleGlobalMouseUp);
    };
  }, [resizeEdge, viewer, handleResizeMouseMove, handleResizeMouseUp]);
}
