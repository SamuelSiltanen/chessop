"""SQLite schema and connection management for the repertoire graph + caches.

Implements the schema from DESIGN.md sec 2. Deliberate deviations, all internal:
  - engine_cache gains a `uci` column and names the MultiPV index `pv_rank`
    (`rank` is a SQLite window-function keyword).
  - The graph is keyed per *named repertoire*: `positions` (and the engine /
    Lichess caches) are shared analysis nodes, while `edges` — your committed
    moves and covered replies — and plan notes belong to one repertoire.
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

CREATE TABLE IF NOT EXISTS repertoires (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    color      TEXT NOT NULL CHECK (color IN ('white', 'black')),
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS edges (
    repertoire_id INTEGER NOT NULL,
    from_fen   TEXT NOT NULL,
    san        TEXT NOT NULL,
    to_fen     TEXT NOT NULL,
    is_mine    INTEGER NOT NULL DEFAULT 0,
    is_covered INTEGER NOT NULL DEFAULT 0,
    why_note   TEXT,
    PRIMARY KEY (repertoire_id, from_fen, san),
    FOREIGN KEY (repertoire_id) REFERENCES repertoires (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges (repertoire_id, to_fen);
CREATE INDEX IF NOT EXISTS idx_edges_from ON edges (repertoire_id, from_fen);

-- Plan notes are per-repertoire (the plan depends on which repertoire you're
-- building); positions.plan_note is legacy and unused.
CREATE TABLE IF NOT EXISTS repertoire_notes (
    repertoire_id INTEGER NOT NULL,
    fen           TEXT NOT NULL,
    plan_note     TEXT,
    PRIMARY KEY (repertoire_id, fen),
    FOREIGN KEY (repertoire_id) REFERENCES repertoires (id) ON DELETE CASCADE
);

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

CREATE TABLE IF NOT EXISTS engine_move_cache (
    fen   TEXT NOT NULL,
    depth INTEGER NOT NULL,
    uci   TEXT NOT NULL,
    san   TEXT NOT NULL,
    cp    INTEGER,
    mate  INTEGER,
    PRIMARY KEY (fen, depth, uci)
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
    """Bring an older DB up to the current schema before it's (re)created.

    Both steps only drop derived/unscoped data, never the engine/Lichess caches:
      - the phase-1 JSON-blob engine_cache (regenerated on demand);
      - the pre-repertoire `edges` table, whose rows have no repertoire to belong
        to under the named-repertoire model — they're dropped so the new,
        repertoire-scoped `edges` is created fresh.
    """
    cols = [row[1] for row in conn.execute("PRAGMA table_info(engine_cache)")]
    if "json" in cols:
        conn.execute("DROP TABLE engine_cache")

    edge_cols = [row[1] for row in conn.execute("PRAGMA table_info(edges)")]
    if edge_cols and "repertoire_id" not in edge_cols:
        conn.execute("DROP TABLE edges")


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
