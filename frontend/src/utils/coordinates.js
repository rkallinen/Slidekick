/**
 * Coordinate Utilities
 *
 * Client-side coordinate transformations mirroring the backend's
 * CoordinateTransformer. All computations use Level-0 pixel space.
 *
 * Mathematical foundation:
 *   d_μm  = d_px × MPP
 *   A_mm² = A_px × MPP² × 1e-6
 *   ρ     = N / A_mm²  (nuclei / mm²)
 */

/**
 * Get the current viewer bounds in Level-0 pixel coordinates.
 *
 * @param {import('openseadragon').Viewer} viewer
 * @param {number} slideWidth
 * @param {number} slideHeight
 * @returns {{ x: number, y: number, width: number, height: number, xMin: number, yMin: number, xMax: number, yMax: number }}
 */
export function getViewportBoundsL0(viewer, slideWidth, slideHeight) {
  const bounds = viewer.viewport.getBounds(true);
  const topLeft = viewer.viewport.viewportToImageCoordinates(bounds.x, bounds.y);
  const bottomRight = viewer.viewport.viewportToImageCoordinates(
    bounds.x + bounds.width,
    bounds.y + bounds.height,
  );

  const xMin = Math.max(0, Math.round(topLeft.x));
  const yMin = Math.max(0, Math.round(topLeft.y));
  const xMax = Math.min(slideWidth, Math.round(bottomRight.x));
  const yMax = Math.min(slideHeight, Math.round(bottomRight.y));

  return {
    x: xMin,
    y: yMin,
    width: xMax - xMin,
    height: yMax - yMin,
    xMin,
    yMin,
    xMax,
    yMax,
  };
}

/**
 * Convert a pixel distance to micrometres.
 * @param {number} distancePx
 * @param {number} mpp - Microns per pixel
 * @returns {number}
 */
export function pxToUm(distancePx, mpp) {
  return distancePx * mpp;
}

/**
 * Convert pixel area to mm².
 * @param {number} areaPx - Area in pixels²
 * @param {number} mpp - Microns per pixel
 * @returns {number}
 */
export function areaPxToMm2(areaPx, mpp) {
  return areaPx * mpp * mpp * 1e-6;
}

/**
 * Compute the current OpenSeadragon zoom level (approximate OpenSlide level).
 *
 * @param {import('openseadragon').Viewer} viewer
 * @param {number} slideWidth - Level-0 width
 * @returns {number} Approximate integer level (0 = highest zoom)
 */
export function getCurrentLevel(viewer, slideWidth) {
  const zoom = viewer.viewport.getZoom(true);
  const containerWidth = viewer.viewport.getContainerSize().x;
  // pixels per viewport pixel at current zoom
  const pixelsPerViewportPx = slideWidth / (containerWidth * zoom);
  // downsample factor → level
  const level = Math.max(0, Math.round(Math.log2(pixelsPerViewportPx)));
  return level;
}

/**
 * Compute scale bar pixel width for a given target length in μm.
 *
 * @param {number} targetUm - Desired scale bar length in micrometres
 * @param {number} mpp - Microns per pixel at Level 0
 * @param {number} currentZoom - OSD viewport zoom
 * @param {number} slideWidth - Level-0 slide width
 * @param {number} containerWidth - Viewer container width in CSS pixels
 * @returns {number} Scale bar width in CSS pixels
 */
export function scaleBarPixels(targetUm, mpp, currentZoom, slideWidth, containerWidth) {
  // How many L0 pixels correspond to targetUm?
  const l0Pixels = targetUm / mpp;
  // How many CSS pixels per L0 pixel at current zoom?
  const cssPerL0 = (containerWidth * currentZoom) / slideWidth;
  return l0Pixels * cssPerL0;
}

/** Cell type colour map (consistent with backend taxonomy). */
export const CELL_TYPE_COLORS = {
  0: "#6b7280", // Background — gray
  1: "#ef4444", // Neoplastic — red
  2: "#3b82f6", // Inflammatory — blue
  3: "#22c55e", // Connective — green
  4: "#a855f7", // Dead — purple
  5: "#f97316", // Epithelial — orange
};

export const CELL_TYPE_NAMES = {
  0: "Background",
  1: "Neoplastic",
  2: "Inflammatory",
  3: "Connective",
  4: "Dead",
  5: "Epithelial",
};
