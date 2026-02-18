/**
 * StatisticsPanel — Dashboard for slide selection and region of interest statistics.
 *
 * Displays:
 *   - List of all slides with thumbnails (for switching)
 *   - List of all regions of interest for the slide
 *   - Detailed stats for the selected region (click in viewer)
 *   - Per-cell-type breakdown with colour-coded bars
 *   - Derived clinical metrics (Shannon diversity, inflammatory index, etc.)
 *   - Delete button to remove a region and its nuclei
 */

import { useState, useEffect, useCallback } from "react";
import { fetchAnalysisBoxDetail } from "../services/api.js";
import { CELL_TYPE_COLORS, CELL_TYPE_NAMES } from "../utils/coordinates.js";
import SlidesList from "./SlidesList.jsx";

/**
 * @param {{
 *   slides: Array,
 *   activeSlideId: string | null,
 *   onSelectSlide: (slideId: string) => void,
 *   slideId: string,
 *   slideInfo: object,
 *   boxes: Array,
 *   selectedBox: object | null,
 *   selectedBoxId: string | null,
 *   onSelectBox: (boxId: string) => void,
 *   onDeleteBox: (boxId: string) => void,
 * }}
 */
export default function StatisticsPanel({
  slides,
  activeSlideId,
  onSelectSlide,
  slideId,
  slideInfo,
  boxes,
  selectedBox,
  selectedBoxId,
  onSelectBox,
  onDeleteBox,
}) {
  const [boxDetail, setBoxDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [taskId, setTaskId] = useState(null);
  const [taskProgress, setTaskProgress] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);

  // Load detailed stats when a box is selected
  useEffect(() => {
    if (!selectedBoxId) {
      setBoxDetail(null);
      return;
    }

    let cancelled = false;
    setDetailLoading(true);

    fetchAnalysisBoxDetail(selectedBoxId)
      .then((data) => {
        if (!cancelled) setBoxDetail(data);
      })
      .catch((err) => {
        console.error("Failed to load box detail:", err);
        if (!cancelled) setBoxDetail(null);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });

    return () => { cancelled = true; };
  }, [selectedBoxId]);

  const handleDelete = (boxId) => {
    if (confirmDelete === boxId) {
      onDeleteBox(boxId);
      setConfirmDelete(null);
    } else {
      setConfirmDelete(boxId);
      // Auto-cancel confirmation after 3s
      setTimeout(() => setConfirmDelete(null), 3000);
    }
  };

  return (
    <div 
      className="flex-shrink-0 overflow-y-auto"
      style={{
        width: '360px',
        background: 'var(--color-void)',
        borderLeft: '1px solid var(--border-hairline)',
        padding: 'var(--space-6)',
      }}
    >
      <h2 
        style={{
          fontSize: 'var(--text-xl)',
          fontWeight: 700,
          color: 'rgba(255, 255, 255, 0.95)',
          marginBottom: 'var(--space-6)',
          letterSpacing: '-0.03em',
        }}
      >
        Analysis
      </h2>

      {/* Slides List */}
      <SlidesList
        slides={slides}
        activeSlideId={activeSlideId}
        onSelectSlide={onSelectSlide}
      />

      {/* Divider */}
      <div className="divider" />

      {/* Regions of Interest List */}
      <div style={{ marginBottom: 'var(--space-6)' }}>
        <h3 
          style={{
            fontSize: 'var(--text-sm)',
            fontWeight: 600,
            color: 'rgba(255, 255, 255, 0.7)',
            marginBottom: 'var(--space-3)',
            letterSpacing: '-0.01em',
          }}
        >
          Regions of Interest
        </h3>

        {(!boxes || boxes.length === 0) && (
          <p 
            style={{
              fontSize: 'var(--text-xs)',
              color: 'rgba(255, 255, 255, 0.7)',
              lineHeight: 1.5,
            }}
          >
            No regions yet. Use "Analyze Viewport" in the viewer to create one.
          </p>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', maxHeight: '280px', overflowY: 'auto' }}>
          {boxes?.map((box) => (
            <div
              key={box.id}
              onClick={() => onSelectBox(box.id)}
              className="card-premium"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                cursor: 'pointer',
                padding: 'var(--space-3)',
                background: box.id === selectedBoxId 
                  ? 'rgba(0, 113, 227, 0.12)' 
                  : 'var(--color-midnight)',
                borderColor: box.id === selectedBoxId 
                  ? 'rgba(0, 113, 227, 0.3)' 
                  : 'var(--border-hairline)',
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div 
                  style={{
                    fontSize: 'var(--text-sm)',
                    fontWeight: 600,
                    color: box.id === selectedBoxId 
                      ? 'rgba(0, 113, 227, 1)' 
                      : 'rgba(255, 255, 255, 0.85)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    marginBottom: '4px',
                  }}
                >
                  {box.label}
                </div>
                <div 
                  style={{
                    fontSize: 'var(--text-micro)',
                    color: 'rgba(255, 255, 255, 0.4)',
                  }}
                >
                  {box.area_mm2.toFixed(3)} mm²
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(box.id);
                }}
                style={{
                  flexShrink: 0,
                  marginLeft: 'var(--space-2)',
                  padding: '4px 8px',
                  fontSize: 'var(--text-micro)',
                  fontWeight: 600,
                  borderRadius: 'var(--radius-sm)',
                  border: 'none',
                  cursor: 'pointer',
                  transition: 'all var(--transition-fast)',
                  background: confirmDelete === box.id 
                    ? '#ef4444' 
                    : 'rgba(255, 255, 255, 0.06)',
                  color: confirmDelete === box.id 
                    ? 'white' 
                    : 'rgba(255, 255, 255, 0.5)',
                }}
                onMouseEnter={(e) => {
                  if (confirmDelete !== box.id) {
                    e.currentTarget.style.background = 'rgba(239, 68, 68, 0.2)';
                    e.currentTarget.style.color = '#ef4444';
                  }
                }}
                onMouseLeave={(e) => {
                  if (confirmDelete !== box.id) {
                    e.currentTarget.style.background = 'rgba(255, 255, 255, 0.06)';
                    e.currentTarget.style.color = 'rgba(255, 255, 255, 0.5)';
                  }
                }}
                title={confirmDelete === box.id ? "Click again to confirm" : "Delete this region"}
              >
                {confirmDelete === box.id ? "Confirm?" : "✕"}
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Selected Region Detail */}
      {selectedBoxId && (
        <div style={{ borderTop: '1px solid var(--border-hairline)', paddingTop: 'var(--space-6)' }}>
          <h3 
            style={{
              fontSize: 'var(--text-sm)',
              fontWeight: 600,
              color: 'rgba(255, 255, 255, 0.7)',
              marginBottom: 'var(--space-4)',
              letterSpacing: '-0.01em',
            }}
          >
            Selected Region
          </h3>

          {detailLoading && (
            <p style={{ fontSize: 'var(--text-xs)', color: 'rgba(255, 255, 255, 0.3)' }}>
              Loading statistics...
            </p>
          )}

          {boxDetail && !detailLoading && (() => {
            // Use derived metrics provided by the backend
            const shannonH = boxDetail.shannon_h ?? 0;
            const inflammatoryIndex = boxDetail.inflammatory_index ?? 0;
            const immuneTumourRatio = boxDetail.immune_tumour_ratio;
            const neRatio = boxDetail.ne_epithelial_ratio;
            const viability = boxDetail.viability ?? 0;

            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-3)' }}>
                  <MetricCard
                    label="Total Nuclei"
                    value={boxDetail.total_nuclei.toLocaleString()}
                    color="#818cf8"
                    description="Total detected nuclei in the region."
                  />
                  <MetricCard
                    label="Density"
                    value={`${boxDetail.density_per_mm2.toFixed(0)}`}
                    unit="nuclei/mm²"
                    color="#34d399"
                    description="Nuclei per square millimetre."
                  />

                  <MetricCard
                    label="Area"
                    value={boxDetail.area_mm2.toFixed(3)}
                    unit="mm²"
                    color="#38bdf8"
                    description="Region area in square millimetres."
                  />
                  <MetricCard
                    label="Rn (Neoplastic)"
                    value={boxDetail.neoplastic_ratio.toFixed(3)}
                    color={boxDetail.neoplastic_ratio > 0.5 ? "#fb7185" : "#fbbf24"}
                    description="Fraction of nuclei labelled neoplastic."
                  />
                  <MetricCard
                    label="Shannon Diversity"
                    value={shannonH.toFixed(2)}
                    unit="H'"
                    color="#c084fc"
                    description="Shannon diversity index of cell types."
                  />
                  <MetricCard
                    label="Cell Viability"
                    value={`${(viability * 100).toFixed(1)}`}
                    unit="%"
                    color="#2dd4bf"
                    description="Estimated percent of alive and metabolic cells."
                  />

                  <MetricCard
                    label="Inflammatory Idx"
                    value={inflammatoryIndex.toFixed(3)}
                    color="#60a5fa"
                    description="Measure of inflammatory cell presence."
                  />
                  <MetricCard
                    label="Immune:Tumour"
                    value={immuneTumourRatio === Infinity ? "∞" : (immuneTumourRatio ?? 0).toFixed(2)}
                    color="#f472b6"
                    description="Ratio of immune to tumour cell counts."
                  />

                  <MetricCard
                    label="N:E Ratio"
                    value={neRatio === Infinity ? "∞" : (neRatio ?? 0).toFixed(2)}
                    color="#fb923c"
                    description="Neoplastic to epithelial cell ratio."
                  />
                </div>
                {/* Cell type breakdown */}
                {boxDetail.cell_type_breakdown?.length > 0 && (
                  <div>
                    <h4 
                      style={{
                        fontSize: 'var(--text-xs)',
                        fontWeight: 600,
                        color: 'rgba(255, 255, 255, 0.5)',
                        marginBottom: 'var(--space-3)',
                        letterSpacing: '-0.01em',
                      }}
                    >
                      Cell Type Breakdown
                    </h4>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                      {boxDetail.cell_type_breakdown.map((ct) => (
                        <CellTypeBar key={ct.cell_type} data={ct} total={boxDetail.total_nuclei} />
                      ))}
                    </div>
                  </div>
                )}

                {/* Region metadata */}
                <div 
                  style={{
                    borderTop: '1px solid var(--border-hairline)',
                    paddingTop: 'var(--space-3)',
                    fontSize: 'var(--text-micro)',
                    color: 'rgba(255, 255, 255, 0.25)',
                    lineHeight: 1.6,
                  }}
                >
                  <p>
                    Bounds: ({boxDetail.x_min.toFixed(0)}, {boxDetail.y_min.toFixed(0)}) → (
                    {boxDetail.x_max.toFixed(0)}, {boxDetail.y_max.toFixed(0)})
                  </p>
                  <p>Created: {new Date(boxDetail.created_at).toLocaleString()}</p>
                </div>

                {/* Delete button for selected region */}
                <button
                  onClick={() => handleDelete(selectedBoxId)}
                  style={{
                    width: '100%',
                    padding: 'var(--space-3)',
                    fontSize: 'var(--text-sm)',
                    fontWeight: 600,
                    borderRadius: 'var(--radius-md)',
                    border: 'none',
                    cursor: 'pointer',
                    transition: 'all var(--transition-fast)',
                    background: confirmDelete === selectedBoxId 
                      ? '#ef4444' 
                      : 'rgba(239, 68, 68, 0.15)',
                    color: confirmDelete === selectedBoxId 
                      ? 'white' 
                      : '#ef4444',
                    letterSpacing: '-0.01em',
                  }}
                  onMouseEnter={(e) => {
                    if (confirmDelete !== selectedBoxId) {
                      e.currentTarget.style.background = 'rgba(239, 68, 68, 0.25)';
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (confirmDelete !== selectedBoxId) {
                      e.currentTarget.style.background = 'rgba(239, 68, 68, 0.15)';
                    }
                  }}
                >
                  {confirmDelete === selectedBoxId ? "Click again to confirm deletion" : "Delete This Region"}
                </button>
              </div>
            );
          })()}

          {!boxDetail && !detailLoading && selectedBoxId && (
            <p style={{ fontSize: 'var(--text-xs)', color: 'rgba(255, 255, 255, 0.3)' }}>
              Select a region in the viewer to see its statistics.
            </p>
          )}
        </div>
      )}

      {!selectedBoxId && boxes?.length > 0 && (
        <div style={{ borderTop: '1px solid var(--border-hairline)', paddingTop: 'var(--space-4)' }}>
          <p style={{ fontSize: 'var(--text-xs)', color: 'rgba(255, 255, 255, 0.7)' }}>
            Click on a region of interest in the viewer or list above to see detailed statistics.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────

function MetricCard({ label, value, unit, color = "rgba(255, 255, 255, 0.9)", description = null }) {
  return (
    <div 
      className="card-premium"
      style={{
        padding: 'var(--space-3)',
        background: 'rgba(255, 255, 255, 0.02)',
        borderColor: 'var(--border-hairline)',
      }}
    >
      <div 
        style={{
          fontSize: 'var(--text-micro)',
          color: 'rgba(255, 255, 255, 0.7)',
          marginBottom: '4px',
          letterSpacing: '-0.01em',
        }}
        title={description}
      >
        {label}
      </div>
      <div 
        style={{
          fontSize: 'var(--text-xl)',
          fontWeight: 700,
          color: 'rgba(255, 255, 255, 0.7)',
          lineHeight: 1.2,
          letterSpacing: '-0.02em',
        }}
        title={description}
      >
        {value}
        {unit && (
          <span 
            style={{
              marginLeft: '4px',
              fontSize: 'var(--text-micro)',
              fontWeight: 400,
              color: 'rgba(255, 255, 255, 0.3)',
            }}
          >
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

function CellTypeBar({ data, total }) {
  const fraction = total > 0 ? data.count / total : 0;
  const color = CELL_TYPE_COLORS[data.cell_type] || "#6b7280";

  return (
    <div>
      <div 
        style={{
          marginBottom: 'var(--space-2)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontSize: 'var(--text-xs)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span
            style={{
              display: 'inline-block',
              height: '8px',
              width: '8px',
              borderRadius: '50%',
              backgroundColor: color,
              boxShadow: `0 0 8px ${color}40`,
            }}
          />
          <span style={{ color: 'rgba(255, 255, 255, 0.8)', fontWeight: 500 }}>
            {data.cell_type_name}
          </span>
        </div>
        <span 
          style={{
            fontVariantNumeric: 'tabular-nums',
            color: 'rgba(255, 255, 255, 0.4)',
            fontSize: 'var(--text-micro)',
          }}
        >
          {data.count.toLocaleString()} ({(fraction * 100).toFixed(1)}%)
        </span>
      </div>
      <div 
        style={{
          height: '4px',
          borderRadius: 'var(--radius-full)',
          background: 'rgba(255, 255, 255, 0.05)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${fraction * 100}%`,
            backgroundColor: color,
            transition: 'width var(--transition-base)',
            boxShadow: `0 0 8px ${color}60`,
          }}
        />
      </div>
    </div>
  );
}
