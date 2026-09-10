"""Postgres access for the data pipelines (local docker compose).

Thin wrapper over psycopg3 using ``DATABASE_URL`` from the environment
(default: the local docker Postgres on :55432). Plus a tiny migration runner
that applies the ``migrations/*.sql`` files (idempotent DDL).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://pravo:pravo_local_dev@localhost:55432/pravo"
)
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


def run_migrations(conn: psycopg.Connection | None = None) -> list[str]:
    """Apply every migrations/*.sql in order. Returns the files applied."""
    own = conn is None
    conn = conn or connect()
    applied: list[str] = []
    try:
        with conn.cursor() as cur:
            for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                sql = sql_file.read_text(encoding="utf-8")
                # psycopg3 executes one statement per call; strip -- comments
                # first so semicolons inside comments don't split mid-statement.
                sql = re.sub(r"--[^\n]*", "", sql)
                for statement in (s.strip() for s in sql.split(";")):
                    if statement:
                        cur.execute(statement)  # type: ignore[arg-type]
                applied.append(sql_file.name)
        conn.commit()
    finally:
        if own:
            conn.close()
    return applied


if __name__ == "__main__":
    print("applied migrations:", run_migrations())
