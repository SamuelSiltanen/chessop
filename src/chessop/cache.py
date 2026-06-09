"""SQLite caches for engine and Lichess results.

Caching is mandatory, not an optimization: the Lichess explorer is rate-limited,
and Stockfish results are only reusable because fixed-depth analysis is
reproducible (see DESIGN.md sec 2 & 4).

NOTE (phase-1 shortcut): engine results are stored as a single JSON blob per
(fen, depth) rather than the per-line `engine_cache` rows of the final schema.
Phase 2 replaces this with the normalized tables in DESIGN.md sec 2.
"""
import json
import sqlite3
from typing import Optional

from . import config


def fen_key(fen: str) -> str:
    """Normalized FEN used as a position identity key.

    Drops the halfmove-clock and fullmove-number fields, which don't change a
    position's identity for repertoire purposes. Keeps side-to-move, castling
    rights and en-passant square. This is what makes transpositions collapse.
    """
    parts = fen.split()
    return " ".join(parts[:4])


def _connect() -> sqlite3.Connection:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.CACHE_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS engine_cache ("
        " fen TEXT, depth INTEGER, json TEXT,"
        " PRIMARY KEY (fen, depth))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS lichess_cache ("
        " fen TEXT, params TEXT, json TEXT, fetched_at TEXT,"
        " PRIMARY KEY (fen, params))"
    )
    return conn


def get_engine(fen: str, depth: int) -> Optional[list]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT json FROM engine_cache WHERE fen=? AND depth=?",
            (fen_key(fen), depth),
        ).fetchone()
    return json.loads(row[0]) if row else None


def put_engine(fen: str, depth: int, results: list) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO engine_cache (fen, depth, json) VALUES (?,?,?)",
            (fen_key(fen), depth, json.dumps(results)),
        )


def get_lichess(fen: str, params: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT json FROM lichess_cache WHERE fen=? AND params=?",
            (fen_key(fen), params),
        ).fetchone()
    return json.loads(row[0]) if row else None


def put_lichess(fen: str, params: str, data: dict, fetched_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO lichess_cache (fen, params, json, fetched_at)"
            " VALUES (?,?,?,?)",
            (fen_key(fen), params, json.dumps(data), fetched_at),
        )
