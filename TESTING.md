# Testing Guide for Slidekick Backend

This document explains what's tested, what's not tested, how to run tests, and how the automated testing pipeline works.

---

## Quick Start

Make sure that your venv is activated

### Running All Tests

```bash
cd backend
pytest tests/
```

### Running Tests with Coverage Report

```bash
cd backend
pytest tests/ --cov=app --cov-report=term-missing --cov-branch -v
```

### Running a Specific Test File

```bash
cd backend
pytest tests/test_routers_slides.py -v
```

### Running a Specific Test

```bash
cd backend
pytest tests/test_routers_slides.py::TestUploadSlide::test_no_filename_direct -v
```

---

## What's Tested (100% Coverage)

The test suite achieves **100% statement and branch coverage** with **299 passing tests** covering 1,128 lines of code and 170 decision branches.

### Configuration (`test_config.py` - 10 tests)

**What it tests:**
- Loading settings from environment variables (with `SLIDEKICK_` prefix)
- Default values when environment variables are missing
- Database connection string construction
- Invalid configuration handling

**Example:** Ensures `SLIDEKICK_DEVICE=mps` correctly sets the device to "mps" for Apple Silicon.

---

### Application Startup (`test_main.py` - 32 tests)

**What it tests:**

#### Security Middleware
- **Localhost-only access**: Blocks requests from non-loopback IP addresses (prevents remote access)
- **Trusted Host validation**: Rejects requests with unexpected Host headers (prevents DNS rebinding attacks)

#### Application Lifecycle
- **Startup**: Loading the HoVerNet ML model, monitoring for unsafe PyTorch operations
- **Shutdown**: Cleaning up database connections and POSIX semaphores (prevents resource leaks)
- **Health endpoint**: The `/health` endpoint returns proper status

#### Edge Cases
- What happens when PyTorch model loading uses unsafe deserialization
- What happens when environment doesn't support certain ML accelerators
- Cleanup of multiprocessing resources (semaphores) on macOS/Linux

**Why this matters:** Ensures the app starts safely, blocks unauthorized access, and cleans up properly.

---

### Database Models (`test_models_database.py`, `test_models_nucleus.py` - 20 tests)

**What it tests:**
- Database connection pooling and session management
- Table schemas (slides, nuclei, analysis boxes)
- Spatial data types (PostGIS geometry columns)
- UUID primary keys and timestamps
- Foreign key relationships and cascading deletes

**Example:** When you delete an analysis box, all its nuclei are automatically deleted too (CASCADE).

---

### Data Validation (`test_schemas.py` - 27 tests)

**What it tests:**
- Input validation for API requests (Pydantic schemas)
- Output serialization for API responses
- Required vs. optional fields
- Type checking (strings, numbers, UUIDs, dates)
- Nested object validation

**Example:** Creating an analysis box requires `slide_id`, `label`, and `box_geom_wkt`, but `cell_type_counts` is optional.

---

### Slide Upload & Management (`test_routers_slides.py` - 30 tests)

**What it tests:**

#### File Upload Security
- Rejecting unsupported file types (only `.svs`, `.ndpi`, `.tiff`, etc. allowed)
- Path traversal prevention (`../../etc/passwd.svs` → sanitized to `passwd.svs`)
- File size limits (rejects files > 10 GB)
- Empty or invalid filenames

#### Slide Operations
- Uploading whole-slide images (WSI)
- Listing all slides
- Fetching slide metadata (dimensions, resolution, etc.)
- Generating Deep Zoom Images (DZI) for web viewers
- Creating thumbnail images
- Rendering scale bars (visual reference for slide magnification)
- Deleting slides

**Why this matters:** Prevents attackers from uploading malicious files or accessing system files.

---

### ML Inference (`test_routers_inference.py`, `test_services_inference.py` - 64 tests)

**What it tests:**

#### Inference Engine
- Device selection (CPU, CUDA GPU, Apple MPS)
- Model loading and caching
- Tile-based processing of large images
- Progress tracking for long-running operations
- Nucleus detection and classification (6 cell types)
- Contour extraction from segmentation masks

#### API Endpoints
- Streaming inference with Server-Sent Events (SSE)
- Progress updates during processing
- Error handling when inference fails
- Creating analysis boxes from inference results
- Assigning unique labels ("Analysis 1", "Analysis 2", etc.)

#### Edge Cases
- Empty tiles (no nuclei detected)
- Very large tiles (dimension limits)
- Invalid viewport bounds
- Nuclei with tiny/huge areas
- Overlapping nuclei

**Note:** All ML model operations are **mocked** in unit tests because they are heavy

---

### Analysis Boxes & ROIs (`test_routers_boxes.py`, `test_routers_roi.py` - 36 tests)

**What it tests:**

#### Analysis Boxes
- Creating boxes with nucleus counts and cell type breakdowns
- Calculating statistics:
  - Inflammatory index
  - Immune-to-tumor ratio
  - Neoplastic-to-epithelial ratio
  - Cell viability (living vs. dead cells)
  - Shannon diversity index
- Handling edge cases (only dead cells, zero counts, division by zero)
- Deleting boxes

#### Regions of Interest (ROIs)
- Creating ROIs with polygon geometries
- Spatial queries (finding nuclei within a polygon)
- Filtering by cell type
- Pagination of large result sets
- Deleting ROIs

---

### Service Layer (`test_services_*.py` - 102 tests)

**What it tests:**

#### Bulk Database Operations
- Inserting thousands of nuclei efficiently (bulk insert)
- Transaction handling
- Retry logic for database errors

#### Slide Service
- Thread-local OpenSlide handles (prevents concurrency bugs)
- Reading WSI regions at specific coordinates
- Generating Deep Zoom tiles
- Cache invalidation
- Cleanup of file handles

#### Spatial Queries
- Finding nuclei within polygons (PostGIS)
- Coordinate transformations
- Viewport bounds calculations

**Why this matters:** These are the heavy-lifting components that must be rock-solid.

---

### Spatial Transformations (`test_spatial_transform.py` - 16 tests)

**What it tests:**
- Converting between pixel coordinates and microns
- Viewport bounds validation
- Coordinate clamping (preventing out-of-bounds access)
- MPP (microns-per-pixel) calculations

---

## What's NOT Tested

### Intentionally Excluded

1. **Real ML Model Execution**
   - TIAToolbox's HoVerNet model is mocked (its large)
   - Testing real inference would require downloading models and sample WSI files
   - Future work: Add integration tests with real models

2. **Real Database Operations**
   - All database calls are mocked using AsyncMock
   - Tests do not connect to an actual PostgreSQL database
   - Future work: Add integration tests with real database

3. **Database Schema Management**
   - Schema is created automatically via `init_models()` at startup
   - Schema creation is tested via mocks in `test_models_database.py`

4. **End-to-End Browser Testing**
   - Frontend integration is not tested

### Coverage Pragmas Explained

You'll see `# pragma: no cover` comments in three places. This directive tells the coverage tool to ignore these lines because they are genuinely untestable:

main.py line 301
```python
# 1. Module-level app instance (line runs before coverage starts)
app = create_app()  # pragma: no cover
```

main.py line 112
```python
# 2. Exception handler in atexit-registered cleanup (coverage.py can't measure it)
except Exception:  # pragma: no cover – atexit context prevents measurement
    pass
```

routers/inference.py line 94
```python
# 3. Defensive error handling after regex that guarantees valid input (unreachable)
except ValueError:  # pragma: no cover – regex \d+ guarantees valid int
    continue
```

## GitHub Actions CI/CD

### Automatic Testing (on every push/PR)

When you push code or open a pull request, GitHub Actions automatically:

1. Sets up Python 3.11.7 environment
2. Installs system dependencies (OpenSlide, GEOS, PROJ)
3. Installs Python dependencies from requirements.txt
4. Runs all tests with mocked database and ML models
5. Checks coverage is at least 99% (fails the build if below threshold)

**Workflow file:** `.github/workflows/backend-tests.yml`

**Triggers:**
- Push to `main` or `develop` branches (only when `backend/` files change)
- Pull requests targeting `main` or `develop`

**Important:** Current tests use mocked database calls (AsyncMock) for speed and isolation. A PostgreSQL+PostGIS database is not required for these tests to run.

---

## Test Architecture

### Directory Structure

```
backend/tests/
├── conftest.py              # Shared fixtures & test utilities
├── test_config.py           # Configuration tests
├── test_main.py             # App startup, middleware, lifecycle
├── test_models_*.py         # Database model tests
├── test_schemas.py          # Pydantic schema tests
├── test_routers_*.py        # API endpoint tests (4 files)
├── test_services_*.py       # Business logic tests (4 files)
├── test_spatial_*.py        # Geometry & coordinate tests
└── test_imports.py          # Smoke test (verifies all modules are importable)
```


## Common Tasks

### Running Specific Test Categories

```bash
# Only router tests (API endpoints)
pytest tests/test_routers_*.py

# Only service layer
pytest tests/test_services_*.py

# Only model tests
pytest tests/test_models_*.py
```

### Debugging Failed Tests

```bash
# Show full error traces
pytest tests/ -vv --tb=long

# Stop on first failure
pytest tests/ -x

# Run last failed tests
pytest tests/ --lf

# Print statements in tests (use print() for debugging)
pytest tests/ -s
```

### Coverage Reports

```bash
# Terminal report with missing lines
pytest tests/ --cov=app --cov-report=term-missing

# HTML report (opens in browser)
pytest tests/ --cov=app --cov-report=html
open htmlcov/index.html

# XML report (for CI tools)
pytest tests/ --cov=app --cov-report=xml
```

---

### "FileNotFoundError: No such file or directory" in multiprocessing cleanup

**What you see:**
```
FileNotFoundError: [Errno 2] No such file or directory
  File ".../multiprocessing/synchronize.py", line 87, in _cleanup
    sem_unlink(name)
```

**Why it happens:**
- Third-party libraries (specifically `numcodecs.blosc`) create POSIX semaphores at import time
- During test shutdown, the application's `lifespan` cleanup explicitly unlinks these semaphores
- Python's `atexit` handler then attempts to clean up the same semaphores and fails
- This is **expected behavior** -- the semaphores have already been cleaned up correctly

**Is it a problem?**
- No. All tests pass successfully.
- The error happens AFTER tests complete
- It is a harmless race condition in cleanup order
- It only happens during test process exit