"""Database access for Shopfront.

Design note: every function in services.py takes an explicit `conn`. No global connection.
That is what lets the eval harness (Node 04) give every trial its own fresh copy of the
database ("clean environment per trial") without monkeypatching anything.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path

from shopfront import clock

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path(os.environ.get("SHOPFRONT_DB", ROOT / "data" / "shopfront.db"))
SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection with sane defaults (row dicts, FK checks)."""
    conn = sqlite3.connect(str(path or DEFAULT_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text())
    conn.commit()


def snapshot(src: str | Path, dst: str | Path) -> Path:
    """Copy a seeded DB to a new file. Used for per-trial isolation in evals."""
    shutil.copyfile(src, dst)
    return Path(dst)


def audit(conn: sqlite3.Connection, actor: str, action: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
        (clock.now_iso(), actor, action, json.dumps(payload, sort_keys=True)),
    )


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def row(cur) -> dict | None:
    r = cur.fetchone()
    return dict(r) if r else None
