# Slidekick

**Whole Slide Image (WSI) Toolkit platform with HoVerNet nuclear segmentation**

Slidekick is a local-first web application for computational pathology. It allows researchers and pathologists to upload gigapixel histology slides, run real-time deep learning inference (HoVerNet) on selected regions, and explore per-cell statistics through an interactive viewer.

---

## Quick Demo

https://github.com/user-attachments/assets/112c2185-1ffc-4c45-8875-ae3b8e2791dc

---

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Technology Stack](#technology-stack)
- [Prerequisites](#prerequisites)
- [Installation and Setup](#installation-and-setup)
- [Running the Application](#running-the-application)
- [Project Structure](#project-structure)
- [Documentation Index](#documentation-index)
- [License](#license)

---

## Features

- **WSI Viewing** -- Slide navigation with Deep Zoom Image (DZI) tiles rendered by OpenSeadragon.
- **Real-time Inference** -- HoVerNet nuclear instance segmentation (PanNuke taxonomy, 6 cell types) with Server-Sent Events (SSE) progress streaming.
- **Spatial Indexing** -- PostGIS storage of every detected nucleus for spatial queries.
- **Analysis Regions** -- Create, select, inspect, and delete rectangular analysis boxes. Each box stores pre-computed summary statistics density, neoplastic ratio, Shannon diversity, inflammatory index, viability, and etc.
- **Physical Measurement** -- Virtual micrometer scale bar, pixel-to-micrometer coordinate transforms, and mm-scale dimension labels on selections and analysis boxes.
- **Slide Management** -- Upload, list, and switch between slides

---

## Architecture Overview

Slidekick follows a **client-server** architecture:

| Layer | Technology | Role |
|---|---|---|
| Frontend | React 19 + Vite + TailwindCSS v4 | Viewer, overlays, statistics panel |
| Backend | FastAPI (async) + Uvicorn | REST API, DZI tile server, inference orchestration |
| Database | PostgreSQL 16 + PostGIS 3.4 | Relational + spatial persistence |
| ML Engine | TIAToolbox HoVerNet + PyTorch | Nuclear segmentation and classification |

For detailed architecture diagrams and data flow, see [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## Technology Stack

### Backend

| Library | Purpose |
|---|---|
| FastAPI | Async REST framework |
| Uvicorn | ASGI server |
| SQLAlchemy 2.0 (async) | ORM with asyncpg driver |
| GeoAlchemy2 | PostGIS geometry column types |
| asyncpg | Native PostgreSQL async driver |
| OpenSlide | WSI file reading (C library) |
| TIAToolbox | HoVerNet pretrained model loading |
| PyTorch + TorchVision | Deep learning inference runtime |
| Pillow | Image processing |
| NumPy | Array operations |
| Shapely | Geometry construction (WKT) |
| pydantic-settings | Configuration from environment variables |
| sse-starlette | Server-Sent Events for progress streaming |
| python-multipart | File upload parsing |

### Frontend

| Library | Purpose |
|---|---|
| React 19 | UI framework |
| Vite 6 | Build tooling and dev server |
| TailwindCSS v4 | Utility-first CSS framework |
| OpenSeadragon 5 | Deep Zoom tile viewer |
| Zustand 5 | Lightweight state management |
| Axios | HTTP client |

### Infrastructure

| Component | Purpose |
|---|---|
| Docker Compose | PostgreSQL + PostGIS container |
| PostGIS 3.4 | Spatial extensions for PostgreSQL |

---

## Prerequisites

- **Python 3.11+**
- **Node.js 18+** and npm
- **Docker** and Docker Compose (for PostgreSQL/PostGIS)
- **OpenSlide** system library (`brew install openslide` on macOS)
- **PyTorch** compatible hardware (MPS on Apple Silicon, CUDA on NVIDIA, or CPU fallback)

---

## Installation and Setup

### 1. Clone the Repository

```bash
git clone https://github.com/rkallinenSlidekick.git
cd Slidekick
```

### 2. Environment Configuration

```bash
cp .env.example .env
# Edit .env with your database credentials and device preferences
```

Key environment variables (all prefixed with `SLIDEKICK_`):

| Variable | Default | Description |
|---|---|---|
| `SLIDEKICK_APP_NAME` | `Slidekick` | Application name (shown in `/health` response and OpenAPI docs) |
| `SLIDEKICK_DEBUG` | `false` | Enable verbose SQLAlchemy SQL/parameter logging |
| `SLIDEKICK_DB_HOST` | `localhost` | PostgreSQL host |
| `SLIDEKICK_DB_PORT` | `5432` | PostgreSQL port |
| `SLIDEKICK_DB_USER` | `slidekick` | Database user |
| `SLIDEKICK_DB_PASSWORD` | `slidekick_secret` | Database password |
| `SLIDEKICK_DB_NAME` | `slidekick` | Database name |
| `SLIDEKICK_SLIDES_DIR` | `slides` | Directory for WSI file storage |
| `SLIDEKICK_HOVERNET_MODEL` | `hovernet_fast-pannuke` | TIAToolbox pretrained model name |
| `SLIDEKICK_DEVICE` | *(auto-detect)* | PyTorch device: `mps`, `cuda`, or `cpu` |
| `SLIDEKICK_TILE_SIZE` | `256` | Default tile size (px) for HoVerNet inference |
| `SLIDEKICK_BATCH_SIZE` | `8` | Inference batch size |
| `SLIDEKICK_ALLOW_UNTRUSTED_MODEL_LOAD` | `false` | Permit model loading via unsafe `torch.load` (no `weights_only=True`) |
| `SLIDEKICK_DEFAULT_MPP` | `0.25` | Default Microns-Per-Pixel |
| `SLIDEKICK_CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Comma-separated list of allowed CORS origins |

### 3. Start the Database

```bash
docker compose up -d
```

This starts PostgreSQL 16 with PostGIS 3.4, bound to `127.0.0.1:5432`. The PostGIS extension is automatically created via `schema.sql`.

### 4. Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. Frontend Setup

```bash
cd frontend
npm install
```

---

## Running the Application

### Backend

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

On startup, the backend:
1. Creates a bounded thread pool (4 workers) for OpenSlide I/O and inference.
2. Loads and warms the HoVerNet model.
3. Verifies PostGIS connectivity.
4. Creates database tables if they do not already exist (idempotent).

### Frontend

```bash
cd frontend
npm run dev
```

The Vite dev server starts on `http://localhost:5173` and proxies `/api` requests to the backend at `http://localhost:8000`.

### Access the Application

Open `http://localhost:5173` in your browser.

---

## Project Structure

```
Slidekick/
  .env.example              # Environment variable template
  docker-compose.yml        # PostgreSQL + PostGIS container

  backend/
    requirements.txt        # Python dependencies
    app/
      main.py               # FastAPI app factory, lifespan, middleware
      config.py             # pydantic-settings configuration
      models/
        database.py         # Async engine, session factory, Base, init_models
        nucleus.py          # Slide, AnalysisBox, Nucleus ORM models
      routers/
        slides.py           # Upload, list, DZI, thumbnail endpoints
        inference.py        # Viewport inference with SSE streaming
        roi.py              # Spatial statistics and viewport nuclei
        boxes.py            # Analysis box CRUD
      schemas/
        nucleus.py          # Pydantic request/response schemas
      services/
        slide.py            # OpenSlide wrapper, DZI generation
        inference.py        # HoVerNet engine (TIAToolbox)
        bulk_insert.py      # Streaming bulk insert via asyncpg
        spatial.py          # PostGIS spatial query service
      spatial/
        transform.py        # Coordinate transformation engine
        schema.sql          # PostGIS extension init script
  slides/                   # WSI file storage directory

  frontend/
    index.html              # Entry HTML
    package.json            # Node dependencies
    vite.config.js          # Vite + proxy configuration
    src/
      main.jsx              # React entry point
      App.jsx               # Root component
      index.css             # Global styles, design tokens
      components/
        DeepZoomViewer.jsx  # Main WSI viewer with overlays
        NucleusOverlay.jsx  # Canvas layer for nucleus dots
        AnalysisBoxOverlay.jsx  # Canvas layer for box outlines
        VirtualMicrometer.jsx   # Scale bar component
        StatisticsPanel.jsx # Analysis dashboard sidebar
        SlidesList.jsx      # Slide list with thumbnails
        viewer/
          ViewerControls.jsx          # Inference and draw-mode buttons
          DrawModeOverlay.jsx         # Area selection mouse capture
          LiveSelectionRect.jsx       # Real-time drag rectangle
          PersistedSelectionRect.jsx  # Confirmed selection with resize
          ProgressOverlay.jsx         # Inference progress indicator
          StatusBar.jsx               # Bottom status bar
      hooks/
        useViewer.js            # OpenSeadragon lifecycle
        useNuclei.js            # Analysis box and nuclei state
        useDrawModeManager.js   # Draw mode side effects
        useSelectionTracker.js  # Selection viewport tracking
        useResizeHandler.js     # Selection resize handles
        useZoomTracker.js       # Zoom level tracking
        useOverlayCenterTracking.js  # Progress overlay centering
      services/
        api.js              # Axios and fetch API client
      stores/
        useViewerStore.js   # Zustand global state
      utils/
        coordinates.js      # Client-side coordinate math
```

---

## Documentation Index

| Document | Description |
|---|---|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System design, data flow diagrams (Mermaid), component relationships, and technology rationale |
| [API.md](./API.md) | Complete REST API reference with endpoints, parameters, and response schemas |
| [Legacy.md](./Legacy.md) | Unused code, empty files, and legacy patterns identified in the codebase |
| [TESTING.md](./TESTING.md) | Testing guide: what is tested, what is not, how to run tests, CI/CD configuration, and coverage details |

---

## License

This project is licensed under the MIT License. See [LICENSE](./LICENSE) for details.
