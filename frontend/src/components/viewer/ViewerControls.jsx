/**
 * ViewerControls — Control buttons for the DeepZoomViewer.
 *
 * Responsibilities:
 * - Analyze View button (run inference on current viewport)
 * - Analyze Area button (toggle draw mode or analyze selected area)
 * - Clear Selection button
 * - Show menu with overlay toggles
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { useViewerStore } from '../../stores/useViewerStore';

export default function ViewerControls({
  viewer,
  slideId,
  onRunInference,
  onRunInferenceOnArea,
  inferenceLoading,
}) {
  const [showMenu, setShowMenu] = useState(false);
  const menuRef = useRef(null);

  const {
    drawMode,
    selectedArea,
    overlayVisible,
    boxesVisible,
    setDrawMode,
    setOverlayVisible,
    setBoxesVisible,
    clearSelection,
  } = useViewerStore();

  // Close menu when clicking outside
  useEffect(() => {
    const handleDocClick = (e) => {
      if (!showMenu) return;
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setShowMenu(false);
      }
    };
    document.addEventListener('mousedown', handleDocClick);
    return () => document.removeEventListener('mousedown', handleDocClick);
  }, [showMenu]);

  // Handle the dual-purpose Analyze Area / Draw toggle button
  const handleDrawOrAnalyze = useCallback(() => {
    if (selectedArea) {
      if (viewer && onRunInferenceOnArea) {
        onRunInferenceOnArea(viewer, selectedArea);
      }
      return;
    }

    setDrawMode(!drawMode);
    if (drawMode) {
      clearSelection();
    }
  }, [selectedArea, viewer, onRunInferenceOnArea, drawMode, setDrawMode, clearSelection]);

  return (
    <div
      className="absolute z-30 flex flex-col items-end"
      style={{ top: 'var(--space-5)', right: 'var(--space-5)', gap: 'var(--space-2)' }}
    >
      {/* Prominent: Run inference on viewport */}
      <button
        onClick={() => viewer && onRunInference && onRunInference(viewer)}
        disabled={inferenceLoading || !slideId}
        className="viewer-btn viewer-btn--success viewer-btn--flat"
        title="Run HoVerNet on current viewport"
      >
        {inferenceLoading ? 'Analyzing...' : 'Analyze View'}
      </button>

      {/* Draw-mode / Select Area */}
      {!inferenceLoading && (
        <button
          onClick={handleDrawOrAnalyze}
          className={`viewer-btn viewer-btn--flat ${drawMode ? 'viewer-btn--accent' : slideId ? 'viewer-btn--primary' : 'viewer-btn--ghost'}`}
          title={
            selectedArea
              ? 'Run HoVerNet on selected area'
              : drawMode
                ? 'Cancel area selection'
                : 'Draw an area to analyze'
          }
        >
          {drawMode ? '✕ Cancel Selection' : 'Analyze Area'}
        </button>
      )}

      {/* Clear selection button */}
      {selectedArea && !inferenceLoading && (
        <button
          onClick={clearSelection}
          className="viewer-btn viewer-btn--ghost"
          title="Clear selection"
        >
          Clear Selection
        </button>
      )}

      {/* Show menu with overlay toggles */}
      <div ref={menuRef} className="relative" style={{ zIndex: 60 }}>
        <button
          onClick={() => setShowMenu((s) => !s)}
          className="viewer-btn viewer-btn--ghost"
          title="Show overlays and measurements"
          aria-haspopup="true"
          aria-expanded={showMenu}
        >
          Show ▾
        </button>

        {showMenu && (
          <div
            style={{
              position: 'absolute',
              top: '100%',
              right: 0,
              marginTop: '8px',
              width: 'max-content',
              minWidth: '120px',
              padding: '6px',
              borderRadius: 'var(--radius-md)',
              boxShadow: 'var(--shadow-lg)',
              background: 'var(--color-midnight)',
              border: '1px solid var(--border-hairline)',
              pointerEvents: 'auto',
            }}
          >
            <label
              className="flex items-center gap-2 px-2 py-2 hover:bg-white/3 rounded"
              style={{ cursor: 'pointer' }}
            >
              <input
                type="checkbox"
                checked={overlayVisible}
                onChange={() => setOverlayVisible(!overlayVisible)}
              />
              <span className="text-sm select-none" style={{ color: 'rgba(255,255,255,0.92)' }}>
                Nuclei
              </span>
            </label>

            <label
              className="flex items-center gap-2 px-2 py-2 hover:bg-white/3 rounded"
              style={{ cursor: 'pointer' }}
            >
              <input
                type="checkbox"
                checked={boxesVisible}
                onChange={() => setBoxesVisible(!boxesVisible)}
              />
              <span className="text-sm select-none" style={{ color: 'rgba(255,255,255,0.92)' }}>
                Boxes
              </span>
            </label>
          </div>
        )}
      </div>
    </div>
  );
}
