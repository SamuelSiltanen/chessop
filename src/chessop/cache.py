"""Caches for engine and Lichess results, backed by the shared SQLite db.

Caching is mandatory, not an optimization: the Lichess explorer is rate-limited,
and Stockfish results are only reusable because fixed-depth analysis is
reproducible (see DESIGN.md sec 2 & 4).

Engine results are now stored in the normalized engine_cache table (one row per
MultiPV line), replacing the phase-1 JSON blob.
"""
import json
from typing import Optional

from . import db, fen


def get_engine(fen_str: str, depth: int) -> Optional[list]:
    key = fen.normalize(fen_str)
    with db.session() as conn:
        rows = conn.execute(
            "SELECT san, uci, cp, mate FROM engine_cache"
            " WHERE fen=? AND depth=? ORDER BY pv_rank",
            (key, depth),
        ).fetchall()
    if not rows:
        return None
    return [dict(r) for r in rows]


def put_engine(fen_str: str, depth: int, results: list) -> None:
    key = fen.normalize(fen_str)
    with db.session() as conn:
        conn.execute(
            "DELETE FROM engine_cache WHERE fen=? AND depth=?", (key, depth)
        )
        conn.executemany(
            "INSERT INTO engine_cache (fen, depth, pv_rank, san, uci, cp, mate)"
            " VALUES (?,?,?,?,?,?,?)",
            [
                (key, depth, i + 1, m["san"], m["uci"], m["cp"], m["mate"])
                for i, m in enumerate(results)
            ],
        )


def get_lichess(fen_str: str, params: str) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute(
            "SELECT json FROM lichess_cache WHERE fen=? AND params=?",
            (fen.normalize(fen_str), params),
        ).fetchone()
    return json.loads(row["json"]) if row else None


def put_lichess(fen_str: str, params: str, data: dict, fetched_at: str) -> None:
    with db.session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO lichess_cache (fen, params, json, fetched_at)"
            " VALUES (?,?,?,?)",
            (fen.normalize(fen_str), params, json.dumps(data), fetched_at),
        )
