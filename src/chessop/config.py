"""Configuration and tunable parameters.

Defaults mirror the table in DESIGN.md. Anything marked TUNABLE there is meant
to be revisited once we see real output.
"""
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a project-root .env into the environment.

    Shell-set variables win (setdefault), so you can still override per-session.
    utf-8-sig tolerates the BOM that PowerShell's Out-File adds.
    """
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# --- Engine -----------------------------------------------------------------
STOCKFISH_PATH = r"C:\stockfish_18\stockfish-windows-x86-64-avx2.exe"
DEPTH = 24            # fixed depth -> reproducible analysis (part of cache key)
MULTIPV = 5           # candidate lines per position
ENGINE_THREADS = 1    # single thread -> deterministic search for a stable cache
ENGINE_HASH_MB = 256

# --- Scorer tunables (centipawns) ------------------------------------------
DELTA_SOUND = 40      # within this of best  -> "sound" / equal-ish
DELTA_SHARP = 80      # 2nd-best worse than this -> position is "sharp" (forced)
COVERAGE = 0.90       # cumulative opponent frequency to cover per node
# Stopping rule for a browsed line: once reach probability (product of opponent
# move frequencies along the line) drops below this, the line is deep enough and
# the "commit line" hint lights up — unless the current position is sharp (only
# one sound move), in which case we keep extending.
REACH_FLOOR = 0.01
# Popular human moves outside the engine's MultiPV get a targeted evaluation so
# they're classified (sound / dubious) instead of left unknown. Below this
# frequency a move stays unanalyzed ("rare").
OFFBOOK_EVAL_FREQ = 0.04

# --- Lichess opening explorer ----------------------------------------------
# Since the Feb-2026 DDoS mitigation, the explorer requires authentication.
# Create a personal token at https://lichess.org/account/oauth/token (no scopes
# needed) and expose it as the LICHESS_TOKEN environment variable.
LICHESS_TOKEN = os.environ.get("LICHESS_TOKEN", "")
LICHESS_EXPLORER_URL = "https://explorer.lichess.ovh/lichess"
# TBD: match the rating bands + speeds of opponents you actually face.
LICHESS_RATINGS = [1600, 1800, 2000, 2200]
LICHESS_SPEEDS = ["blitz", "rapid", "classical"]

# --- Paths ------------------------------------------------------------------
PROJECT_ROOT = _PROJECT_ROOT
CACHE_DIR = PROJECT_ROOT / "cache"
CACHE_DB = CACHE_DIR / "chessop_cache.sqlite"

STARTPOS_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
