/**
 * DeepZoomViewer — OpenSeadragon integration with Canvas overlays.
 *
 * This is the primary WSI viewer component. It:
 *   1. Renders the WSI via OpenSeadragon's DZI tile protocol.
 *   2. Overlays a Canvas2D layer for nucleus rendering.
 *   3. Overlays a Canvas2D layer for analysis box outlines.
 *   4. Emits viewport change events for data fetching.
 *   5. Provides controls for inference and overlay toggling.
 */

import { useCallback } from 'react';
import useViewer from '../hooks/useViewer.js';
import NucleusOverlay from './NucleusOverlay.jsx';
import AnalysisBoxOverlay from './AnalysisBoxOverlay.jsx';
import VirtualMicrometer from './VirtualMicrometer.jsx';
import DrawModeOverlay from './viewer/DrawModeOverlay.jsx';
import LiveSelectionRect from './viewer/LiveSelectionRect.jsx';
import PersistedSelectionRect from './viewer/PersistedSelectionRect.jsx';
import ViewerControls from './viewer/ViewerControls.jsx';
import ProgressOverlay from './viewer/ProgressOverlay.jsx';
import StatusBar from './viewer/StatusBar.jsx';
import { useViewerStore } from '../stores/useViewerStore.js';
import { useDrawModeManager } from '../hooks/useDrawModeManager.js';
import { useSelectionTracker } from '../hooks/useSelectionTracker.js';
import { useResizeHandler } from '../hooks/useResizeHandler.js';
import { useZoomTracker } from '../hooks/useZoomTracker.js';
import { useOverlayCenterTracking } from '../hooks/useOverlayCenterTracking.js';

/**
 * @param {{ slideId: string|null, slideInfo: object, onBoxSelect: function, selectedBoxId: string|null }}
 */
export default function DeepZoomViewer({
  slideId,
  slideInfo,
  boxes: externalBoxes,
  nuclei: externalNuclei,
  selectedBoxId: externalSelectedBoxId,
  onSelectBox: externalSelectBox,
  onRunInference: externalRunInference,
  onRunInferenceOnArea: externalRunInferenceOnArea,
  onRefreshNuclei: externalRefreshNuclei,
  fetchLoading: externalFetchLoading,
  inferenceLoading: externalInferenceLoading,
  error: externalError,
  progress: externalProgress,
}) {
  // Get state from Zustand store
  const { overlayVisible, boxesVisible, zoomInfo } = useViewerStore();

  // Callback when viewport changes (debounced by useViewer)
  const onViewportChange = useCallback(
    (viewer) => {
      if (externalRefreshNuclei) externalRefreshNuclei(viewer);
    },
    [externalRefreshNuclei],
  );

  const { containerRef, viewer, isReady } = useViewer(
    slideId,
    slideInfo,
    onViewportChange,
  );

  // Track the viewer container center for overlay positioning
  const overlayCenterX = useOverlayCenterTracking(containerRef, viewer);

  // Custom hooks for managing viewer behavior
  useDrawModeManager(viewer, externalInferenceLoading);
  useSelectionTracker(viewer);
  useResizeHandler(viewer, slideInfo);
  useZoomTracker(viewer, slideInfo);

  return (
    <div className="relative flex-1 bg-black overflow-hidden">
      {/* OpenSeadragon container */}
      <div 
        ref={containerRef} 
        className="absolute inset-0"
        style={{ pointerEvents: 'auto' }}
      />

      {/* Draw-mode overlay and banner */}
      <DrawModeOverlay viewer={viewer} slideInfo={slideInfo} />

      {/* Live drag selection rectangle */}
      <LiveSelectionRect viewer={viewer} slideInfo={slideInfo} />

      {/* Persisted selection rectangle (tracks viewport) */}
      <PersistedSelectionRect viewer={viewer} slideInfo={slideInfo} />

      {/* Canvas overlay for nuclei */}
      {isReady && viewer && (
        <NucleusOverlay
          viewer={viewer}
          nuclei={externalNuclei}
          visible={overlayVisible}
        />
      )}

      {/* Canvas overlay for analysis boxes */}
      {isReady && viewer && (
        <AnalysisBoxOverlay
          viewer={viewer}
          boxes={externalBoxes}
          selectedBoxId={externalSelectedBoxId}
          onSelectBox={externalSelectBox}
          visible={boxesVisible}
          slideInfo={slideInfo}
        />
      )}

      {/* Virtual micrometer scale bar */}
      {isReady && viewer && slideInfo && (
        <VirtualMicrometer viewer={viewer} slideInfo={slideInfo} />
      )}

      {/* Controls overlay — viewer button family */}
      <ViewerControls
        viewer={viewer}
        slideId={slideId}
        onRunInference={externalRunInference}
        onRunInferenceOnArea={externalRunInferenceOnArea}
        inferenceLoading={externalInferenceLoading}
      />

      {/* Progress bar overlay — Premium style */}
      <ProgressOverlay progress={externalProgress} overlayCenterX={overlayCenterX} />

      {/* Status bar — Premium minimal */}
      <StatusBar slideInfo={slideInfo} zoomInfo={zoomInfo} error={externalError} />
    </div>
  );
}
