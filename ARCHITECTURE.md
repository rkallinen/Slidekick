# Architecture

This document provides a deep technical analysis of Slidekick's system design, data flow, component relationships, and identified areas for improvement.

---

## Table of Contents

- [High-Level Architecture](#high-level-architecture)
- [System Design Patterns](#system-design-patterns)
- [Component Architecture](#component-architecture)
  - [Backend](#backend)
  - [Frontend](#frontend)
- [Data Flow](#data-flow)
  - [Slide Upload Flow](#slide-upload-flow)
  - [Viewport Inference Flow](#viewport-inference-flow)
  - [Nuclei Fetch Flow](#nuclei-fetch-flow)
- [Database Design](#database-design)
- [Coordinate System](#coordinate-system)
- [Thread Safety Model](#thread-safety-model)
- [Security Architecture](#security-architecture)
- [Technology Rationale](#technology-rationale)
- [Integration Points](#integration-points)

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ BROWSER (localhost:5173)                                                     │
│                                                                              │
│  ┌────────────────┐  ┌──────────────────┐  ┌──────────────────┐              │
│  │  React 19 SPA  │  │  OpenSeadragon   │  │  Canvas2D        │              │
│  │  (Components)  │──│  Viewer          │──│  Overlays        │              │
│  └────────────────┘  └──────────────────┘  └──────────────────┘              │
│          │                    │                                              │
│          └────────────────────┴────────────────┐                             │
│                                                │                             │
│                                    ┌───────────▼──────────┐                  │
│                                    │  Zustand Store       │                  │
│                                    │  (Global State)      │                  │
│                                    └──────────────────────┘                  │
└───────────────────────────────────────────│──────────────────────────────────┘
                                            │
                                            ▼ HTTP/SSE
┌──────────────────────────────────────────────────────────────────────────────┐
│ VITE DEV SERVER (:5173)                                                      │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  /api/* Proxy ──────────────► http://localhost:8000                    │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────│──────────────────────────────────┘
                                            │
                                            ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ FASTAPI BACKEND (:8000)                                                      │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │  Middleware Stack                                                   │     │
│  │  • LocalhostOnlyMiddleware                                          │     │
│  │  • TrustedHostMiddleware                                            │     │
│  │  • CORSMiddleware                                                   │     │
│  └────────────────────────────┬────────────────────────────────────────┘     │
│                               │                                              │
│                               ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │  API Routers                                                        │     │
│  │  • /slides      (upload, list, DZI descriptor, DZI tiles)           │     │
│  │  • /inference   (viewport-stream via SSE)                           │     │
│  │  • /roi         (stats, nuclei fetch)                               │     │
│  │  • /boxes       (list, detail, delete)                              │     │
│  └────────────────────────────┬────────────────────────────────────────┘     │
│                               │                                              │
│                               ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │  Service Layer                                                      │     │
│  │  • SlideService (Thread-local OpenSlide handles)                    │     │
│  │  • HoVerNetEngine (Model loading, batch inference)                  │     │
│  │  • SpatialQueryService (PostGIS ST_Contains queries)                │     │
│  │  • NucleiStreamer (Zero-copy generator for bulk insert)             │     │
│  └────┬──────────────────────────────┬─────────────────────────────────┘     │
│       │                              │                                       │
│       │  ┌───────────────────────────┘                                       │
│       │  │                                                                   │
│       │  ▼                                                                   │
│       │  ThreadPoolExecutor (max_workers=4)                                  │
│       │  • Tile serving (parallel OpenSlide reads)                           │
│       │  • HoVerNet inference (CPU/GPU worker)                               │
│       │                                                                      │
│       │  ┌───────────────────────────────────┐                               │
│       │  │  HoVerNet (TIAToolbox)            │                               │
│       │  │  └──► PyTorch Runtime             │                               │
│       │  └───────────────────────────────────┘                               │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │  Storage                                                            │     │
│  │  • PostgreSQL 16 + PostGIS 3.4 (asyncpg via SQLAlchemy)             │     │
│  │  • Filesystem (slides/*.svs)                                        │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## System Design Patterns

### Architecture Style: Client-Server

Slidekick is a single-process backend and a single-page-application frontend.

## Component Architecture

### Backend

**Component Flow:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ROUTERS (HTTP Layer)                                                        │
│                                                                             │
│  slides.py              inference.py          roi.py            boxes.py    │
│  /api/slides/*          /api/inference/*      /api/roi/*        /api/boxes/*│
│      │                       │                    │                 │       │
│      └───────┬───────────────┴────────────────────┴─────────────────┘       │
└──────────────┼──────────────────────────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ SERVICES (Business Logic)                                                  │
│                                                                            │
│  ┌────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐    │
│  │  SlideService  │  │  HoVerNetEngine  │  │  SpatialQueryService     │    │
│  │                │  │                  │  │                          │    │
│  │  • slide_info()│  │  • infer_tile()  │  │  • get_nuclei_in_        │    │
│  │  • read_region │  │  • postproc()    │  │    viewport()            │    │
│  │  • get_tile()  │  │  • morphometrics │  │  • get_roi_stats()       │    │
│  └────────┬───────┘  └─────────┬────────┘  └───────────┬──────────────┘    │
│           │                    │                       │                   │
│           │          ┌─────────▼──────────┐            │                   │
│           │          │  NucleiStreamer    │            │                   │
│           │          │  (Generator)       │            │                   │
│           │          └─────────┬──────────┘            │                   │
│           │                    │                       │                   │
│           │          ┌─────────▼──────────┐            │                   │
│           │          │  bulk_insert_      │            │                   │
│           │          │  nuclei_async()    │            │                   │
│           │          └─────────┬──────────┘            │                   │
└───────────┼────────────────────┼───────────────────────┼───────────────────┘
            │                    │                       │
            ▼                    ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ MODELS (ORM) + SPATIAL                                                      │
│                                                                             │
│  Slide                AnalysisBox              Nucleus                      │
│  • id (UUID)          • id (UUID)              • id (BIGINT)                │
│  • filepath           • slide_id (FK)          • slide_id (FK)              │
│  • mpp                • geom (POLYGON)         • analysis_box_id (FK)       │
│  • width_px           • total_nuclei           • geom (POINT)               │
│  • height_px          • density_per_mm2        • cell_type                  │
│  • metadata_          • neoplastic_ratio       • probability                │
│                       • cell_type_counts       • contour (POLYGON)          │
│                                                                             │
│  CoordinateTransformer                         schema.sql (PostGIS)         │
│  • bounds_from_level0_rect()                   • GIST indexes               │
│  • physical_to_pixels()                        • ST_Contains()              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Router Responsibilities

| Router | Prefix | Responsibility |
|---|---|---|
| `slides.py` | `/api/slides` | Upload, list, single slide, DZI descriptor, DZI tiles, scale bar, thumbnails |
| `inference.py` | `/api/inference` | Viewport inference with SSE progress streaming |
| `roi.py` | `/api/roi` | Spatial ROI statistics, viewport nuclei fetch (PostGIS) |
| `boxes.py` | `/api/boxes` | Analysis box CRUD (list, detail, delete) |

#### Service Layer

| Service | Responsibility |
|---|---|
| `SlideService` | Thread-safe OpenSlide access, metadata extraction, DZI tile generation, region reading |
| `HoVerNetEngine` | Model loading (TIAToolbox), patch-based inference, post-processing, morphometrics |
| `NucleiStreamer` | Zero-copy generator transforming inference results into bulk-insert tuples |
| `bulk_insert_nuclei_async` | Parameterized `asyncpg.executemany` for bulk writes (zero SQL interpolation). Does not commit; caller owns the transaction boundary. |
| `SpatialQueryService` | PostGIS ST_Contains queries with GIST index for viewport and ROI lookups |
| `CoordinateTransformer` | Pixel-to-physical unit conversion, viewport bounds computation, scale bar math |

### Frontend

**Component Hierarchy:**

```
App.jsx
  │
  ├─ Header
  │   ├─ Brand ("Slidekick")
  │   └─ Upload Button (via handleUpload)
  │
  ├─ useNuclei(activeSlideId, activeSlideInfo)
  │   │
  │   └─ State Management:
  │       • boxes (all AnalysisBox[] for slide)
  │       • nuclei (flat array for rendering)
  │       • selectedBoxId
  │       • progress (SSE updates)
  │       • refreshNuclei(viewer) ────► POST /api/roi/nuclei
  │       • runInference(viewer) ────► POST /api/inference/viewport-stream (SSE)
  │       • runInferenceOnArea(viewer, bounds) ────► POST /api/inference/viewport-stream (SSE)
  │       • removeBox(boxId) ────► DELETE /api/boxes/{boxId}
  │
  ├─ DeepZoomViewer (passes nuclei + boxes as props)
  │   │
  │   ├─ useViewer()
  │   │   └─ Initializes OpenSeadragon instance
  │   │       • Loads DZI descriptor from /api/slides/{id}/dzi
  │   │       • Fetches tiles from /api/slides/{id}/dzi_files/{level}/{col}_{row}.jpeg
  │   │
  │   ├─ NucleusOverlay (Canvas2D)
  │   │   └─ Renders nuclei as colored circles
  │   │       • useEffect on viewer changes
  │   │       • requestAnimationFrame loop
  │   │
  │   ├─ AnalysisBoxOverlay (Canvas2D)
  │   │   └─ Renders box outlines + labels
  │   │       • Click hit-testing → selectBox(id)
  │   │
  │   ├─ VirtualMicrometer
  │   │   └─ Auto-scaling distance bar (uses MPP)
  │   │
  │   ├─ ViewerControls
  │   │   ├─ "Analyze View" button → runInference(viewer)
  │   │   ├─ "Analyze Area" button → enters draw mode
  │   │   └─ Overlay toggle buttons
  │   │
  │   ├─ DrawModeOverlay
  │   │   └─ Mouse capture for area selection
  │   │       • useDrawModeManager() (Zustand draw state)
  │   │
  │   ├─ LiveSelectionRect
  │   │   └─ Real-time drag feedback (shows mm dimensions)
  │   │
  │   ├─ PersistedSelectionRect
  │   │   └─ Confirmed selection with resize handles
  │   │       • useSelectionTracker() (Zustand selected area)
  │   │
  │   ├─ ProgressOverlay
  │   │   └─ SSE-driven progress bar during inference
  │   │
  │   └─ StatusBar
  │       └─ Slide info, zoom level, MPP, selection dimensions
  │
  └─ StatisticsPanel (Sidebar)
      │
      ├─ SlidesList
      │   └─ Lazy-loaded thumbnails from /api/slides/{id}/thumbnail/{size}
      │
      └─ Box Statistics Display
          • Per-box metrics (density, Rn, cell counts)
          • Delete button → removeBox(boxId)
```

**State Flow:**

```
useViewerStore (Zustand)        Local State (App.jsx)       useNuclei Hook
────────────────────────        ─────────────────────       ──────────────
• overlaysVisible               • slides[]                  • boxes[]
• drawMode                      • activeSlideId             • nuclei[]
• dragState                     • activeSlideInfo           • selectedBoxId
• selectedArea                  • uploading                 • progress
• zoomInfo                                                  • inferenceLoading
                                                            • fetchLoading
```

#### Component Responsibilities

| Component | Role |
|---|---|
| `App.jsx` | Root layout (header + viewer + panel), slide state, upload handling |
| `DeepZoomViewer` | OpenSeadragon container, composes all overlay and control sub-components |
| `NucleusOverlay` | Canvas2D layer rendering nucleus centroids as colored circles |
| `AnalysisBoxOverlay` | Canvas2D layer rendering box outlines with labels and click hit-testing |
| `VirtualMicrometer` | Auto-scaling physical distance reference bar |
| `StatisticsPanel` | Sidebar displaying slide list, region list, and detailed statistics with clinical metrics |
| `SlidesList` | Slide list with lazy-loaded thumbnails |
| `ViewerControls` | "Analyze View", "Analyze Area", overlay toggle buttons |
| `DrawModeOverlay` | Mouse capture layer for area selection |
| `LiveSelectionRect` | Real-time drag feedback rectangle with mm dimensions |
| `PersistedSelectionRect` | Confirmed selection with resize handles |
| `ProgressOverlay` | Inference progress bar with SSE-driven updates |
| `StatusBar` | Bottom bar showing slide dimensions, MPP, zoom level, selection info |

#### State Management Strategy

**Local state** (via `useState`) is used for component-specific concerns: slide list, active slide, upload status, selected box detail, and loading states.

**Zustand** (`useViewerStore`) holds cross-component state that needs to be shared without prop threading: overlay visibility, draw mode, drag state, selected area, and zoom information.

**No React Context** is used. The `useNuclei` hook manages the analysis box and nuclei lifecycle and passes results down as props from `App.jsx`.

---

## Data Flow

### Slide Upload Flow

```
USER ACTION                    FRONTEND                     BACKEND                      STORAGE
────────────                   ────────────                 ───────────                  ────────

1. Select WSI file
   (via <input type="file">)
                        │
                        ├──► handleUpload(file)
                        │
                        │    setUploading(true)
                        │
                        ├──► uploadSlide(file)
                        │    POST /api/slides/upload
                        │    (multipart/form-data)
                        │                            │
                        │                            ├──► upload_slide()
                        │                            │    
                        │                            │    1. Sanitize filename
                        │                            │       PurePosixPath(filename).name
                        │                            │       "../../evil.svs" → "evil.svs"
                        │                            │
                        │                            │    2. Validate extension
                        │                            │       .svs, .ndpi, .mrxs, etc.
                        │                            │
                        │                            │    3. Generate UUID name
                        │                            │       uuid4() + extension
                        │                            │
                        │                            │    4. Size check
                        │                            │       file.file.seek(0, 2)
                        │                            │       file_size <= 10 GiB
                        │                            │                            
                        │                            │    5. Write to disk        
                        │                            │       shutil.copyfileobj() ──► slides/{uuid}.svs
                        │                            │
                        │                            │    6. Extract metadata
                        │                            │       SlideService(filepath)
                        │                            │       svc.slide_info()
                        │                            │       • OpenSlide.dimensions
                        │                            │       • properties["openslide.mpp-x"]
                        │                            │       • vendor, magnification
                        │                            │
                        │                            │    7. Create Slide record
                        │                            │       Slide(filename, filepath, mpp, ...)
                        │                            │       db.add(slide)
                        │                            │       db.flush()
                        │                            │       db.commit()        ──► PostgreSQL
                        │                            │                               INSERT INTO slides
                        │                            │
                        │    ◄───── 201 Created ─────┤
                        │          SlideOut JSON
                        │          { id, filename, mpp, width_px, ... }
                        │
                        ├──► setSlides([newSlide, ...prev])
                        │    setActiveSlideId(newSlide.id)
                        │    setUploading(false)
                        │
                        ▼
                   Slide appears in list
                   Viewer loads DZI

VALIDATION CHECKS:
- Filename sanitization (directory traversal prevention)
- Extension allow-list (arbitrary file upload prevention)
- Path canonicalization (path escape prevention)
- Size limit (DoS prevention)
- OpenSlide validation (corrupt file detection)
```

### Viewport Inference Flow

This is the core workflow demonstrating SSE streaming for real-time progress updates.

```
USER ACTION             FRONTEND                  BACKEND                        ML ENGINE                    DATABASE
───────────             ────────                  ───────                        ─────────                    ────────

1. Click "Analyze View"
                   │
                   ├──► runInference(viewer)
                   │
                   │    Compute L0 bounds:
                   │    • Get OSD viewport bounds
                   │    • Convert to level 0 pixels
                   │    • getViewportBoundsL0()
                   │    → { x, y, width, height }
                   │
                   │    setInferenceLoading(true)
                   │    setProgress({ current: 0, total: 1, ... })
                   │
                   ├──► inferViewportWithProgress(slideId, bounds, level, onProgress)
                   │    POST /api/inference/viewport-stream
                   │    Accept: text/event-stream
                   │                          │
                   │                          ├──► infer_viewport_stream()
                   │                          │    EventSourceResponse(event_generator())
                   │                          │
                   │                          │    async def event_generator():
                   │                          │
                   │                          │    1. Fetch slide metadata
                   │                          │       slide = db.get(Slide, slide_id)
                   │                          │       CoordinateTransformer(mpp, width, height)
                   │                          │
                   │                          │    2. Validate bounds
                   │                          │       bounds_from_level0_rect(x, y, w, h)
                   │                          │
                   │                          │    3. Read WSI region
                   │                          │       slide_svc = get_slide_service(filepath)
                   │                          │       tile_rgb = slide_svc.read_region_l0(x, y, w, h)
                   │                          │       → NumPy array (H, W, 3) uint8
                   │                          │
                   │                          │    4. Create ProgressTracker
                   │                          │       progress_tracker = ProgressTracker()
                   │                          │       def progress_callback(current, total, message):
                   │                          │           progress_tracker.update(...)
                   │                          │
                   │                          │    5. Start inference in thread pool
                   │                          │       engine = get_inference_engine()
                   │                          │       inference_task = loop.run_in_executor(
                   │                          │           None,
                   │                          │           lambda: engine.infer_tile(
                   │                          │               tile_rgb, offset_x, offset_y, mpp,
                   │                          │               progress_callback=progress_callback
                   │                          │           )
                   │                          │       )
                   │                          │                              │
                   │                          │                              ├──► HoVerNetEngine.infer_tile()
                   │                          │                              │
                   │                          │    ┌─── INFERENCE LOOP ──────────────────────────────────────┐
                   │                          │    │                                                         │
                   │                          │    │   6. Pad tile to patch size                             │
                   │                          │    │      ioconfig.patch_input_shape = (256, 256, 3)         │
                   │                          │    │      _pad_to_patch_size(tile_rgb)                       │
                   │                          │    │                                                         │
                   │                          │    │   7. Batch inference loop                               │
                   │                          │    │      For each 256×256 patch:                            │
                   │                          │    │        progress_callback(current_patch, total_patches)  │
                   │                          │    │        tensor = torch.from_numpy(patch)                 │
                   │                          │    │        model.infer_batch(tensor, device)                │
                   │                          │    │        → (np_map, hv_map, tp_map)                       │
                   │                          │    │                                                         │
                   │                          │    │   8. Post-processing per patch                          │
                   │                          │    │      model.postproc([np_map, hv_map, tp_map])           │
                   │                          │    │      → (inst_map, inst_dict)                            │
                   │                          │    │      inst_dict = {                                      │
                   │                          │    │        1: {bbox, centroid, contour, type, type_prob},   │
                   │                          │    │        2: {...},                                        │
                   │                          │    │        ...                                              │
                   │                          │    │      }                                                  │
                   │                          │    │                                                         │
                   │                          │    └─────────────────────────────────────────────────────────┘
                   │                          │                              │
                   │                          │    ┌─── PROGRESS STREAMING (parallel) ───────────────────────┐
                   │                          │    │                                                         │
                   │                          │    │   while not inference_task.done():                      │
                   │                          │    │       await asyncio.sleep(0.3)                          │
                   │                          │    │       progress = progress_tracker.get_progress()        │
                   │                          │    │                                                         │
                   │    ◄──── SSE event ──────┤    │       yield {                                           │
                   │    data: {               │    │           "event": "progress",                          │
                   │      type: "progress",   │    │           "data": json.dumps({                          │
                   │      current: N,         │    │               "type": "progress",                       │
                   │      total: M,           │    │               "current": N,                             │
                   │      percentage: X,      │    │               "total": M,                               │
                   │      message: "..."      │    │               "percentage": X,                          │
                   │    }                     │    │               "message": "Processing patch N/M"         │
                   │                          │    │           })                                            │
                   │    setProgress(data)     │    │       }                                                 │
                   │                          │    │                                                         │
                   │                          │    └─────────────────────────────────────────────────────────┘
                   │                          │
                   │                          │    9. Get inference result
                   │                          │       result = await inference_task
                   │                          │       → InferenceResult(nuclei=[...], tile_x, tile_y, ...)
                   │                          │
                   │                          │    10. Compute box statistics
                   │                          │        _compute_box_stats(result.nuclei, bounds, mpp)
                   │                          │        → { total_nuclei, area_mm2, density_per_mm2,
                   │                          │            neoplastic_ratio, cell_type_counts }
                   │                          │
                   │                          │    11. Assign auto-incrementing label
                   │                          │        label = await _assign_analysis_label(db, slide_id)
                   │                          │        → "Analysis 1", "Analysis 2", etc.
                   │                          │
                   │                          │    12. Create AnalysisBox record
                   │                          │        box_geom_wkt = f"POLYGON(({x_min} {y_min}, ...))"
                   │                          │        analysis_box = AnalysisBox(
                   │                          │            slide_id, label, x_min, y_min, x_max, y_max,
                   │                          │            geom=box_geom_wkt, **stats
                   │                          │        )
                   │                          │        db.add(analysis_box)
                   │                          │        db.flush()           ──────────────────────────────► INSERT INTO                        
                   │                          │        box_id = analysis_box.id                               analysis_boxes              
                   │                          │
                   │                          │    13. Bulk insert nuclei
                   │                          │        streamer = NucleiStreamer(slide_id, mpp, box_id)
                   │                          │        rows_gen = streamer.from_viewport_result(nuclei)
                   │                          │        
                   │                          │        ┌─ Generator (zero-copy) ─────────────────────┐
                   │                          │        │ for nuc in result.nuclei:                   │
                   │                          │        │     contour_wkt = _contour_to_wkt(contour)  │
                   │                          │        │     yield (slide_id, box_id, cx, cy,        │
                   │                          │        │            contour_wkt, cell_type, ...)     │
                   │                          │        └─────────────────────────────────────────────┘
                   │                          │
                   │                          │        bulk_insert_nuclei_async(db, rows_gen, page_size=500)
                   │                          │        
                   │                          │        ┌─ Parameterized INSERT ──────────────────────┐
                   │                          │        │ INSERT INTO nuclei                          │
                   │                          │        │   (slide_id, analysis_box_id, geom, ...)    │
                   │                          │        │ VALUES                                      │
                   │                          │        │   ($1::uuid, $2::uuid,                      │
                   │                          │        │    ST_GeomFromText('POINT(' ||              │
                   │                          │        │        $3 || ' ' || $4 || ')', 0),          │
                   │                          │        │    ..., $10)                                │
                   │                          │        │                                             │
                   │                          │        │ asyncpg_conn.executemany(SQL, buffer)       │
                   │                          │        └─────────────────────────────────────────────┘
                   │                          │                                  ──────────────────────────► INSERT INTO                        
                   │                          │                                                               nuclei (bulk)                     
                   │                          │                                                               (500 rows/batch)                
                   │                          │    14. Commit transaction
                   │                          │        db.commit()           ──────────────────────────────► COMMIT
                   │                          │
                   │                          │    15. Build response
                   │                          │        nuclei_out = [{ id, x, y, cell_type, ... }, ...]
                   │                          │        box_out = AnalysisBoxOut.model_validate(box)
                   │                          │
                   │    ◄──── SSE event ──────┤        yield {
                   │    data: {               │            "event": "complete",
                   │      type: "complete",   │            "data": json.dumps({
                   │      box: {...},         │                "type": "complete",
                   │      nuclei: [...],      │                "box": box_out,
                   │      count: N            │                "nuclei": nuclei_out,
                   │    }                     │                "count": len(nuclei_out)
                   │                          │            })
                   │                          │        }
                   │                          │
                   │    setBoxes([box, ...prev])
                   │    setNuclei([...prev, ...nuclei])
                   │    setSelectedBoxId(box.id)
                   │    setProgress(null)
                   │    setInferenceLoading(false)
                   │
                   ▼
              Box + nuclei rendered
              on canvas overlays

PERFORMANCE CHARACTERISTICS:
• SSE streaming: real-time progress updates (300ms interval)
• Zero-copy generator: O(1) memory for nuclei streaming
• Bulk insert: 500 rows/batch via asyncpg.executemany
• Thread pool inference: CPU/GPU worker doesn't block asyncio event loop
• Thread-safe progress: ProgressTracker uses threading.Lock
```

### Nuclei Fetch Flow

When the user pans or zooms the viewer, pre-computed nuclei are re-fetched from PostGIS (no inference).

```
USER ACTION               FRONTEND                    BACKEND                      DATABASE
───────────               ────────                    ───────                      ────────

1. Pan / Zoom viewer
   (OpenSeadragon event)
                     │
                     ├──► OpenSeadragon events:
                     │    • 'animation-finish'
                     │    • 'zoom'
                     │    • 'pan'
                     │
                     ├──► useNuclei.refreshNuclei(viewer)
                     │    [debounced 150ms via useEffect]
                     │
                     │    1. Compute viewport bounds (L0)
                     │       const bounds = getViewportBoundsL0(
                     │           viewer,
                     │           slideInfo.width_px,
                     │           slideInfo.height_px
                     │       )
                     │       → { x, y, width, height }
                     │
                     │    2. Get current zoom level
                     │       const level = getCurrentLevel(viewer, width_px)
                     │
                     │    3. Abort any in-flight request
                     │       if (abortRef.current) {
                     │           abortRef.current.abort()
                     │       }
                     │       abortRef.current = new AbortController()
                     │
                     │    setFetchLoading(true)
                     │
                     ├──► fetchViewportNuclei(slideId, bounds, level)
                     │    POST /api/roi/nuclei
                     │    {
                     │        slide_id: "...",
                     │        x: 1024,
                     │        y: 2048,
                     │        width: 4096,
                     │        height: 3072
                     │    }
                     │                            │
                     │                            ├──► viewport_nuclei(req)
                     │                            │
                     │                            │    1. Fetch slide metadata
                     │                            │       slide = db.get(Slide, slide_id)
                     │                            │
                     │                            │    2. Build coordinate transformer
                     │                            │       transformer = CoordinateTransformer(
                     │                            │           mpp=slide.mpp,
                     │                            │           level_0_width=slide.width_px,
                     │                            │           level_0_height=slide.height_px
                     │                            │       )
                     │                            │
                     │                            │    3. Validate + clamp bounds
                     │                            │       bounds = transformer.bounds_from_level0_rect(
                     │                            │           x=req.x, y=req.y,
                     │                            │           w=req.width, h=req.height
                     │                            │       )
                     │                            │       → ViewportBounds(x_min, y_min, x_max, y_max)
                     │                            │
                     │                            │    4. Spatial query
                     │                            │       spatial_svc = SpatialQueryService(db)
                     │                            │       spatial_svc.get_nuclei_in_viewport(
                     │                            │           slide_id, bounds
                     │                            │       )
                     │                            │                          │
                     │                            │                          ├──► PostGIS Query:
                     │                            │                          │    
                     │                            │                          │    SELECT
                     │                            │                          │        id,
                     │                            │                          │        ST_X(geom) AS x,
                     │                            │                          │        ST_Y(geom) AS y,
                     │                            │                          │        cell_type,
                     │                            │                          │        cell_type_name,
                     │                            │                          │        probability
                     │                            │                          │    FROM nuclei
                     │                            │                          │    WHERE slide_id = $1
                     │                            │                          │      AND ST_Contains(
                     │                            │                          │          ST_MakeEnvelope(
                     │                            │                          │              $2, $3, $4, $5, 0
                     │                            │                          │          ),
                     │                            │                          │          geom
                     │                            │                          │      )
                     │                            │                          │    LIMIT 50000
                     │                            │                          │
                     │                            │                          │    [Uses GIST index on geom]
                     │                            │                          │    [O(log n) R-tree lookup]
                     │                            │                          │
                     │                            │                          ◄─── Rows (id, x, y, type, prob)
                     │                            │
                     │                            │    5. Build response
                     │                            │       ViewportNucleiResponse(
                     │                            │           slide_id=slide_id,
                     │                            │           bounds_l0={...},
                     │                            │           nuclei=[
                     │                            │               NucleusBase(id, x, y, cell_type, ...),
                     │                            │               ...
                     │                            │           ]
                     │                            │       )
                     │                            │
                     │    ◄────── 200 OK ─────────┤
                     │    {
                     │        slide_id: "...",
                     │        bounds_l0: {...},
                     │        nuclei: [
                     │            { id, x, y, cell_type, cell_type_name, probability },
                     │            ...
                     │        ]
                     │    }
                     │
                     ├──► setNuclei(data.nuclei)
                     │    setFetchLoading(false)
                     │
                     ├──► NucleusOverlay: useEffect([nuclei, viewer])
                     │
                     │    requestAnimationFrame(() => {
                     │        for (const nuc of nuclei) {
                     │            const viewportPoint = viewer.viewport.imageToViewportCoordinates(nuc.x, nuc.y)
                     │            const canvasPoint = viewer.viewport.viewportToViewerElementCoordinates(viewportPoint)
                     │            
                     │            ctx.fillStyle = CELL_TYPE_COLORS[nuc.cell_type]
                     │            ctx.beginPath()
                     │            ctx.arc(canvasPoint.x, canvasPoint.y, radius, 0, 2 * Math.PI)
                     │            ctx.fill()
                     │        }
                     │    })
                     │
                     ▼
                Nuclei rendered on canvas
                (colored circles at centroids)

PERFORMANCE CHARACTERISTICS:
• Debounced 150ms: prevents query spam during rapid panning
• AbortController: cancels in-flight requests on new pan/zoom
• PostGIS GIST index: O(log n) spatial lookup (not full table scan)
• Max 50,000 nuclei per viewport (memory safety cap)
• Canvas2D rendering: GPU-accelerated, requestAnimationFrame batching
• No inference: retrieves pre-computed nuclei from database only
```

---

## Database Design

### Entity-Relationship Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                   SLIDES                                    │
├──────────────────┬─────────────────────────────┬────────────────────────────┤
│ id               │ UUID                        │ PRIMARY KEY                │
│ filename         │ TEXT                        │ NOT NULL                   │
│ filepath         │ TEXT                        │ UNIQUE, NOT NULL           │
│ mpp              │ FLOAT                       │ Microns-per-pixel          │
│ width_px         │ INTEGER                     │ Level 0 width              │
│ height_px        │ INTEGER                     │ Level 0 height             │
│ metadata_        │ JSONB                       │ OpenSlide properties       │
│ created_at       │ TIMESTAMP WITH TIME ZONE    │ DEFAULT CURRENT_TIMESTAMP  │
│ updated_at       │ TIMESTAMP WITH TIME ZONE    │ ON UPDATE                  │
└──────────────────┴─────────────────────────────┴────────────────────────────┘
        │
        │ 1
        │
        │ has many
        │
        │ N
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ANALYSIS_BOXES                                 │
├──────────────────┬─────────────────────────────┬────────────────────────────┤
│ id               │ UUID                        │ PRIMARY KEY                │
│ slide_id         │ UUID                        │ FOREIGN KEY → slides.id    │
│                  │                             │ ON DELETE CASCADE          │
│ label            │ TEXT                        │ "Analysis 1", "Analysis 2" │
│ x_min            │ FLOAT                       │ L0 pixel coordinates       │
│ y_min            │ FLOAT                       │                            │
│ x_max            │ FLOAT                       │                            │
│ y_max            │ FLOAT                       │                            │
│ geom             │ GEOMETRY(POLYGON, 0)        │ PostGIS spatial            │
│                  │                             │ GIST indexed               │
│ total_nuclei     │ INTEGER                     │ Cached count               │
│ area_mm2         │ FLOAT                       │ Physical area              │
│ density_per_mm2  │ FLOAT                       │ nuclei / mm²               │
│ neoplastic_ratio │ FLOAT                       │ Rn (neoplastic/total)      │
│ cell_type_counts │ JSONB                       │ {"1": {count, name}, ...}  │
│ created_at       │ TIMESTAMP WITH TIME ZONE    │ DEFAULT CURRENT_TIMESTAMP  │
└──────────────────┴─────────────────────────────┴────────────────────────────┘
        │
        │ 1
        │
        │ contains
        │
        │ N
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                  NUCLEI                                     │
├──────────────────┬─────────────────────────────┬────────────────────────────┤
│ id               │ BIGSERIAL                   │ PRIMARY KEY                │
│ slide_id         │ UUID                        │ FOREIGN KEY → slides.id    │
│                  │                             │ ON DELETE CASCADE          │
│ analysis_box_id  │ UUID                        │ FOREIGN KEY →              │
│                  │                             │   analysis_boxes.id        │
│                  │                             │ ON DELETE CASCADE          │
│ geom             │ GEOMETRY(POINT, 0)          │ Centroid (L0 pixels)       │
│                  │                             │ GIST indexed               │
│ contour          │ GEOMETRY(POLYGON, 0)        │ Nucleus boundary           │
│                  │                             │ GIST indexed               │
│ cell_type        │ SMALLINT                    │ 0-5 (PanNuke taxonomy)     │
│ cell_type_name   │ TEXT                        │ Human-readable label       │
│ probability      │ FLOAT                       │ Softmax confidence         │
│ area_um2         │ FLOAT                       │ Morphometric (μm²)         │
│ perimeter_um     │ FLOAT                       │ Morphometric (μm)          │
│ created_at       │ TIMESTAMP WITH TIME ZONE    │ DEFAULT CURRENT_TIMESTAMP  │
└──────────────────┴─────────────────────────────┴────────────────────────────┘

RELATIONSHIPS:
  slides (1) ──────────────── (N) analysis_boxes
  slides (1) ──────────────── (N) nuclei
  analysis_boxes (1) ──────── (N) nuclei

CASCADE BEHAVIOR:
  DELETE slides.id
    ├──► CASCADE DELETE analysis_boxes WHERE slide_id = ...
    │      └──► CASCADE DELETE nuclei WHERE analysis_box_id = ...
    └──► CASCADE DELETE nuclei WHERE slide_id = ...

CELL TYPE TAXONOMY (PanNuke):
  0 = Background / Other
  1 = Neoplastic
  2 = Inflammatory
  3 = Connective / Soft tissue
  4 = Dead cells
  5 = Epithelial
```

### Index Strategy

**Optimized for spatial queries and foreign key lookups:**

```
TABLE: analysis_boxes
┌──────────────────────────┬──────────┬─────────────────┬──────────────────────────────────┐
│ Index Name               │ Type     │ Column(s)       │ Purpose                          │
├──────────────────────────┼──────────┼─────────────────┼──────────────────────────────────┤
│ idx_abox_geom_gist       │ GIST     │ geom            │ Spatial queries on box regions   │
│                          │          │                 │ (ST_Contains, ST_Intersects)     │
├──────────────────────────┼──────────┼─────────────────┼──────────────────────────────────┤
│ idx_abox_slide_id        │ B-tree   │ slide_id        │ Filter boxes by slide            │
│                          │          │                 │ (FK lookup, cascade deletes)     │
└──────────────────────────┴──────────┴─────────────────┴──────────────────────────────────┘

TABLE: nuclei
┌──────────────────────────┬──────────┬─────────────────┬──────────────────────────────────┐
│ Index Name               │ Type     │ Column(s)       │ Purpose                          │
├──────────────────────────┼──────────┼─────────────────┼──────────────────────────────────┤
│ idx_nuclei_geom_gist     │ GIST     │ geom            │ CRITICAL: Viewport nuclei        │
│                          │          │                 │ fetch via ST_Contains            │
│                          │          │                 │ O(log n) R-tree lookup           │
├──────────────────────────┼──────────┼─────────────────┼──────────────────────────────────┤
│ idx_nuclei_contour_gist  │ GIST     │ contour         │ Spatial queries on full contours │
│                          │          │                 │ (polygon intersection, overlap)  │
├──────────────────────────┼──────────┼─────────────────┼──────────────────────────────────┤
│ idx_nuclei_slide_id      │ B-tree   │ slide_id        │ Filter nuclei by slide           │
│                          │          │                 │ (FK lookup, cascade deletes)     │
├──────────────────────────┼──────────┼─────────────────┼──────────────────────────────────┤
│ idx_nuclei_box_id        │ B-tree   │ analysis_box_id │ Filter nuclei by analysis box    │
│                          │          │                 │ (FK lookup, cascade deletes)     │
├──────────────────────────┼──────────┼─────────────────┼──────────────────────────────────┤
│ idx_nuclei_cell_type     │ B-tree   │ slide_id,       │ Composite: cell type filtering   │
│                          │          │ cell_type       │ per slide (for statistics)       │
└──────────────────────────┴──────────┴─────────────────┴──────────────────────────────────┘

QUERY PATTERNS:
  1. Viewport nuclei fetch (pan/zoom):
     SELECT ... FROM nuclei
     WHERE slide_id = $1 AND ST_Contains(envelope, geom)
     → Uses: idx_nuclei_slide_id + idx_nuclei_geom_gist (index intersection)

  2. Box statistics aggregation:
     SELECT cell_type, COUNT(*), ... FROM nuclei
     WHERE slide_id = $1 AND analysis_box_id = $2
     GROUP BY cell_type
     → Uses: idx_nuclei_box_id

  3. ROI stats (custom rectangle):
     SELECT ... FROM nuclei
     WHERE slide_id = $1 AND ST_Contains(ST_MakeEnvelope(...), geom)
     → Uses: idx_nuclei_geom_gist

  4. Box deletion cascade:
     DELETE FROM analysis_boxes WHERE id = $1
     → Triggers: DELETE FROM nuclei WHERE analysis_box_id = $1
     → Uses: idx_nuclei_box_id (for efficient cascade)
```

### Cascade Behavior

**Referential integrity enforcement with automatic cleanup:**

```
DELETE CASCADE TREE:

┌─────────────────────────────────────────────────────────────────────┐
│ DELETE FROM slides WHERE id = '...'                                 │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                       ├──► CASCADES TO:
                       │
                       │    ┌──────────────────────────────────────────┐
                       │    │ DELETE FROM analysis_boxes               │
                       │    │ WHERE slide_id = '...'                   │
                       │    └────────────┬─────────────────────────────┘
                       │                 │
                       │                 └──► CASCADES TO:
                       │                      ┌─────────────────────────┐
                       │                      │ DELETE FROM nuclei      │
                       │                      │ WHERE analysis_box_id   │
                       │                      │   IN (deleted boxes)    │
                       │                      └─────────────────────────┘
                       │
                       └──► ALSO CASCADES TO:
                            ┌──────────────────────────────────────────┐
                            │ DELETE FROM nuclei                       │
                            │ WHERE slide_id = '...'                   │
                            └──────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ DELETE FROM analysis_boxes WHERE id = '...'                         │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                       └──► CASCADES TO:
                            ┌──────────────────────────────────────────┐
                            │ DELETE FROM nuclei                       │
                            │ WHERE analysis_box_id = '...'            │
                            └──────────────────────────────────────────┘

FOREIGN KEY CONSTRAINTS:
  nuclei.slide_id → slides.id (ON DELETE CASCADE)
  nuclei.analysis_box_id → analysis_boxes.id (ON DELETE CASCADE)
  analysis_boxes.slide_id → slides.id (ON DELETE CASCADE)

DELETION IMPLICATIONS:
  - Deleting a slide: removes all its boxes and all nuclei
  - Deleting a box: removes only its nuclei (other boxes unaffected)
  - No orphaned nuclei: impossible due to FK constraints
  - Atomic: all cascade deletes happen in single transaction
```

---

## Coordinate System

Slidekick operates in three coordinate spaces with precise transformations between them.

### Coordinate Spaces

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ LEVEL 0 (L0) PIXEL SPACE                                                    │
│ • Origin: Top-left corner of WSI                                            │
│ • Units: Pixels at highest resolution (level 0)                             │
│ • Range: [0, width_px) × [0, height_px)                                     │
│ • Storage: All PostGIS geometries stored in this space (SRID 0, Cartesian)  │
│ • Example: Point(12543.7, 8921.3) represents a nucleus centroid             │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   │ × MPP (Microns-Per-Pixel)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHYSICAL SPACE (Micrometers)                                                │
│ • Units: μm (micrometers)                                                   │
│ • Conversion: d_physical = d_pixels × MPP                                   │
│ • Area conversion: A_mm² = A_px × MPP² × 1e-6                               │
│ • Used for: Density (nuclei/mm²), scale bar, clinical metrics               │
│ • Example: 500 pixels @ 0.25 MPP = 125 μm = 0.125 mm                        │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   │ / 2^level (downsample factor)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ VIEWPORT SPACE (OpenSeadragon)                                              │
│ • Origin: Top-left of current zoom level pyramid tile                       │
│ • Units: Pixels at current zoom level                                       │
│ • Conversion: L0_px = viewport_px × 2^level                                 │
│ • Used by: OpenSeadragon viewer, tile requests                              │
│ • Example: Level 3 viewport → 2³ = 8× downsampled from L0                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Transformation Formulas

**Pixel ↔ Physical:**
```
d_physical_μm = d_pixels × MPP
A_mm² = A_px × MPP² × 1e-6

Example (MPP = 0.25):
  500 px → 500 × 0.25 = 125 μm
  1000 px × 800 px → 1000 × 800 × (0.25)² × 1e-6 = 0.05 mm²
```

**Level 0 ↔ Viewport Level N:**
```
L0_px = viewport_px × 2^level
viewport_px = L0_px / 2^level

Example (level = 3):
  Viewport: (100, 200) at level 3
  → L0: (100 × 2³, 200 × 2³) = (800, 1600)
```

**Density Calculation:**
```
density_per_mm² = N_nuclei / A_mm²
                = N_nuclei / (A_px × MPP² × 1e-6)

Example (1000 nuclei in 500×500 px box, MPP=0.25):
  A_mm² = 500 × 500 × (0.25)² × 1e-6 = 0.015625 mm²
  density = 1000 / 0.015625 = 64,000 nuclei/mm²
```

**Neoplastic Ratio (Rn):**
```
Rn = N_neoplastic / N_total

Example:
  Total: 1000 nuclei
  Neoplastic (type=1): 350
  Rn = 350 / 1000 = 0.35 (35%)
```

### Implementation

**Backend:** `CoordinateTransformer` class (`app/spatial/transform.py`)
- `bounds_from_level0_rect(x, y, w, h)` — validate and clamp L0 rectangle
- `physical_to_pixels(distance_um)` — μm → pixels
- `pixels_to_physical(distance_px)` — pixels → μm

**Frontend:** `coordinates.js` (`src/utils/coordinates.js`)
- `getViewportBoundsL0(viewer, width_px, height_px)` — OSD viewport → L0 rect
- `getCurrentLevel(viewer, width_px)` — determine pyramid level from zoom
- Identical math ensures client/server coordinate consistency

### Storage Convention

**ALL PostGIS geometries are stored in Level-0 pixel coordinates (SRID 0):**

```sql
-- Nucleus centroid (POINT)
ST_GeomFromText('POINT(12543.7 8921.3)', 0)

-- Analysis box bounds (POLYGON)
ST_GeomFromText('POLYGON((1024 2048, 5120 2048, 5120 5120, 1024 5120, 1024 2048))', 0)

-- Spatial query (viewport fetch)
SELECT * FROM nuclei
WHERE ST_Contains(
    ST_MakeEnvelope(1024, 2048, 5120, 5120, 0),  -- L0 pixel bounds
    geom
)
```

This eliminates coordinate system confusion and ensures all spatial operations happen in a consistent, well-defined space.

---

## Thread Safety Model

OpenSlide's C library (`libopenslide`) is **not thread-safe**. Concurrent reads from the same `OpenSlide` handle cause corrupted tiles or segfaults.

### Solution: Thread-Local Storage

Slidekick uses **thread-local storage** (`threading.local()`) so each worker thread in the `ThreadPoolExecutor(max_workers=4)` gets its own independent `OpenSlide` handle.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ FASTAPI PROCESS (main.py)                                                   │
│                                                                             │
│  ThreadPoolExecutor(max_workers=4)                                          │
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │   Thread 1      │  │   Thread 2      │  │   Thread 3      │   ...        │
│  ├─────────────────┤  ├─────────────────┤  ├─────────────────┤              │
│  │ _tls.slides = { │  │ _tls.slides = { │  │ _tls.slides = { │              │
│  │   "path/a.svs": │  │   "path/a.svs": │  │   "path/a.svs": │              │
│  │     OpenSlide   │  │     OpenSlide   │  │     OpenSlide   │              │
│  │       handle_A1 │  │       handle_A2 │  │       handle_A3 │              │
│  │   "path/b.svs": │  │   "path/b.svs": │  │   "path/b.svs": │              │
│  │     OpenSlide   │  │     OpenSlide   │  │     OpenSlide   │              │
│  │       handle_B1 │  │       handle_B2 │  │       handle_B3 │              │
│  │ }               │  │ }               │  │ }               │              │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘              │
│          │                    │                    │                        │
│          └────────────────────┴────────────────────┘                        │
│                               │                                             │
│                               ▼                                             │
│                    SAME FILE, DIFFERENT C HANDLES                           │
│                    → No lock contention                                     │
│                    → Truly parallel tile serving                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation

**`app/services/slide.py`:**

```python
import threading

_tls = threading.local()  # Thread-local storage container

def _tls_open(filepath: str) -> OpenSlide:
    """Return a thread-local OpenSlide handle for filepath."""
    if not hasattr(_tls, "slides"):
        _tls.slides = {}  # Each thread gets its own dict
    
    handle = _tls.slides.get(filepath)
    if handle is None:
        handle = OpenSlide(filepath)  # New handle for this thread
        _tls.slides[filepath] = handle
    return handle

class SlideService:
    def __init__(self, filepath: str | Path):
        self.filepath = Path(filepath)
        self._filepath_str = str(self.filepath)
        # Eagerly validate file on the CALLING thread
        # Then close to avoid keeping a long-lived handle
        # (Validation only, not used for serving)
    
    def get_tile(self, level, col, row):
        # Each thread gets its own DeepZoomGenerator
        dz = _tls_dz(self._filepath_str)  # Thread-local
        tile = dz.get_tile(level, (col, row))
        # ...
```

### Concurrency Characteristics

```
+----------------------------------------------------------------------+
| REQUEST HANDLING                                                     |
|                                                                      |
|  Request 1: GET /slides/abc/dzi_files/10/5_3.jpeg                    |
|  Request 2: GET /slides/abc/dzi_files/10/6_3.jpeg                    |
|  Request 3: GET /slides/abc/dzi_files/10/7_3.jpeg                    |
|  Request 4: GET /slides/abc/dzi_files/10/8_3.jpeg                    |
|                                                                      |
|  All 4 requests for SAME slide, DIFFERENT tiles                      |
|                                                                      |
|  Without TLS:                                                        |
|    - Global lock on OpenSlide handle                                 |
|    - Requests serialize (1 → 2 → 3 → 4)                              |
|    - 3 threads idle while 1 thread reads                             |
|                                                                      |
|  With TLS:                                                           |
|    - Each request gets own thread + own OpenSlide handle             |
|    - All 4 requests execute in parallel                              |
|    - ~4× throughput improvement                                      |
|                                                                      |
+----------------------------------------------------------------------+
```

### HoVerNet Inference

**HoVerNet inference runs on a single thread** via `run_in_executor`, but uses **PyTorch's internal parallelism** for tensor operations:

```python
# In routers/inference.py
loop = asyncio.get_event_loop()
inference_task = loop.run_in_executor(
    None,  # Uses default ThreadPoolExecutor
    lambda: engine.infer_tile(tile_rgb, offset_x, offset_y, mpp, progress_callback)
)
```

This keeps the blocking inference work off the asyncio event loop while still allowing SSE progress streaming.

### Key Invariants

```
- SlideService instance: cached and shared across threads (@lru_cache)
- OpenSlide handles: per-thread, never shared
- DeepZoomGenerator instances: per-thread, never shared
- No global locks on tile serving path
- No race conditions: each thread reads from its own C handle
```

This design achieves **lock-free parallel tile serving** while respecting OpenSlide's thread-safety limitations.

---

## Security Architecture

Slidekick is designed as a **local-first, single-user tool**.:

| Layer | Mechanism | What It Prevents |
|---|---|---|
| Network | `LocalhostOnlyMiddleware` | Non-loopback connections (even if Docker port mapping is misconfigured) |
| Host | `TrustedHostMiddleware` | DNS rebinding attacks |
| CORS | Origins configurable via `SLIDEKICK_CORS_ORIGINS` | Cross-origin requests from other sites |
| Upload | Filename sanitization + UUID rename | Directory traversal, filename collision |
| Upload | Extension allow-list | Arbitrary file upload |
| Upload | Path canonicalization check | Path escape attacks |
| Upload | 10 GiB size limit | Denial of service |
| SQL | Fully parameterized queries (`$1..$N` bind params) | SQL injection (zero string interpolation) |
| SQL | `asyncpg.executemany` for bulk inserts | Parameter limit bypass without concatenation |


---

## Integration Points

### Frontend-Backend Communication

| Mechanism | Endpoint Pattern | Used For |
|---|---|---|
| Axios (REST) | `GET /api/slides/`, `POST /api/slides/upload`, etc. | Standard CRUD operations |
| Fetch + SSE | `POST /api/inference/viewport-stream` | Real-time progress during inference |
| Direct URL | `GET /api/slides/{id}/dzi`, `.../dzi_files/{level}/{col}_{row}.jpeg` | OpenSeadragon tile loading |

### Vite Proxy

The frontend dev server proxies `/api` to `http://localhost:8000`

### Database Connection

- **Async path**: `asyncpg` via SQLAlchemy's `create_async_engine` for all runtime queries.
- **Schema management**: `Base.metadata.create_all` (via `run_sync`) during FastAPI lifespan startup. This is idempotent (`CREATE TABLE IF NOT EXISTS`) and safe to run on every boot.
- **Raw connection**: To keep things fast, bulk inserts communicate directly with the database driver using `asyncpg.Connection.executemany`.
---


