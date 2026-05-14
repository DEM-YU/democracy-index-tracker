"""Shared pytest fixtures for Democracy Index Tracker test suite.

Design decisions
----------------
* **In-memory SQLite + StaticPool**: every test shares the same in-memory DB
  connection, so data written by direct ORM code is visible to the FastAPI
  TestClient in the same test function.
* **Table isolation**: the ``client`` fixture drops and re-creates all tables
  before each test, giving a clean slate without re-creating the engine.
* **Redis mock**: ``app.services.cache.get_client`` is patched to return a
  MagicMock that always returns ``None`` on ``.get()`` (cache-miss path).
  This keeps tests free from Redis connectivity requirements.
* **Scheduler / lifespan mocks**: ``init_redis``, ``start_scheduler``, and
  their shutdown counterparts are patched in ``app.main`` so the lifespan
  context manager completes cleanly inside the TestClient.
"""

import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure the project root is on sys.path when pytest is run from any directory.
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

TEST_DATABASE_URL = "sqlite:///:memory:"

# ---------------------------------------------------------------------------
# Engine (session-scoped — one in-memory DB per pytest session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_engine():
    """Create a single in-memory SQLite engine shared across the test session.

    ``StaticPool`` ensures all ORM sessions and the TestClient use the same
    underlying SQLite connection, so direct inserts are immediately visible
    to HTTP handlers within the same test.
    """
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# HTTP client (function-scoped — clean tables + mocked side-effects per test)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def client(test_engine):
    """Yield a FastAPI TestClient with isolated DB and mocked external services.

    Table isolation is achieved by dropping and re-creating the schema before
    every test function.  Redis and APScheduler are replaced with lightweight
    mocks so tests run without any network or background-thread dependencies.
    """
    # Fresh schema for each test
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Redis mock: always a cache miss; writes are no-ops
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    mock_redis.setex.return_value = True
    mock_redis.ping.return_value = True
    mock_redis.scan_iter.return_value = iter([])
    mock_redis.delete.return_value = 0

    with (
        patch("app.main.init_redis"),
        patch("app.main.close_redis"),
        patch("app.main.start_scheduler"),
        patch("app.main.stop_scheduler"),
        patch("app.services.cache.get_client", return_value=mock_redis),
    ):
        with TestClient(app) as test_client:
            yield test_client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sample CSV file (function-scoped temp file)
# ---------------------------------------------------------------------------

SAMPLE_CSV = """\
Entity,Code,Year,Electoral Democracy Index,World region according to OWID
Canada,CAN,2023,0.85,Americas
Canada,CAN,2022,0.84,Americas
United States,USA,2023,0.78,Americas
China,CHN,2023,0.05,Asia and Pacific
Russia,RUS,2023,0.12,Eastern Europe and Central Asia
Hungary,HUN,2023,0.42,Eastern Europe and Central Asia
"""


@pytest.fixture(scope="function")
def sample_csv(tmp_path: Path) -> str:
    """Write a small Freedom House CSV to a temp directory and return its path."""
    csv_file = tmp_path / "freedom_house_test.csv"
    csv_file.write_text(SAMPLE_CSV, encoding="utf-8")
    return str(csv_file)


# ---------------------------------------------------------------------------
# Pre-populated database (convenience fixture for data-dependent tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def populated_db(client, test_engine, sample_csv):
    """Import sample CSV data into the test database.

    Depends on ``client`` so table cleanup runs first, then inserts six rows
    (five unique country-year combinations, four distinct countries).
    """
    from app.services.data_import import import_democracy_csv

    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        import_democracy_csv(db, sample_csv)
    finally:
        db.close()
