/**
 * App — Root application component.
 *
 * Layout:
 *   ┌─────────────────────────────────────┬──────────┐
 *   │                                     │          │
 *   │         DeepZoomViewer              │ Analysis │
 *   │   (OpenSeadragon + Box Overlay)     │ Panel    │
 *   │                                     │          │
 *   └─────────────────────────────────────┴──────────┘
 *
 * State is lifted here so both the viewer and the panel can
 * access analysis boxes and selected box state.
 */

import { useState, useEffect } from "react";
import DeepZoomViewer from "./components/DeepZoomViewer.jsx";
import StatisticsPanel from "./components/StatisticsPanel.jsx";
import useNuclei from "./hooks/useNuclei.js";
import { fetchSlides, uploadSlide } from "./services/api.js";

export default function App() {
  const [slides, setSlides] = useState([]);
  const [activeSlideId, setActiveSlideId] = useState(null);
  const [activeSlideInfo, setActiveSlideInfo] = useState(null);
  const [uploading, setUploading] = useState(false);

  // Shared analysis state (boxes + nuclei)
  const {
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
  } = useNuclei(activeSlideId, activeSlideInfo);

  // Load slide list on mount
  useEffect(() => {
    fetchSlides()
      .then((loadedSlides) => {
        setSlides(loadedSlides);
        if (loadedSlides.length > 0 && !activeSlideId) {
          setActiveSlideId(loadedSlides[0].id);
        }
      })
      .catch((err) => console.error("Failed to load slides:", err));
  }, []);

  // Update active slide info when selection changes
  useEffect(() => {
    if (activeSlideId) {
      const slide = slides.find((s) => s.id === activeSlideId);
      setActiveSlideInfo(slide || null);
    } else {
      setActiveSlideInfo(null);
    }
  }, [activeSlideId, slides]);

  // Handle file upload
  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setUploading(true);
      const newSlide = await uploadSlide(file);
      setSlides((prev) => [newSlide, ...prev]);
      setActiveSlideId(newSlide.id);
    } catch (err) {
      console.error("Upload failed:", err);
      alert("Failed to upload slide: " + (err.response?.data?.detail || err.message));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="flex h-full flex-col" style={{ background: 'var(--color-obsidian)' }}>
      {/* Header */}
      <header 
        className="relative flex items-center justify-between px-8 backdrop-blur-xl"
        style={{ 
          height: '64px',
          background: 'rgba(10, 10, 10, 0.85)',
          borderBottom: '1px solid var(--border-hairline)',
          boxShadow: '0 1px 0 rgba(255, 255, 255, 0.03)',
        }}
      >
        {/* Brand */}
        <div className="flex items-center gap-4">
          <h1 
            className="text-gradient"
            style={{ 
              fontSize: '20px',
              fontWeight: 700,
              letterSpacing: '-0.03em',
              lineHeight: 1,
            }}
          >
            Slidekick
          </h1>
          <div 
            style={{
              width: '1px',
              height: '16px',
              background: 'var(--border-subtle)',
            }}
          />
          <span 
            style={{
              fontSize: 'var(--text-xs)',
              fontWeight: 500,
              color: 'rgba(255, 255, 255, 0.45)',
              letterSpacing: '-0.01em',
            }}
          >
            WSI Cellular Analysis
          </span>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3">
          {/* Upload button */}
          <label className="btn-primary" style={{ cursor: uploading ? 'not-allowed' : 'pointer', opacity: uploading ? 0.6 : 1 }}>
            {uploading ? (
              <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ 
                  width: '12px', 
                  height: '12px', 
                  border: '2px solid rgba(255,255,255,0.3)',
                  borderTopColor: 'white',
                  borderRadius: '50%',
                  animation: 'spin 0.6s linear infinite'
                }} />
                Uploading...
              </span>
            ) : "Upload Slide"}
            <input
              type="file"
              style={{ display: 'none' }}
              accept=".svs,.ndpi,.mrxs,.tiff,.tif,.vms"
              onChange={handleUpload}
              disabled={uploading}
            />
          </label>
        </div>
      </header>

      {/* Add spin animation */}
      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {activeSlideId && activeSlideInfo ? (
          <>
            <DeepZoomViewer
              slideId={activeSlideId}
              slideInfo={activeSlideInfo}
              boxes={boxes}
              nuclei={nuclei}
              selectedBoxId={selectedBoxId}
              onSelectBox={selectBox}
              onRunInference={runInference}
              onRunInferenceOnArea={runInferenceOnArea}
              onRefreshNuclei={refreshNuclei}
              fetchLoading={fetchLoading}
              inferenceLoading={inferenceLoading}
              error={error}
              progress={progress}
            />
            <StatisticsPanel
              slides={slides}
              activeSlideId={activeSlideId}
              onSelectSlide={setActiveSlideId}
              slideId={activeSlideId}
              slideInfo={activeSlideInfo}
              boxes={boxes}
              selectedBox={selectedBox}
              selectedBoxId={selectedBoxId}
              onSelectBox={selectBox}
              onDeleteBox={removeBox}
            />
          </>
        ) : (
          <>
            <div 
              className="flex flex-1 items-center justify-center"
              style={{ background: 'var(--color-void)' }}
            >
              <div className="text-center animate-fadeIn" style={{ maxWidth: '400px' }}>
                <p 
                  style={{
                    fontSize: 'var(--text-lg)',
                    fontWeight: 600,
                    color: 'rgba(255, 255, 255, 0.9)',
                    marginBottom: 'var(--space-2)',
                    letterSpacing: '-0.02em',
                  }}
                >
                  No slides available
                </p>
                <p 
                  style={{
                    fontSize: 'var(--text-sm)',
                    color: 'rgba(255, 255, 255, 0.4)',
                    letterSpacing: '-0.01em',
                  }}
                >
                  Upload a Whole Slide Image to begin cellular analysis
                </p>
              </div>
            </div>
            <StatisticsPanel
              slides={slides}
              activeSlideId={activeSlideId}
              onSelectSlide={setActiveSlideId}
              slideId={null}
              slideInfo={null}
              boxes={[]}
              selectedBox={null}
              selectedBoxId={null}
              onSelectBox={() => {}}
              onDeleteBox={() => {}}
            />
          </>
        )}
      </div>
    </div>
  );
}
