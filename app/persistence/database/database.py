"""Engine/session management. SQLite for the prototype; a PostgreSQL URL works unchanged
(add a driver + migrations then)."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.persistence.database.base import Base

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, url: str, echo: bool = False) -> None:
        parsed = make_url(url)
        self.backend = parsed.get_backend_name()
        kwargs: dict = {"echo": echo, "future": True}
        if self.backend == "sqlite":
            kwargs["connect_args"] = {"check_same_thread": False}
            if parsed.database in (None, "", ":memory:"):
                kwargs["poolclass"] = StaticPool  # one shared in-memory DB (tests)
            else:
                Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, **kwargs)
        if self.backend == "sqlite":
            @event.listens_for(self.engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _):  # noqa: ANN001
                dbapi_conn.execute("PRAGMA foreign_keys=ON")
                # WAL lets the API read while a worker's HTTP callbacks write, instead of
                # "database is locked" under concurrent cameras.
                dbapi_conn.execute("PRAGMA journal_mode=WAL")
                dbapi_conn.execute("PRAGMA busy_timeout=5000")
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        import app.persistence.models  # noqa: F401  (register tables)

        Base.metadata.create_all(self.engine)
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        """Add nullable columns that ``create_all`` cannot add to an already-existing table.

        A stopgap, not a migration tool: it only ever ADDs nullable/defaulted columns, never drops,
        renames or re-types anything, and it is idempotent. It exists so an existing
        ``data/oceaneye.db`` keeps working when a release adds a field - replacing it with Alembic is
        the right move once the schema stops moving. Anything beyond an additive column must be a
        real migration.
        """
        inspector = inspect(self.engine)
        additions = {
            # table: {column: SQL type with its default}
            "cameras": {"beach_id": "VARCHAR(64)"},
        }
        for table, columns in additions.items():
            if not inspector.has_table(table):
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name in present:
                    continue
                with self.engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                logger.info("schema updated: added %s.%s", table, name)

    def ping(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001
            return False

    def dispose(self) -> None:
        self.engine.dispose()
