"""APScheduler background task: nightly check for new CSV data.

The scheduler runs as part of the FastAPI process using
``AsyncIOScheduler``, which integrates with the running event loop.
The job itself (``auto_check_new_data``) is a plain synchronous function;
APScheduler executes sync jobs in the event loop's default thread-pool
executor so the event loop is never blocked.
"""

import csv
import logging
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func

from app.database import SessionLocal
from app.models import DemocracyIndex
from app.services import cache as cache_service
from app.services.data_import import import_democracy_csv

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_csv_max_year(csv_path: Path) -> int | None:
    """Return the maximum value in the ``Year`` column of *csv_path*.

    Returns ``None`` when the file cannot be opened, lacks a ``Year``
    column, or contains no parseable year values.
    """
    max_year: int | None = None
    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or "Year" not in reader.fieldnames:
                logger.debug("%s: no 'Year' column — skipping", csv_path.name)
                return None
            for row in reader:
                raw = row.get("Year", "").strip()
                try:
                    year = int(raw)
                    if max_year is None or year > max_year:
                        max_year = year
                except ValueError:
                    continue
    except OSError as exc:
        logger.warning("Cannot read %s: %s", csv_path, exc)
    return max_year


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


def auto_check_new_data() -> None:
    """Detect CSV files newer than the DB's latest year and import them.

    Algorithm
    ---------
    1. Query ``MAX(year)`` from ``democracy_indices`` (DB baseline).
    2. Walk every ``*.csv`` file in ``./data/``.
    3. For each CSV, compute its own ``MAX(Year)``.
    4. If CSV max year > DB baseline, run a full import and clear the cache.
    5. Update the in-memory baseline so subsequent files in the same run
       are compared against the freshly imported data.

    The function is intentionally synchronous so APScheduler runs it in the
    thread-pool executor without blocking the asyncio event loop.
    """
    db = SessionLocal()
    try:
        db_max_year: int = db.query(func.max(DemocracyIndex.year)).scalar() or 0
        logger.info("Scheduler: DB latest year = %d", db_max_year)

        data_dir = Path("./data")
        if not data_dir.exists():
            logger.warning("Scheduler: data/ directory not found — aborting check")
            return

        csv_files = sorted(data_dir.glob("*.csv"))
        if not csv_files:
            logger.info("Scheduler: no CSV files found in data/")
            return

        for csv_path in csv_files:
            csv_max_year = _get_csv_max_year(csv_path)
            if csv_max_year is None:
                continue
            if csv_max_year <= db_max_year:
                logger.debug(
                    "Scheduler: %s — CSV max year %d ≤ DB max year %d, skipping",
                    csv_path.name,
                    csv_max_year,
                    db_max_year,
                )
                continue

            logger.info(
                "Scheduler: new data in %s (year %d > %d) — starting import",
                csv_path.name,
                csv_max_year,
                db_max_year,
            )
            result = import_democracy_csv(db, str(csv_path))
            cleared = cache_service.clear_all_cache()
            logger.info(
                "Scheduler: import done — created=%d updated=%d cache_cleared=%d",
                result["created"],
                result["updated"],
                cleared,
            )
            # Advance the baseline so the next CSV in this run is compared
            # against the data we just imported.
            db_max_year = csv_max_year

    except Exception:
        logger.exception("Scheduler: auto_check_new_data raised an unexpected error")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def start_scheduler() -> None:
    """Register the daily-check job and start the scheduler.

    The job is configured with ``replace_existing=True`` so repeated
    application restarts never create duplicate job entries.
    ``misfire_grace_time=3600`` allows the job to run up to 1 hour late
    (e.g., after a brief outage) rather than being silently skipped.
    """
    _scheduler.add_job(
        auto_check_new_data,
        trigger=CronTrigger(hour=2, minute=0),
        id="auto_check_new_data",
        name="Daily new-data check",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info("APScheduler started — daily check scheduled at 02:00")


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler without waiting for running jobs."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
