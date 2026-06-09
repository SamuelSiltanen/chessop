# chessop

Interactively build a chess opening repertoire by fusing four sources at every
position: **Stockfish 18**, the **Lichess opening explorer**, **verbal
explanations**, and **your own preference**. See [DESIGN.md](DESIGN.md) for the
full design.

## Status

Phase 1 — engine + Lichess explorer spike. Given a position, prints Stockfish's
candidate lines next to Lichess's human stats in one merged table.

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

## Run

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
