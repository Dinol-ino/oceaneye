"""One-off migration: add push_subscriptions.assigned_camera_ids to an existing database.

SQLAlchemy's create_all() makes missing TABLES but never alters existing ones, so a database
created before lifeguard posts existed keeps the old push_subscriptions shape and every query
against it fails with "no such column". Run this once; it is safe to run again.

    python scripts/migrate_push_posts.py

Deleting data/oceaneye.db also works and is what a throwaway demo should do - but it discards
registered phones, configured beaches and the event history, which are the labelled outcomes the
risk thresholds are meant to be tuned against.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import Settings  # noqa: E402

COLUMN = "assigned_camera_ids"
TABLE = "push_subscriptions"


def main() -> int:
    url = Settings().database_url
    if not url.startswith("sqlite"):
        print(f"This migration only handles SQLite; your database is {url.split(':')[0]}.\n"
              f"Add the column by hand:  ALTER TABLE {TABLE} ADD COLUMN {COLUMN} JSON;", file=sys.stderr)
        return 2
    path = Path(url.split("///", 1)[-1]).resolve()
    if not path.is_file():
        print(f"No database at {path} - nothing to migrate. It will be created correctly on first run.")
        return 0

    con = sqlite3.connect(path)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if TABLE not in tables:
            print(f"No {TABLE} table yet; it will be created with the right shape on first run.")
            return 0
        columns = {r[1] for r in con.execute(f"PRAGMA table_info({TABLE})")}
        if COLUMN in columns:
            print(f"{TABLE}.{COLUMN} already present - nothing to do.")
            return 0
        con.execute(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} JSON")
        con.commit()
        print(f"Added {TABLE}.{COLUMN}. Existing phones have no post, which means roaming: they "
              f"keep receiving every alert until a guard picks a post.")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
