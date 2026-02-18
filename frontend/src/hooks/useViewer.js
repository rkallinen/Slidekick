/**
 * useViewer — OpenSeadragon viewer lifecycle hook.
 *
 * Manages OSD initialisation, DZI tile source binding,
 * and viewport change events.
 */

import { useEffect, useRef, useState } from "react";
import OpenSeadragon from "openseadragon";
import { getDziUrl } from "../services/api.js";

/**
 * @param {string|null} slideId - UUID of the active slide
 * @param {object} slideInfo - { width_px, height_px, mpp }
 * @param {function} onViewportChange - callback(bounds) on pan/zoom
 * @returns {{ containerRef, viewer, isReady }}
 */
export default function useViewer(slideId, slideInfo, onViewportChange) {
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const [isReady, setIsReady] = useState(false);

  // Initialise OpenSeadragon
  useEffect(() => {
    if (!containerRef.current) return;

    const viewer = OpenSeadragon({
      element: containerRef.current,    

      // Navigator configuration
      showNavigator: true,
      navigatorPosition: "BOTTOM_RIGHT",
      navigatorSizeRatio: 0.15,
      showZoomControl: false,
      showHomeControl: false,
      showFullPageControl: false,
      crossOriginPolicy: "Anonymous",
      animationTime: 0.3,
      blendTime: 0.1,
      constrainDuringPan: true,
      maxZoomPixelRatio: 4,
      minZoomImageRatio: 0.5,
      visibilityRatio: 0.8,

      // These ensure scroll wheel zoom and drag-to-pan work correctly
      gestureSettingsMouse: {
        clickToZoom: false,        // Prevent accidental click-zoom
        dblClickToZoom: true,       // Allow double-click zoom
        scrollToZoom: true,         // ENABLE scroll wheel zoom
        flickEnabled: true,         // Smooth momentum panning
        flickMinSpeed: 10,          // Minimum flick speed
        flickMomentum: 0.25,        // Flick decay rate
      },
      
      gestureSettingsTouch: {
        pinchToZoom: true,          // Multi-touch pinch zoom
        flickEnabled: true,         // Touch momentum
      },
      
      // Pan/zoom constraints must allow movement
      panHorizontal: true,          //  Allow horizontal panning
      panVertical: true,            //  Allow vertical panning
      
      // Zoom sensitivity (higher = faster zoom)
      zoomPerScroll: 1.2,           // 20% zoom per scroll tick 
      zoomPerClick: 2.0,            // Zoom factor for click/double-click
      
      // Tile handling
      immediateRender: true,
      imageLoaderLimit: 10,
    });

    // Explicitly ensure mouse navigation is enabled
    viewer.setMouseNavEnabled(true);

    viewerRef.current = viewer;
    setIsReady(true);

    return () => {
      viewer.destroy();
      viewerRef.current = null;
      setIsReady(false);
    };
  }, []);

  // Load DZI tile source when slide changes
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !slideId) return;

    // OpenSeadragon can consume DZI XML directly
    viewer.open(getDziUrl(slideId));
  }, [slideId]);

  // Viewport change listener (debounced)
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !slideInfo || !onViewportChange) return;

    let timeoutId = null;

    const handler = () => {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        if (!viewer.viewport) return;
        onViewportChange(viewer);
      }, 150); // 150ms debounce
    };

    viewer.addHandler("animation-finish", handler);
    viewer.addHandler("zoom", handler);
    viewer.addHandler("pan", handler);

    // Fire once immediately so nuclei load on first render
    handler();

    return () => {
      clearTimeout(timeoutId);
      viewer.removeHandler("animation-finish", handler);
      viewer.removeHandler("zoom", handler);
      viewer.removeHandler("pan", handler);
    };
  }, [slideInfo, onViewportChange]);

  return { containerRef, viewer: viewerRef.current, isReady };
}
