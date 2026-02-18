"""
Slide Management Endpoints
===========================
Upload, list, and serve DZI tiles for WSIs via OpenSeadragon.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db
from app.models.nucleus import Slide
from app.schemas.nucleus import ScaleBarResponse, SlideOut
from app.services.slide import SlideService, get_slide_service
from app.spatial.transform import CoordinateTransformer

router = APIRouter(prefix="/slides", tags=["Slides"])
settings = get_settings()

# Allowed WSI file extensions (lowercase, with leading dot).
_ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {".svs", ".ndpi", ".mrxs", ".tiff", ".tif", ".vms", ".scn", ".bif"}
)

# Maximum upload size: 10 GiB.
_MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024 * 1024


# ── Upload a WSI ──────────────────────────────────────────────────
@router.post("/upload", response_model=SlideOut, status_code=201)
async def upload_slide(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a Whole Slide Image.

    Supported formats: .svs, .ndpi, .mrxs, .tiff, .tif, .vms, .scn, .bif
    The file is saved to disk under a random UUID filename and metadata
    is extracted via OpenSlide.

    Security
    --------
    - **Filename sanitization**: The original filename is stripped of all
      path components (``PurePosixPath(...).name``) so directory traversal
      payloads like ``../../etc/passwd`` are neutralised.
    - **UUID storage name**: The file is stored on disk under a new
      ``uuid4`` name, making filename-collision and overwrite attacks
      impossible.
    - **Extension allow-list**: Only known WSI extensions are accepted.
    - **Path canonicalization**: The resolved destination path is
      validated to reside inside the configured ``slides_dir``.
    - **Size check**: Rejects uploads exceeding 10 GiB.
    """
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    # ── 1. Sanitize the original filename ─────────────────────
    # Strip any directory components from the user-supplied name.
    safe_basename = PurePosixPath(file.filename).name  # "../../foo.svs" → "foo.svs"
    if not safe_basename:
        raise HTTPException(400, "Invalid filename")

    # ── 2. Validate extension against allow-list ──────────────
    extension = Path(safe_basename).suffix.lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Unsupported file type '{extension}'. "
            f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )

    # ── 3. Generate a collision-resistant storage name ────────
    storage = Path(settings.slides_dir).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    unique_name = f"{uuid.uuid4()}{extension}"
    dest = (storage / unique_name).resolve()

    # ── 4. Canonicalize and verify path is inside storage root ─
    # Defense against any edge-case where the resolved path escapes
    # the designated slide directory.
    if not str(dest).startswith(str(storage)):
        raise HTTPException(400, "Invalid file path")

    # ── 5. Size check (stream-safe: read size from seek) ──────
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)     # Reset to beginning
    if file_size > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"File too large ({file_size / (1024**3):.1f} GiB). "
            f"Maximum allowed: {_MAX_UPLOAD_BYTES / (1024**3):.0f} GiB.",
        )

    # ── 6. Write to disk ──────────────────────────────────────
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # ── 7. Extract metadata via OpenSlide ─────────────────────
    try:
        svc = SlideService(dest)
        info = svc.slide_info()
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, f"Failed to open WSI: {e}")

    # ── 8. Persist to database ────────────────────────────────
    slide = Slide(
        filename=safe_basename,     # Store the sanitized original name
        filepath=str(dest),         # Store the UUID-based on-disk path
        mpp=info["mpp"],
        width_px=info["width_px"],
        height_px=info["height_px"],
        metadata_=info,
    )
    db.add(slide)
    await db.flush()
    await db.refresh(slide)
    await db.commit()
    return slide


# ── List all slides ───────────────────────────────────────────────
@router.get("/", response_model=list[SlideOut])
async def list_slides(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Slide).order_by(Slide.created_at.desc())
    )
    return result.scalars().all()


# ── Get single slide ─────────────────────────────────────────────
@router.get("/{slide_id}", response_model=SlideOut)
async def get_slide(
    slide_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    slide = await db.get(Slide, slide_id)
    if not slide:
        raise HTTPException(404, "Slide not found")
    return slide


# ── DZI descriptor ────────────────────────────────────────────────
@router.get("/{slide_id}/dzi")
async def get_dzi(
    slide_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return the DZI XML descriptor for OpenSeadragon."""
    slide = await db.get(Slide, slide_id)
    if not slide:
        raise HTTPException(404, "Slide not found")

    svc = get_slide_service(slide.filepath)
    return Response(
        content=svc.get_dzi_xml(),
        media_type="application/xml",
    )


# ── DZI tile ──────────────────────────────────────────────────────
@router.get("/{slide_id}/dzi_files/{level}/{col}_{row}.jpeg")
async def get_dzi_tile(
    slide_id: uuid.UUID,
    level: int,
    col: int,
    row: int,
    db: AsyncSession = Depends(get_db),
):
    """Serve a single Deep Zoom tile for OpenSeadragon."""
    slide = await db.get(Slide, slide_id)
    if not slide:
        raise HTTPException(404, "Slide not found")

    svc = get_slide_service(slide.filepath)
    try:
        # Offload blocking OpenSlide I/O to thread pool to avoid
        # starving the asyncio event loop during tile-heavy panning.
        loop = asyncio.get_event_loop()
        tile_bytes = await loop.run_in_executor(
            None, svc.get_dzi_tile, level, col, row,
        )
    except Exception as e:
        raise HTTPException(404, f"Tile not found: {e}")

    return Response(
        content=tile_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ── Scale bar (for VirtualMicrometer) ────────────────────────────
@router.get("/{slide_id}/scale-bar", response_model=ScaleBarResponse)
async def get_scale_bar(
    slide_id: uuid.UUID,
    target_um: float = 100.0,
    level: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """
    How many pixels correspond to `target_um` μm at the given level?

    Used by the VirtualMicrometer component.
    """
    slide = await db.get(Slide, slide_id)
    if not slide:
        raise HTTPException(404, "Slide not found")

    transformer = CoordinateTransformer(
        mpp=slide.mpp,
        level_0_width=slide.width_px,
        level_0_height=slide.height_px,
    )
    px = transformer.scale_bar_px(target_um, level)

    return ScaleBarResponse(
        target_um=target_um,
        pixels_at_level=px,
        level=level,
        mpp=slide.mpp,
    )


# ── Thumbnail ─────────────────────────────────────────────────────
@router.get("/{slide_id}/thumbnail")
async def get_thumbnail(
    slide_id: uuid.UUID,
    max_size: int = 200,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a thumbnail of the slide.
    
    Returns a JPEG thumbnail with max dimension of `max_size` pixels.
    Thumbnails are cached to disk under ``<slides_dir>/.thumbnails/``
    so subsequent requests are served without touching OpenSlide.
    """
    slide = await db.get(Slide, slide_id)
    if not slide:
        raise HTTPException(404, "Slide not found")

    # ── Check disk cache first ────────────────────────────────
    cache_dir = Path(settings.slides_dir).resolve() / ".thumbnails"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{slide_id}_{max_size}.jpg"

    if cache_path.exists():
        return Response(
            content=cache_path.read_bytes(),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # ── Generate thumbnail ────────────────────────────────────
    svc = get_slide_service(slide.filepath)
    
    try:
        # Get the lowest resolution level for faster thumbnail generation
        level_count = svc.level_count
        thumb_level = level_count - 1  # Lowest resolution level
        
        # Get dimensions at this level
        level_dims = svc.level_dimensions[thumb_level]
        
        # Calculate the downsampling factor
        downsample = max(level_dims[0] / max_size, level_dims[1] / max_size, 1)
        new_width = int(level_dims[0] / downsample)
        new_height = int(level_dims[1] / downsample)
        
        # Offload blocking I/O to thread pool
        loop = asyncio.get_event_loop()
        
        def generate_thumbnail():
            import io
            from PIL import Image
            from app.services.slide import _tls_open
            
            # Use thread-local OpenSlide handle (thread-safe).
            slide_handle = _tls_open(slide.filepath)
            region = slide_handle.read_region(
                (0, 0), thumb_level, level_dims
            ).convert("RGB")
            
            # Resize if needed
            if downsample > 1:
                region = region.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Save to bytes
            buf = io.BytesIO()
            region.save(buf, format="JPEG", quality=85)
            thumb_bytes = buf.getvalue()

            # Persist to disk cache
            cache_path.write_bytes(thumb_bytes)

            return thumb_bytes
        
        thumbnail_bytes = await loop.run_in_executor(None, generate_thumbnail)
        
    except Exception as e:
        raise HTTPException(500, f"Failed to generate thumbnail: {e}")

    return Response(
        content=thumbnail_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
