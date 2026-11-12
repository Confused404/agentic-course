"""GIVEN: an append-only run journal in SQLite (Node 14 TEXTBOOK §3).

Every step of a durable run is appended BEFORE the next step starts: the run's starting point, each model
response, the intent to run a tool, its result, approval requests and decisions, and the end. After a crash the
journal is the only truth about what happened; `recovery.plan_recovery` reads it to decide what to do next.

Entry kinds and fields (all JSON-serialisable):
  start              {system, messages: [message dicts], config: {...}}
  assistant          {message: message dict, stop_reason}    one model response, verbatim
  intent             {call_id, tool, args}                    written BEFORE a tool runs
  result             {call_id, content, is_error, reconciled?}   written AFTER it ran (or was reconciled, or a
                                                              human recorded what happened); a denial is an
                                                              `approval` with approved=false, not a result
  approval_requested {call_id, tool, args}
  approval           {call_id, approved: bool, by, note}
  end                {stop, final_text}
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

KINDS = ("start", "assistant", "intent", "result", "approval_requested", "approval", "end")


class Journal:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS entries (
            run_id TEXT NOT NULL, seq INTEGER NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL, ts REAL NOT NULL,
            PRIMARY KEY (run_id, seq))""")

    def append(self, run_id: str, kind: str, **data) -> dict:
        """Append and COMMIT one entry (it's durable when this returns). Returns the entry."""
        if kind not in KINDS:
            raise ValueError(f"unknown entry kind {kind!r}")
        with self._lock:
            seq = self._conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM entries WHERE run_id = ?",
                                     (run_id,)).fetchone()[0]
            ts = time.time()
            self._conn.execute("INSERT INTO entries VALUES (?, ?, ?, ?, ?)",
                               (run_id, seq, kind, json.dumps(data, sort_keys=True), ts))
        return {"run_id": run_id, "seq": seq, "kind": kind, "ts": ts, **data}

    def entries(self, run_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT seq, kind, data, ts FROM entries WHERE run_id = ? ORDER BY seq",
                                      (run_id,)).fetchall()
        return [{"run_id": run_id, "seq": s, "kind": k, "ts": t, **json.loads(d)} for s, k, d, t in rows]

    def runs(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute("SELECT DISTINCT run_id FROM entries ORDER BY run_id")]

    def close(self) -> None:
        self._conn.close()
