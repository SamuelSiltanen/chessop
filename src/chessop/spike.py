"""Phase-1 spike CLI (now a thin text view over the shared scorer).

Given a position, print Stockfish's candidate lines next to Lichess's human
stats, merged into one table.

Usage:
    python -m chessop.spike                       # start position
    python -m chessop.spike --moves "e4 c5 Nf3"   # build from SAN
    python -m chessop.spike --fen "<FEN>"
"""
import argparse

import chess

from . import config, scorer


def fen_from_moves(sans: str) -> str:
    board = chess.Board()
    for token in sans.split():
        board.push_san(token)
    return board.fen()


def main() -> None:
    parser = argparse.ArgumentParser(description="chessop phase-1 spike")
    parser.add_argument("--fen", default=config.STARTPOS_FEN)
    parser.add_argument("--moves", help="SAN moves from the start position")
    args = parser.parse_args()

    fen = fen_from_moves(args.moves) if args.moves else args.fen
    data = scorer.score_position(fen)

    print(f"\nPosition : {data['fen']}")
    if data["opening"]:
        print(f"Opening  : {data['opening']}")
    print(
        f"To move  : {data['side_to_move'].capitalize()}"
        f"   depth={config.DEPTH} multipv={config.MULTIPV}"
        f"   ratings={config.LICHESS_RATINGS} speeds={config.LICHESS_SPEEDS}"
    )
    if data["sharp"]:
        print("** SHARP: only one sound move -> extend this line **")
    print()

    head = (
        f"{'move':<7}{'eval':>7}{'dcp':>6}{'sound':>6}"
        f"{'games':>15}{'score':>8}{'freq':>8}  flag"
    )
    print(head)
    print("-" * len(head))
    for r in data["candidates"]:
        delta = "" if r["delta"] is None else str(r["delta"])
        sound = "" if r["sound"] is None else ("Y" if r["sound"] else "n")
        score = "" if r["score"] is None else f"{r['score'] * 100:.1f}%"
        freq = f"{r['freq'] * 100:.1f}%" if r["games"] else ""
        print(
            f"{r['san']:<7}{r['eval']:>7}{delta:>6}{sound:>6}"
            f"{r['games']:>15,}{score:>8}{freq:>8}  {r['flag']}"
        )
    print()


if __name__ == "__main__":
    main()
