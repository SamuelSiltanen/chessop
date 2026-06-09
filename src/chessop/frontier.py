"""The construction frontier: what still needs a decision, and how complete the
repertoire is (DESIGN.md sec 6-7).

A repertoire is built for one colour. Walking the committed edges from the root:

  - At a *your-turn* node you should have exactly one committed move (`is_mine`).
    None committed -> a "play your move here" gap.
  - At an *opponent-turn* node you cover replies up to the cumulative-frequency
    floor (config.COVERAGE). Covered replies summing below the floor -> a "cover
    more replies here" gap.

Reach probability = product of opponent-move frequencies along the path (your
own moves are certain). It ranks gaps by how often you'd actually hit them.

The Lichess frequency lookup is injected (`freq_fn`) so the logic is testable
offline.
"""
from typing import Callable, Optional

import sqlite3

from . import config, fen as fenmod, lichess, repertoire

FreqFn = Callable[[str], dict]


def _lichess_freqs(fen_str: str) -> dict:
    moves, _ = lichess.moves(fen_str)
    return {m["san"]: m["frequency"] for m in moves}


def walk(
    conn: sqlite3.Connection,
    root_fen: str,
    color: str,
    freq_fn: FreqFn = _lichess_freqs,
) -> tuple[dict, list]:
    """Traverse committed edges from the root.

    Returns (reach, records): `reach` maps fen -> best reach probability;
    `records` is one dict per node in first-visit order, each with role
    ('mine'|'opp'), is_gap, and (for opp nodes) covered_freq.
    """
    side = "w" if color == "white" else "b"
    root = fenmod.normalize(root_fen)

    reach: dict = {}
    records: list = []
    seen: set = set()
    fcache: dict = {}

    def freqs(node: str) -> dict:
        if node not in fcache:
            fcache[node] = freq_fn(node)
        return fcache[node]

    stack = [(root, 1.0)]
    while stack:
        node, r = stack.pop()
        if r <= reach.get(node, -1.0):
            continue  # already reached at least this well; avoids cycles
        reach[node] = r

        stm = fenmod.side_to_move(node)
        edges = repertoire.children(conn, node)

        if node not in seen:
            seen.add(node)
            if stm == side:
                has_move = any(e["is_mine"] for e in edges)
                records.append({"fen": node, "role": "mine", "is_gap": not has_move})
            else:
                covered = [e for e in edges if e["is_covered"]]
                cov = sum(freqs(node).get(e["san"], 0.0) for e in covered)
                records.append(
                    {
                        "fen": node,
                        "role": "opp",
                        "is_gap": cov < config.COVERAGE,
                        "covered_freq": cov,
                    }
                )

        if stm == side:
            for e in edges:
                if e["is_mine"]:
                    stack.append((e["to_fen"], r))
        else:
            f = freqs(node)
            for e in edges:
                if e["is_covered"]:
                    stack.append((e["to_fen"], r * f.get(e["san"], 0.0)))

    return reach, records


def _gaps(reach: dict, records: list) -> list:
    return [{**rec, "reach": reach[rec["fen"]]} for rec in records if rec["is_gap"]]


def next_gap(
    conn: sqlite3.Connection,
    root_fen: str,
    color: str,
    mode: str = "impact",
    exclude_fen: Optional[str] = None,
    freq_fn: FreqFn = _lichess_freqs,
) -> Optional[dict]:
    """The next position to work on, per mode.

    'impact'    -> highest reach probability (most likely to actually face).
    'traversal' -> first gap in depth-first order (finish one line before next).
    'free'      -> no worklist.
    """
    if mode == "free":
        return None
    reach, records = walk(conn, root_fen, color, freq_fn)
    order = {rec["fen"]: i for i, rec in enumerate(records)}
    gaps = _gaps(reach, records)
    if exclude_fen:
        ex = fenmod.normalize(exclude_fen)
        gaps = [g for g in gaps if g["fen"] != ex]
    if not gaps:
        return None
    if mode == "traversal":
        return min(gaps, key=lambda g: order[g["fen"]])
    return max(gaps, key=lambda g: g["reach"])  # impact (default)


def coverage(
    conn: sqlite3.Connection,
    root_fen: str,
    color: str,
    freq_fn: FreqFn = _lichess_freqs,
) -> dict:
    """Completeness report: opponent-reply coverage plus gap counts."""
    reach, records = walk(conn, root_fen, color, freq_fn)
    opp = [r for r in records if r["role"] == "opp"]
    den = sum(reach[r["fen"]] for r in opp)
    num = sum(reach[r["fen"]] * r["covered_freq"] for r in opp)
    return {
        "opponent_coverage": (num / den) if den else 1.0,
        "move_gaps": sum(1 for r in records if r["role"] == "mine" and r["is_gap"]),
        "cover_gaps": sum(1 for r in records if r["role"] == "opp" and r["is_gap"]),
        "positions": len(records),
    }
