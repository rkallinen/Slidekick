/**
 * SlidesList — Displays slides in the sidebar with thumbnails
 * 
 * Shows all available slides with small thumbnail previews,
 * allowing users to switch between slides.
 */

import { useState, useEffect } from "react";

/**
 * @param {{
 *   slides: Array,
 *   activeSlideId: string | null,
 *   onSelectSlide: (slideId: string) => void,
 * }}
 */
export default function SlidesList({ slides, activeSlideId, onSelectSlide }) {
  return (
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
        Slides ({slides?.length || 0})
      </h3>

      {(!slides || slides.length === 0) && (
        <p 
          style={{
            fontSize: 'var(--text-xs)',
            color: 'rgba(255, 255, 255, 0.3)',
            lineHeight: 1.5,
          }}
        >
          No slides available. Upload a WSI to begin.
        </p>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', maxHeight: '320px', overflowY: 'auto' }}>
        {slides?.map((slide) => (
          <SlideItem
            key={slide.id}
            slide={slide}
            isActive={slide.id === activeSlideId}
            onSelect={() => onSelectSlide(slide.id)}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * Individual slide item with thumbnail
 */
function SlideItem({ slide, isActive, onSelect }) {
  const [thumbnailUrl, setThumbnailUrl] = useState(null);
  const [thumbnailLoading, setThumbnailLoading] = useState(true);
  const [thumbnailError, setThumbnailError] = useState(false);

  useEffect(() => {
    // Load thumbnail for this slide
    const url = `/api/slides/${slide.id}/thumbnail?max_size=100`;
    
    // Preload the image
    const img = new Image();
    img.onload = () => {
      setThumbnailUrl(url);
      setThumbnailLoading(false);
    };
    img.onerror = () => {
      setThumbnailError(true);
      setThumbnailLoading(false);
    };
    img.src = url;
  }, [slide.id]);

  return (
    <div
      onClick={onSelect}
      className="card-premium"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-3)',
        padding: 'var(--space-3)',
        cursor: 'pointer',
        background: isActive 
          ? 'rgba(0, 113, 227, 0.12)' 
          : 'var(--color-midnight)',
        borderColor: isActive 
          ? 'rgba(0, 113, 227, 0.3)' 
          : 'var(--border-hairline)',
      }}
    >
      {/* Thumbnail */}
      <div 
        style={{
          flexShrink: 0,
          width: '56px',
          height: '56px',
          borderRadius: 'var(--radius-md)',
          background: 'rgba(255, 255, 255, 0.03)',
          overflow: 'hidden',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: '1px solid var(--border-hairline)',
        }}
      >
        {thumbnailLoading && (
          <div style={{ fontSize: 'var(--text-micro)', color: 'rgba(255, 255, 255, 0.2)' }}>
            Loading...
          </div>
        )}
        {thumbnailError && !thumbnailLoading && (
            <div style={{ width: '100%', height: '100%', background: 'rgba(255,255,255,0.02)' }} />
        )}
        {thumbnailUrl && !thumbnailLoading && !thumbnailError && (
          <img
            src={thumbnailUrl}
            alt={slide.filename}
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        )}
      </div>

      {/* Slide info */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div 
          style={{
            fontSize: 'var(--text-sm)',
            fontWeight: 600,
            color: isActive 
              ? 'rgba(0, 113, 227, 1)' 
              : 'rgba(255, 255, 255, 0.85)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            marginBottom: '4px',
          }}
          title={slide.filename}
        >
          {slide.filename}
        </div>
        <div 
          style={{
            fontSize: 'var(--text-micro)',
            color: 'rgba(255, 255, 255, 0.4)',
          }}
        >
          {slide.width_px?.toLocaleString() || '—'} × {slide.height_px?.toLocaleString() || '—'} px
        </div>
      </div>
    </div>
  );
}
