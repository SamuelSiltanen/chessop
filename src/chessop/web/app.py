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

from .. import config, db, repertoire, scorer

app = Flask(__name__, static_folder="static", static_url_path="")


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/position")
def position():
    fen = request.args.get("fen") or config.STARTPOS_FEN
    try:
        data = scorer.score_position(fen)
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
    for cand in data["candidates"]:
        state = committed.get(cand["san"])
        cand["mine"] = state["mine"] if state else False
        cand["covered"] = state["covered"] if state else False

    return jsonify(data)


def main() -> None:
    app.run(host="127.0.0.1", port=5000, debug=True)


if __name__ == "__main__":
    main()
