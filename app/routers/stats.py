"""Statistics and analytics endpoints."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Country, DemocracyIndex
from app.services.cache import cache_response

router = APIRouter(prefix="/stats", tags=["Statistics"])


# ---------------------------------------------------------------------------
# Inline response schemas
# ---------------------------------------------------------------------------


class DeclineEntry(BaseModel):
    """One row in the fastest-declining countries ranking."""

    country: str
    start_year: int
    start_score: float
    end_year: int
    end_score: float
    change: float


class RegionSummary(BaseModel):
    """Average democracy index for a single region in a given year."""

    region: str
    year: int
    avg_democracy_index: float
    country_count: int


class YearlySummary(BaseModel):
    """Aggregate statistics for all countries in a given year."""

    year: int | None
    country_count: int
    avg_democracy_index: float | None
    min_democracy_index: float | None
    max_democracy_index: float | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/declining", response_model=list[DeclineEntry])
@cache_response(ttl=3600)
def declining_countries(
    request: Request,
    years: int = 10,
    limit: int = 10,
    db: Session = Depends(get_db),
) -> list[DeclineEntry]:
    """Return the *limit* countries with the steepest democracy index decline.

    Compares the globally latest year in the database against
    ``(latest_year - years)``.  Only countries with data for both years are
    included.  Results are ordered by change ascending (most negative first).
    """
    latest_year: int | None = db.query(func.max(DemocracyIndex.year)).scalar()
    if latest_year is None:
        return []

    comparison_year = latest_year - years

    latest_sq = (
        db.query(
            DemocracyIndex.country_id.label("cid"),
            DemocracyIndex.democracy_index.label("score"),
        )
        .filter(DemocracyIndex.year == latest_year)
        .subquery()
    )

    old_sq = (
        db.query(
            DemocracyIndex.country_id.label("cid"),
            DemocracyIndex.democracy_index.label("score"),
        )
        .filter(DemocracyIndex.year == comparison_year)
        .subquery()
    )

    change_expr = latest_sq.c.score - old_sq.c.score

    rows = (
        db.query(
            Country.name.label("country"),
            old_sq.c.score.label("start_score"),
            latest_sq.c.score.label("end_score"),
            change_expr.label("change"),
        )
        .join(latest_sq, Country.id == latest_sq.c.cid)
        .join(old_sq, Country.id == old_sq.c.cid)
        .filter(latest_sq.c.score < old_sq.c.score)
        .order_by(change_expr.asc())
        .limit(limit)
        .all()
    )

    return [
        DeclineEntry(
            country=r.country,
            start_year=comparison_year,
            start_score=round(float(r.start_score), 4),
            end_year=latest_year,
            end_score=round(float(r.end_score), 4),
            change=round(float(r.change), 4),
        )
        for r in rows
    ]


@router.get("/regions", response_model=list[RegionSummary])
@cache_response(ttl=3600)
def regions_summary(
    request: Request,
    year: int | None = None,
    db: Session = Depends(get_db),
) -> list[RegionSummary]:
    """Return average ``democracy_index`` grouped by region for a given year.

    When *year* is omitted, the latest year in the database is used.
    Results are ordered by average score descending.
    """
    if year is None:
        year = db.query(func.max(DemocracyIndex.year)).scalar()
    if year is None:
        return []

    rows = (
        db.query(
            Country.region.label("region"),
            func.avg(DemocracyIndex.democracy_index).label("avg_score"),
            func.count(Country.id).label("country_count"),
        )
        .join(DemocracyIndex, Country.id == DemocracyIndex.country_id)
        .filter(DemocracyIndex.year == year)
        .group_by(Country.region)
        .order_by(func.avg(DemocracyIndex.democracy_index).desc())
        .all()
    )

    return [
        RegionSummary(
            region=r.region,
            year=year,
            avg_democracy_index=round(float(r.avg_score), 4),
            country_count=r.country_count,
        )
        for r in rows
    ]


@router.get("/summary", response_model=YearlySummary)
@cache_response(ttl=3600)
def yearly_summary(
    request: Request,
    year: int | None = None,
    db: Session = Depends(get_db),
) -> YearlySummary:
    """Return aggregate statistics (count, avg, min, max) for a given year.

    When *year* is omitted, the latest year in the database is used.
    All index values are rounded to four decimal places.
    """
    if year is None:
        year = db.query(func.max(DemocracyIndex.year)).scalar()

    if year is None:
        return YearlySummary(
            year=None,
            country_count=0,
            avg_democracy_index=None,
            min_democracy_index=None,
            max_democracy_index=None,
        )

    result = (
        db.query(
            func.count(DemocracyIndex.id).label("cnt"),
            func.avg(DemocracyIndex.democracy_index).label("avg_idx"),
            func.min(DemocracyIndex.democracy_index).label("min_idx"),
            func.max(DemocracyIndex.democracy_index).label("max_idx"),
        )
        .filter(DemocracyIndex.year == year)
        .one()
    )

    def _r(v) -> float | None:
        return round(float(v), 4) if v is not None else None

    return YearlySummary(
        year=year,
        country_count=result.cnt,
        avg_democracy_index=_r(result.avg_idx),
        min_democracy_index=_r(result.min_idx),
        max_democracy_index=_r(result.max_idx),
    )
