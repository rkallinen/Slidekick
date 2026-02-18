"""
Slidekick — FastAPI Application
====================================
High-performance WSI platform with HoVerNet cellular segmentation
and PostGIS spatial indexing.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.routers import boxes, inference, roi, slides


# ── Localhost-only access guard ───────────────────────────────────
class LocalhostOnlyMiddleware(BaseHTTPMiddleware):
    """
    Reject any request not originating from the loopback interface.

    When the backend is started with ``--host 0.0.0.0`` inside a
    container, Docker port-mapping ``127.0.0.1:8000:8000`` already
    prevents LAN connections at the network layer.  This middleware
    provides **defense-in-depth** so that even if the port mapping is
    accidentally changed to ``0.0.0.0:8000:8000``, the application
    itself will still reject non-local requests.
    """

    _LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})

    async def dispatch(self, request: Request, call_next):
        client_host = request.client.host if request.client else None
        if client_host not in self._LOOPBACK:
            return Response(
                content="Forbidden: only localhost access is permitted",
                status_code=403,
            )
        return await call_next(request)

logger = logging.getLogger(__name__)
settings = get_settings()

# ── POSIX semaphore cleanup ───────────────────────────────────────
def _cleanup_posix_semaphores() -> None:
    """Explicitly unlink leaked POSIX named semaphores.

    ``numcodecs.blosc`` creates a ``multiprocessing.Lock`` at import
    time.  On macOS / Linux with the ``spawn`` start-method the
    underlying POSIX named semaphore (``/mp-*`` or ``/loky-*``) is
    **not** automatically unlinked when the process is killed by a
    signal (SIGTERM from ``uvicorn --reload``, SIGKILL, etc.).

    Python's ``multiprocessing.util.Finalize`` handler *should* call
    ``sem_unlink``, but in practice it races against the interpreter
    shutdown sequence and loses — leaving one leaked semaphore per
    worker restart.

    This function walks every ``multiprocessing.synchronize.SemLock``
    that is reachable from known third-party module globals and calls
    ``sem_unlink`` + ``resource_tracker.unregister`` for each.  It is
    safe to call more than once (double-unlink raises
    ``FileNotFoundError`` which we suppress).
    """
    try:
        import _multiprocessing
        from multiprocessing import resource_tracker
    except ImportError:
        return

    if sys.platform == "win32":
        # Windows uses kernel-managed semaphores — no named leak.
        return

    # Collect all module-level multiprocessing Locks / Semaphores that
    # hold a named POSIX semaphore.  Currently the only known source is
    # ``numcodecs.blosc.mutex``, but we scan defensively.
    targets: list[str] = []

    try:
        import numcodecs.blosc as _blosc
        name = getattr(
            getattr(_blosc, "mutex", None), "_semlock", None
        )
        if name is not None:
            name = name.name
        if name is not None:
            targets.append(name)
    except Exception:
        pass

    for sem_name in targets:
        try:
            _multiprocessing.sem_unlink(sem_name)
            logger.debug("sem_unlink(%s) succeeded", sem_name)
        except FileNotFoundError:
            pass  # Already cleaned by Finalize — nothing to do.
        except Exception:
            logger.debug("sem_unlink(%s) failed", sem_name, exc_info=True)

        try:
            resource_tracker.unregister(sem_name, "semaphore")
        except Exception:  # pragma: no cover – atexit context prevents measurement
            pass


# Atexit handler so that even if the lifespan shutdown block is skipped
# we still attempt cleanup.
atexit.register(_cleanup_posix_semaphores)


# ── Lifespan (startup / shutdown) ─────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Startup:
        - Warm up the HoVerNet model.
        - Verify DB connectivity.
    Shutdown:
        - Dispose engine pool.
        - Clean up POSIX semaphores.
    """
    logger.info("Slidekick starting up...")

    # Set a bounded thread pool executor for run_in_executor() calls.
    # This prevents unbounded concurrent GPU inference or OpenSlide I/O
    # from exhausting memory.  4 threads: 1 inference + 3 tile-serving.
    executor = ThreadPoolExecutor(
        max_workers=4, thread_name_prefix="slidekick-io"
    )
    asyncio.get_event_loop().set_default_executor(executor)

    # Warm up the inference engine (lazy load).
    #
    # Perform a check to detect
    # whether any library (TIAToolbox) invokes ``torch.load`` without
    # the ``weights_only=True`` argument.  If detected log a clear
    # message with remediation steps and either continue or abort based
    # on runtime settings (see `Settings` in app.config).
    supports_weights_only = False
    _orig_torch_load = None
    _unsafe_counter: dict[str, int] = {"count": 0}

    try:
        import inspect
        import torch

        sig = inspect.signature(torch.load)
        if "weights_only" in sig.parameters:
            supports_weights_only = True
            _orig_torch_load = torch.load

            def _monitor_torch_load(f, *args, **kwargs):
                # Track calls that did not explicitly opt into weights_only
                if "weights_only" not in kwargs or kwargs.get("weights_only") is False:
                    _unsafe_counter["count"] += 1
                return _orig_torch_load(f, *args, **kwargs)

            torch.load = _monitor_torch_load
    except Exception:
        # If anything goes wrong with inspection (old torch, import
        # error, etc.), fall back to no monitoring.
        supports_weights_only = False

    try:
        from app.services.inference import get_inference_engine
        engine = get_inference_engine()
        engine.ensure_loaded()
    finally:
        # Restore original torch.load if we wrapped it.
        if supports_weights_only and _orig_torch_load is not None:
            try:
                import torch as _torch

                _torch.load = _orig_torch_load
            except Exception:
                pass

    logger.info("HoVerNet engine loaded (device=%s)", engine.device)

    # If monitoring detected insecure loads, log guidance and act
    # according to settings.
    if supports_weights_only and _unsafe_counter["count"] > 0:
        message = (
            "Detected insecure torch.load(...) usage during model load: "
            "TIAToolbox (or another library) called torch.load without "
            "weights_only=True. This may unpickle arbitrary Python objects "
            "and could be a security risk."
        )

        guidance = (
            "Pickle files can contain malicious code\n"
            "Recommended actions:\n"
            " - If you trust the author of the pickle file and accept the risk, set\n"
            "   SLIDEKICK_ALLOW_UNTRUSTED_MODEL_LOAD=true in your environment to proceed.\n"
        )

        full_msg = f"{message}\n\n{guidance}"

        if settings.allow_untrusted_model_load:
            logger.warning(full_msg + "\nProceeding because SLIDEKICK_ALLOW_UNTRUSTED_MODEL_LOAD is set.")
        else:
            # If the user hasn't explicitly allowed untrusted model loads,
            # abort startup to prevent potentially unsafe unpickling.
            logger.error(
                full_msg
                + "\nAborting startup because SLIDEKICK_ALLOW_UNTRUSTED_MODEL_LOAD is not set."
            )
            raise RuntimeError(
                "Insecure model load detected: aborting startup. "
                "Set SLIDEKICK_ALLOW_UNTRUSTED_MODEL_LOAD=true to proceed."
            )

    # Verify DB connectivity
    from app.models.database import engine as db_engine
    async with db_engine.begin() as conn:
        from sqlalchemy import text
        result = await conn.execute(text("SELECT PostGIS_Version()"))
        version = result.scalar()
        logger.info("PostGIS connected (version=%s)", version)

    # Create tables (idempotent — uses CREATE TABLE IF NOT EXISTS).
    # All ORM models are already imported via app.models.nucleus at
    # module level through the router imports, so Base.metadata is
    # fully populated by this point.
    from app.models.database import init_models
    await init_models()
    logger.info("Database schema verified / created.")

    yield

    # Shutdown
    from app.models.database import engine as db_engine_shutdown
    await db_engine_shutdown.dispose()
    executor.shutdown(wait=False)

    # Explicitly clean up POSIX semaphores created by numcodecs.blosc
    # *before* the interpreter shutdown sequence (where Finalize may fail).
    _cleanup_posix_semaphores()

    logger.info("Slidekick shut down.")


# ── App factory ───────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description=(
            "High-performance Whole Slide Image platform with "
            "HoVerNet nuclear segmentation and PostGIS spatial indexing."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Security middleware
    # 1. Localhost-only guard — rejects any non-loopback client IP.
    app.add_middleware(LocalhostOnlyMiddleware)

    # 2. Trusted Host — rejects requests with unexpected Host headers
    #    (prevents DNS rebinding attacks).
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1"],
    )

    # 3. CORS for React frontend (configurable via SLIDEKICK_CORS_ORIGINS).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(slides.router, prefix="/api")
    app.include_router(inference.router, prefix="/api")
    app.include_router(roi.router, prefix="/api")
    app.include_router(boxes.router, prefix="/api")

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": settings.app_name}

    return app


# ── Module-level app instance (for `uvicorn app.main:app`) ───────
app = create_app()  # pragma: no cover
