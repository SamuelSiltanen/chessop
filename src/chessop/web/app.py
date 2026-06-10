"""Flask app serving the board UI and the position/fusion/repertoire API.

The frontend (chessground + chess.js) owns board interaction and move legality;
the backend answers "what do the sources say about this position?" and manages
the named repertoires (the committed moves you build).

Repertoire-scoped routes take a `rep` id; the repertoire's colour is read from
its record (not passed by the client). `/api/position` works without a `rep`
too, so the board is usable before any repertoire exists.
"""
from flask import Flask, Response, jsonify, request

from .. import config, db, frontier, pgn_export, repertoire, scorer

ROOT = config.STARTPOS_FEN

app = Flask(__name__, static_folder="static", static_url_path="")


@app.get("/")
def index():
    return app.send_static_file("index.html")


# --- repertoires ------------------------------------------------------------

def _rep_dict(row) -> dict:
    return {"id": row["id"], "name": row["name"], "color": row["color"]}


@app.get("/api/repertoires")
def repertoires_list():
    with db.session() as conn:
        return jsonify([_rep_dict(r) for r in repertoire.list_repertoires(conn)])


@app.post("/api/repertoires")
def repertoires_create():
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip() or "Untitled"
    color = body.get("color", "white")
    try:
        with db.session() as conn:
            rep_id = repertoire.create_repertoire(conn, name, color)
            row = repertoire.get_repertoire(conn, rep_id)
            return jsonify(_rep_dict(row)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/repertoires/<int:rep_id>", methods=["PATCH", "DELETE"])
def repertoires_modify(rep_id: int):
    with db.session() as conn:
        if repertoire.get_repertoire(conn, rep_id) is None:
            return jsonify({"error": "no such repertoire"}), 404
        if request.method == "DELETE":
            repertoire.delete_repertoire(conn, rep_id)
            return jsonify({"ok": True})
        name = (request.get_json(force=True).get("name") or "").strip()
        if not name:
            return jsonify({"error": "name required"}), 400
        repertoire.rename_repertoire(conn, rep_id, name)
        return jsonify(_rep_dict(repertoire.get_repertoire(conn, rep_id)))


@app.get("/api/repertoires/<int:rep_id>/pgn")
def export_pgn_route(rep_id: int):
    """Download the repertoire as one annotated PGN (notes become comments)."""
    with db.session() as conn:
        rep = repertoire.get_repertoire(conn, rep_id)
        if rep is None:
            return jsonify({"error": "no such repertoire"}), 404
        pgn = pgn_export.export_pgn(conn, rep_id)
    safe = "".join(c if (c.isalnum() or c in "-_ ") else "_" for c in rep["name"])
    safe = safe.strip() or "repertoire"
    return Response(
        pgn,
        mimetype="application/x-chess-pgn",
        headers={"Content-Disposition": f'attachment; filename="{safe}.pgn"'},
    )


def _require_rep(conn, rep_id):
    """Return the repertoire row or raise a 400-friendly ValueError."""
    if rep_id is None:
        raise ValueError("rep id required")
    row = repertoire.get_repertoire(conn, int(rep_id))
    if row is None:
        raise ValueError("no such repertoire")
    return row


# --- position fusion --------------------------------------------------------

@app.get("/api/position")
def position():
    fen = request.args.get("fen") or config.STARTPOS_FEN
    with_engine = request.args.get("engine", "1") != "0"
    rep_id = request.args.get("rep", type=int)
    try:
        data = scorer.score_position(fen, with_engine=with_engine)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Annotate each candidate with this repertoire's committed state.
    committed: dict = {}
    completeness: dict = {}
    plan_note = ""
    with db.session() as conn:
        rep = repertoire.get_repertoire(conn, rep_id) if rep_id is not None else None
        if rep:
            committed = {
                row["san"]: {"mine": bool(row["is_mine"]),
                             "covered": bool(row["is_covered"])}
                for row in repertoire.children(conn, rep["id"], fen)
            }
            plan_note = repertoire.get_plan_note(conn, rep["id"], fen)
            # Subtree completeness is the costly part (it walks each branch and
            # hits Lichess); compute it only on the full pass, not the fast paint.
            if with_engine:
                completeness = frontier.branch_completeness(
                    conn, rep["id"], fen, rep["color"]
                )
        node = repertoire.get_position(conn, fen)

    data["in_repertoire"] = bool(committed)
    data["plan_note"] = plan_note
    data["reach_floor"] = config.REACH_FLOOR
    data["analyzed"] = node is not None
    for cand in data["candidates"]:
        state = committed.get(cand["san"])
        cand["mine"] = state["mine"] if state else False
        cand["covered"] = state["covered"] if state else False
        cand["completeness"] = completeness.get(cand["san"])

    return jsonify(data)


# --- construction -----------------------------------------------------------

@app.post("/api/commit_line")
def commit_line_route():
    """Commit a whole browsed line: your single move at each of your nodes, all
    frequent replies fanned out at each opponent node. `root` is where the line
    started (the start position, or an in-repertoire gap you jumped to), so the
    new edges stay connected. Colour comes from the repertoire."""
    body = request.get_json(force=True)
    root = body.get("root") or ROOT
    sans = body.get("sans", [])
    try:
        with db.session() as conn:
            rep = _require_rep(conn, body.get("rep"))
            summary = repertoire.commit_line(
                conn, rep["id"], root, sans, rep["color"]
            )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with db.session() as conn:
        cov = frontier.coverage(conn, rep["id"], ROOT, rep["color"])
    return jsonify({"ok": True, "summary": summary, "coverage": cov})


@app.post("/api/remove")
def remove_route():
    """Remove a committed move and prune whatever it orphans."""
    body = request.get_json(force=True)
    fen, san = body.get("fen"), body.get("san")
    try:
        with db.session() as conn:
            rep = _require_rep(conn, body.get("rep"))
            removed = repertoire.remove_move(conn, rep["id"], fen, san)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "removed": removed})


@app.post("/api/note")
def note():
    body = request.get_json(force=True)
    fen, text = body["fen"], body.get("text", "")
    try:
        with db.session() as conn:
            rep = _require_rep(conn, body.get("rep"))
            if body.get("san"):
                repertoire.set_why_note(conn, rep["id"], fen, body["san"], text)
            else:
                repertoire.set_plan_note(conn, rep["id"], fen, text)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


@app.get("/api/frontier")
def frontier_route():
    mode = request.args.get("mode", "impact")
    exclude = request.args.get("exclude")
    try:
        with db.session() as conn:
            rep = _require_rep(conn, request.args.get("rep", type=int))
            gap = frontier.next_gap(
                conn, rep["id"], ROOT, rep["color"], mode, exclude_fen=exclude
            )
            cov = frontier.coverage(conn, rep["id"], ROOT, rep["color"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"gap": gap, "coverage": cov, "color": rep["color"]})


def main() -> None:
    app.run(host="127.0.0.1", port=5000, debug=True)


if __name__ == "__main__":
    main()
