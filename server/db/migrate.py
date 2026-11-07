"""@brief Apply the numbered SQL files in db/migrations/ that are not applied yet.

Usage: python -m server.db.migrate   (reads DATABASE_URL)

Each file runs in its own transaction together with its row in
schema_migrations: a failing file leaves no half-applied schema behind.
Files are never edited after being applied; changes go in a new file.
"""

import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def _applied_migrations(conn: psycopg.Connection) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " filename text PRIMARY KEY,"
        " applied_at timestamptz NOT NULL DEFAULT now())"
    )
    rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def apply_migrations(conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """@brief Apply pending migrations in file name order.
    @param conn Connection in autocommit mode (each file gets its own transaction).
    @param migrations_dir Folder with the NNN_name.sql files.
    @return Names of the files applied by this call.
    """
    if not conn.autocommit:
        raise ValueError("apply_migrations needs an autocommit connection")
    already_applied = _applied_migrations(conn)
    newly_applied = []
    for sql_file in sorted(migrations_dir.glob("*.sql")):
        if sql_file.name in already_applied:
            continue
        with conn.transaction():
            # No query parameters, so psycopg accepts several statements at once.
            conn.execute(sql_file.read_text())
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (sql_file.name,))
        newly_applied.append(sql_file.name)
    return newly_applied


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    with psycopg.connect(database_url, autocommit=True) as conn:
        applied = apply_migrations(conn)
    print("applied: " + (", ".join(applied) if applied else "nothing, schema is up to date"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
