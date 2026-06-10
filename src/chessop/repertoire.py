"""The repertoire graph: positions (nodes) and committed moves (edges).

Most operations are storage-only and offline. The exceptions are `commit_line`
and `enrich_position`, which consult Lichess/Stockfish; `commit_line` takes an
injectable `replies_fn` (defaulting to a Lichess-backed one) so its graph logic
stays testable offline, mirroring `frontier.py`.

Transpositions are handled natively: because positions are keyed by normalized
FEN, the same position reached by different move orders is one node. A commit
that lands on a node already reachable by a *different* move is reported as a
transposition.
"""
import sqlite3
from typing import Callable, Optional, TypedDict

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


def uncommit_move(
    conn: sqlite3.Connection, from_fen: str, san: str, *, mine: bool
) -> None:
    """Clear one flag on an edge; delete the edge if neither flag remains."""
    parent = fen.normalize(from_fen)
    column = "is_mine" if mine else "is_covered"
    conn.execute(
        f"UPDATE edges SET {column}=0 WHERE from_fen=? AND san=?", (parent, san)
    )
    conn.execute(
        "DELETE FROM edges WHERE from_fen=? AND san=?"
        " AND is_mine=0 AND is_covered=0",
        (parent, san),
    )


def set_my_move(
    conn: sqlite3.Connection, from_fen: str, san: str
) -> CommitResult:
    """Commit `san` as *the* move you play here — exactly one per position.

    Any other move previously marked `is_mine` at this node is unset (and the
    edge dropped if it carried no `is_covered` flag). This is the asymmetric
    half of construction: one chosen move for you, vs. a fan-out of replies for
    the opponent (`commit_line`).
    """
    parent = fen.normalize(from_fen)
    others = conn.execute(
        "SELECT san FROM edges WHERE from_fen=? AND is_mine=1 AND san<>?",
        (parent, san),
    ).fetchall()
    for o in others:
        uncommit_move(conn, parent, o["san"], mine=True)
    return commit_move(conn, parent, san, mine=True)


FreqList = Callable[[str], list[dict]]


def _lichess_replies(fen_str: str) -> list[dict]:
    """Opponent replies with their frequencies (Lichess-backed default)."""
    human, _ = lichess.moves(fen_str)
    return [{"san": m["san"], "frequency": m["frequency"]} for m in human]


def _covered_replies(replies: list[dict], spine_san: Optional[str]) -> list[str]:
    """The frequent replies to cover: most-played first until the cumulative
    frequency reaches COVERAGE. The line's own (spine) reply is always kept, so
    the committed line stays connected even when it's an off-beat choice."""
    chosen: list[str] = []
    cum = 0.0
    for r in sorted(replies, key=lambda r: r["frequency"], reverse=True):
        chosen.append(r["san"])
        cum += r["frequency"]
        if cum >= config.COVERAGE:
            break
    if spine_san and spine_san not in chosen:
        chosen.append(spine_san)
    return chosen


class LineResult(TypedDict):
    end_fen: str        # normalized FEN the line ends on
    my_moves: int       # your single moves set along the spine
    opp_nodes: int      # opponent nodes fanned out
    covered_edges: int  # new covered-reply edges created


def commit_line(
    conn: sqlite3.Connection,
    root_fen: str,
    sans: list[str],
    color: str,
    *,
    replies_fn: FreqList = _lichess_replies,
) -> LineResult:
    """Commit a whole browsed line at once, asymmetrically.

    Walking `sans` from `root_fen` (which must already be in the repertoire, or
    be the true root — keeping everything edge-connected): at each of *your*
    nodes the spine move becomes your single move; at each *opponent* node all
    frequent replies are covered (fan-out), not just the one walked. The fan-out
    also runs on the terminal node if the opponent is to move there, surfacing
    the next layer of "play your move" gaps.
    """
    side = "w" if color == "white" else "b"
    node = fen.normalize(root_fen)
    add_position(conn, node)

    res: LineResult = {"end_fen": node, "my_moves": 0,
                       "opp_nodes": 0, "covered_edges": 0}

    def fan_out(at: str, spine_san: Optional[str]) -> None:
        res["opp_nodes"] += 1
        for s in _covered_replies(replies_fn(at), spine_san):
            if commit_move(conn, at, s, mine=False)["edge_created"]:
                res["covered_edges"] += 1

    for san in sans:
        if fen.side_to_move(node) == side:
            set_my_move(conn, node, san)
            res["my_moves"] += 1
        else:
            fan_out(node, san)
        board = fen.to_board(node)
        board.push(board.parse_san(san))   # raises on illegal SAN
        node = fen.normalize(board.fen())

    if fen.side_to_move(node) != side:
        fan_out(node, None)

    res["end_fen"] = node
    return res


def set_plan_note(conn: sqlite3.Connection, fen_str: str, text: str) -> None:
    key = fen.normalize(fen_str)
    add_position(conn, key)
    conn.execute("UPDATE positions SET plan_note=? WHERE fen=?", (text, key))


def set_why_note(
    conn: sqlite3.Connection, from_fen: str, san: str, text: str
) -> None:
    conn.execute(
        "UPDATE edges SET why_note=? WHERE from_fen=? AND san=?",
        (text, fen.normalize(from_fen), san),
    )


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
