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
    rep_id: int,
    root_fen: str,
    color: str,
    freq_fn: FreqFn = _lichess_freqs,
) -> tuple[dict, list]:
    """Traverse committed edges from the root.

    Returns (reach, records): `reach` maps fen -> best reach probability;
    `records` is one dict per node in first-visit order, each with role
    ('mine'|'opp'), is_gap, `ply` (half-moves from the root along the path it
    was first reached by — for display/numbering), and (for opp nodes)
    covered_freq.
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

    stack = [(root, 1.0, 0)]
    while stack:
        node, r, ply = stack.pop()
        if r <= reach.get(node, -1.0):
            continue  # already reached at least this well; avoids cycles
        reach[node] = r

        stm = fenmod.side_to_move(node)
        edges = repertoire.children(conn, rep_id, node)

        if node not in seen:
            seen.add(node)
            if stm == side:
                has_move = any(e["is_mine"] for e in edges)
                records.append({"fen": node, "role": "mine",
                                "is_gap": not has_move, "ply": ply})
            else:
                fnode = freqs(node)
                covered = [e for e in edges if e["is_covered"]]
                cov = 0.0       # reply mass you've acknowledged (breadth)
                answered = 0.0  # reply mass you actually have a response ready for
                for e in covered:
                    fr = fnode.get(e["san"], 0.0)
                    cov += fr
                    child = e["to_fen"]
                    has_move = any(ce["is_mine"]
                                   for ce in repertoire.children(conn, rep_id, child))
                    # "Answered" = you've committed your reply there, or the line
                    # is rare enough that the stopping rule says you can stop.
                    if has_move or r * fr < config.REACH_FLOOR:
                        answered += fr
                records.append(
                    {
                        "fen": node,
                        "role": "opp",
                        "is_gap": cov < config.COVERAGE,
                        "covered_freq": cov,
                        "answered_freq": answered,
                        "ply": ply,
                    }
                )

        if stm == side:
            for e in edges:
                if e["is_mine"]:
                    stack.append((e["to_fen"], r, ply + 1))
        else:
            f = freqs(node)
            for e in edges:
                if e["is_covered"]:
                    stack.append((e["to_fen"], r * f.get(e["san"], 0.0), ply + 1))

    return reach, records


def _gaps(reach: dict, records: list) -> list:
    return [{**rec, "reach": reach[rec["fen"]]} for rec in records if rec["is_gap"]]


def next_gap(
    conn: sqlite3.Connection,
    rep_id: int,
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
    reach, records = walk(conn, rep_id, root_fen, color, freq_fn)
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
    rep_id: int,
    root_fen: str,
    color: str,
    freq_fn: FreqFn = _lichess_freqs,
) -> dict:
    """Completeness report: how ready you actually are, plus gap counts.

    `prepared` is the headline number — the reach-weighted fraction of opponent
    replies you have an answer ready for (your move committed in the resulting
    position, or a deliberate stop below the reach floor). It's low for a shallow
    repertoire and climbs as you fill in responses, unlike raw breadth coverage
    (`opponent_coverage`), which the fan-out pins near the floor by construction.
    """
    reach, records = walk(conn, rep_id, root_fen, color, freq_fn)
    opp = [r for r in records if r["role"] == "opp"]
    den = sum(reach[r["fen"]] for r in opp)
    cov_num = sum(reach[r["fen"]] * r["covered_freq"] for r in opp)
    ans_num = sum(reach[r["fen"]] * r["answered_freq"] for r in opp)
    return {
        "prepared": (ans_num / den) if den else 0.0,
        "opponent_coverage": (cov_num / den) if den else 1.0,
        "move_gaps": sum(1 for r in records if r["role"] == "mine" and r["is_gap"]),
        "cover_gaps": sum(1 for r in records if r["role"] == "opp" and r["is_gap"]),
        "positions": len(records),
    }


def branch_completeness(
    conn: sqlite3.Connection,
    rep_id: int,
    parent_fen: str,
    color: str,
    freq_fn: FreqFn = _lichess_freqs,
) -> dict:
    """Per-branch completeness for the committed moves out of `parent_fen`.

    Maps san -> the `prepared` fraction of the subtree that move leads to, each
    subtree treated as its own local root. So a covered reply with nothing built
    under it reads ~0, and a fully built-out line reads near 1 — letting the UI
    show how complete each branch is, not just that it exists. (It is the same
    readiness metric as `coverage`, scoped to the subtree.)
    """
    out: dict = {}
    for e in repertoire.children(conn, rep_id, parent_fen):
        if e["is_mine"] or e["is_covered"]:
            out[e["san"]] = coverage(
                conn, rep_id, e["to_fen"], color, freq_fn
            )["prepared"]
    return out
