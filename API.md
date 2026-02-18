# API Reference

This document provides a complete reference for every HTTP endpoint exposed by the Slidekick backend. All endpoints are prefixed with `/api` and served by FastAPI on `http://localhost:8000`.

---

## Table of Contents

- [Overview](#overview)
- [Authentication](#authentication)
- [Slides](#slides)
  - [POST /api/slides/upload](#post-apislidesupload)
  - [GET /api/slides/](#get-apislides)
  - [GET /api/slides/{slide_id}](#get-apislidesslide_id)
  - [GET /api/slides/{slide_id}/dzi](#get-apislidesslide_iddzi)
  - [GET /api/slides/{slide_id}/dzi_files/{level}/{col}\_{row}.jpeg](#get-apislidesslide_iddzi_fileslevelcol_rowjpeg)
  - [GET /api/slides/{slide_id}/scale-bar](#get-apislidesslide_idscale-bar)
  - [GET /api/slides/{slide_id}/thumbnail](#get-apislidesslide_idthumbnail)
- [Inference](#inference)
  - [POST /api/inference/viewport-stream](#post-apiinferenceviewport-stream)
- [ROI (Region of Interest)](#roi-region-of-interest)
  - [POST /api/roi/stats](#post-apiroistats)
  - [POST /api/roi/nuclei](#post-apiroinuclei)
- [Analysis Boxes](#analysis-boxes)
  - [GET /api/boxes/{slide_id}](#get-apiboxesslide_id)
  - [GET /api/boxes/detail/{box_id}](#get-apiboxesdetailbox_id)
  - [DELETE /api/boxes/{box_id}](#delete-apiboxesbox_id)
- [Health Check](#health-check)
  - [GET /health](#get-health)
- [Core Business Logic](#core-business-logic)
  - [HoVerNetEngine](#hovernetengine)
  - [NucleiStreamer](#nucleistreamer)
  - [SpatialQueryService](#spatialqueryservice)
  - [CoordinateTransformer](#coordinatetransformer)
  - [SlideService](#slideservice)
- [Pydantic Schemas](#pydantic-schemas)

---

## Overview

| Property | Value |
|---|---|
| Base URL | `http://localhost:8000` |
| API Prefix | `/api` |
| Content Type | `application/json` (unless noted) |
| Authentication | None (localhost-only) |
| OpenAPI Docs | `http://localhost:8000/docs` |

All UUID parameters use the standard format: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`.

---

## Authentication

**Slidekick does not implement authentication or authorization.**

Access is restricted to the loopback interface via `LocalhostOnlyMiddleware` (rejects any request where `request.client.host` is not `127.0.0.1`, `::1`, or `localhost`) and `TrustedHostMiddleware` (rejects requests with unexpected `Host` headers).

---

## Slides

### POST /api/slides/upload

Upload a Whole Slide Image file.

**Request**

- Content-Type: `multipart/form-data`
- Body: `file` (required) -- the WSI file

**Allowed Extensions:** `.svs`, `.ndpi`, `.mrxs`, `.tiff`, `.tif`, `.vms`, `.scn`, `.bif`

**Size Limit:** 10 GiB

**Security Measures:**
- Filename stripped of path components (prevents directory traversal)
- File stored under a random UUID name (prevents collision/overwrite)
- Extension validated against allow-list
- Resolved path verified to be inside the configured slides directory
- File size checked before write

**Response** `201 Created`

```json
{
  "id": "uuid",
  "filename": "original_name.svs",
  "mpp": 0.2528,
  "width_px": 98304,
  "height_px": 75264,
  "created_at": "2026-02-13T12:00:00Z"
}
```

**Error Responses**

| Status | Condition |
|---|---|
| `400` | No filename, invalid filename, unsupported extension, invalid path |
| `413` | File exceeds 10 GiB |
| `422` | OpenSlide failed to open the file |

---

### GET /api/slides/

List all uploaded slides, ordered by creation time (newest first).

**Response** `200 OK`

```json
[
  {
    "id": "uuid",
    "filename": "slide.svs",
    "mpp": 0.2528,
    "width_px": 98304,
    "height_px": 75264,
    "created_at": "2026-02-13T12:00:00Z"
  }
]
```

---

### GET /api/slides/{slide_id}

Get a single slide by ID.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `slide_id` | UUID | Slide identifier |

**Response** `200 OK` -- Same schema as list item.

**Error:** `404` if slide not found.

---

### GET /api/slides/{slide_id}/dzi

Return the DZI XML descriptor for OpenSeadragon.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `slide_id` | UUID | Slide identifier |

**Response** `200 OK`

- Content-Type: `application/xml`
- Body: DZI XML document

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Image xmlns="http://schemas.microsoft.com/deepzoom/2008"
       Format="jpeg" Overlap="1" TileSize="254">
  <Size Width="98304" Height="75264"/>
</Image>
```

**Error:** `404` if slide not found.

---

### GET /api/slides/{slide_id}/dzi_files/{level}/{col}\_{row}.jpeg

Serve a single Deep Zoom tile.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `slide_id` | UUID | Slide identifier |
| `level` | int | DZI zoom level (not OpenSlide level) |
| `col` | int | Tile column |
| `row` | int | Tile row |

**Response** `200 OK`

- Content-Type: `image/jpeg`
- Cache-Control: `public, max-age=86400`
- Body: JPEG image bytes

**Note:** Tile rendering is offloaded to a thread pool executor to prevent blocking the asyncio event loop during pan gestures.

**Error:** `404` if slide or tile not found.

---

### GET /api/slides/{slide_id}/scale-bar

Compute how many pixels correspond to a target distance in micrometers.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `slide_id` | UUID | Slide identifier |

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `target_um` | float | `100.0` | Target distance in micrometers |
| `level` | int | `0` | WSI zoom level |

**Response** `200 OK`

```json
{
  "target_um": 100.0,
  "pixels_at_level": 396.0,
  "level": 0,
  "mpp": 0.2528
}
```

**Error:** `404` if slide not found.

---

### GET /api/slides/{slide_id}/thumbnail

Generate a JPEG thumbnail of the slide.

Thumbnails are cached to disk under `<slides_dir>/.thumbnails/`. Subsequent requests for the same slide and size are served directly from the cache without touching OpenSlide.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `slide_id` | UUID | Slide identifier |

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `max_size` | int | `200` | Maximum dimension in pixels |

**Response** `200 OK`

- Content-Type: `image/jpeg`
- Cache-Control: `public, max-age=86400`
- Body: JPEG image bytes

**Error:** `404` if slide not found. `500` if thumbnail generation fails.

---

## Inference

### POST /api/inference/viewport-stream

Run HoVerNet nuclear segmentation on a viewport region with real-time SSE progress streaming.

**Request Body**

```json
{
  "slide_id": "uuid",
  "x": 10240,
  "y": 8192,
  "width": 2048,
  "height": 2048,
  "level": 0
}
```

| Field | Type | Description |
|---|---|---|
| `slide_id` | UUID | Slide to analyze |
| `x` | float | Top-left X in L0 pixel coordinates |
| `y` | float | Top-left Y in L0 pixel coordinates |
| `width` | float | Region width in pixels |
| `height` | float | Region height in pixels |
| `level` | int | Zoom level (default 0) |

**Response** -- Server-Sent Events stream (`text/event-stream`)

**Progress Event:**

```
event: progress
data: {"type": "progress", "current": 3, "total": 12, "percentage": 25, "message": "Processing batch 3/12"}
```

**Complete Event:**

```
event: complete
data: {
  "type": "complete",
  "box": {
    "id": "uuid",
    "slide_id": "uuid",
    "label": "Analysis 1",
    "x_min": 10240,
    "y_min": 8192,
    "x_max": 12288,
    "y_max": 10240,
    "total_nuclei": 1523,
    "area_mm2": 0.267,
    "density_per_mm2": 5702.2,
    "neoplastic_ratio": 0.312,
    "cell_type_counts": {
      "0": {"count": 45, "name": "Background"},
      "1": {"count": 475, "name": "Neoplastic"},
      "2": {"count": 312, "name": "Inflammatory"},
      "3": {"count": 289, "name": "Connective"},
      "4": {"count": 67, "name": "Dead"},
      "5": {"count": 335, "name": "Non-Neoplastic Epithelial"}
    },
    "created_at": "2026-02-13T12:05:00Z"
  },
  "nuclei": [
    {"id": 0, "x": 10356.7, "y": 8234.2, "cell_type": 1, "cell_type_name": "Neoplastic", "probability": 0.94}
  ],
  "count": 1523
}
```


**Pipeline:**
1. Validate bounds (width and height must be positive after clamping to slide extent).
2. Read WSI region via OpenSlide (thread pool).
3. Pad and partition into 256x256 patches with 46px context overlap.
4. Run HoVerNet `infer_batch` + `postproc` in batches (thread pool).
5. Stream progress events every 300ms.
6. Parse raw output: shift local coordinates to L0, compute morphometrics.
7. Create `AnalysisBox` with summary statistics.
8. Bulk insert nuclei via `asyncpg.executemany` (parameterized).
9. Stream completion event with box and nuclei data.

---

## ROI (Region of Interest)

### POST /api/roi/stats

Compute spatial statistics for a rectangular ROI using PostGIS.

**Request Body**

```json
{
  "slide_id": "uuid",
  "x_min": 5000,
  "y_min": 5000,
  "x_max": 10000,
  "y_max": 10000
}
```

**Response** `200 OK`

```json
{
  "slide_id": "uuid",
  "total_nuclei": 3421,
  "area_mm2": 1.602,
  "density_per_mm2": 2136.1,
  "neoplastic_ratio": 0.287,
  "cell_type_breakdown": [
    {"cell_type": 0, "cell_type_name": "Background", "count": 102, "fraction": 0.030},
    {"cell_type": 1, "cell_type_name": "Neoplastic", "count": 982, "fraction": 0.287},
    {"cell_type": 2, "cell_type_name": "Inflammatory", "count": 756, "fraction": 0.221},
    {"cell_type": 3, "cell_type_name": "Connective", "count": 689, "fraction": 0.201},
    {"cell_type": 4, "cell_type_name": "Dead", "count": 198, "fraction": 0.058},
    {"cell_type": 5, "cell_type_name": "Non-Neoplastic Epithelial", "count": 694, "fraction": 0.203}
  ],
  "mpp": 0.2528,
  "bounds_l0": {"x_min": 5000, "y_min": 5000, "x_max": 10000, "y_max": 10000}
}
```

**Error:** `404` if slide not found.

---

### POST /api/roi/nuclei

Fetch pre-computed nuclei within the user's viewport (no inference, PostGIS query only).

**Request Body**

```json
{
  "slide_id": "uuid",
  "x": 10240,
  "y": 8192,
  "width": 4096,
  "height": 4096,
  "level": 0
}
```

**Safety Cap:** 50,000 nuclei maximum per response.

**Response** `200 OK`

```json
{
  "slide_id": "uuid",
  "bounds_l0": {"x_min": 10240, "y_min": 8192, "x_max": 14336, "y_max": 12288},
  "nuclei": [
    {"id": 12345, "x": 10356.7, "y": 8234.2, "cell_type": 1, "cell_type_name": "Neoplastic", "probability": 0.94}
  ]
}
```

**Error:** `404` if slide not found.

---

## Analysis Boxes

### GET /api/boxes/{slide_id}

List all analysis boxes for a slide, ordered by creation time (newest first).

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `slide_id` | UUID | Slide identifier |

**Response** `200 OK`

```json
{
  "slide_id": "uuid",
  "boxes": [
    {
      "id": "uuid",
      "slide_id": "uuid",
      "label": "Analysis 1",
      "x_min": 10240,
      "y_min": 8192,
      "x_max": 12288,
      "y_max": 10240,
      "total_nuclei": 1523,
      "area_mm2": 0.267,
      "density_per_mm2": 5702.2,
      "neoplastic_ratio": 0.312,
      "cell_type_counts": {},
      "created_at": "2026-02-13T12:05:00Z"
    }
  ]
}
```

**Error:** `404` if slide not found.

---

### GET /api/boxes/detail/{box_id}

Get a single analysis box with full cell type breakdown and derived clinical metrics.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `box_id` | UUID | Analysis box identifier |

**Response** `200 OK`

```json
{
  "id": "uuid",
  "slide_id": "uuid",
  "label": "Analysis 1",
  "x_min": 10240,
  "y_min": 8192,
  "x_max": 12288,
  "y_max": 10240,
  "total_nuclei": 1523,
  "area_mm2": 0.267,
  "density_per_mm2": 5702.2,
  "neoplastic_ratio": 0.312,
  "cell_type_counts": {},
  "created_at": "2026-02-13T12:05:00Z",
  "cell_type_breakdown": [
    {"cell_type": 0, "cell_type_name": "Background", "count": 45, "fraction": 0.030},
    {"cell_type": 1, "cell_type_name": "Neoplastic", "count": 475, "fraction": 0.312}
  ],
  "shannon_h": 1.62,
  "inflammatory_index": 0.211,
  "immune_tumour_ratio": 0.657,
  "ne_epithelial_ratio": 1.418,
  "viability": 0.956
}
```

**Derived Clinical Metrics:**

| Metric | Formula | Description |
|---|---|---|
| `shannon_h` | `-SUM(p_i * ln(p_i))` | Shannon diversity index across all cell types |
| `inflammatory_index` | `N_inflammatory / N_non_background` | Fraction of non-background cells that are inflammatory |
| `immune_tumour_ratio` | `N_inflammatory / N_neoplastic` | Ratio of immune to tumor cells |
| `ne_epithelial_ratio` | `N_neoplastic / N_epithelial` | Ratio of neoplastic to epithelial cells |
| `viability` | `(N_total - N_dead) / N_total` | Fraction of live cells |

**Error:** `404` if box not found.

---

### DELETE /api/boxes/{box_id}

Delete an analysis box and all its nuclei (via CASCADE).

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `box_id` | UUID | Analysis box identifier |

**Response** `204 No Content`

**Error:** `404` if box not found.

---

## Health Check

### GET /health

Basic liveness probe.

**Response** `200 OK`

```json
{
  "status": "ok",
  "service": "Slidekick"
}
```

---

## Core Business Logic

### HoVerNetEngine

**Location:** `backend/app/services/inference.py`

Singleton instance managing the HoVerNet deep learning model.

| Method | Signature | Description |
|---|---|---|
| `load_model()` | `-> None` | Load pretrained model via `tiatoolbox.models.architecture.get_pretrained_model`. Downloads/caches weights on first call. |
| `ensure_loaded()` | `-> None` | Lazy-load wrapper. Calls `load_model()` if not yet loaded. |
| `infer_tile()` | `(tile_rgb, offset_x, offset_y, mpp, progress_callback) -> InferenceResult` | Run full inference pipeline on a single RGB tile. Handles patching, batching, post-processing, coordinate translation, and morphometrics. |
| `infer_batch()` | `(tiles, offsets, mpp) -> list[InferenceResult]` | Convenience wrapper for multiple tiles (sequential). |

**Inference Pipeline (per tile):**
1. Compute context padding: `(patch_input - patch_output) // 2` = 46 pixels.
2. Pad tile with reflection.
3. Extract patches at `stride = patch_output_shape` (164x164).
4. Batch patches and run `model.infer_batch` (3 heads: NP, HV, TP).
5. Post-process each patch: `model.postproc` returns `(inst_map, inst_dict)`.
6. Accumulate nuclei with tile-local coordinates shifted by patch origin.
7. Parse raw output: shift by `(offset_x, offset_y)` to L0 coordinates.
8. Compute morphometrics: area (Shoelace formula * MPP^2), perimeter (edge sum * MPP).

**Device Selection:** MPS (Apple Silicon) > CUDA (NVIDIA) > CPU (fallback). Configurable via `SLIDEKICK_DEVICE`.

---

### NucleiStreamer

**Location:** `backend/app/services/bulk_insert.py`

Zero-copy generator transforming `DetectedNucleus` objects into flat tuples for bulk insertion.

| Method | Signature | Description |
|---|---|---|
| `from_viewport_result()` | `(nuclei) -> Generator[tuple]` | Yields `(slide_id, box_id, cx, cy, contour_wkt, cell_type, cell_type_name, prob, area, perimeter)` tuples. |

**Contour Conversion:** Nucleus contour arrays are converted to WKT POLYGON strings via Shapely. Invalid polygons (< 3 vertices, self-intersecting) are set to `NULL`.

---

### SpatialQueryService

**Location:** `backend/app/services/spatial.py`

Executes PostGIS spatial queries.

| Method | Signature | Description |
|---|---|---|
| `get_nuclei_in_viewport()` | `(slide_id, bounds, max_results) -> ViewportNucleiResponse` | Fetch nuclei centroids within an envelope using `ST_Contains(ST_MakeEnvelope(...), geom)`. Capped at 50,000 results. |
| `get_roi_stats()` | `(slide_id, bounds, mpp) -> ROIStatsResponse` | Aggregate query: `GROUP BY cell_type` with `COUNT(*)`. Computes density, neoplastic ratio, and per-type breakdown. |

---

### CoordinateTransformer

**Location:** `backend/app/spatial/transform.py`

Handles all coordinate conversions.

| Method | Signature | Description |
|---|---|---|
| `downsample_factor(level)` | `-> int` | Returns `2^level`. |
| `viewport_to_level0(vp_x, vp_y, level)` | `-> (float, float)` | Scale viewport coordinates to L0. |
| `px_to_um(distance_px)` | `-> float` | `distance * MPP` |
| `area_px_to_mm2(area_px)` | `-> float` | `area * MPP^2 * 1e-6` |
| `density_per_mm2(count, area_px)` | `-> float` | `count / area_mm2` |
| `viewport_bounds_to_level0(...)` | `-> ViewportBounds` | Convert viewport rect to L0, clamped to slide extent. |
| `bounds_from_level0_rect(...)` | `-> ViewportBounds` | Create bounds directly from L0 coordinates, clamped. |
| `scale_bar_px(target_um, level)` | `-> float` | Pixels per target micrometers at given level. |

---

### SlideService

**Location:** `backend/app/services/slide.py`

Thread-safe OpenSlide wrapper with DZI tile generation.

| Method | Signature | Description |
|---|---|---|
| `slide_info()` | `-> dict` | Summary metadata: filename, dimensions, MPP, magnification, vendor. |
| `get_dzi_xml()` | `-> str` | DZI XML descriptor string. |
| `get_dzi_tile(level, col, row)` | `-> bytes` | Render a single DZI tile as JPEG bytes. |
| `read_region_l0(x, y, w, h)` | `-> np.ndarray` | Read L0 region as RGB array. Clamps to slide bounds. |
| `mpp` | property | Extract MPP from `openslide.mpp-x` or fall back to default. |

**Cache Invalidation:** `invalidate_slide_service(filepath)` clears the LRU cache and closes thread-local OpenSlide handles for the given filepath. Call this when a slide file is deleted from disk.

**Thread Safety:** All OpenSlide access goes through `threading.local()` thread-local storage. Each thread gets its own `OpenSlide` handle. The `SlideService` instance is cached via `@lru_cache(maxsize=16)` and shared.

---

## Pydantic Schemas

### Request Schemas

| Schema | Fields | Used By |
|---|---|---|
| `InferenceViewportRequest` | `slide_id`, `x`, `y`, `width`, `height`, `level` | `POST /api/inference/viewport-stream` |
| `ViewportQuery` | `slide_id`, `x`, `y`, `width`, `height`, `level` | `POST /api/roi/nuclei` |
| `ROIStatsRequest` | `slide_id`, `x_min`, `y_min`, `x_max`, `y_max` | `POST /api/roi/stats` |

### Response Schemas

| Schema | Key Fields | Used By |
|---|---|---|
| `SlideOut` | `id`, `filename`, `mpp`, `width_px`, `height_px`, `created_at` | Slide endpoints |
| `NucleusBase` | `id`, `x`, `y`, `cell_type`, `cell_type_name`, `probability` | Viewport nuclei |
| `NucleusDetail` | Extends `NucleusBase` + `area_um2`, `perimeter_um`, `contour` | (Available but not directly exposed via endpoint) |
| `CellTypeCount` | `cell_type`, `cell_type_name`, `count`, `fraction` | ROI stats, box detail |
| `AnalysisBoxOut` | `id`, `slide_id`, `label`, bounds, stats, `created_at` | Box list, inference complete |
| `AnalysisBoxDetail` | Extends `AnalysisBoxOut` + `cell_type_breakdown`, clinical metrics | Box detail |
| `AnalysisBoxListResponse` | `slide_id`, `boxes[]` | Box list |
| `ViewportNucleiResponse` | `slide_id`, `bounds_l0`, `nuclei[]` | Viewport nuclei |
| `ROIStatsResponse` | Full statistics + `cell_type_breakdown` | ROI stats |
| `ScaleBarResponse` | `target_um`, `pixels_at_level`, `level`, `mpp` | Scale bar |
