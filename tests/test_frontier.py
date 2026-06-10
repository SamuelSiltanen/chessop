"""Phase-4 checks for the construction frontier and coverage.

Runs as a plain script (no framework, no network):

    python tests/test_frontier.py

Uses a throwaway temp db and a fake Lichess-frequency provider so the graph
logic is exercised deterministically and offline.
"""
import pathlib
import sys
import tempfile

_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))

from chessop import config  # noqa: E402

_TMP = pathlib.Path(tempfile.mkdtemp()) / "test_frontier.sqlite"
config.CACHE_DIR = _TMP.parent
config.CACHE_DB = _TMP

from chessop import db, fen as fenmod, frontier, repertoire  # noqa: E402

START = config.STARTPOS_FEN

# Fake opponent frequencies keyed by normalized FEN, filled in as we learn FENs.
FAKE: dict = {}


def freq_fn(fen_str):
    return FAKE.get(fenmod.normalize(fen_str), {})


def _new_rep(name="Frontier", color="white"):
    with db.session() as conn:
        return repertoire.create_repertoire(conn, name, color)


def test_frontier_and_coverage():
    rep = _new_rep()
    with db.session() as conn:
        # Empty White repertoire -> the only gap is "play your first move".
        g = frontier.next_gap(conn, rep, START, "white", "impact", freq_fn=freq_fn)
        assert g["fen"] == fenmod.normalize(START) and g["role"] == "mine", g
        assert g["ply"] == 0, g                     # root is at depth 0

        # Commit 1.e4; Black replies are now an opponent node needing coverage.
        after_e4 = repertoire.commit_move(conn, rep, START, "e4", mine=True)["to_fen"]
        FAKE[after_e4] = {"c5": 0.60, "e5": 0.35, "e6": 0.05}

        g = frontier.next_gap(conn, rep, START, "white", "impact", freq_fn=freq_fn)
        assert g["fen"] == after_e4 and g["role"] == "opp", g
        assert g["ply"] == 1, g                     # one half-move deep

        # Cover the two main replies (0.60 + 0.35 = 0.95 >= COVERAGE).
        after_c5 = repertoire.commit_move(conn, rep, after_e4, "c5", mine=False)["to_fen"]
        after_e5 = repertoire.commit_move(conn, rep, after_e4, "e5", mine=False)["to_fen"]

        cov = frontier.coverage(conn, rep, START, "white", freq_fn=freq_fn)
        assert cov["cover_gaps"] == 0, cov
        assert cov["move_gaps"] == 2, cov           # both replies need my move
        assert abs(cov["opponent_coverage"] - 0.95) < 1e-9, cov
        # Breadth (95%) is not readiness: with no responses committed, the
        # honest "prepared" number is 0 — you'd be out of book immediately.
        assert cov["prepared"] == 0.0, cov
        print("ok  coverage report: 95% breadth but 0% prepared, 2 move gaps")

        # Impact mode picks the higher-reach line (c5: 0.60 > e5: 0.35).
        g = frontier.next_gap(conn, rep, START, "white", "impact", freq_fn=freq_fn)
        assert g["fen"] == after_c5 and g["role"] == "mine", g
        # Excluding it advances to the next-most-likely (e5).
        g2 = frontier.next_gap(
            conn, rep, START, "white", "impact", exclude_fen=after_c5, freq_fn=freq_fn
        )
        assert g2["fen"] == after_e5, g2
        print("ok  impact mode ranks gaps by reach probability")

        # Free mode has no worklist.
        assert frontier.next_gap(conn, rep, START, "white", "free", freq_fn=freq_fn) is None
        print("ok  free mode returns no gap")

        # Uncommitting a reply reopens the coverage gap.
        repertoire.uncommit_move(conn, rep, after_e4, "e5", mine=False)
        cov2 = frontier.coverage(conn, rep, START, "white", freq_fn=freq_fn)
        assert cov2["cover_gaps"] == 1, cov2        # 0.60 < COVERAGE again
        print("ok  uncommit reopens the coverage gap")

        # Now commit a response to 1...c5; that reply becomes "answered" while
        # the new opponent node (after 2.Nf3) is not, so prepared sits between.
        repertoire.commit_move(conn, rep, after_c5, "Nf3", mine=True)
        cov3 = frontier.coverage(conn, rep, START, "white", freq_fn=freq_fn)
        # (1.0*0.60 answered at after_e4 + 0.60*0 at after_Nf3) / (1.0 + 0.60)
        assert abs(cov3["prepared"] - 0.375) < 1e-9, cov3
        print("ok  answering a reply raises prepared above 0")


def test_branch_completeness():
    rep = _new_rep("Branch")
    with db.session() as conn:
        after_e4 = repertoire.commit_move(conn, rep, START, "e4", mine=True)["to_fen"]
        FAKE[after_e4] = {"c5": 0.60, "e5": 0.35, "e6": 0.05}
        after_c5 = repertoire.commit_move(conn, rep, after_e4, "c5", mine=False)["to_fen"]
        repertoire.commit_move(conn, rep, after_e4, "e5", mine=False)
        after_nf3 = repertoire.commit_move(conn, rep, after_c5, "Nf3", mine=True)["to_fen"]
        FAKE[after_nf3] = {"d6": 0.50, "Nc6": 0.40, "g6": 0.10}
        after_d6 = repertoire.commit_move(conn, rep, after_nf3, "d6", mine=False)["to_fen"]
        repertoire.commit_move(conn, rep, after_nf3, "Nc6", mine=False)
        repertoire.commit_move(conn, rep, after_d6, "d4", mine=True)   # answer ...d6

        bc = frontier.branch_completeness(conn, rep, after_e4, "white", freq_fn=freq_fn)
        # ...e5 is a bare covered stub (no move beyond) -> 0% built.
        assert bc["e5"] == 0.0, bc
        # ...c5 -> Nf3; below Nf3 only ...d6 is answered (0.5 of reply mass) plus
        # one deeper unbuilt node -> prepared = 0.5 / 1.5.
        assert abs(bc["c5"] - (0.5 / 1.5)) < 1e-9, bc
    print("ok  branch completeness distinguishes stubs from built subtrees")


def test_notes_persist():
    rep = _new_rep("Notes")
    with db.session() as conn:
        repertoire.set_plan_note(conn, rep, START, "Control the centre, develop, castle.")
        repertoire.commit_move(conn, rep, START, "d4", mine=True)
        repertoire.set_why_note(conn, rep, START, "d4", "Stake the centre; my main try.")
        assert repertoire.get_plan_note(conn, rep, START).startswith("Control")
        edge = conn.execute(
            "SELECT why_note FROM edges WHERE repertoire_id=? AND san='d4'", (rep,)
        ).fetchone()
        assert edge["why_note"].startswith("Stake")
    print("ok  plan and why notes persist")


if __name__ == "__main__":
    test_frontier_and_coverage()
    test_branch_completeness()
    test_notes_persist()
    print("\nAll phase-4 checks passed.")
