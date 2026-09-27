"""FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from paperpath import __version__
from paperpath.api.routes import router
from paperpath.config import Settings
from paperpath.errors import (
    ConfigurationError,
    IngestionError,
    NotFoundError,
    NotReadyError,
    PaperPathError,
    UpstreamError,
)
from paperpath.export.vault import VaultError
from paperpath.pipeline.wiring import Runtime, build_runtime

logger = logging.getLogger(__name__)


def create_app(runtime: Runtime | None = None, settings: Settings | None = None) -> FastAPI:
    runtime = runtime or build_runtime(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await app.state.runtime.http.aclose()

    app = FastAPI(title=runtime.settings.app_name, version=__version__, lifespan=lifespan)
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime.settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _register_errors(app)
    app.include_router(router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


def _register_errors(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def not_found(_request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(NotReadyError)
    async def not_ready(_request, exc: NotReadyError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ConfigurationError)
    async def missing_config(_request, exc: ConfigurationError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(UpstreamError)
    async def upstream(_request, exc: UpstreamError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(VaultError)
    async def bad_vault(_request, exc: VaultError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc), "errors": exc.errors})

    @app.exception_handler(IngestionError)
    async def bad_input(_request, exc: IngestionError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(PaperPathError)
    async def pipeline_error(_request, exc: PaperPathError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
