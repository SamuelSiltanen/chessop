"""Stockfish integration via python-chess UCI.

Analyses a position at fixed depth and MultiPV, returning candidate moves with
evals from the side-to-move's perspective (positive = good for the player on
move). Results are cached by (fen, depth) so identical positions aren't
re-analysed.
"""
from typing import Optional, TypedDict

import chess
import chess.engine

from . import cache, config, fen as fenmod


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

    board = fenmod.to_board(fen)
    with chess.engine.SimpleEngine.popen_uci(config.STOCKFISH_PATH) as engine:
        engine.configure(
            {"Threads": config.ENGINE_THREADS, "Hash": config.ENGINE_HASH_MB}
        )
        infos = engine.analyse(
            board, chess.engine.Limit(depth=depth), multipv=multipv
        )

    results = [_line(board, info) for info in infos]
    cache.put_engine(fen, depth, results)
    return results


def evaluate_moves(
    fen: str, ucis: list[str], depth: int = config.DEPTH
) -> list[EngineMove]:
    """Evaluate specific moves (e.g. popular off-book replies), cached per move.

    One search restricted to `ucis` via root_moves, so all requested moves are
    scored in a single engine pass.
    """
    cached = cache.get_engine_moves(fen, depth, ucis)
    missing = [u for u in ucis if u not in cached]

    if missing:
        board = fenmod.to_board(fen)
        moves = [chess.Move.from_uci(u) for u in missing]
        with chess.engine.SimpleEngine.popen_uci(config.STOCKFISH_PATH) as engine:
            engine.configure(
                {"Threads": config.ENGINE_THREADS, "Hash": config.ENGINE_HASH_MB}
            )
            infos = engine.analyse(
                board,
                chess.engine.Limit(depth=depth),
                multipv=len(moves),
                root_moves=moves,
            )
        fresh = [_line(board, info) for info in infos]
        cache.put_engine_moves(fen, depth, fresh)
        for m in fresh:
            cached[m["uci"]] = m

    return [cached[u] for u in ucis if u in cached]


def _line(board: chess.Board, info: dict) -> EngineMove:
    move = info["pv"][0]
    score = info["score"].pov(board.turn)  # side-to-move perspective
    return {
        "san": board.san(move),
        "uci": move.uci(),
        "cp": score.score(),   # None if mate
        "mate": score.mate(),  # None if not mate
    }


def sort_value(move: EngineMove) -> int:
    """Map an eval to a single sortable integer (higher = better for mover).

    Mate scores are mapped far outside the centipawn range so they always sort
    above/below real evals while still ordering by distance to mate.
    """
    if move["mate"] is not None:
        m = move["mate"]
        return 1_000_000 - m if m > 0 else -1_000_000 - m
    return move["cp"] if move["cp"] is not None else 0
