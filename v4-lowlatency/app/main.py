"""
FastAPI entrypoint.

Run locally:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes.voice import router as voice_router
from app.services.session_manager import store
from app.config import STATIC_DIR


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("app")


async def _cleanup_loop():
    """Background task — purge expired sessions every 5 min."""
    while True:
        try:
            removed = store.cleanup_expired()
            if removed:
                log.info("[cleanup] removed %d expired sessions", removed)
        except Exception as e:
            log.warning("[cleanup] failed: %s", e)
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_cleanup_loop())
    log.info("IVF Voice Engine v4 started")
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="IVF Voice Engine", version="4.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(voice_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "active_sessions": len(store.all()),
    }


@app.get("/")
def root():
    return {"service": "ivf-voice-engine", "version": "4.0.0"}
