"""The candidate scorer: fuse Stockfish + Lichess into one ranked list.

This is the single source of truth behind both the CLI spike and the web API.
Given a position it returns, per legal candidate move, the row shape from
DESIGN.md sec 3 plus the raw fields the UI needs (uci, cp, mate).
"""
from typing import Optional, TypedDict

from . import config, engine, fen as fenmod, lichess


class Candidate(TypedDict):
    san: str
    uci: str
    cp: Optional[int]
    mate: Optional[int]
    eval: str            # display string, e.g. "+0.35" or "#5"
    delta: Optional[int]  # cp behind the best move (None if not an engine move)
    sound: Optional[bool]
    games: int
    score: Optional[float]
    freq: float
    flag: str


def fmt_eval(m: Optional[dict]) -> str:
    if m is None:
        return "-"
    if m["mate"] is not None:
        return f"#{m['mate']}"
    return f"{m['cp'] / 100:+.2f}"


def score_position(fen_str: str) -> dict:
    eng = {m["san"]: m for m in engine.analyse(fen_str)}
    human_list, opening = lichess.moves(fen_str)
    human = {m["san"]: m for m in human_list}

    best = max(eng.values(), key=engine.sort_value) if eng else None
    best_val = engine.sort_value(best) if best else None

    sound_count = 0
    candidates: list[Candidate] = []
    for san in set(eng) | set(human):
        e = eng.get(san)
        h = human.get(san)

        delta = sound = None
        if e is not None and best_val is not None:
            delta = best_val - engine.sort_value(e)
            sound = delta <= config.DELTA_SOUND
            if sound:
                sound_count += 1

        freq = h["frequency"] if h else 0.0
        flag = ""
        if e is None and h is not None:
            flag = "off-top5?"
        elif sound and h is not None and freq < 0.05:
            flag = "surprise"
        elif sound is False and freq >= 0.10:
            flag = "dubious-pop"

        candidates.append(
            {
                "san": san,
                "uci": (e or h)["uci"],
                "cp": e["cp"] if e else None,
                "mate": e["mate"] if e else None,
                "eval": fmt_eval(e),
                "delta": delta,
                "sound": sound,
                "games": h["games"] if h else 0,
                "score": h["score"] if h else None,
                "freq": freq,
                "flag": flag,
            }
        )

    # Most-played first (the human view); engine-only lines fall to the bottom.
    candidates.sort(
        key=lambda r: (r["games"], -(r["delta"] or 1_000_000)), reverse=True
    )

    board = fenmod.to_board(fen_str)
    return {
        "fen": board.fen(),
        "side_to_move": "white" if board.turn else "black",
        "opening": opening,
        "sharp": sound_count == 1,
        "candidates": candidates,
    }
