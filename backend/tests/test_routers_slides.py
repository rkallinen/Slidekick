"""
Tests for app.routers.slides — Upload, list, get, DZI, thumbnail, scale-bar.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers.slides import router, _ALLOWED_EXTENSIONS, _MAX_UPLOAD_BYTES
from tests.conftest import SAMPLE_SLIDE_ID, make_slide_row


def _create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


@pytest.fixture()
def app():
    return _create_test_app()


@pytest.fixture()
def mock_db():
    return AsyncMock()


@pytest.fixture()
def client(app, mock_db):
    from app.models.database import get_db

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════
class TestConstants:
    def test_allowed_extensions(self):
        assert ".svs" in _ALLOWED_EXTENSIONS
        assert ".ndpi" in _ALLOWED_EXTENSIONS
        assert ".tiff" in _ALLOWED_EXTENSIONS
        assert ".jpg" not in _ALLOWED_EXTENSIONS

    def test_max_upload_bytes(self):
        assert _MAX_UPLOAD_BYTES == 10 * 1024 * 1024 * 1024


# ═══════════════════════════════════════════════════════════════════
# POST /slides/upload
# ═══════════════════════════════════════════════════════════════════
class TestUploadSlide:
    @pytest.mark.asyncio
    async def test_no_filename(self, client, mock_db):
        """Empty filename should return 400 or 422 (multipart validation)."""
        resp = await client.post(
            "/api/slides/upload",
            files={"file": ("", b"data")},
        )
        # Empty filename is caught either by multipart validation (422)
        # or by our handler (400) — both are correct rejections.
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_no_filename_direct(self, mock_db):
        """Directly call upload_slide with filename=None to hit line 65."""
        from app.routers.slides import upload_slide
        from fastapi import HTTPException

        mock_file = MagicMock()
        mock_file.filename = None
        with pytest.raises(HTTPException) as exc_info:
            await upload_slide(file=mock_file, db=mock_db)
        assert exc_info.value.status_code == 400
        assert "No filename" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_unsupported_extension(self, client, mock_db):
        resp = await client.post(
            "/api/slides/upload",
            files={"file": ("test.jpg", b"data", "image/jpeg")},
        )
        assert resp.status_code == 400
        assert "Unsupported" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_path_traversal_sanitized(self, client, mock_db):
        """Path traversal in filename should be stripped."""
        # The filename "../../etc/passwd.svs" should be sanitized
        # to just "passwd.svs" and then processed normally.
        # It will fail at the OpenSlide stage, not path traversal.
        with patch("app.routers.slides.SlideService") as MockSvc:
            MockSvc.side_effect = Exception("test")
            resp = await client.post(
                "/api/slides/upload",
                files={"file": ("../../etc/passwd.svs", b"fake", "application/octet-stream")},
            )
            # Should either succeed or fail at WSI open, not with path traversal
            assert resp.status_code in (201, 422)

    @pytest.mark.asyncio
    @patch("app.routers.slides.SlideService")
    async def test_successful_upload(self, mock_svc_cls, client, mock_db, tmp_path):
        """Test the full upload path with mocked file I/O."""
        mock_svc = MagicMock()
        mock_svc.slide_info.return_value = {
            "filename": "test.svs",
            "filepath": str(tmp_path / "test.svs"),
            "mpp": 0.25,
            "width_px": 10000,
            "height_px": 8000,
            "width_mm": 2.5,
            "height_mm": 2.0,
            "level_count": 5,
            "magnification": "40",
            "vendor": "aperio",
        }
        mock_svc_cls.return_value = mock_svc

        # Capture the Slide object added to the session and mock refresh to
        # populate the fields that the DB would normally set.
        added_objects = []
        def capture_add(obj):
            added_objects.append(obj)
            # Simulate what the DB would set after flush
            obj.id = uuid.uuid4()
            obj.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        mock_db.add = capture_add
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch("app.routers.slides.settings") as mock_settings:
            mock_settings.slides_dir = str(tmp_path)
            with patch("builtins.open", MagicMock()):
                with patch("shutil.copyfileobj"):
                    resp = await client.post(
                        "/api/slides/upload",
                        files={"file": ("test.svs", b"fakedata", "application/octet-stream")},
                    )

        assert resp.status_code == 201
        assert len(added_objects) == 1
        assert added_objects[0].filename == "test.svs"

    @pytest.mark.asyncio
    async def test_file_too_large(self, client, mock_db, tmp_path):
        """Files exceeding _MAX_UPLOAD_BYTES should be rejected with 413."""
        import io
        fake_content = b"x" * 100

        with (
            patch("app.routers.slides.settings") as mock_settings,
            patch("app.routers.slides._MAX_UPLOAD_BYTES", 10),  # 10 bytes max
        ):
            mock_settings.slides_dir = str(tmp_path)

            resp = await client.post(
                "/api/slides/upload",
                files={"file": ("big.svs", fake_content, "application/octet-stream")},
            )
            assert resp.status_code == 413
            assert "too large" in resp.json()["detail"]

    @pytest.mark.asyncio
    @patch("app.routers.slides.SlideService")
    async def test_upload_invalid_basename(self, mock_svc_cls, client, mock_db, tmp_path):
        """PurePosixPath('.').name → '.' with no valid extension → 400."""
        resp = await client.post(
            "/api/slides/upload",
            files={"file": (".", b"data", "application/octet-stream")},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_empty_basename(self, client, mock_db, tmp_path):
        """Filename '/' produces empty basename after sanitization → 400."""
        resp = await client.post(
            "/api/slides/upload",
            files={"file": ("/", b"data", "application/octet-stream")},
        )
        assert resp.status_code in (400, 422)  # Empty basename or multipart rejection

    @pytest.mark.asyncio
    @patch("app.routers.slides.SlideService")
    async def test_upload_wsi_open_failure(self, mock_svc_cls, client, mock_db, tmp_path):
        """When SlideService raises, the file is cleaned up and 422 returned."""
        mock_svc_cls.side_effect = Exception("Not a valid WSI")

        with patch("app.routers.slides.settings") as mock_settings:
            mock_settings.slides_dir = str(tmp_path)
            resp = await client.post(
                "/api/slides/upload",
                files={"file": ("test.svs", b"fakedata", "application/octet-stream")},
            )
        assert resp.status_code == 422
        assert "Failed to open WSI" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_path_escape(self, client, mock_db, tmp_path):
        """When resolved dest escapes slides_dir, return 400 (line 92)."""
        from pathlib import Path

        with patch("app.routers.slides.settings") as mock_settings:
            mock_settings.slides_dir = str(tmp_path)

            original_resolve = Path.resolve

            def hijack_resolve(self, strict=False):
                r = original_resolve(self, strict=strict)
                # If this is a UUID-named .svs file (i.e. the dest), redirect outside
                if str(r).endswith(".svs") and str(tmp_path) in str(r):
                    return Path("/etc/evil") / self.name
                return r

            with patch.object(Path, "resolve", hijack_resolve):
                resp = await client.post(
                    "/api/slides/upload",
                    files={"file": ("test.svs", b"fakedata", "application/octet-stream")},
                )
            assert resp.status_code == 400
            assert "Invalid file path" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════
# GET /slides/
# ═══════════════════════════════════════════════════════════════════
class TestListSlides:
    @pytest.mark.asyncio
    async def test_list_slides_empty(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        resp = await client.get("/api/slides/")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_slides_with_data(self, client, mock_db):
        slide = make_slide_row()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [slide]
        mock_db.execute.return_value = mock_result

        resp = await client.get("/api/slides/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1


# ═══════════════════════════════════════════════════════════════════
# GET /slides/{slide_id}
# ═══════════════════════════════════════════════════════════════════
class TestGetSlide:
    @pytest.mark.asyncio
    async def test_slide_not_found(self, client, mock_db):
        mock_db.get.return_value = None
        resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_slide_success(self, client, mock_db):
        mock_db.get.return_value = make_slide_row()
        resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test.svs"


# ═══════════════════════════════════════════════════════════════════
# GET /slides/{slide_id}/dzi
# ═══════════════════════════════════════════════════════════════════
class TestGetDZI:
    @pytest.mark.asyncio
    async def test_dzi_slide_not_found(self, client, mock_db):
        mock_db.get.return_value = None
        resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}/dzi")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    @patch("app.routers.slides.get_slide_service")
    async def test_dzi_success(self, mock_svc_fn, client, mock_db):
        mock_db.get.return_value = make_slide_row()
        mock_svc = MagicMock()
        mock_svc.get_dzi_xml.return_value = '<Image TileSize="254"/>'
        mock_svc_fn.return_value = mock_svc

        resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}/dzi")
        assert resp.status_code == 200
        assert "TileSize" in resp.text


# ═══════════════════════════════════════════════════════════════════
# GET /slides/{slide_id}/dzi_files/{level}/{col}_{row}.jpeg
# ═══════════════════════════════════════════════════════════════════
class TestGetDZITile:
    @pytest.mark.asyncio
    async def test_tile_slide_not_found(self, client, mock_db):
        mock_db.get.return_value = None
        resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}/dzi_files/12/5_3.jpeg")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    @patch("app.routers.slides.get_slide_service")
    async def test_tile_success(self, mock_svc_fn, client, mock_db):
        mock_db.get.return_value = make_slide_row()
        mock_svc = MagicMock()
        mock_svc.get_dzi_tile.return_value = b"\xff\xd8\xff\xe0"  # JPEG magic bytes
        mock_svc_fn.return_value = mock_svc

        resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}/dzi_files/12/5_3.jpeg")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"

    @pytest.mark.asyncio
    @patch("app.routers.slides.get_slide_service")
    async def test_tile_not_found(self, mock_svc_fn, client, mock_db):
        mock_db.get.return_value = make_slide_row()
        mock_svc = MagicMock()
        mock_svc.get_dzi_tile.side_effect = ValueError("Invalid tile")
        mock_svc_fn.return_value = mock_svc

        resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}/dzi_files/99/99_99.jpeg")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# GET /slides/{slide_id}/scale-bar
# ═══════════════════════════════════════════════════════════════════
class TestScaleBar:
    @pytest.mark.asyncio
    async def test_scale_bar_slide_not_found(self, client, mock_db):
        mock_db.get.return_value = None
        resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}/scale-bar")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_scale_bar_default(self, client, mock_db):
        mock_db.get.return_value = make_slide_row()
        resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}/scale-bar")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_um"] == 100.0
        assert data["level"] == 0
        assert data["mpp"] == 0.25
        # 100 / 0.25 = 400
        assert data["pixels_at_level"] == 400.0

    @pytest.mark.asyncio
    async def test_scale_bar_custom_params(self, client, mock_db):
        mock_db.get.return_value = make_slide_row()
        resp = await client.get(
            f"/api/slides/{SAMPLE_SLIDE_ID}/scale-bar?target_um=50&level=1"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_um"] == 50.0
        assert data["level"] == 1
        # 50 / (0.25 * 2) = 100
        assert data["pixels_at_level"] == 100.0


# ═══════════════════════════════════════════════════════════════════
# GET /slides/{slide_id}/thumbnail
# ═══════════════════════════════════════════════════════════════════
class TestThumbnail:
    @pytest.mark.asyncio
    async def test_thumbnail_slide_not_found(self, client, mock_db):
        mock_db.get.return_value = None
        resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}/thumbnail")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    @patch("app.routers.slides.get_slide_service")
    async def test_thumbnail_cached(self, mock_svc_fn, client, mock_db, tmp_path):
        """When a cached thumbnail exists, it should be served directly."""
        mock_db.get.return_value = make_slide_row()

        with patch("app.routers.slides.settings") as mock_settings:
            mock_settings.slides_dir = str(tmp_path)

            # Create cached thumbnail
            cache_dir = tmp_path / ".thumbnails"
            cache_dir.mkdir()
            cache_file = cache_dir / f"{SAMPLE_SLIDE_ID}_200.jpg"
            cache_file.write_bytes(b"\xff\xd8fake_jpeg")

            resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}/thumbnail")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "image/jpeg"

    @pytest.mark.asyncio
    @patch("app.routers.slides.get_slide_service")
    async def test_thumbnail_generated(self, mock_svc_fn, client, mock_db, tmp_path):
        """When no cached thumbnail exists, generate and cache it."""
        from PIL import Image as PILImage

        mock_db.get.return_value = make_slide_row()

        mock_svc = MagicMock()
        mock_svc.level_count = 3
        mock_svc.level_dimensions = [(10000, 8000), (5000, 4000), (2500, 2000)]
        mock_svc_fn.return_value = mock_svc

        # Create a real small image that the mocked OpenSlide would return
        test_img = PILImage.new("RGBA", (2500, 2000), (255, 0, 0, 255))

        with patch("app.routers.slides.settings") as mock_settings:
            mock_settings.slides_dir = str(tmp_path)

            with patch("app.services.slide._tls_open") as mock_tls_open:
                mock_slide_handle = MagicMock()
                mock_slide_handle.read_region.return_value = test_img
                mock_tls_open.return_value = mock_slide_handle

                resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}/thumbnail")
                assert resp.status_code == 200
                assert resp.headers["content-type"] == "image/jpeg"

                # Verify the thumbnail was cached
                cache_file = tmp_path / ".thumbnails" / f"{SAMPLE_SLIDE_ID}_200.jpg"
                assert cache_file.exists()

    @pytest.mark.asyncio
    @patch("app.routers.slides.get_slide_service")
    async def test_thumbnail_generation_error(self, mock_svc_fn, client, mock_db, tmp_path):
        """When thumbnail generation fails, return 500."""
        mock_db.get.return_value = make_slide_row()

        mock_svc = MagicMock()
        mock_svc.level_count = 3
        mock_svc.level_dimensions = [(10000, 8000), (5000, 4000), (2500, 2000)]
        mock_svc_fn.return_value = mock_svc

        with patch("app.routers.slides.settings") as mock_settings:
            mock_settings.slides_dir = str(tmp_path)

            with patch("app.services.slide._tls_open") as mock_tls_open:
                mock_tls_open.side_effect = RuntimeError("OpenSlide error")

                resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}/thumbnail")
                assert resp.status_code == 500
                assert "Failed to generate thumbnail" in resp.json()["detail"]

    @pytest.mark.asyncio
    @patch("app.routers.slides.get_slide_service")
    async def test_thumbnail_no_downscale_needed(self, mock_svc_fn, client, mock_db, tmp_path):
        """When the lowest-resolution level is already small, no downscale needed."""
        from PIL import Image as PILImage

        mock_db.get.return_value = make_slide_row()

        mock_svc = MagicMock()
        mock_svc.level_count = 3
        mock_svc.level_dimensions = [(10000, 8000), (5000, 4000), (100, 80)]
        mock_svc_fn.return_value = mock_svc

        # Small image (100x80) — smaller than max_size (200)
        test_img = PILImage.new("RGBA", (100, 80), (0, 255, 0, 255))

        with patch("app.routers.slides.settings") as mock_settings:
            mock_settings.slides_dir = str(tmp_path)

            with patch("app.services.slide._tls_open") as mock_tls_open:
                mock_slide_handle = MagicMock()
                mock_slide_handle.read_region.return_value = test_img
                mock_tls_open.return_value = mock_slide_handle

                resp = await client.get(f"/api/slides/{SAMPLE_SLIDE_ID}/thumbnail")
                assert resp.status_code == 200
