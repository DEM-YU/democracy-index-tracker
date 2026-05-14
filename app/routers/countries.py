"""Country query endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Country, DemocracyIndex
from app.schemas import CountryDetailResponse, DemocracyIndexResponse
from app.services.cache import cache_response

router = APIRouter(prefix="/countries", tags=["Countries"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_detail(country: Country, indices: list[DemocracyIndex]) -> CountryDetailResponse:
    """Construct a CountryDetailResponse from an ORM Country and index rows."""
    return CountryDetailResponse(
        id=country.id,
        name=country.name,
        region=country.region,
        history=[
            DemocracyIndexResponse(
                year=di.year,
                democracy_index=di.democracy_index,
            )
            for di in indices
        ],
    )


# ---------------------------------------------------------------------------
# Routes  (NOTE: /compare must be defined before /{country_name} so that
#          FastAPI does not greedily match "compare" as a country_name.)
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[CountryDetailResponse])
@cache_response(ttl=3600)
def list_countries(
    request: Request,
    region: str | None = None,
    year: int | None = None,
    sort_by_score: bool = False,
    db: Session = Depends(get_db),
) -> list[CountryDetailResponse]:
    """Return countries with optional filtering and sorting.

    When *year* is omitted, each country's latest available year is used.
    The returned ``history`` list contains only the single matched record.
    Set ``sort_by_score=true`` to order results by ``democracy_index``
    descending (most democratic first).
    """
    if year is not None:
        year_filter = DemocracyIndex.year == year
    else:
        latest_year_sq = (
            db.query(func.max(DemocracyIndex.year))
            .filter(DemocracyIndex.country_id == Country.id)
            .correlate(Country)
            .scalar_subquery()
        )
        year_filter = DemocracyIndex.year == latest_year_sq

    query = (
        db.query(Country, DemocracyIndex)
        .join(DemocracyIndex, Country.id == DemocracyIndex.country_id)
        .filter(year_filter)
    )

    if region:
        query = query.filter(Country.region == region)

    if sort_by_score:
        query = query.order_by(desc(DemocracyIndex.democracy_index))
    else:
        query = query.order_by(Country.name)

    pairs: list[tuple[Country, DemocracyIndex]] = query.all()
    return [_build_detail(country, [di]) for country, di in pairs]


@router.get("/compare", response_model=list[CountryDetailResponse])
@cache_response(ttl=3600)
def compare_countries(
    request: Request,
    countries: str = Query(
        ...,
        description="Comma-separated country names, e.g. 'Canada,United States,China'",
    ),
    year: int | None = None,
    db: Session = Depends(get_db),
) -> list[CountryDetailResponse]:
    """Compare multiple countries in a given year.

    Countries not found in the database are silently skipped.
    When *year* is omitted, each country's latest available year is used.
    """
    names = [n.strip() for n in countries.split(",") if n.strip()]
    results: list[CountryDetailResponse] = []

    for name in names:
        country = db.query(Country).filter(Country.name == name).first()
        if country is None:
            continue

        if year is not None:
            target_year: int | None = year
        else:
            target_year = (
                db.query(func.max(DemocracyIndex.year))
                .filter(DemocracyIndex.country_id == country.id)
                .scalar()
            )

        indices: list[DemocracyIndex] = []
        if target_year is not None:
            indices = (
                db.query(DemocracyIndex)
                .filter(
                    DemocracyIndex.country_id == country.id,
                    DemocracyIndex.year == target_year,
                )
                .all()
            )

        results.append(_build_detail(country, indices))

    return results


@router.get("/{country_name}", response_model=CountryDetailResponse)
@cache_response(ttl=3600)
def get_country(
    request: Request,
    country_name: str,
    db: Session = Depends(get_db),
) -> CountryDetailResponse:
    """Return the latest year democracy index record for a single country."""
    country = db.query(Country).filter(Country.name == country_name).first()
    if country is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Country '{country_name}' not found",
        )
    latest_di = (
        db.query(DemocracyIndex)
        .filter(DemocracyIndex.country_id == country.id)
        .order_by(desc(DemocracyIndex.year))
        .first()
    )
    return _build_detail(country, [latest_di] if latest_di else [])


@router.get("/{country_name}/history", response_model=CountryDetailResponse)
@cache_response(ttl=3600)
def get_country_history(
    request: Request,
    country_name: str,
    db: Session = Depends(get_db),
) -> CountryDetailResponse:
    """Return all historical democracy index records for a country (year ASC)."""
    country = db.query(Country).filter(Country.name == country_name).first()
    if country is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Country '{country_name}' not found",
        )
    return _build_detail(country, list(country.history))
