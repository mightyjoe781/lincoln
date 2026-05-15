import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.router import v1_router
from app.core.logging import configure_logging

configure_logging()
logger = logging.getLogger("lincoln")

app = FastAPI(
    title="Lincoln — Financial Document Parser",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(v1_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
