# Democracy Index Tracker

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/tests-39%20passed-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)

A production-ready REST API that tracks the electoral democracy history of 180+ countries from 1789 to the present, powered by the [V-Dem dataset](https://ourworldindata.org/democracy) via Our World in Data (34,000+ records).

---

## Features

- **Historical trends** — query any country's democracy index year by year
- **Multi-country comparison** — benchmark several countries side-by-side in a single request
- **Regional aggregation** — average democracy scores grouped by world region
- **Decline ranking** — identify countries that regressed the most over the past *N* years
- **User accounts** — JWT-authenticated registration, login, and personal watchlists
- **Admin data import** — bulk-upsert CSV data via a protected API endpoint; cache is invalidated automatically
- **Redis caching** — all read endpoints are cached (TTL 1 h); cache degrades gracefully when Redis is unavailable
- **Nightly scheduler** — APScheduler job at 02:00 checks `data/` for newer CSV files and auto-imports

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI 0.111 + Uvicorn |
| ORM / database | SQLAlchemy 2.0 + SQLite |
| Caching | Redis 7 (sync client, `scan_iter` invalidation) |
| Auth | JWT (python-jose HS256) + bcrypt |
| Scheduler | APScheduler 3 — `AsyncIOScheduler` + `CronTrigger` |
| Validation | Pydantic v2 + pydantic-settings |
| Testing | pytest 8 + FastAPI `TestClient` (39 tests, in-memory SQLite) |
| Containers | Docker + Docker Compose |

---

## Quick Start

### Local

```bash
git clone https://github.com/your-handle/democracy-index-tracker.git
cd democracy-index-tracker

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # set SECRET_KEY to any random string

python reset_db.py            # create DB, tables, and default admin (brooks / test1234)

uvicorn app.main:app --reload
# → http://localhost:8000/docs
```

### Docker

```bash
cp .env.example .env          # set SECRET_KEY before building

docker-compose up --build -d
docker-compose exec api python reset_db.py
# → http://localhost:8000/docs
```

### Load data

Place `electoral-democracy-index.csv` (downloaded from [Our World in Data](https://ourworldindata.org/democracy)) in the `data/` directory, then:

```bash
# Obtain a token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -d "username=brooks&password=test1234" | python -m json.tool | grep access_token | awk -F'"' '{print $4}')

# Import
curl -s -X POST http://localhost:8000/admin/import \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"file_path": "./data/electoral-democracy-index.csv"}'
```

---

## API Reference

Base URL: `http://localhost:8000`  
Interactive docs: `/docs` (Swagger UI) · `/redoc`

### Authentication

#### Register

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret123"}'
```

```json
{ "id": 2, "username": "alice", "is_admin": false }
```

#### Login

```bash
curl -X POST http://localhost:8000/auth/login \
  -d "username=alice&password=secret123"
```

```json
{ "access_token": "eyJhbGciOiJIUzI1NiJ9...", "token_type": "bearer" }
```

#### Watchlist — add / list / remove

```bash
# Add Sweden to watchlist
curl -X POST http://localhost:8000/auth/me/watchlist/Sweden \
  -H "Authorization: Bearer $TOKEN"

# View watchlist
curl http://localhost:8000/auth/me/watchlist \
  -H "Authorization: Bearer $TOKEN"
```

```json
[{ "id": 164, "name": "Sweden", "region": "Europe" }]
```

```bash
# Remove
curl -X DELETE http://localhost:8000/auth/me/watchlist/Sweden \
  -H "Authorization: Bearer $TOKEN"
# 204 No Content
```

---

### Countries

#### List with filters

```bash
# All countries in 2023, sorted by democracy score (descending)
curl "http://localhost:8000/countries/?year=2023&sort_by_score=true"

# Filter by region
curl "http://localhost:8000/countries/?region=Americas&year=2023"
```

```json
[
  {
    "id": 164, "name": "Sweden", "region": "Europe",
    "history": [{ "year": 2023, "democracy_index": 0.9285 }]
  },
  {
    "id": 144, "name": "Norway", "region": "Europe",
    "history": [{ "year": 2023, "democracy_index": 0.9198 }]
  }
]
```

#### Country detail (latest year)

```bash
curl http://localhost:8000/countries/Hungary
```

```json
{
  "id": 72, "name": "Hungary", "region": "Eastern Europe and Central Asia",
  "history": [{ "year": 2023, "democracy_index": 0.4213 }]
}
```

#### Full historical record

```bash
curl http://localhost:8000/countries/Hungary/history
```

```json
{
  "id": 72, "name": "Hungary", "region": "Eastern Europe and Central Asia",
  "history": [
    { "year": 1990, "democracy_index": 0.6891 },
    { "year": 1991, "democracy_index": 0.7012 },
    "...",
    { "year": 2010, "democracy_index": 0.7234 },
    { "year": 2023, "democracy_index": 0.4213 }
  ]
}
```

#### Multi-country comparison

```bash
curl "http://localhost:8000/countries/compare?countries=Sweden,Hungary,Russia&year=2023"
```

```json
[
  { "name": "Sweden",  "region": "Europe",                          "history": [{ "year": 2023, "democracy_index": 0.9285 }] },
  { "name": "Hungary", "region": "Eastern Europe and Central Asia", "history": [{ "year": 2023, "democracy_index": 0.4213 }] },
  { "name": "Russia",  "region": "Eastern Europe and Central Asia", "history": [{ "year": 2023, "democracy_index": 0.1192 }] }
]
```

---

### Statistics

#### Annual summary

```bash
curl "http://localhost:8000/stats/summary?year=2023"
```

```json
{
  "year": 2023,
  "country_count": 179,
  "avg_democracy_index": 0.4821,
  "min_democracy_index": 0.0132,
  "max_democracy_index": 0.9285
}
```

#### Regional averages

```bash
curl "http://localhost:8000/stats/regions?year=2023"
```

```json
[
  { "region": "Europe",                          "year": 2023, "avg_democracy_index": 0.7431, "country_count": 34 },
  { "region": "Americas",                        "year": 2023, "avg_democracy_index": 0.5612, "country_count": 35 },
  { "region": "Asia and Pacific",                "year": 2023, "avg_democracy_index": 0.3874, "country_count": 28 },
  { "region": "Eastern Europe and Central Asia", "year": 2023, "avg_democracy_index": 0.2943, "country_count": 28 },
  { "region": "Sub-Saharan Africa",              "year": 2023, "avg_democracy_index": 0.3021, "country_count": 44 },
  { "region": "Middle East and North Africa",    "year": 2023, "avg_democracy_index": 0.1587, "country_count": 20 }
]
```

#### Fastest-declining democracies

```bash
# Countries whose score dropped the most in the past 15 years
curl "http://localhost:8000/stats/declining?years=15&limit=5"
```

```json
[
  { "country": "Hungary",    "start_year": 2008, "start_score": 0.7892, "end_year": 2023, "end_score": 0.4213, "change": -0.3679 },
  { "country": "Serbia",     "start_year": 2008, "start_score": 0.5934, "end_year": 2023, "end_score": 0.2841, "change": -0.3093 },
  { "country": "Bangladesh", "start_year": 2008, "start_score": 0.5103, "end_year": 2023, "end_score": 0.2214, "change": -0.2889 },
  { "country": "Nicaragua",  "start_year": 2008, "start_score": 0.4821, "end_year": 2023, "end_score": 0.1943, "change": -0.2878 },
  { "country": "Mali",       "start_year": 2008, "start_score": 0.4412, "end_year": 2023, "end_score": 0.1621, "change": -0.2791 }
]
```

---

### Admin

#### Import CSV

```bash
curl -X POST http://localhost:8000/admin/import \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"file_path": "./data/electoral-democracy-index.csv"}'
```

```json
{ "created": 33842, "updated": 0 }
```

> Requires `is_admin=true`. Automatically invalidates all Redis cache keys after import.

---

## Data Source

| Field | Detail |
|---|---|
| Dataset | Electoral Democracy Index (V-Dem) |
| Provider | [Our World in Data](https://ourworldindata.org/democracy) |
| Original source | V-Dem Institute, University of Gothenburg |
| Coverage | 180+ countries · 1789–present · 34,000+ observations |
| Score range | 0 (least democratic) → 1 (most democratic) |
| License | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

Download: [electoral-democracy-index.csv](https://ourworldindata.org/grapher/electoral-democracy-index)

---

## Testing

```bash
pytest tests/ -v
```

```
tests/test_api.py::test_health                              PASSED
tests/test_api.py::test_countries_list_returns_all          PASSED
tests/test_api.py::test_countries_sort_by_score             PASSED
tests/test_api.py::test_stats_summary_with_year             PASSED
tests/test_api.py::test_stats_regions                       PASSED
tests/test_api.py::test_import_creates_then_updates         PASSED
tests/test_api.py::test_import_skips_invalid_index          PASSED
tests/test_auth.py::test_login_success                      PASSED
tests/test_auth.py::test_watchlist_add_and_retrieve         PASSED
... (39 total)

39 passed in 3.49s
```

Tests use an **in-memory SQLite** database and a **mocked Redis client** — no external services required.

---

## Project Structure

```
app/
├── core/           config.py · security.py (JWT + bcrypt)
├── routers/        auth.py · countries.py · stats.py
├── services/       cache.py · data_import.py · scheduler.py
├── database.py     engine · SessionLocal · get_db
├── models.py       User · Country · DemocracyIndex (SQLAlchemy ORM)
├── schemas.py      Pydantic request / response models
└── main.py         app factory · lifespan · /admin/import
tests/
├── conftest.py     fixtures (in-memory DB, mocked Redis / APScheduler)
├── test_auth.py    registration · login · JWT · watchlist CRUD
└── test_api.py     countries · stats · import edge cases
data/               SQLite DB + CSV files (Docker volume mount)
reset_db.py         drop → recreate tables → seed admin user
```

---

## License

MIT
