"""Phase-2 checks for the repertoire graph.

Runs as a plain script (no test framework needed):

    python tests/test_repertoire.py

Uses a throwaway temp database so it never touches the real cache.
"""
import pathlib
import sys
import tempfile

_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))

from chessop import config  # noqa: E402

# Point all storage at a fresh temp db BEFORE anything connects.
_TMP = pathlib.Path(tempfile.mkdtemp()) / "test_cache.sqlite"
config.CACHE_DIR = _TMP.parent
config.CACHE_DB = _TMP

from chessop import cache, db, fen, repertoire  # noqa: E402

START = config.STARTPOS_FEN


def test_transposition_collapses_to_one_node():
    with db.session() as conn:
        # Order A: 1.Nf3 Nf6 2.Nc3
        a1 = repertoire.commit_move(conn, START, "Nf3", mine=True)
        a2 = repertoire.commit_move(conn, a1["to_fen"], "Nf6", mine=False)
        a3 = repertoire.commit_move(conn, a2["to_fen"], "Nc3", mine=True)

        # Order B: 1.Nc3 Nf6 2.Nf3 -> same final position
        b1 = repertoire.commit_move(conn, START, "Nc3", mine=True)
        b2 = repertoire.commit_move(conn, b1["to_fen"], "Nf6", mine=False)
        b3 = repertoire.commit_move(conn, b2["to_fen"], "Nf3", mine=True)

        assert not any(r["transposition"] for r in (a1, a2, a3, b1, b2)), \
            "fresh edges should not report transposition"
        assert b3["transposition"], "Nf3 should land on the existing node"
        assert b3["to_fen"] == a3["to_fen"], "both orders must reach one FEN"

        leaf = a3["to_fen"]
        count = conn.execute(
            "SELECT COUNT(*) c FROM positions WHERE fen=?", (leaf,)
        ).fetchone()["c"]
        assert count == 1, "the shared position must be a single node"

        # The leaf has two distinct incoming edges (one per move order).
        incoming = conn.execute(
            "SELECT COUNT(*) c FROM edges WHERE to_fen=?", (leaf,)
        ).fetchone()["c"]
        assert incoming == 2, f"expected 2 incoming edges, got {incoming}"
    print("ok  transposition collapses to one node")


def test_commit_is_idempotent():
    with db.session() as conn:
        first = repertoire.commit_move(conn, START, "e4", mine=True)
        again = repertoire.commit_move(conn, START, "e4", mine=True)
        assert first["edge_created"] and not again["edge_created"]
        rows = conn.execute(
            "SELECT COUNT(*) c FROM edges WHERE from_fen=? AND san='e4'",
            (fen.normalize(START),),
        ).fetchone()["c"]
        assert rows == 1, "re-committing must not duplicate the edge"
    print("ok  commit is idempotent")


def test_flags_set_correctly():
    with db.session() as conn:
        repertoire.commit_move(conn, START, "d4", mine=True)
        edge = conn.execute(
            "SELECT is_mine, is_covered FROM edges WHERE san='d4'"
        ).fetchone()
        assert edge["is_mine"] == 1 and edge["is_covered"] == 0
    print("ok  flags set correctly")


def test_engine_cache_roundtrip_normalized():
    lines = [
        {"san": "e4", "uci": "e2e4", "cp": 35, "mate": None},
        {"san": "d4", "uci": "d2d4", "cp": 33, "mate": None},
        {"san": "Qh5", "uci": "d1h5", "cp": None, "mate": 5},
    ]
    cache.put_engine(START, 24, lines)
    got = cache.get_engine(START, 24)
    assert got == lines, f"round-trip mismatch: {got}"
    # Stored as one row per line, ordered by pv_rank.
    with db.session() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM engine_cache").fetchone()["c"]
    assert n == 3, f"expected 3 rows, got {n}"
    print("ok  engine cache round-trips (normalized, per-line)")


def test_illegal_san_raises():
    with db.session() as conn:
        try:
            repertoire.commit_move(conn, START, "e5", mine=True)  # illegal for white
        except ValueError:
            print("ok  illegal SAN raises ValueError")
            return
    raise AssertionError("illegal SAN should have raised")


if __name__ == "__main__":
    test_transposition_collapses_to_one_node()
    test_commit_is_idempotent()
    test_flags_set_correctly()
    test_engine_cache_roundtrip_normalized()
    test_illegal_san_raises()
    print("\nAll phase-2 checks passed.")
