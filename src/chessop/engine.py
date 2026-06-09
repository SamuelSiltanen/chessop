"""Stockfish integration via python-chess UCI.

Analyses a position at fixed depth and MultiPV, returning candidate moves with
evals from the side-to-move's perspective (positive = good for the player on
move). Results are cached by (fen, depth) so identical positions aren't
re-analysed.
"""
from typing import Optional, TypedDict

import chess
import chess.engine

from . import cache, config


class EngineMove(TypedDict):
    san: str
    uci: str
    cp: Optional[int]    # centipawns, side-to-move POV; None if mate
    mate: Optional[int]  # mate-in-N, side-to-move POV; None if not mate


def analyse(
    fen: str,
    depth: int = config.DEPTH,
    multipv: int = config.MULTIPV,
) -> list[EngineMove]:
    cached = cache.get_engine(fen, depth)
    if cached is not None:
        return cached

    board = chess.Board(fen)
    with chess.engine.SimpleEngine.popen_uci(config.STOCKFISH_PATH) as engine:
        engine.configure(
            {"Threads": config.ENGINE_THREADS, "Hash": config.ENGINE_HASH_MB}
        )
        infos = engine.analyse(
            board, chess.engine.Limit(depth=depth), multipv=multipv
        )

    results: list[EngineMove] = []
    for info in infos:
        move = info["pv"][0]
        score = info["score"].pov(board.turn)  # side-to-move perspective
        results.append(
            {
                "san": board.san(move),
                "uci": move.uci(),
                "cp": score.score(),       # None if mate
                "mate": score.mate(),      # None if not mate
            }
        )

    cache.put_engine(fen, depth, results)
    return results


def sort_value(move: EngineMove) -> int:
    """Map an eval to a single sortable integer (higher = better for mover).

    Mate scores are mapped far outside the centipawn range so they always sort
    above/below real evals while still ordering by distance to mate.
    """
    if move["mate"] is not None:
        m = move["mate"]
        return 1_000_000 - m if m > 0 else -1_000_000 - m
    return move["cp"] if move["cp"] is not None else 0
