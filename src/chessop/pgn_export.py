"""Export a repertoire to annotated PGN.

The repertoire is a FEN-keyed DAG; PGN is a move *tree*. We serialize from the
start position, depth-first:

  - At one of *your* nodes the single committed move is the continuation.
  - At an *opponent* node every covered reply becomes a variation, ordered
    most-frequent first (so the mainline follows the likeliest game).
  - Plan notes (per position) and "why this move" notes (per edge) are emitted
    as PGN `{comments}`.
  - Because positions can be reached by several move orders, a position is
    expanded only once; later arrivals get a `(transposes)` marker instead of a
    duplicated subtree, keeping the tree finite.

The result imports directly into a Lichess study, Chessable, or Anki (via a PGN
importer). Ordering opponent replies consults Lichess (cached); `freq_fn` is
injectable so the logic stays testable offline.
"""
import datetime
import sqlite3
from typing import Callable

import chess
import chess.pgn

from . import config, fen as fenmod, lichess, repertoire

FreqFn = Callable[[str], dict]


def _lichess_freqs(fen_str: str) -> dict:
    moves, _ = lichess.moves(fen_str)
    return {m["san"]: m["frequency"] for m in moves}


def _comment(conn: sqlite3.Connection, rep_id: int, why: str, child_fen: str) -> str:
    parts = []
    if why:
        parts.append(why)
    plan = repertoire.get_plan_note(conn, rep_id, child_fen)
    if plan:
        parts.append(f"[plan] {plan}")
    return "  ".join(parts)


def _expand(
    conn: sqlite3.Connection,
    rep_id: int,
    side: str,
    node_fen: str,
    board: chess.Board,
    pgn_node: chess.pgn.GameNode,
    visited: set,
    freq_fn: FreqFn,
) -> None:
    stm = fenmod.side_to_move(node_fen)
    edges = repertoire.children(conn, rep_id, node_fen)
    if stm == side:
        kids = [e for e in edges if e["is_mine"]]
    else:
        kids = [e for e in edges if e["is_covered"]]
        freqs = freq_fn(node_fen)
        kids.sort(key=lambda e: freqs.get(e["san"], 0.0), reverse=True)

    for e in kids:
        move = board.parse_san(e["san"])
        child = pgn_node.add_variation(move)   # first child becomes the mainline
        board.push(move)
        child_fen = fenmod.normalize(board.fen())

        comment = _comment(conn, rep_id, e["why_note"] or "", child_fen)
        if child_fen in visited:
            comment = (comment + "  " if comment else "") + "(transposes)"
            if comment:
                child.comment = comment
        else:
            if comment:
                child.comment = comment
            visited.add(child_fen)
            _expand(conn, rep_id, side, child_fen, board, child, visited, freq_fn)
        board.pop()


def export_pgn(
    conn: sqlite3.Connection,
    rep_id: int,
    *,
    freq_fn: FreqFn = _lichess_freqs,
) -> str:
    """Render the repertoire `rep_id` as a single annotated PGN string."""
    rep = repertoire.get_repertoire(conn, rep_id)
    if rep is None:
        raise ValueError("no such repertoire")

    color = rep["color"]
    side = "w" if color == "white" else "b"
    root_fen = fenmod.normalize(config.STARTPOS_FEN)

    game = chess.pgn.Game()
    game.headers["Event"] = f"chessop: {rep['name']}"
    game.headers["Site"] = "chessop"
    game.headers["White"] = rep["name"] if color == "white" else "Opponent"
    game.headers["Black"] = "Opponent" if color == "white" else rep["name"]
    game.headers["Date"] = datetime.date.today().strftime("%Y.%m.%d")
    game.headers["Result"] = "*"

    root_plan = repertoire.get_plan_note(conn, rep_id, root_fen)
    if root_plan:
        game.comment = root_plan

    board = fenmod.to_board(root_fen)
    visited = {root_fen}
    _expand(conn, rep_id, side, root_fen, board, game, visited, freq_fn)

    exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    return game.accept(exporter)
