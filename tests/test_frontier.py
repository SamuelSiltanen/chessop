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


def test_frontier_and_coverage():
    with db.session() as conn:
        # Empty White repertoire -> the only gap is "play your first move".
        g = frontier.next_gap(conn, START, "white", "impact", freq_fn=freq_fn)
        assert g["fen"] == fenmod.normalize(START) and g["role"] == "mine", g

        # Commit 1.e4; Black replies are now an opponent node needing coverage.
        after_e4 = repertoire.commit_move(conn, START, "e4", mine=True)["to_fen"]
        FAKE[after_e4] = {"c5": 0.60, "e5": 0.35, "e6": 0.05}

        g = frontier.next_gap(conn, START, "white", "impact", freq_fn=freq_fn)
        assert g["fen"] == after_e4 and g["role"] == "opp", g

        # Cover the two main replies (0.60 + 0.35 = 0.95 >= COVERAGE).
        after_c5 = repertoire.commit_move(conn, after_e4, "c5", mine=False)["to_fen"]
        after_e5 = repertoire.commit_move(conn, after_e4, "e5", mine=False)["to_fen"]

        cov = frontier.coverage(conn, START, "white", freq_fn=freq_fn)
        assert cov["cover_gaps"] == 0, cov
        assert cov["move_gaps"] == 2, cov           # both replies need my move
        assert abs(cov["opponent_coverage"] - 0.95) < 1e-9, cov
        print("ok  coverage report: 95% opp coverage, 2 move gaps, 0 cover gaps")

        # Impact mode picks the higher-reach line (c5: 0.60 > e5: 0.35).
        g = frontier.next_gap(conn, START, "white", "impact", freq_fn=freq_fn)
        assert g["fen"] == after_c5 and g["role"] == "mine", g
        # Excluding it advances to the next-most-likely (e5).
        g2 = frontier.next_gap(
            conn, START, "white", "impact", exclude_fen=after_c5, freq_fn=freq_fn
        )
        assert g2["fen"] == after_e5, g2
        print("ok  impact mode ranks gaps by reach probability")

        # Free mode has no worklist.
        assert frontier.next_gap(conn, START, "white", "free", freq_fn=freq_fn) is None
        print("ok  free mode returns no gap")

        # Uncommitting a reply reopens the coverage gap.
        repertoire.uncommit_move(conn, after_e4, "e5", mine=False)
        cov2 = frontier.coverage(conn, START, "white", freq_fn=freq_fn)
        assert cov2["cover_gaps"] == 1, cov2        # 0.60 < COVERAGE again
        print("ok  uncommit reopens the coverage gap")


def test_notes_persist():
    with db.session() as conn:
        repertoire.set_plan_note(conn, START, "Control the centre, develop, castle.")
        repertoire.commit_move(conn, START, "d4", mine=True)
        repertoire.set_why_note(conn, START, "d4", "Stake the centre; my main try.")
        node = repertoire.get_position(conn, START)
        edge = conn.execute(
            "SELECT why_note FROM edges WHERE san='d4'"
        ).fetchone()
        assert node["plan_note"].startswith("Control")
        assert edge["why_note"].startswith("Stake")
    print("ok  plan and why notes persist")


if __name__ == "__main__":
    test_frontier_and_coverage()
    test_notes_persist()
    print("\nAll phase-4 checks passed.")
