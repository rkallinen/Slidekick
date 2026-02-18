/**
 * useOverlayCenterTracking — Hook to track the viewer container center position.
 *
 * Responsibilities:
 * - Calculates the horizontal center of the viewer container
 * - Updates when the container resizes or window resizes
 * - Used for centering the progress overlay
 */

import { useState, useEffect } from 'react';

export function useOverlayCenterTracking(containerRef, viewer) {
  const [overlayCenterX, setOverlayCenterX] = useState(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const update = () => setOverlayCenterX(el.clientWidth / 2);

    // Initial
    update();

    // Resize observer keeps center updated when the viewer resizes
    const ro = new ResizeObserver(() => update());
    ro.observe(el);
    window.addEventListener('resize', update);

    return () => {
      ro.disconnect();
      window.removeEventListener('resize', update);
    };
  }, [containerRef, viewer]);

  return overlayCenterX;
}
