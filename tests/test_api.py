"""Tests for Countries, Stats, and Data Import endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.services.data_import import import_democracy_csv


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "project" in body


# ---------------------------------------------------------------------------
# Countries — empty DB
# ---------------------------------------------------------------------------


def test_countries_list_empty(client: TestClient) -> None:
    response = client.get("/countries/")
    assert response.status_code == 200
    assert response.json() == []


def test_country_detail_not_found(client: TestClient) -> None:
    response = client.get("/countries/Atlantis")
    assert response.status_code == 404


def test_country_history_not_found(client: TestClient) -> None:
    response = client.get("/countries/Atlantis/history")
    assert response.status_code == 404


def test_stats_summary_empty_db(client: TestClient) -> None:
    response = client.get("/stats/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["year"] is None
    assert data["country_count"] == 0
    assert data["avg_democracy_index"] is None


def test_stats_regions_empty_db(client: TestClient) -> None:
    response = client.get("/stats/regions")
    assert response.status_code == 200
    assert response.json() == []


def test_stats_declining_empty_db(client: TestClient) -> None:
    response = client.get("/stats/declining")
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# Countries — populated DB
# ---------------------------------------------------------------------------


def test_countries_list_returns_all(
    client: TestClient, populated_db: None
) -> None:
    response = client.get("/countries/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Sample CSV: Canada, United States, China, Russia, Hungary
    assert len(data) == 5
    names = {c["name"] for c in data}
    assert {"Canada", "United States", "China", "Russia", "Hungary"} == names


def test_countries_list_each_has_one_history_entry(
    client: TestClient, populated_db: None
) -> None:
    """List endpoint must return only the single matched-year record per country."""
    data = client.get("/countries/").json()
    for country in data:
        assert isinstance(country["history"], list)
        assert len(country["history"]) == 1
        assert "democracy_index" in country["history"][0]


def test_countries_filter_by_region(
    client: TestClient, populated_db: None
) -> None:
    response = client.get("/countries/?region=Americas")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(c["region"] == "Americas" for c in data)


def test_countries_sort_by_score(
    client: TestClient, populated_db: None
) -> None:
    response = client.get("/countries/?year=2023&sort_by_score=true")
    assert response.status_code == 200
    scores = [c["history"][0]["democracy_index"] for c in response.json()]
    assert scores == sorted(scores, reverse=True)


def test_country_detail_latest_year(
    client: TestClient, populated_db: None
) -> None:
    """GET /{name} must return only the latest available year."""
    response = client.get("/countries/Canada")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Canada"
    assert len(data["history"]) == 1
    assert data["history"][0]["year"] == 2023   # latest in sample CSV
    assert abs(data["history"][0]["democracy_index"] - 0.85) < 1e-4


def test_country_history_all_years(
    client: TestClient, populated_db: None
) -> None:
    """GET /{name}/history must return every year, sorted ascending."""
    response = client.get("/countries/Canada/history")
    assert response.status_code == 200
    history = response.json()["history"]
    assert len(history) == 2   # 2022 and 2023 in sample CSV
    years = [h["year"] for h in history]
    assert years == sorted(years)
    # democracy_index field present on every entry
    assert all("democracy_index" in h for h in history)


def test_compare_endpoint(
    client: TestClient, populated_db: None
) -> None:
    response = client.get("/countries/compare?countries=Canada,China&year=2023")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {c["name"] for c in data} == {"Canada", "China"}


def test_compare_skips_unknown_countries(
    client: TestClient, populated_db: None
) -> None:
    response = client.get("/countries/compare?countries=Canada,Wakanda")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Canada"


# ---------------------------------------------------------------------------
# Stats — populated DB
# ---------------------------------------------------------------------------


def test_stats_summary_with_year(
    client: TestClient, populated_db: None
) -> None:
    response = client.get("/stats/summary?year=2023")
    assert response.status_code == 200
    data = response.json()
    assert data["year"] == 2023
    # All 5 countries have a 2023 entry in the sample CSV
    assert data["country_count"] == 5
    assert data["avg_democracy_index"] is not None
    # China (0.05) → min; Canada (0.85) → max
    assert abs(data["min_democracy_index"] - 0.05) < 1e-3
    assert abs(data["max_democracy_index"] - 0.85) < 1e-3


def test_stats_summary_defaults_to_latest_year(
    client: TestClient, populated_db: None
) -> None:
    response = client.get("/stats/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["year"] == 2023
    assert data["country_count"] == 5


def test_stats_regions(
    client: TestClient, populated_db: None
) -> None:
    response = client.get("/stats/regions?year=2023")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    for entry in data:
        assert "region" in entry
        assert "avg_democracy_index" in entry
        assert "country_count" in entry
        assert entry["year"] == 2023
    # Americas (Canada 0.85, US 0.78) should rank above Asia and Pacific (China 0.05)
    region_names = [e["region"] for e in data]
    americas_idx = region_names.index("Americas")
    asia_idx = region_names.index("Asia and Pacific")
    assert data[americas_idx]["avg_democracy_index"] > data[asia_idx]["avg_democracy_index"]


def test_stats_declining(
    client: TestClient, populated_db: None
) -> None:
    """Declining endpoint should not crash even with limited historical data."""
    response = client.get("/stats/declining?years=1&limit=5")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# Data Import service — unit-level (no HTTP, own in-memory DB)
# ---------------------------------------------------------------------------


def test_import_creates_then_updates(sample_csv: str) -> None:
    """Verify the upsert semantics of import_democracy_csv directly."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from app.database import Base
    from app.models import Country, DemocracyIndex

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        # First import: all 6 rows are new
        result1 = import_democracy_csv(db, sample_csv)
        assert result1["created"] == 6
        assert result1["updated"] == 0

        # Second import of same file: all rows already exist → updated
        result2 = import_democracy_csv(db, sample_csv)
        assert result2["created"] == 0
        assert result2["updated"] == 6

        assert db.query(Country).count() == 5           # distinct countries
        assert db.query(DemocracyIndex).count() == 6    # total rows
        canada = db.query(Country).filter_by(name="Canada").first()
        assert canada is not None
        assert canada.region == "Americas"
        canada_entries = (
            db.query(DemocracyIndex)
            .filter_by(country_id=canada.id)
            .count()
        )
        assert canada_entries == 2  # years 2022 and 2023
    finally:
        db.close()
        engine.dispose()


def test_import_missing_file(client: TestClient, test_engine) -> None:
    """import_democracy_csv must raise FileNotFoundError for missing paths."""
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        with pytest.raises(FileNotFoundError):
            import_democracy_csv(db, "/nonexistent/path/file.csv")
    finally:
        db.close()


def test_import_skips_invalid_index(
    tmp_path, client: TestClient, test_engine
) -> None:
    """Rows whose Electoral Democracy Index is '-' or blank are silently skipped."""
    csv_file = tmp_path / "edge_case.csv"
    csv_file.write_text(
        "Entity,Code,Year,Electoral Democracy Index,World region according to OWID\n"
        "BadLand,BAD,2023,-,TestRegion\n"       # invalid → skip
        "EmptyLand,EMP,2023,,TestRegion\n"      # blank  → skip
        "GoodLand,GLD,2023,0.75,TestRegion\n",  # valid  → import
        encoding="utf-8",
    )
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        result = import_democracy_csv(db, str(csv_file))
        assert result["created"] == 1   # only GoodLand
        assert result["updated"] == 0
        from app.models import DemocracyIndex
        row = db.query(DemocracyIndex).first()
        assert abs(row.democracy_index - 0.75) < 1e-6
    finally:
        db.close()


def test_import_skips_rows_without_code(
    tmp_path, client: TestClient, test_engine
) -> None:
    """Rows with an empty Code column (OWID aggregates) are silently skipped."""
    csv_file = tmp_path / "aggregates.csv"
    csv_file.write_text(
        "Entity,Code,Year,Electoral Democracy Index,World region according to OWID\n"
        "World,,2023,0.45,World\n"          # aggregate → skip
        "Sweden,SWE,2023,0.92,Europe\n",    # country  → import
        encoding="utf-8",
    )
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        result = import_democracy_csv(db, str(csv_file))
        assert result["created"] == 1   # only Sweden
        from app.models import Country
        assert db.query(Country).filter_by(name="World").first() is None
        assert db.query(Country).filter_by(name="Sweden").first() is not None
    finally:
        db.close()
