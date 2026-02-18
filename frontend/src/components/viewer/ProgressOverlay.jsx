/**
 * ProgressOverlay — Premium progress indicator for inference operations.
 *
 * Responsibilities:
 * - Displays a centered, animated progress bar
 * - Shows current percentage, batch information
 * - Auto-positioned relative to viewer center
 */

export default function ProgressOverlay({ progress, overlayCenterX }) {
  if (!progress) return null;

  return (
    <div
      className="absolute z-50 pointer-events-none"
      style={{
        top: '28px',
        left: overlayCenterX ? `${overlayCenterX}px` : '50%',
        transform: 'translateX(-50%)',
        width: '440px',
        maxWidth: '90vw',
      }}
    >
      <div
        className="card-premium animate-scaleIn"
        style={{
          padding: 'var(--space-6)',
          borderRadius: 'var(--radius-xl)',
          boxShadow: 'var(--shadow-xl)',
          pointerEvents: 'none',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 'var(--space-4)',
          }}
        >
          <h3
            style={{
              fontSize: 'var(--text-lg)',
              fontWeight: 700,
              color: 'rgba(255, 255, 255, 0.95)',
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
              letterSpacing: '-0.02em',
            }}
          >
            <svg
              style={{
                width: '20px',
                height: '20px',
                animation: 'spin 0.8s linear infinite',
                color: '#10b981',
              }}
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                style={{ opacity: 0.25 }}
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              ></circle>
              <path
                style={{ opacity: 0.75 }}
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              ></path>
            </svg>
            Analyzing…
          </h3>
          <span
            style={{
              fontSize: '28px',
              fontWeight: 700,
              color: '#10b981',
              fontVariantNumeric: 'tabular-nums',
              letterSpacing: '-0.03em',
            }}
          >
            {progress.percentage}%
          </span>
        </div>

        <div
          style={{
            position: 'relative',
            height: '8px',
            background: 'rgba(255, 255, 255, 0.05)',
            borderRadius: 'var(--radius-full)',
            overflow: 'hidden',
            marginBottom: 'var(--space-3)',
          }}
        >
          {/* Filled portion */}
          <div
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              bottom: 0,
              background: 'linear-gradient(90deg, #10b981 0%, #34d399 100%)',
              width: `${progress.percentage}%`,
              transition: 'width 300ms cubic-bezier(0.4, 0, 0.2, 1)',
              borderRadius: 'var(--radius-full)',
              boxShadow: '0 0 20px rgba(16, 185, 129, 0.4)',
            }}
          />

          {/* Global shimmer overlay */}
          <div
            className="animate-shimmer-overlay"
            aria-hidden="true"
            style={{ position: 'absolute', left: 0, right: 0, top: 0, bottom: 0 }}
          />
        </div>

        <p
          style={{
            fontSize: 'var(--text-sm)',
            color: 'rgba(255, 255, 255, 0.5)',
            letterSpacing: '-0.01em',
          }}
        >
          {progress.message ||
            `Processing batch ${progress.current} of ${progress.total}...`}
        </p>
      </div>
    </div>
  );
}
