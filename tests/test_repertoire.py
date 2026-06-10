"""Phase-2 checks for the repertoire graph, plus named-repertoire scoping.

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


def _new_rep(name="Test", color="white"):
    with db.session() as conn:
        return repertoire.create_repertoire(conn, name, color)


# A default repertoire for the graph-mechanics tests.
REP = _new_rep()


def test_transposition_collapses_to_one_node():
    with db.session() as conn:
        # Order A: 1.Nf3 Nf6 2.Nc3
        a1 = repertoire.commit_move(conn, REP, START, "Nf3", mine=True)
        a2 = repertoire.commit_move(conn, REP, a1["to_fen"], "Nf6", mine=False)
        a3 = repertoire.commit_move(conn, REP, a2["to_fen"], "Nc3", mine=True)

        # Order B: 1.Nc3 Nf6 2.Nf3 -> same final position
        b1 = repertoire.commit_move(conn, REP, START, "Nc3", mine=True)
        b2 = repertoire.commit_move(conn, REP, b1["to_fen"], "Nf6", mine=False)
        b3 = repertoire.commit_move(conn, REP, b2["to_fen"], "Nf3", mine=True)

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
            "SELECT COUNT(*) c FROM edges WHERE repertoire_id=? AND to_fen=?",
            (REP, leaf),
        ).fetchone()["c"]
        assert incoming == 2, f"expected 2 incoming edges, got {incoming}"
    print("ok  transposition collapses to one node")


def test_commit_is_idempotent():
    with db.session() as conn:
        first = repertoire.commit_move(conn, REP, START, "e4", mine=True)
        again = repertoire.commit_move(conn, REP, START, "e4", mine=True)
        assert first["edge_created"] and not again["edge_created"]
        rows = conn.execute(
            "SELECT COUNT(*) c FROM edges"
            " WHERE repertoire_id=? AND from_fen=? AND san='e4'",
            (REP, fen.normalize(START)),
        ).fetchone()["c"]
        assert rows == 1, "re-committing must not duplicate the edge"
    print("ok  commit is idempotent")


def test_flags_set_correctly():
    with db.session() as conn:
        repertoire.commit_move(conn, REP, START, "d4", mine=True)
        edge = conn.execute(
            "SELECT is_mine, is_covered FROM edges"
            " WHERE repertoire_id=? AND san='d4'",
            (REP,),
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
            repertoire.commit_move(conn, REP, START, "e5", mine=True)  # illegal
        except ValueError:
            print("ok  illegal SAN raises ValueError")
            return
    raise AssertionError("illegal SAN should have raised")


def test_repertoire_isolation():
    a = _new_rep("Iso A", "white")
    b = _new_rep("Iso B", "white")
    with db.session() as conn:
        repertoire.commit_move(conn, a, START, "e4", mine=True)
        repertoire.set_plan_note(conn, a, START, "A's plan")
        assert {e["san"] for e in repertoire.children(conn, a, START)} == {"e4"}
        # B shares positions but sees none of A's edges or notes.
        assert repertoire.children(conn, b, START) == []
        assert repertoire.get_plan_note(conn, b, START) == ""
        assert repertoire.get_plan_note(conn, a, START) == "A's plan"
    print("ok  edges and notes are isolated per repertoire")


def test_delete_cascades():
    r = _new_rep("Doomed", "white")
    with db.session() as conn:
        repertoire.commit_move(conn, r, START, "e4", mine=True)
        repertoire.set_plan_note(conn, r, START, "note")
        repertoire.delete_repertoire(conn, r)
        assert repertoire.get_repertoire(conn, r) is None
        n_edges = conn.execute(
            "SELECT COUNT(*) c FROM edges WHERE repertoire_id=?", (r,)
        ).fetchone()["c"]
        n_notes = conn.execute(
            "SELECT COUNT(*) c FROM repertoire_notes WHERE repertoire_id=?", (r,)
        ).fetchone()["c"]
        assert n_edges == 0 and n_notes == 0, "delete must cascade edges + notes"
    print("ok  deleting a repertoire cascades its edges and notes")


def test_remove_move_prunes_orphans():
    r = _new_rep("Prune", "white")
    with db.session() as conn:
        e4 = repertoire.commit_move(conn, r, START, "e4", mine=True)["to_fen"]
        c5 = repertoire.commit_move(conn, r, e4, "c5", mine=False)["to_fen"]
        repertoire.commit_move(conn, r, c5, "Nf3", mine=True)
        total = conn.execute(
            "SELECT COUNT(*) c FROM edges WHERE repertoire_id=?", (r,)
        ).fetchone()["c"]
        assert total == 3, total

        # Removing 1.e4 orphans the entire subtree below it.
        removed = repertoire.remove_move(conn, r, START, "e4")
        assert removed == 3, removed
        left = conn.execute(
            "SELECT COUNT(*) c FROM edges WHERE repertoire_id=?", (r,)
        ).fetchone()["c"]
        assert left == 0, left
    print("ok  remove_move deletes the edge and prunes orphaned lines")


if __name__ == "__main__":
    test_transposition_collapses_to_one_node()
    test_commit_is_idempotent()
    test_flags_set_correctly()
    test_engine_cache_roundtrip_normalized()
    test_illegal_san_raises()
    test_repertoire_isolation()
    test_delete_cascades()
    test_remove_move_prunes_orphans()
    print("\nAll phase-2 checks passed.")
