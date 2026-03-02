"""MeritMolt FastAPI app: health and auth."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from meritmolt import database as db
from meritmolt.auth.router import router as auth_router
from meritmolt.backpressure import BackpressureMiddleware
from meritmolt.config import get_settings
from meritmolt.database import init_db
from meritmolt.events.router import router as events_router
from meritmolt.rank.router import router as rank_router
from meritmolt.ratelimit import RateLimitMiddleware
from meritmolt.scores.router import router as scores_router


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Create DB engine and tables on startup; dispose on shutdown."""
    settings = get_settings()
    await init_db(settings)
    yield
    if db.engine is not None:
        await db.engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)
app.include_router(events_router)
app.include_router(scores_router)
app.include_router(rank_router)

settings = get_settings()
app.add_middleware(RateLimitMiddleware, settings=settings)
app.add_middleware(BackpressureMiddleware, settings=settings)


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/db")
async def db_ping() -> dict[str, str | bool]:
    """Ping Postgres via async engine."""
    if db.engine is None:
        return {"status": "error", "db": False, "message": "Database not initialized"}
    try:
        from sqlalchemy import text

        async with db.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": True}
    except Exception as e:
        return {"status": "error", "db": False, "message": str(e)}
