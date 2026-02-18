/**
 * StatusBar — Bottom status bar displaying slide information and zoom details.
 *
 * Responsibilities:
 * - Shows slide dimensions, MPP, zoom level
 * - Displays selected area information if present
 * - Shows error messages
 */

import { useViewerStore } from '../../stores/useViewerStore';

export default function StatusBar({ slideInfo, zoomInfo, error }) {
  const { selectedArea } = useViewerStore();

  return (
    <div
      className="absolute z-30"
      style={{
        bottom: 0,
        left: 0,
        right: 0,
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-4)',
        background: 'rgba(10, 10, 10, 0.85)',
        backdropFilter: 'blur(20px)',
        padding: '8px var(--space-4)',
        fontSize: 'var(--text-xs)',
        color: 'rgba(255, 255, 255, 0.4)',
        borderTop: '1px solid var(--border-hairline)',
        fontVariantNumeric: 'tabular-nums',
        letterSpacing: '-0.01em',
      }}
    >
      {slideInfo && (
        <>
          <span>
            {slideInfo.width_px.toLocaleString()} × {slideInfo.height_px.toLocaleString()} px
          </span>
          <span>MPP: {slideInfo.mpp.toFixed(4)} μm/px</span>
          {zoomInfo.level !== null && zoomInfo.zoom !== null && (
            <span>
              Level {zoomInfo.level} • ×{zoomInfo.zoom.toFixed(2)}
            </span>
          )}
          <span>
            {(slideInfo.width_px * slideInfo.mpp * 0.001).toFixed(1)} ×{' '}
            {(slideInfo.height_px * slideInfo.mpp * 0.001).toFixed(1)} mm
          </span>
        </>
      )}
      {selectedArea && (
        <span className="text-cyan-400">
          Selection: {selectedArea.width.toLocaleString()} × {selectedArea.height.toLocaleString()}{' '}
          px
        </span>
      )}
      {error && <span className="text-red-400">Error: {error}</span>}
    </div>
  );
}
