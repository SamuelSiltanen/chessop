"""SQLite schema and connection management for the repertoire graph + caches.

Implements the schema from DESIGN.md sec 2. Two small, deliberate deviations
from the doc, both internal:
  - engine_cache gains a `uci` column and names the MultiPV index `pv_rank`
    (`rank` is a SQLite window-function keyword).
"""
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    fen            TEXT PRIMARY KEY,
    side_to_move   TEXT NOT NULL,
    opening_eco    TEXT,
    opening_name   TEXT,
    plan_note      TEXT,
    analyzed_depth INTEGER
);

CREATE TABLE IF NOT EXISTS edges (
    from_fen   TEXT NOT NULL,
    san        TEXT NOT NULL,
    to_fen     TEXT NOT NULL,
    is_mine    INTEGER NOT NULL DEFAULT 0,
    is_covered INTEGER NOT NULL DEFAULT 0,
    why_note   TEXT,
    PRIMARY KEY (from_fen, san)
);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges (to_fen);

CREATE TABLE IF NOT EXISTS engine_cache (
    fen     TEXT NOT NULL,
    depth   INTEGER NOT NULL,
    pv_rank INTEGER NOT NULL,
    san     TEXT NOT NULL,
    uci     TEXT NOT NULL,
    cp      INTEGER,
    mate    INTEGER,
    PRIMARY KEY (fen, depth, pv_rank)
);

CREATE TABLE IF NOT EXISTS lichess_cache (
    fen        TEXT NOT NULL,
    params     TEXT NOT NULL,
    json       TEXT NOT NULL,
    fetched_at TEXT,
    PRIMARY KEY (fen, params)
);

CREATE TABLE IF NOT EXISTS confusable_pairs (
    fen_a    TEXT NOT NULL,
    fen_b    TEXT NOT NULL,
    distance INTEGER,
    cue_a    TEXT,
    cue_b    TEXT,
    PRIMARY KEY (fen_a, fen_b)
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Drop the phase-1 JSON-blob engine_cache so the normalized schema applies.

    Safe: engine_cache only holds derived Stockfish results, regenerated on demand.
    """
    cols = [row[1] for row in conn.execute("PRAGMA table_info(engine_cache)")]
    if "json" in cols:
        conn.execute("DROP TABLE engine_cache")


def connect() -> sqlite3.Connection:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.CACHE_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    conn.executescript(_SCHEMA)
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    """A connection that commits on clean exit and always closes."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
