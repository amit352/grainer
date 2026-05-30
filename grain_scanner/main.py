"""FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.core.config import settings
from app.core.logging import setup_logging
from app.database.session import init_db

# ── Routers ───────────────────────────────────────────────────────────────────
from app.api.routes import images, measurements, reports, calibration, scanner, quality, vendors


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings.ensure_dirs()
    await init_db()
    logger.info(f"{settings.app_name} v{settings.app_version} starting up")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Production-grade grain size measurement API. "
        "Upload or scan images, measure individual grains, export results."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files (annotated images) ──────────────────────────────────────────
settings.output_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(settings.output_dir)), name="static")

# ── Routes ────────────────────────────────────────────────────────────────────
prefix = settings.api_prefix
app.include_router(images.router, prefix=prefix)
app.include_router(measurements.router, prefix=prefix)
app.include_router(reports.router, prefix=prefix)
app.include_router(calibration.router, prefix=prefix)
app.include_router(scanner.router, prefix=prefix)
app.include_router(quality.router, prefix=prefix)
app.include_router(vendors.router, prefix=prefix)


# ── Health ────────────────────────────────────────────────────────────────────
@app.get(f"{prefix}/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "version": settings.app_version}


# ── Global error handler ──────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(f"Unhandled exception on {request.url}: {exc}")
    return JSONResponse(status_code=500, content={"error": str(exc)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.debug)
