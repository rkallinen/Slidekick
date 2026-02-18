/**
 * useNuclei — Manages analysis boxes and nucleus data.
 *
 * Each viewport inference creates an AnalysisBox on the backend.
 * This hook tracks all boxes for the current slide and their nuclei.
 */

import { useState, useCallback, useRef, useEffect } from "react";
import {
  fetchViewportNuclei,
  inferViewportWithProgress,
  fetchAnalysisBoxes,
  deleteAnalysisBox,
} from "../services/api.js";
import { getViewportBoundsL0, getCurrentLevel } from "../utils/coordinates.js";

/**
 * @param {string|null} slideId
 * @param {{ width_px: number, height_px: number }} slideInfo
 */
export default function useNuclei(slideId, slideInfo) {
  // All analysis boxes for this slide
  const [boxes, setBoxes] = useState([]);
  // Nuclei from all boxes (flat array for rendering)
  const [nuclei, setNuclei] = useState([]);
  // Currently selected box id
  const [selectedBoxId, setSelectedBoxId] = useState(null);
  // Loading states
  const [fetchLoading, setFetchLoading] = useState(false);
  const [inferenceLoading, setInferenceLoading] = useState(false);
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState(null);
  const abortRef = useRef(null);

  /**
   * Load all analysis boxes for the current slide.
   */
  const loadBoxes = useCallback(async () => {
    if (!slideId) return;
    try {
      const data = await fetchAnalysisBoxes(slideId);
      setBoxes(data.boxes || []);
    } catch (err) {
      console.error("Failed to load analysis boxes:", err);
    }
  }, [slideId]);

  // Reload boxes when slide changes
  useEffect(() => {
    setBoxes([]);
    setNuclei([]);
    setSelectedBoxId(null);
    loadBoxes();
  }, [loadBoxes]);

  /**
   * Fetch pre-computed nuclei from PostGIS for the current viewport.
   */
  const refreshNuclei = useCallback(
    async (viewer) => {
      if (!slideId || !slideInfo || !viewer?.viewport) return;

      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        setFetchLoading(true);
        setError(null);

        const bounds = getViewportBoundsL0(
          viewer,
          slideInfo.width_px,
          slideInfo.height_px,
        );
        const level = getCurrentLevel(viewer, slideInfo.width_px);

        const data = await fetchViewportNuclei(slideId, bounds, level);
        setNuclei(data.nuclei || []);
      } catch (err) {
        if (err.name !== "AbortError" && err.name !== "CanceledError") {
          console.error("Failed to fetch nuclei:", err);
          setError(err.message);
        }
      } finally {
        setFetchLoading(false);
      }
    },
    [slideId, slideInfo],
  );

  /**
   * Internal helper — run inference on explicit L0 bounds.
   */
  const _runInferenceOnBounds = useCallback(
    async (bounds, level) => {
      if (!slideId) return;

      try {
        setInferenceLoading(true);
        setError(null);
        setProgress({ current: 0, total: 1, percentage: 0, message: "Preparing..." });

        const data = await inferViewportWithProgress(
          slideId,
          bounds,
          level,
          (progressData) => {
            setProgress(progressData);
          }
        );

        // Add the new box to state
        if (data.box) {
          setBoxes((prev) => [data.box, ...prev]);
          setSelectedBoxId(data.box.id);
        }

        // Merge new nuclei into current set
        setNuclei((prev) => [...prev, ...(data.nuclei || [])]);
        setProgress(null);
      } catch (err) {
        console.error("Inference failed:", err);
        setError(err.message);
        setProgress(null);
      } finally {
        setInferenceLoading(false);
      }
    },
    [slideId],
  );

  /**
  * Run real-time HoVerNet inference on the current viewport.
   * Creates a new AnalysisBox on the backend.
   */
  const runInference = useCallback(
    async (viewer) => {
      if (!slideId || !slideInfo || !viewer?.viewport) return;

      const bounds = getViewportBoundsL0(
        viewer,
        slideInfo.width_px,
        slideInfo.height_px,
      );
      const level = getCurrentLevel(viewer, slideInfo.width_px);

      await _runInferenceOnBounds(bounds, level);
    },
    [slideId, slideInfo, _runInferenceOnBounds],
  );

  /**
   * Run inference on a user-selected area (L0 pixel bounds).
   */
  const runInferenceOnArea = useCallback(
    async (viewer, areaBounds) => {
      if (!slideId || !slideInfo || !viewer?.viewport) return;

      const level = getCurrentLevel(viewer, slideInfo.width_px);
      await _runInferenceOnBounds(areaBounds, level);
    },
    [slideId, slideInfo, _runInferenceOnBounds],
  );

  /**
   * Delete an analysis box and refresh the view.
   */
  const removeBox = useCallback(
    async (boxId, viewer) => {
      try {
        await deleteAnalysisBox(boxId);
        setBoxes((prev) => prev.filter((b) => b.id !== boxId));
        if (selectedBoxId === boxId) {
          setSelectedBoxId(null);
        }
        // Clear nuclei so the deleted box's dots disappear immediately.
        // The viewer's debounced viewport handler will refetch from PostGIS.
        setNuclei([]);
      } catch (err) {
        console.error("Failed to delete analysis box:", err);
        setError(err.message);
      }
    },
    [selectedBoxId],
  );

  /**
   * Select a box — used when clicking a box overlay.
   */
  const selectBox = useCallback((boxId) => {
    setSelectedBoxId((prev) => (prev === boxId ? null : boxId));
  }, []);

  // Get the currently selected box object
  const selectedBox = boxes.find((b) => b.id === selectedBoxId) || null;

  return {
    boxes,
    nuclei,
    selectedBox,
    selectedBoxId,
    selectBox,
    removeBox,
    fetchLoading,
    inferenceLoading,
    error,
    progress,
    refreshNuclei,
    runInference,
    runInferenceOnArea,
    loadBoxes,
  };
}
