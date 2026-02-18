/**
 * useZoomTracker — Hook to track viewer zoom level and current pyramid level.
 *
 * Responsibilities:
 * - Monitors OpenSeadragon zoom events
 * - Calculates the current pyramid level
 * - Updates zoomInfo state for status bar display
 */

import { useEffect } from 'react';
import { getCurrentLevel } from '../utils/coordinates';
import { useViewerStore } from '../stores/useViewerStore';

export function useZoomTracker(viewer, slideInfo) {
  const { setZoomInfo } = useViewerStore();

  useEffect(() => {
    if (!viewer || !slideInfo) return;

    let raf = null;

    const update = () => {
      if (!viewer || !viewer.viewport) return;
      const zoom = viewer.viewport.getZoom(true);
      const level = getCurrentLevel(viewer, slideInfo.width_px);
      setZoomInfo({ zoom, level });
    };

    const handler = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(update);
    };

    viewer.addHandler('zoom', handler);
    viewer.addHandler('animation-finish', handler);
    viewer.addHandler('open', handler);

    handler();

    return () => {
      viewer.removeHandler('zoom', handler);
      viewer.removeHandler('animation-finish', handler);
      viewer.removeHandler('open', handler);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [viewer, slideInfo, setZoomInfo]);
}
