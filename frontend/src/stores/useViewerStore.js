/**
 * Viewer Store — Zustand store for DeepZoomViewer shared state.
 *
 * Manages:
 * - Overlay visibility toggles (nuclei, boxes)
 * - Draw mode state and selected area
 * - Zoom information
 */

import { create } from 'zustand';

export const useViewerStore = create((set) => ({
  // Overlay visibility
  overlayVisible: true,
  boxesVisible: true,
  setOverlayVisible: (visible) => set({ overlayVisible: visible }),
  setBoxesVisible: (visible) => set({ boxesVisible: visible }),
  toggleOverlayVisible: () => set((state) => ({ overlayVisible: !state.overlayVisible })),
  toggleBoxesVisible: () => set((state) => ({ boxesVisible: !state.boxesVisible })),

  // Draw mode state
  drawMode: false,
  isDragging: false,
  dragStart: null,
  dragEnd: null,
  selectedArea: null,
  selectionRect: null,
  resizeEdge: null,

  setDrawMode: (mode) => set({ drawMode: mode }),
  setIsDragging: (dragging) => set({ isDragging: dragging }),
  setDragStart: (start) => set({ dragStart: start }),
  setDragEnd: (end) => set({ dragEnd: end }),
  setSelectedArea: (area) => set({ selectedArea: area }),
  setSelectionRect: (rect) => set({ selectionRect: rect }),
  setResizeEdge: (edge) => set({ resizeEdge: edge }),

  clearSelection: () => set({
    selectedArea: null,
    selectionRect: null,
    dragStart: null,
    dragEnd: null,
    drawMode: false,
  }),

  // Zoom tracking
  zoomInfo: { zoom: null, level: null },
  setZoomInfo: (info) => set({ zoomInfo: info }),
}));
