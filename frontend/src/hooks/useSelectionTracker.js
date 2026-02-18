/**
 * useSelectionTracker — Hook to update selection rectangle as viewport moves.
 *
 * Responsibilities:
 * - Recalculates the screen position of the selected area when the viewport changes
 * - Updates the selectionRect state to keep the visual indicator in sync
 */

import { useEffect } from 'react';
import { useViewerStore } from '../stores/useViewerStore';

export function useSelectionTracker(viewer) {
  const { selectedArea, setSelectionRect } = useViewerStore();

  useEffect(() => {
    if (!viewer || !selectedArea) return;

    const updateSelectionRect = () => {
      if (!viewer.viewport) return;
      const topLeftVP = viewer.viewport.imageToViewportCoordinates(
        selectedArea.xMin,
        selectedArea.yMin,
      );
      const bottomRightVP = viewer.viewport.imageToViewportCoordinates(
        selectedArea.xMax,
        selectedArea.yMax,
      );
      const topLeftScreen = viewer.viewport.viewportToViewerElementCoordinates(topLeftVP);
      const bottomRightScreen = viewer.viewport.viewportToViewerElementCoordinates(bottomRightVP);
      setSelectionRect({
        x: topLeftScreen.x,
        y: topLeftScreen.y,
        w: bottomRightScreen.x - topLeftScreen.x,
        h: bottomRightScreen.y - topLeftScreen.y,
      });
    };

    viewer.addHandler('animation', updateSelectionRect);
    viewer.addHandler('animation-finish', updateSelectionRect);
    viewer.addHandler('zoom', updateSelectionRect);

    return () => {
      viewer.removeHandler('animation', updateSelectionRect);
      viewer.removeHandler('animation-finish', updateSelectionRect);
      viewer.removeHandler('zoom', updateSelectionRect);
    };
  }, [viewer, selectedArea, setSelectionRect]);
}
