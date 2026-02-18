/**
 * useDrawModeManager — Hook to manage draw mode side effects.
 *
 * Responsibilities:
 * - Disables OpenSeadragon mouse navigation when draw mode is active
 * - Re-enables it when draw mode is disabled
 * - Keeps scroll-to-zoom enabled in draw mode
 * - Clears selection when inference starts
 */

import { useEffect } from 'react';
import { useViewerStore } from '../stores/useViewerStore';

export function useDrawModeManager(viewer, inferenceLoading) {
  const { drawMode, setDrawMode, clearSelection } = useViewerStore();

  // Clear selection when inference starts
  useEffect(() => {
    if (inferenceLoading) {
      clearSelection();
    }
  }, [inferenceLoading, clearSelection]);

  // Toggle OSD mouse navigation based on draw mode
  useEffect(() => {
    if (!viewer) return;
    if (drawMode) {
      viewer.setMouseNavEnabled(false);
      // Re-enable scroll zoom even in draw mode
      viewer.gestureSettingsMouse.scrollToZoom = true;
    } else {
      viewer.setMouseNavEnabled(true);
    }
  }, [viewer, drawMode]);
}
