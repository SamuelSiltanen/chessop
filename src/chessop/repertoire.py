"""The repertoire graph: positions (nodes) and committed moves (edges).

Operations are deliberately storage-only and offline — they don't call
Stockfish or Lichess. Enrichment (opening names, engine depth) is layered on top
via `enrich_position`, which the interactive workflow (phase 4) will drive.

Transpositions are handled natively: because positions are keyed by normalized
FEN, the same position reached by different move orders is one node. A commit
that lands on a node already reachable by a *different* move is reported as a
transposition.
"""
import sqlite3
from typing import Optional, TypedDict

from . import config, engine, fen, lichess


class CommitResult(TypedDict):
    to_fen: str          # normalized FEN reached by the move
    edge_created: bool   # False if this (from_fen, san) edge already existed
    transposition: bool  # True if to_fen was already reachable by another move


def add_position(
    conn: sqlite3.Connection,
    fen_str: str,
    *,
    opening_name: Optional[str] = None,
    opening_eco: Optional[str] = None,
    analyzed_depth: Optional[int] = None,
) -> bool:
    """Insert a position node if absent. Returns True if newly created."""
    key = fen.normalize(fen_str)
    if conn.execute("SELECT 1 FROM positions WHERE fen=?", (key,)).fetchone():
        return False
    conn.execute(
        "INSERT INTO positions"
        " (fen, side_to_move, opening_eco, opening_name, analyzed_depth)"
        " VALUES (?,?,?,?,?)",
        (key, fen.side_to_move(key), opening_eco, opening_name, analyzed_depth),
    )
    return True


def get_position(conn: sqlite3.Connection, fen_str: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM positions WHERE fen=?", (fen.normalize(fen_str),)
    ).fetchone()


def children(conn: sqlite3.Connection, fen_str: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM edges WHERE from_fen=? ORDER BY san",
        (fen.normalize(fen_str),),
    ).fetchall()


def commit_move(
    conn: sqlite3.Connection, from_fen: str, san: str, *, mine: bool
) -> CommitResult:
    """Add (or update) an edge for `san` from `from_fen`.

    `mine=True` marks it as the move you'll play; `mine=False` marks an opponent
    reply you're covering. Re-committing the same move is idempotent except that
    it may set the other flag. Both endpoint nodes are ensured to exist.
    """
    parent = fen.normalize(from_fen)
    board = fen.to_board(parent)
    board.push(board.parse_san(san))   # raises ValueError on an illegal/ambiguous SAN
    child = fen.normalize(board.fen())

    # Transposition: is `child` already reachable via a *different* edge?
    incoming = conn.execute(
        "SELECT from_fen, san FROM edges WHERE to_fen=?", (child,)
    ).fetchall()
    transposition = any((r["from_fen"], r["san"]) != (parent, san) for r in incoming)

    add_position(conn, parent)
    add_position(conn, child)

    existing = conn.execute(
        "SELECT 1 FROM edges WHERE from_fen=? AND san=?", (parent, san)
    ).fetchone()
    if existing:
        column = "is_mine" if mine else "is_covered"
        conn.execute(
            f"UPDATE edges SET {column}=1, to_fen=? WHERE from_fen=? AND san=?",
            (child, parent, san),
        )
        edge_created = False
    else:
        conn.execute(
            "INSERT INTO edges (from_fen, san, to_fen, is_mine, is_covered)"
            " VALUES (?,?,?,?,?)",
            (parent, san, child, int(mine), int(not mine)),
        )
        edge_created = True

    return {
        "to_fen": child,
        "edge_created": edge_created,
        "transposition": transposition,
    }


def enrich_position(conn: sqlite3.Connection, fen_str: str) -> None:
    """Fill in opening name/ECO (Lichess) and analyzed depth (Stockfish).

    Online: hits Lichess (cached) and runs the engine (cached). Optional —
    the graph is fully usable without it.
    """
    key = fen.normalize(fen_str)
    add_position(conn, key)

    _, opening = lichess.moves(key)
    engine.analyse(key)  # populates the engine cache for this position

    conn.execute(
        "UPDATE positions SET opening_name=?, analyzed_depth=? WHERE fen=?",
        (opening, config.DEPTH, key),
    )
