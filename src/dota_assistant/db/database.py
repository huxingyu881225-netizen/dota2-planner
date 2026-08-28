"""SQLite connection + schema init."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_DEFAULT_PATH = os.environ.get("DOTA_DB", str(Path(__file__).resolve().parents[3] / "data" / "dota_planner.db"))


def default_db_path() -> Path:
    return Path(_DEFAULT_PATH)


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    schema = Path(__file__).resolve().parent / "schema.sql"
    conn.executescript(schema.read_text(encoding="utf-8"))
    conn.commit()
