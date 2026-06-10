"""Checks for asymmetric, line-based construction: one move for you, a fan-out
of frequent replies for the opponent (`set_my_move` / `commit_line`).

Runs as a plain script (no framework, no network):

    python tests/test_commit_line.py

A fake Lichess-frequency provider keyed by normalized FEN keeps it offline and
deterministic.
"""
import pathlib
import sys
import tempfile

_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))

from chessop import config  # noqa: E402

_TMP = pathlib.Path(tempfile.mkdtemp()) / "test_commit_line.sqlite"
config.CACHE_DIR = _TMP.parent
config.CACHE_DB = _TMP

from chessop import db, fen as fenmod, repertoire  # noqa: E402

START = config.STARTPOS_FEN


def fen_after(sans):
    board = fenmod.to_board(START)
    for s in sans:
        board.push(board.parse_san(s))
    return fenmod.normalize(board.fen())


# Opponent replies (Black) at each opponent node on the test line. Frequencies
# clear the 0.90 floor cleanly (no exact-boundary float ambiguity) so the
# covered set is deterministic.
FAKE = {
    fen_after(["e4"]): {"c5": 0.60, "e5": 0.33, "e6": 0.05, "c6": 0.02},
    fen_after(["e4", "c5", "Nf3"]): {"d6": 0.55, "Nc6": 0.40, "g6": 0.05},
    fen_after(["e4", "c5", "Nf3", "d6", "d4"]): {"Nf6": 0.62, "g6": 0.30, "e6": 0.08},
}


def replies_fn(fen_str):
    return [{"san": s, "frequency": f}
            for s, f in FAKE.get(fenmod.normalize(fen_str), {}).items()]


def mine_sans(conn, fen_str):
    return {e["san"] for e in repertoire.children(conn, fen_str) if e["is_mine"]}


def covered_sans(conn, fen_str):
    return {e["san"] for e in repertoire.children(conn, fen_str) if e["is_covered"]}


def test_single_choice():
    with db.session() as conn:
        # An isolated node (after 1.d4 d5) so this doesn't touch the e4 line.
        node = fen_after(["d4", "d5"])
        repertoire.set_my_move(conn, node, "c4")
        repertoire.set_my_move(conn, node, "Nf3")   # replaces c4
        assert mine_sans(conn, node) == {"Nf3"}, mine_sans(conn, node)
        # c4 carried no other flag, so its edge is gone entirely.
        all_sans = {e["san"] for e in repertoire.children(conn, node)}
        assert all_sans == {"Nf3"}, all_sans
    print("ok  set_my_move keeps exactly one of your moves per node")


def test_commit_line_asymmetry():
    sans = ["e4", "c5", "Nf3", "d6", "d4"]
    with db.session() as conn:
        res = repertoire.commit_line(conn, START, sans, "white", replies_fn=replies_fn)

        assert res["my_moves"] == 3, res          # e4, Nf3, d4
        assert res["opp_nodes"] == 3, res         # after e4, after Nf3, terminal
        assert res["covered_edges"] == 6, res     # 2 + 2 + 2
        assert res["end_fen"] == fen_after(sans), res

        # Your single move at each of your nodes.
        assert mine_sans(conn, START) == {"e4"}
        assert mine_sans(conn, fen_after(["e4", "c5"])) == {"Nf3"}
        assert mine_sans(conn, fen_after(["e4", "c5", "Nf3", "d6"])) == {"d4"}

        # Opponent fan-out: most-played replies up to COVERAGE (0.90), plus the
        # spine move. e6/c6 (below the cut) are not covered.
        assert covered_sans(conn, fen_after(["e4"])) == {"c5", "e5"}
        assert covered_sans(conn, fen_after(["e4", "c5", "Nf3"])) == {"d6", "Nc6"}
        # Terminal node (Black to move after ...d4) is fanned out too.
        assert covered_sans(conn, fen_after(sans)) == {"Nf6", "g6"}
    print("ok  commit_line: one move for you, frequent replies fanned for opponent")


def test_spine_reply_always_kept():
    # A spine reply rarer than the coverage cut must still be committed, or the
    # line would detach. Cover a node where the walked reply is the rare one.
    node = fen_after(["e4"])
    with db.session() as conn:
        res = repertoire.commit_line(
            conn, START, ["e4", "e6"], "white", replies_fn=replies_fn
        )
        # e6 (0.06) is below the cut but is the spine move -> kept; the line's
        # end position therefore exists and is connected.
        assert "e6" in covered_sans(conn, node), covered_sans(conn, node)
        assert repertoire.get_position(conn, res["end_fen"]) is not None
    print("ok  commit_line always keeps the walked reply (stays connected)")


def test_subroot_connectivity():
    # Committing a line that starts at an already-committed node attaches to it
    # rather than orphaning: the start node must pre-exist as a position.
    subroot = fen_after(["e4", "c5"])   # in the graph from the asymmetry test
    with db.session() as conn:
        assert repertoire.get_position(conn, subroot) is not None
        before = repertoire.get_position(conn, fen_after(["e4", "c5", "Nf3", "Nc6"]))
        # (that node exists because Nc6 was a covered reply); give it our move.
        repertoire.commit_line(
            conn, subroot, ["Nf3", "Nc6", "d4"], "white", replies_fn=replies_fn
        )
        assert mine_sans(conn, fen_after(["e4", "c5", "Nf3", "Nc6"])) == {"d4"}
    print("ok  commit_line from a sub-root stays edge-connected")


if __name__ == "__main__":
    test_single_choice()
    test_commit_line_asymmetry()
    test_spine_reply_always_kept()
    test_subroot_connectivity()
    print("\nAll commit-line checks passed.")
