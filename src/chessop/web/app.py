"""Flask app serving the board UI and the position/fusion API.

Routes:
    GET /                     -> the single-page board UI
    GET /api/position?fen=    -> scorer output for a position, annotated with
                                 repertoire state (which moves are committed)

The frontend (chessground + chess.js) owns board interaction and move legality;
the backend only answers "what do the sources say about this position, and what
have I already committed here?".
"""
from flask import Flask, jsonify, request

from .. import config, db, fen as fenmod, frontier, repertoire, scorer

ROOT = config.STARTPOS_FEN

app = Flask(__name__, static_folder="static", static_url_path="")


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/position")
def position():
    fen = request.args.get("fen") or config.STARTPOS_FEN
    with_engine = request.args.get("engine", "1") != "0"
    try:
        data = scorer.score_position(fen, with_engine=with_engine)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Annotate each candidate with repertoire state from the edges table.
    with db.session() as conn:
        node = repertoire.get_position(conn, fen)
        committed = {
            row["san"]: {"mine": bool(row["is_mine"]),
                         "covered": bool(row["is_covered"])}
            for row in repertoire.children(conn, fen)
        }
    data["in_repertoire"] = node is not None
    data["plan_note"] = node["plan_note"] if node and node["plan_note"] else ""
    for cand in data["candidates"]:
        state = committed.get(cand["san"])
        cand["mine"] = state["mine"] if state else False
        cand["covered"] = state["covered"] if state else False

    return jsonify(data)


def _is_mine(fen: str, color: str) -> bool:
    """Whether the side to move at `fen` is the repertoire's own colour."""
    return fenmod.side_to_move(fen) == ("w" if color == "white" else "b")


@app.post("/api/commit")
def commit():
    body = request.get_json(force=True)
    fen, san, color = body["fen"], body["san"], body.get("color", "white")
    try:
        with db.session() as conn:
            repertoire.commit_move(conn, fen, san, mine=_is_mine(fen, color))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


@app.post("/api/uncommit")
def uncommit():
    body = request.get_json(force=True)
    fen, san, color = body["fen"], body["san"], body.get("color", "white")
    with db.session() as conn:
        repertoire.uncommit_move(conn, fen, san, mine=_is_mine(fen, color))
    return jsonify({"ok": True})


@app.post("/api/note")
def note():
    body = request.get_json(force=True)
    fen, text = body["fen"], body.get("text", "")
    with db.session() as conn:
        if body.get("san"):
            repertoire.set_why_note(conn, fen, body["san"], text)
        else:
            repertoire.set_plan_note(conn, fen, text)
    return jsonify({"ok": True})


@app.get("/api/frontier")
def frontier_route():
    color = request.args.get("color", "white")
    mode = request.args.get("mode", "impact")
    exclude = request.args.get("exclude")
    with db.session() as conn:
        gap = frontier.next_gap(conn, ROOT, color, mode, exclude_fen=exclude)
        cov = frontier.coverage(conn, ROOT, color)
    return jsonify({"gap": gap, "coverage": cov})


def main() -> None:
    app.run(host="127.0.0.1", port=5000, debug=True)


if __name__ == "__main__":
    main()
