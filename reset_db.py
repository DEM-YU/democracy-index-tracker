"""Utility: drop the SQLite database, recreate all tables, seed an admin user."""

import sys
from pathlib import Path

# Ensure the project root is importable when the script is run directly.
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings
from app.core.security import get_password_hash
from app.database import Base, engine, SessionLocal
from app.models import User  # noqa: F401 — registers all ORM models with Base

DB_PATH = Path(settings.database_url.removeprefix("sqlite:///"))

ADMIN_USERNAME = "brooks"
ADMIN_PASSWORD = "test1234"


def main() -> None:
    # 1. Remove stale database file
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Deleted {DB_PATH}")
    else:
        print(f"No existing database at {DB_PATH}")

    # 2. Recreate schema
    Base.metadata.create_all(bind=engine)
    print("All tables created.")

    # 3. Seed admin user
    db = SessionLocal()
    try:
        admin = User(
            username=ADMIN_USERNAME,
            hashed_password=get_password_hash(ADMIN_PASSWORD),
            is_admin=True,
        )
        db.add(admin)
        db.commit()
        print(f"Admin user created: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
    finally:
        db.close()

    # 4. Seed initial dataset if available
    csv_path = Path("data/electoral-democracy-index.csv")
    if csv_path.exists():
        from app.services.data_import import import_democracy_csv

        db = SessionLocal()
        try:
            print(f"Importing initial dataset from {csv_path}...")
            result = import_democracy_csv(db, str(csv_path))
            print(f"Data import complete: {result['created']} records created.")
        finally:
            db.close()


if __name__ == "__main__":
    main()

