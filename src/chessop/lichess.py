"""Lichess opening-explorer integration.

Uses the free, unauthenticated public API (explorer.lichess.ovh). Responses are
cached by (fen, params); params encodes the rating bands + speeds so changing
them doesn't collide with old entries. Per-move stats are returned from the
side-to-move's perspective.
"""
import datetime
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional, TypedDict

import chess

from . import cache, config


class HumanMove(TypedDict):
    san: str
    uci: str
    games: int        # total games in this position playing this move
    score: float      # (wins + 0.5*draws)/games, for the side to move
    frequency: float  # share of games in this position playing this move


def _params_key() -> str:
    return (
        f"ratings={','.join(map(str, config.LICHESS_RATINGS))}"
        f";speeds={','.join(config.LICHESS_SPEEDS)}"
    )


def explorer(fen: str) -> dict:
    """Raw explorer response for a position (cached)."""
    params = _params_key()
    cached = cache.get_lichess(fen, params)
    if cached is not None:
        return cached

    query = urllib.parse.urlencode(
        {
            "fen": fen,
            "ratings": ",".join(map(str, config.LICHESS_RATINGS)),
            "speeds": ",".join(config.LICHESS_SPEEDS),
        }
    )
    url = f"{config.LICHESS_EXPLORER_URL}?{query}"
    headers = {"User-Agent": "chessop-spike/0.1"}
    if config.LICHESS_TOKEN:
        headers["Authorization"] = f"Bearer {config.LICHESS_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise SystemExit(
                "Lichess explorer returned 401 Unauthorized. Since the Feb-2026 "
                "DDoS mitigation it requires authentication.\n"
                "Create a token at https://lichess.org/account/oauth/token "
                "(no scopes needed) and set it:\n"
                '  PowerShell:  $env:LICHESS_TOKEN = "<your token>"'
            ) from exc
        raise

    cache.put_lichess(
        fen, params, data, datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    return data


def moves(fen: str) -> tuple[list[HumanMove], Optional[str]]:
    """Per-move human stats (side-to-move POV) and the opening name, if any."""
    data = explorer(fen)
    white_to_move = chess.Board(fen).turn == chess.WHITE

    raw = data.get("moves", [])
    total = sum(m["white"] + m["draws"] + m["black"] for m in raw) or 1

    out: list[HumanMove] = []
    for m in raw:
        games = m["white"] + m["draws"] + m["black"]
        wins = m["white"] if white_to_move else m["black"]
        score = (wins + 0.5 * m["draws"]) / games if games else 0.0
        out.append(
            {
                "san": m["san"],
                "uci": m["uci"],
                "games": games,
                "score": score,
                "frequency": games / total,
            }
        )

    opening = data.get("opening")
    name = opening["name"] if opening else None
    return out, name
