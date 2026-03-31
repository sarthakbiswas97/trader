#!/usr/bin/env python3
"""
Set up the database — create all tables.

Usage:
    python -m backend.scripts.setup_db              # Create tables
    python -m backend.scripts.setup_db --check      # Check connection only
    python -m backend.scripts.setup_db --drop        # Drop all tables (dangerous!)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.config import settings


def main():
    parser = argparse.ArgumentParser(description="Database setup")
    parser.add_argument("--check", action="store_true", help="Check connection only")
    parser.add_argument("--drop", action="store_true", help="Drop all tables")
    args = parser.parse_args()

    # Redact password from URL for logging
    import re
    redacted = re.sub(r"://[^:]+:[^@]+@", "://***:***@", settings.database_url)
    print(f"Database: {redacted}")

    from sqlalchemy import create_engine, text
    engine = create_engine(settings.database_url, pool_pre_ping=True)

    if args.check:
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT version()"))
                version = result.scalar()
                print(f"Connected: {version}")
        except Exception as e:
            print(f"Connection failed: {e}")
            sys.exit(1)
        return

    from backend.db.models import Base

    if args.drop:
        confirm = input("This will DROP all tables. Type 'yes' to confirm: ")
        if confirm != "yes":
            print("Aborted.")
            return
        Base.metadata.drop_all(bind=engine)
        print("All tables dropped.")

    Base.metadata.create_all(bind=engine)
    print("Tables created successfully:")

    from sqlalchemy import inspect
    inspector = inspect(engine)
    for table in inspector.get_table_names():
        cols = len(inspector.get_columns(table))
        print(f"  {table} ({cols} columns)")


if __name__ == "__main__":
    main()
