"""Phase-1 spike CLI.

Given a position, print Stockfish's candidate lines next to Lichess's human
stats, merged into one table. This is the seed of the candidate scorer
(DESIGN.md sec 3): it already computes eval_delta, the soundness flag, and the
divergence signals (sound-but-rare surprise weapons; popular-but-not-sound).

Usage:
    python -m chessop.spike                       # start position
    python -m chessop.spike --moves "e4 c5 Nf3"   # build from SAN
    python -m chessop.spike --fen "<FEN>"
"""
import argparse

import chess

from . import config, engine, lichess


def fen_from_moves(sans: str) -> str:
    board = chess.Board()
    for token in sans.split():
        board.push_san(token)
    return board.fen()


def fmt_eval(m: dict) -> str:
    if m is None:
        return "-"
    if m["mate"] is not None:
        return f"#{m['mate']}"
    return f"{m['cp'] / 100:+.2f}"


def build_rows(fen: str):
    eng = {m["san"]: m for m in engine.analyse(fen)}
    human_list, opening = lichess.moves(fen)
    human = {m["san"]: m for m in human_list}

    best = max(eng.values(), key=engine.sort_value) if eng else None
    best_val = engine.sort_value(best) if best else None

    sound_count = 0
    rows = []
    for san in set(eng) | set(human):
        e = eng.get(san)
        h = human.get(san)

        delta = None
        sound = None
        if e is not None and best_val is not None:
            delta = best_val - engine.sort_value(e)
            sound = delta <= config.DELTA_SOUND
            if sound:
                sound_count += 1

        freq = h["frequency"] if h else 0.0
        flag = ""
        if e is None and h is not None:
            flag = "off-top5?"          # unknown soundness (outside MultiPV)
        elif sound and h is not None and freq < 0.05:
            flag = "surprise"           # sound but rarely played
        elif sound is False and freq >= 0.10:
            flag = "dubious-pop"        # popular but not sound -> wants refuting

        rows.append(
            {
                "san": san,
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
    rows.sort(key=lambda r: (r["games"], -(r["delta"] or 1_000_000)), reverse=True)
    sharp = sound_count == 1
    return rows, opening, sharp


def main() -> None:
    parser = argparse.ArgumentParser(description="chessop phase-1 spike")
    parser.add_argument("--fen", default=config.STARTPOS_FEN)
    parser.add_argument("--moves", help="SAN moves from the start position")
    args = parser.parse_args()

    fen = fen_from_moves(args.moves) if args.moves else args.fen
    board = chess.Board(fen)
    rows, opening, sharp = build_rows(fen)

    stm = "White" if board.turn == chess.WHITE else "Black"
    print(f"\nPosition : {fen}")
    if opening:
        print(f"Opening  : {opening}")
    print(
        f"To move  : {stm}   depth={config.DEPTH} multipv={config.MULTIPV}"
        f"   ratings={config.LICHESS_RATINGS} speeds={config.LICHESS_SPEEDS}"
    )
    if sharp:
        print("** SHARP: only one sound move -> extend this line **")
    print()

    head = f"{'move':<7}{'eval':>7}{'dcp':>6}{'sound':>6}{'games':>15}{'score':>8}{'freq':>8}  flag"
    print(head)
    print("-" * len(head))
    for r in rows:
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
