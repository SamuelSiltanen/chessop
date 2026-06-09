# chessop

Interactively build a chess opening repertoire by fusing four sources at every
position: **Stockfish 18**, the **Lichess opening explorer**, **verbal
explanations**, and **your own preference**. See [DESIGN.md](DESIGN.md) for the
full design.

## Status

Phase 2 — the SQLite repertoire graph: positions/edges keyed by normalized FEN
(transpositions collapse to one node), move-commit operations, and the
normalized per-line engine cache. Phase 1 (the engine + Lichess explorer fusion
table) remains runnable via the spike below.

## Requirements

- Python 3.10+
- [`python-chess`](https://python-chess.readthedocs.io/) (`pip install chess`)
- Stockfish 18 — path set in `src/chessop/config.py`
  (`STOCKFISH_PATH`, currently `C:\stockfish_18\...`).
- A **Lichess API token** — since the Feb-2026 DDoS mitigation, the opening
  explorer requires authentication. Create one at
  <https://lichess.org/account/oauth/token> (no scopes needed). Then either
  persist it in a `.env` file at the project root (gitignored, loaded
  automatically — recommended):
  ```
  LICHESS_TOKEN=<your token>
  ```
  or set it per-session: `$env:LICHESS_TOKEN = "<your token>"`. A shell variable
  overrides the `.env` value. See `.env.example`.

No other dependencies — the Lichess call uses the standard library.

## Web board (phase 3)

```pwsh
cd src
python -m chessop.web.app
```

Then open <http://127.0.0.1:5000>. Drag a piece or click a row in the table to
walk the tree; **Back** / **Reset** navigate. The right-hand panel is the live
fusion view — Stockfish eval + Δcp + soundness beside Lichess games/score/freq,
with rows tinted by signal (sound / surprise / dubious-pop / off-top5?) and dots
marking moves already in your repertoire. The board (chessground) and chess.js
load from a CDN, so the browser needs internet; the Lichess token is still
required for the data panel.

## Run (CLI spike)

```pwsh
cd src
python -m chessop.spike                       # start position
python -m chessop.spike --moves "e4 c5 Nf3"   # build a position from SAN
python -m chessop.spike --fen "<FEN>"
```

Columns: `eval` (side-to-move POV), `dcp` (centipawns behind the best move),
`sound` (within `DELTA_SOUND` of best), `games`/`score`/`freq` (Lichess at the
configured rating bands), and `flag` — `surprise` (sound but rarely played),
`dubious-pop` (popular but not sound → wants a refutation), `off-top5?` (a human
move outside the engine's MultiPV, so soundness is unknown).

Engine and Lichess results are cached in `cache/chessop_cache.sqlite`, so the
second run on a position is instant.

## Tests

```pwsh
python tests/test_repertoire.py
```

Exercises the graph operations offline (no engine/network): transposition
collapse, idempotent commits, edge flags, the normalized engine-cache
round-trip, and illegal-move rejection.
