"""Checks for annotated PGN export.

Runs as a plain script (no framework, no network):

    python tests/test_pgn_export.py

A fake frequency provider keeps opponent-reply ordering deterministic offline.
"""
import pathlib
import sys
import tempfile

_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))

from chessop import config  # noqa: E402

_TMP = pathlib.Path(tempfile.mkdtemp()) / "test_pgn.sqlite"
config.CACHE_DIR = _TMP.parent
config.CACHE_DB = _TMP

from chessop import db, fen as fenmod, pgn_export, repertoire  # noqa: E402

START = config.STARTPOS_FEN
FREQ: dict = {}


def freq_fn(fen_str):
    return FREQ.get(fenmod.normalize(fen_str), {})


def _new_rep(name, color="white"):
    with db.session() as conn:
        return repertoire.create_repertoire(conn, name, color)


def test_pgn_structure():
    rep = _new_rep("White e4")
    with db.session() as conn:
        after_e4 = repertoire.commit_move(conn, rep, START, "e4", mine=True)["to_fen"]
        repertoire.set_why_note(conn, rep, START, "e4", "stake the centre")
        FREQ[after_e4] = {"c5": 0.60, "e5": 0.40}
        after_c5 = repertoire.commit_move(conn, rep, after_e4, "c5", mine=False)["to_fen"]
        repertoire.commit_move(conn, rep, after_e4, "e5", mine=False)
        repertoire.commit_move(conn, rep, after_c5, "Nf3", mine=True)
        repertoire.set_plan_note(conn, rep, after_c5, "develop and fight for d4")

        pgn = pgn_export.export_pgn(conn, rep, freq_fn=freq_fn)

    assert 'Event "chessop: White e4"' in pgn, pgn
    assert "e4" in pgn and "stake the centre" in pgn, pgn      # why-note comment
    assert "develop and fight for d4" in pgn, pgn             # plan-note comment
    assert "c5" in pgn and "e5" in pgn and "Nf3" in pgn, pgn
    # The more frequent reply (c5) is the mainline; e5 is the variation after it.
    assert pgn.index("c5") < pgn.index("e5"), pgn
    print("ok  PGN has mainline+variation, frequency order, and note comments")


def test_transposition_marker():
    rep = _new_rep("Knights")
    with db.session() as conn:
        # Two move orders (1.Nf3 Nf6 2.Nc3 / 1.Nc3 Nf6 2.Nf3) reach one position.
        a1 = repertoire.commit_move(conn, rep, START, "Nf3", mine=True)["to_fen"]
        a2 = repertoire.commit_move(conn, rep, a1, "Nf6", mine=False)["to_fen"]
        leaf = repertoire.commit_move(conn, rep, a2, "Nc3", mine=True)["to_fen"]

        b1 = repertoire.commit_move(conn, rep, START, "Nc3", mine=True)["to_fen"]
        b2 = repertoire.commit_move(conn, rep, b1, "Nf6", mine=False)["to_fen"]
        leaf2 = repertoire.commit_move(conn, rep, b2, "Nf3", mine=True)["to_fen"]
        assert leaf == leaf2, "both orders must reach one FEN"

        pgn = pgn_export.export_pgn(conn, rep, freq_fn=freq_fn)

    # The position is expanded once; the second arrival is marked, not duplicated.
    assert "(transposes)" in pgn, pgn
    print("ok  transpositions are marked, not duplicated")


def test_empty_repertoire():
    rep = _new_rep("Empty")
    with db.session() as conn:
        pgn = pgn_export.export_pgn(conn, rep, freq_fn=freq_fn)
    assert 'Event "chessop: Empty"' in pgn and "*" in pgn, pgn
    print("ok  empty repertoire exports headers only")


if __name__ == "__main__":
    test_pgn_structure()
    test_transposition_marker()
    test_empty_repertoire()
    print("\nAll PGN export checks passed.")
