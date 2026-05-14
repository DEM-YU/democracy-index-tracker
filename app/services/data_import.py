"""CSV import service for Our World in Data electoral democracy index data.

Expected CSV columns (as shipped by OWID):
    Entity                              — country / territory name
    Code                                — ISO-3 country code (used to filter aggregates)
    Year                                — calendar year (integer)
    Electoral Democracy Index           — V-Dem score, float in [0, 1]
    World region according to OWID      — OWID region label
"""

import csv
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Country, DemocracyIndex

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = {
    "Entity",
    "Year",
    "Electoral Democracy Index",
    "World region according to OWID",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_float(raw: str) -> float | None:
    """Convert a raw CSV value to float.

    Returns ``None`` for blank cells, ``"-"``, or any non-numeric token so
    that the caller can decide to skip the row rather than storing bad data.
    """
    stripped = raw.strip()
    if not stripped or stripped == "-":
        return None
    try:
        return float(stripped)
    except ValueError:
        logger.debug("Unparseable democracy index value %r — skipping row", raw)
        return None


def _get_or_create_country(db: Session, name: str, region: str) -> Country:
    """Return an existing Country row, creating one if absent.

    The ``region`` is updated on every call so the country table stays in
    sync with the latest OWID region taxonomy.
    """
    country = db.query(Country).filter(Country.name == name).first()
    if country is None:
        country = Country(name=name, region=region)
        db.add(country)
        db.flush()          # populate country.id without committing
    else:
        country.region = region
    return country


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def import_democracy_csv(db: Session, file_path: str) -> dict[str, int]:
    """Parse *file_path* and upsert all rows into the database.

    Rows are skipped when:
    * ``Entity`` or ``Year`` is blank / unparseable.
    * ``Electoral Democracy Index`` is blank or non-numeric (e.g. ``"-"``).
    * ``Code`` column is present **and** the value is empty — this filters
      OWID regional / global aggregates that lack a country code.

    Args:
        db: An active SQLAlchemy session.  The caller is responsible for
            any rollback; this function commits on success.
        file_path: Path to the OWID CSV file.

    Returns:
        ``{"created": N, "updated": N}`` row counts.

    Raises:
        FileNotFoundError: If *file_path* does not exist.
        KeyError: If a required column is absent from the header row.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    created = 0
    updated = 0

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = set(reader.fieldnames or [])

        missing = _REQUIRED_COLUMNS - fieldnames
        if missing:
            raise KeyError(f"CSV is missing required columns: {missing}")

        has_code_column = "Code" in fieldnames

        for row in reader:
            # Skip OWID aggregate rows (no ISO code)
            if has_code_column and not row.get("Code", "").strip():
                continue

            country_name = row["Entity"].strip()
            region = row["World region according to OWID"].strip()
            year_raw = row["Year"].strip()
            index_raw = row["Electoral Democracy Index"].strip()

            if not country_name or not year_raw:
                continue

            try:
                year = int(year_raw)
            except ValueError:
                logger.warning("Invalid year %r — skipping row", year_raw)
                continue

            democracy_index = _parse_float(index_raw)
            if democracy_index is None:
                logger.debug(
                    "No valid democracy index for %s %d — skipping row",
                    country_name,
                    year,
                )
                continue

            country = _get_or_create_country(db, country_name, region)

            existing = (
                db.query(DemocracyIndex)
                .filter(
                    DemocracyIndex.country_id == country.id,
                    DemocracyIndex.year == year,
                )
                .first()
            )

            if existing is None:
                db.add(
                    DemocracyIndex(
                        country_id=country.id,
                        year=year,
                        democracy_index=democracy_index,
                    )
                )
                created += 1
            else:
                existing.democracy_index = democracy_index
                updated += 1

    db.commit()

    logger.info(
        "Import complete — file: %s | created: %d | updated: %d",
        file_path,
        created,
        updated,
    )
    print(f"[data_import] created={created}  updated={updated}  file={file_path}")
    return {"created": created, "updated": updated}
