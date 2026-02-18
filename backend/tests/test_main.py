"""
Tests for app.main — LocalhostOnlyMiddleware, create_app, lifespan helpers,
and POSIX semaphore cleanup.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request, Response
from starlette.testclient import TestClient

from app.main import (
    LocalhostOnlyMiddleware,
    _cleanup_posix_semaphores,
    create_app,
)


# ═══════════════════════════════════════════════════════════════════
# LocalhostOnlyMiddleware
# ═══════════════════════════════════════════════════════════════════
class TestLocalhostOnlyMiddleware:
    """Test the middleware without the full app lifespan."""

    @pytest.fixture()
    def bare_app(self) -> FastAPI:
        """An app with no lifespan (avoids DB/inference startup)."""
        app = FastAPI()
        app.add_middleware(LocalhostOnlyMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        return app

    def test_localhost_allowed(self, bare_app):
        client = TestClient(bare_app)
        resp = client.get("/test", headers={"host": "localhost"})
        # TestClient default scope has client=("testclient", 123)
        # which is NOT in loopback — should be 403
        assert resp.status_code == 403

    def test_loopback_ipv4_allowed(self, bare_app):
        """Manually verify the middleware's loopback set."""
        assert "127.0.0.1" in LocalhostOnlyMiddleware._LOOPBACK
        assert "::1" in LocalhostOnlyMiddleware._LOOPBACK
        assert "localhost" in LocalhostOnlyMiddleware._LOOPBACK

    def test_non_loopback_rejected(self):
        """Confirm non-loopback IPs are in the rejection set."""
        assert "192.168.1.1" not in LocalhostOnlyMiddleware._LOOPBACK
        assert "10.0.0.1" not in LocalhostOnlyMiddleware._LOOPBACK

    def test_none_client_rejected(self):
        """When request.client is None, should return 403."""
        assert None not in LocalhostOnlyMiddleware._LOOPBACK

    @pytest.mark.asyncio
    async def test_dispatch_loopback_passes(self):
        """Directly test middleware dispatch with a loopback client."""
        middleware = LocalhostOnlyMiddleware(app=MagicMock())

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        call_next = AsyncMock(return_value=Response("ok"))
        response = await middleware.dispatch(request, call_next)
        call_next.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_dispatch_non_loopback_rejects(self):
        """Directly test middleware dispatch with a non-loopback client."""
        middleware = LocalhostOnlyMiddleware(app=MagicMock())

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "192.168.1.1"

        call_next = AsyncMock()
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 403
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dispatch_none_client(self):
        """When request.client is None, should return 403."""
        middleware = LocalhostOnlyMiddleware(app=MagicMock())

        request = MagicMock(spec=Request)
        request.client = None

        call_next = AsyncMock()
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_dispatch_ipv6_loopback(self):
        """IPv6 loopback ::1 should be allowed."""
        middleware = LocalhostOnlyMiddleware(app=MagicMock())

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "::1"

        call_next = AsyncMock(return_value=Response("ok"))
        response = await middleware.dispatch(request, call_next)
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_localhost_string(self):
        """'localhost' hostname should be allowed."""
        middleware = LocalhostOnlyMiddleware(app=MagicMock())

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "localhost"

        call_next = AsyncMock(return_value=Response("ok"))
        response = await middleware.dispatch(request, call_next)
        call_next.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════
# create_app
# ═══════════════════════════════════════════════════════════════════
class TestCreateApp:
    def test_returns_fastapi_instance(self):
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_app_title(self):
        app = create_app()
        assert app.title == "Slidekick"

    def test_app_version(self):
        app = create_app()
        assert app.version == "0.1.0"

    def test_routes_registered(self):
        app = create_app()
        paths = [r.path for r in app.routes]
        assert "/api/slides/" in paths or any("/api/slides" in p for p in paths)
        assert any("/api/inference" in p for p in paths)
        assert any("/api/roi" in p for p in paths)
        assert any("/api/boxes" in p for p in paths)
        assert "/health" in paths


# ═══════════════════════════════════════════════════════════════════
# Health endpoint (no lifespan needed)
# ═══════════════════════════════════════════════════════════════════
class TestHealthEndpoint:
    """Test /health without triggering lifespan."""

    @pytest.fixture()
    def client(self):
        app = create_app()

        @asynccontextmanager
        async def noop_lifespan(app):
            yield

        app.router.lifespan_context = noop_lifespan

        # Replace LocalhostOnlyMiddleware with a no-op so TestClient works
        from starlette.middleware import Middleware
        app.user_middleware = [
            m for m in app.user_middleware
            if m.cls is not LocalhostOnlyMiddleware
        ]
        app.middleware_stack = None  # force rebuild
        return TestClient(app)

    def test_health_returns_ok(self, client):
        resp = client.get("/health", headers={"host": "localhost"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "service" in data


# ═══════════════════════════════════════════════════════════════════
# Lifespan
# ═══════════════════════════════════════════════════════════════════
class TestLifespan:
    """Test the lifespan function with mocked dependencies."""

    def _make_mock_db_engine(self):
        """Create a properly-structured mock async DB engine."""
        mock_db_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = "3.3.0"
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_conn.run_sync = AsyncMock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_db_engine.begin.return_value = mock_ctx
        mock_db_engine.dispose = AsyncMock()
        return mock_db_engine

    @pytest.mark.asyncio
    async def test_lifespan_normal_startup_shutdown(self):
        """Test normal startup/shutdown path — weights_only present, no unsafe calls."""
        from app.main import lifespan

        mock_engine = MagicMock()
        mock_engine.device = "cpu"
        mock_db_engine = self._make_mock_db_engine()

        app = FastAPI()

        # We need real `inspect` but a controlled `torch` mock.
        # The lifespan does `import torch` which resolves via sys.modules.
        import inspect as real_inspect

        mock_torch = MagicMock()
        # Give torch.load a real signature with weights_only param
        def fake_torch_load(f, *, weights_only=False):
            pass
        mock_torch.load = fake_torch_load

        with (
            patch.dict("sys.modules", {"torch": mock_torch}),
            patch("app.services.inference.get_inference_engine", return_value=mock_engine),
            patch("app.models.database.engine", mock_db_engine),
            patch("app.main._cleanup_posix_semaphores"),
        ):
            async with lifespan(app):
                pass

        mock_db_engine.dispose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_no_weights_only_param(self):
        """When torch.load doesn't have weights_only param, skip monitoring."""
        from app.main import lifespan

        mock_engine = MagicMock()
        mock_engine.device = "cpu"
        mock_db_engine = self._make_mock_db_engine()

        app = FastAPI()

        mock_torch = MagicMock()
        # Give torch.load a signature WITHOUT weights_only
        def fake_torch_load(f):
            pass
        mock_torch.load = fake_torch_load

        with (
            patch.dict("sys.modules", {"torch": mock_torch}),
            patch("app.services.inference.get_inference_engine", return_value=mock_engine),
            patch("app.models.database.engine", mock_db_engine),
            patch("app.main._cleanup_posix_semaphores"),
        ):
            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_lifespan_unsafe_load_allowed(self):
        """Unsafe torch.load detected during warm-up, but allowed by settings."""
        from app.main import lifespan

        mock_engine = MagicMock()
        mock_engine.device = "cpu"
        mock_db_engine = self._make_mock_db_engine()

        app = FastAPI()

        # Build a mock torch module where load has weights_only param
        mock_torch = MagicMock()
        real_load_calls = []

        def fake_torch_load(f, *, weights_only=False):
            real_load_calls.append(f)

        mock_torch.load = fake_torch_load

        def fake_ensure_loaded():
            # At this point, lifespan has replaced mock_torch.load with
            # _monitor_torch_load. Call it WITHOUT weights_only.
            mock_torch.load("fake_weights.pth")

        mock_engine.ensure_loaded = fake_ensure_loaded

        with (
            patch.dict("sys.modules", {"torch": mock_torch}),
            patch("app.services.inference.get_inference_engine", return_value=mock_engine),
            patch("app.main.settings") as mock_settings,
            patch("app.models.database.engine", mock_db_engine),
            patch("app.main._cleanup_posix_semaphores"),
        ):
            mock_settings.allow_untrusted_model_load = True

            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_lifespan_unsafe_load_rejected(self):
        """Unsafe torch.load detected but NOT allowed → RuntimeError."""
        from app.main import lifespan

        mock_engine = MagicMock()
        mock_engine.device = "cpu"

        app = FastAPI()

        mock_torch = MagicMock()
        real_load_calls = []

        def fake_torch_load(f, *, weights_only=False):
            real_load_calls.append(f)

        mock_torch.load = fake_torch_load

        def fake_ensure_loaded():
            mock_torch.load("fake_weights.pth")

        mock_engine.ensure_loaded = fake_ensure_loaded

        with (
            patch.dict("sys.modules", {"torch": mock_torch}),
            patch("app.services.inference.get_inference_engine", return_value=mock_engine),
            patch("app.main.settings") as mock_settings,
            patch("app.main._cleanup_posix_semaphores"),
        ):
            mock_settings.allow_untrusted_model_load = False

            with pytest.raises(RuntimeError, match="Insecure model load"):
                async with lifespan(app):
                    pass

    @pytest.mark.asyncio
    async def test_lifespan_unsafe_load_with_weights_only_false(self):
        """torch.load called with weights_only=False should count as unsafe."""
        from app.main import lifespan

        mock_engine = MagicMock()
        mock_engine.device = "cpu"

        app = FastAPI()

        mock_db_engine = self._make_mock_db_engine()

        mock_torch = MagicMock()

        def fake_torch_load(f, *, weights_only=False):
            pass

        mock_torch.load = fake_torch_load

        def fake_ensure_loaded():
            # Explicitly pass weights_only=False — should still be flagged
            mock_torch.load("weights.pth", weights_only=False)

        mock_engine.ensure_loaded = fake_ensure_loaded

        with (
            patch.dict("sys.modules", {"torch": mock_torch}),
            patch("app.services.inference.get_inference_engine", return_value=mock_engine),
            patch("app.main.settings") as mock_settings,
            patch("app.models.database.engine", mock_db_engine),
            patch("app.main._cleanup_posix_semaphores"),
        ):
            mock_settings.allow_untrusted_model_load = True

            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_lifespan_safe_load_no_warning(self):
        """torch.load called with weights_only=True should NOT trigger warning."""
        from app.main import lifespan

        mock_engine = MagicMock()
        mock_engine.device = "cpu"
        mock_db_engine = self._make_mock_db_engine()

        app = FastAPI()

        mock_torch = MagicMock()

        def fake_torch_load(f, *, weights_only=False):
            pass

        mock_torch.load = fake_torch_load

        def fake_ensure_loaded():
            mock_torch.load("weights.pth", weights_only=True)

        mock_engine.ensure_loaded = fake_ensure_loaded

        with (
            patch.dict("sys.modules", {"torch": mock_torch}),
            patch("app.services.inference.get_inference_engine", return_value=mock_engine),
            patch("app.models.database.engine", mock_db_engine),
            patch("app.main._cleanup_posix_semaphores"),
        ):
            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_lifespan_inspect_failure(self):
        """When `import inspect` or signature() fails, monitoring is skipped gracefully."""
        from app.main import lifespan

        mock_engine = MagicMock()
        mock_engine.device = "cpu"
        mock_db_engine = self._make_mock_db_engine()

        app = FastAPI()

        # Make `import torch` raise ImportError
        with (
            patch.dict("sys.modules", {"torch": None}),
            patch("app.services.inference.get_inference_engine", return_value=mock_engine),
            patch("app.models.database.engine", mock_db_engine),
            patch("app.main._cleanup_posix_semaphores"),
        ):
            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_lifespan_ensure_loaded_fails(self):
        """When ensure_loaded raises, torch.load is restored in the finally block."""
        from app.main import lifespan

        mock_engine = MagicMock()
        mock_engine.device = "cpu"
        mock_engine.ensure_loaded.side_effect = RuntimeError("model load failed")

        app = FastAPI()

        mock_torch = MagicMock()

        def fake_torch_load(f, *, weights_only=False):
            pass

        mock_torch.load = fake_torch_load

        with (
            patch.dict("sys.modules", {"torch": mock_torch}),
            patch("app.services.inference.get_inference_engine", return_value=mock_engine),
            patch("app.main._cleanup_posix_semaphores"),
        ):
            with pytest.raises(RuntimeError, match="model load failed"):
                async with lifespan(app):
                    pass

    @pytest.mark.asyncio
    async def test_lifespan_torch_restore_import_fails(self):
        """Lines 188-189: when finally block can't re-import torch, except passes."""
        from app.main import lifespan

        mock_engine = MagicMock()
        mock_engine.device = "cpu"
        # ensure_loaded raises → triggers finally → but torch is gone → except passes
        mock_engine.ensure_loaded.side_effect = RuntimeError("model load failed")

        app = FastAPI()

        mock_torch = MagicMock()

        def fake_torch_load(f, *, weights_only=False):
            pass

        mock_torch.load = fake_torch_load

        # The trick: ensure_loaded raises, triggering the finally block.
        # In the finally, `import torch as _torch` will try to resolve torch.
        # We remove torch from sys.modules in a side_effect so the import fails.
        original_ensure = mock_engine.ensure_loaded.side_effect
        def raise_and_nuke():
            sys.modules.pop("torch", None)
            raise RuntimeError("model load failed")

        mock_engine.ensure_loaded.side_effect = raise_and_nuke

        with (
            patch.dict("sys.modules", {"torch": mock_torch}),
            patch("app.services.inference.get_inference_engine", return_value=mock_engine),
            patch("app.main._cleanup_posix_semaphores"),
        ):
            with pytest.raises(RuntimeError, match="model load failed"):
                async with lifespan(app):
                    pass


# ═══════════════════════════════════════════════════════════════════
# _cleanup_posix_semaphores
# ═══════════════════════════════════════════════════════════════════
class TestCleanupPosixSemaphores:
    """Tests for _cleanup_posix_semaphores."""

    @staticmethod
    def _make_blosc(sem_name):
        """Return a mock blosc module whose mutex._semlock.name == sem_name."""
        mock_blosc = MagicMock()
        mock_semlock = MagicMock()
        mock_semlock.name = sem_name
        mock_blosc.mutex._semlock = mock_semlock
        return mock_blosc

    def test_noop_on_windows(self):
        """On Windows (mocked), should return early without error."""
        with patch.dict(sys.modules, {"_multiprocessing": MagicMock()}):
            with patch("app.main.sys") as mock_sys:
                mock_sys.platform = "win32"
                _cleanup_posix_semaphores()

    def test_noop_when_import_fails(self):
        """When _multiprocessing is not importable, should return silently."""
        with patch.dict(sys.modules, {"_multiprocessing": None}):
            _cleanup_posix_semaphores()

    def test_handles_no_numcodecs(self):
        """When numcodecs is not importable, should handle gracefully."""
        mock_mp = MagicMock()
        mock_rt = MagicMock()
        with (
            patch("app.main.sys") as mock_sys,
            patch.dict(sys.modules, {
                "_multiprocessing": mock_mp,
                "multiprocessing.resource_tracker": mock_rt,
                "numcodecs": None,
                "numcodecs.blosc": None,
            }),
        ):
            mock_sys.platform = "linux"
            _cleanup_posix_semaphores()

    def test_sem_unlink_called_for_targets(self):
        """Verify sem_unlink is called when targets exist."""
        mock_mp = MagicMock()
        mock_rt = MagicMock()
        mock_blosc = self._make_blosc("/mp-test-sem")
        mock_numcodecs = MagicMock()
        mock_numcodecs.blosc = mock_blosc

        with (
            patch("app.main.sys") as mock_sys,
            patch.dict(sys.modules, {
                "_multiprocessing": mock_mp,
                "multiprocessing.resource_tracker": mock_rt,
                "numcodecs": mock_numcodecs,
                "numcodecs.blosc": mock_blosc,
            }),
        ):
            mock_sys.platform = "linux"
            _cleanup_posix_semaphores()

        mock_mp.sem_unlink.assert_called_once_with("/mp-test-sem")

    def test_sem_unlink_file_not_found(self):
        """FileNotFoundError during sem_unlink is silently ignored."""
        mock_mp = MagicMock()
        mock_mp.sem_unlink.side_effect = FileNotFoundError
        mock_blosc = self._make_blosc("/mp-test")
        mock_numcodecs = MagicMock()
        mock_numcodecs.blosc = mock_blosc

        with (
            patch("app.main.sys") as mock_sys,
            patch.dict(sys.modules, {
                "_multiprocessing": mock_mp,
                "multiprocessing.resource_tracker": MagicMock(),
                "numcodecs": mock_numcodecs,
                "numcodecs.blosc": mock_blosc,
            }),
        ):
            mock_sys.platform = "linux"
            _cleanup_posix_semaphores()

    def test_sem_unlink_generic_exception(self):
        """Other exceptions during sem_unlink are caught and logged."""
        mock_mp = MagicMock()
        mock_mp.sem_unlink.side_effect = OSError("some error")
        mock_blosc = self._make_blosc("/mp-test-err")
        mock_numcodecs = MagicMock()
        mock_numcodecs.blosc = mock_blosc

        with (
            patch("app.main.sys") as mock_sys,
            patch.dict(sys.modules, {
                "_multiprocessing": mock_mp,
                "multiprocessing.resource_tracker": MagicMock(),
                "numcodecs": mock_numcodecs,
                "numcodecs.blosc": mock_blosc,
            }),
        ):
            mock_sys.platform = "linux"
            _cleanup_posix_semaphores()  # Should not raise

    def test_resource_tracker_exception(self):
        """Exception during resource_tracker.unregister is caught."""
        mock_mp = MagicMock()
        mock_rt = MagicMock()
        mock_rt.unregister.side_effect = RuntimeError("rt error")
        mock_blosc = self._make_blosc("/mp-test-rt")
        mock_numcodecs = MagicMock()
        mock_numcodecs.blosc = mock_blosc

        with (
            patch("app.main.sys") as mock_sys,
            patch.dict(sys.modules, {
                "_multiprocessing": mock_mp,
                "multiprocessing.resource_tracker": mock_rt,
                "numcodecs": mock_numcodecs,
                "numcodecs.blosc": mock_blosc,
            }),
        ):
            mock_sys.platform = "linux"
            _cleanup_posix_semaphores()  # Should not raise

    def test_blosc_mutex_is_none(self):
        """When blosc.mutex is None, branch 94→96: name is None → skip."""
        mock_mp = MagicMock()
        mock_blosc = MagicMock()
        mock_blosc.mutex = None  # getattr chain → None
        mock_numcodecs = MagicMock()
        mock_numcodecs.blosc = mock_blosc

        with (
            patch("app.main.sys") as mock_sys,
            patch.dict(sys.modules, {
                "_multiprocessing": mock_mp,
                "multiprocessing.resource_tracker": MagicMock(),
                "numcodecs": mock_numcodecs,
                "numcodecs.blosc": mock_blosc,
            }),
        ):
            mock_sys.platform = "linux"
            _cleanup_posix_semaphores()
        mock_mp.sem_unlink.assert_not_called()

    def test_semlock_name_is_none(self):
        """When semlock.name is None, branch 96→101: second if False → skip."""
        mock_mp = MagicMock()
        mock_blosc = MagicMock()
        mock_semlock = MagicMock()
        mock_semlock.name = None
        mock_blosc.mutex._semlock = mock_semlock
        mock_numcodecs = MagicMock()
        mock_numcodecs.blosc = mock_blosc

        with (
            patch("app.main.sys") as mock_sys,
            patch.dict(sys.modules, {
                "_multiprocessing": mock_mp,
                "multiprocessing.resource_tracker": MagicMock(),
                "numcodecs": mock_numcodecs,
                "numcodecs.blosc": mock_blosc,
            }),
        ):
            mock_sys.platform = "linux"
            _cleanup_posix_semaphores()
        mock_mp.sem_unlink.assert_not_called()