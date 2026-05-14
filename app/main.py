"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.models import User
from app.routers import auth, countries, stats
from app.routers.auth import get_current_admin_user
from app.services.cache import clear_all_cache, close_redis, init_redis
from app.services.data_import import import_democracy_csv
from app.services.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown of Redis and APScheduler.

    Startup
    -------
    * Initialise and ping the Redis connection pool.
      A failed ping is logged as a warning rather than crashing the process
      so the API starts successfully even when Redis is temporarily offline.
    * Start the APScheduler instance (runs inside the asyncio event loop).

    Shutdown
    --------
    * Gracefully stop the scheduler (running jobs are not waited on).
    * Close the Redis connection pool.
    """
    # --- startup ---
    try:
        init_redis()
    except Exception as exc:
        logger.warning("Redis unavailable at startup — cache disabled: %s", exc)

    start_scheduler()

    yield

    # --- shutdown ---
    stop_scheduler()
    close_redis()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(title=settings.project_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(countries.router)
app.include_router(stats.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    """Return a simple application-level liveness indicator."""
    return {"status": "ok", "project": settings.project_name}


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


class ImportRequest(BaseModel):
    """Request body for the CSV import endpoint."""

    file_path: str = Field(
        default="./data/electoral-democracy-index.csv",
        description="Path to the OWID Electoral Democracy Index CSV file",
    )


@app.post("/admin/import", tags=["Admin"])
def admin_import(
    body: ImportRequest,
    _: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Trigger a full CSV import.  Requires admin privileges.

    After a successful import, **all cached query results are invalidated**
    so clients immediately see the updated data on their next request.

    Returns a dict with ``created`` and ``updated`` row counts.
    """
    result = import_democracy_csv(db, body.file_path)
    cleared = clear_all_cache()
    logger.info("admin_import: cache cleared after import (%d key(s))", cleared)
    return result
