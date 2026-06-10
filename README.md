# chessop

Interactively build a chess opening repertoire by fusing four sources at every
position: **Stockfish 18**, the **Lichess opening explorer**, **verbal
explanations**, and **your own preference**. See [DESIGN.md](DESIGN.md) for the
full design.

## Status

Phase 4 — the interactive construction workflow: commit moves into the
repertoire from the board, a frontier worklist (largest-gap / ordered / free
modes), a coverage report, and per-position plan notes. Built on the phase-2
FEN-keyed graph and the phase-3 fusion board.

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
with rows tinted by soundness and flags shown as badges (surprise / dubious-pop
/ rare). Dots mark moves already in your repertoire.

You can keep several **named repertoires** side by side (e.g. a White e4 system
and a Black Sicilian). The **Repertoire** dropdown switches between them;
**+ New** creates one (its colour is fixed at creation and orients the board),
**Rename**/**Delete** manage it. Positions and the engine/Lichess caches are
shared across repertoires; only your committed moves and notes are per-repertoire.
Removing work: the **✕** on a committed row deletes that move and prunes any
lines orphaned below it; **Delete** drops a whole repertoire.

**Building a repertoire** is asymmetric and line-based: you choose *one* move
for yourself but stay ready for *all* of the opponent's frequent replies. Pick
or create a repertoire, then just **play moves** to browse a line forward —
nothing is written yet, so you can see where the line leads before committing.
A hint under the bar tracks the line's *reach* (how often you'd actually face
it) and lights up when the **stopping rule** is met (reach below the floor, or
the line transposes into a position already in your repertoire); a sharp
position — only one sound move — tells you to keep extending instead.

Press **✓ Commit line** to write the whole line at once: your single move at
each of your turns, and a fan-out covering every frequent reply (up to the
cumulative-frequency floor) at each of the opponent's. Those new reply positions
become gaps; **Next gap** jumps to the next one needing your move, ranked by the
selected mode (largest gap by reach probability / ordered depth-first / free
roam). The readout shows the reach-weighted **% of replies answered** — replies
you actually have a response ready for, not just acknowledged — plus the count
of open move and cover gaps. It's low for a shallow repertoire and climbs as you
fill in responses. The **Plan** box saves a note for the current position.

The board (chessground) and chess.js load from a CDN, so the browser needs
internet; the Lichess token is still required for the data panel.

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
python tests/test_frontier.py
```

Exercise the logic offline (no engine/network). `test_repertoire` covers
transposition collapse, idempotent commits, edge flags, the normalized
engine-cache round-trip, and illegal-move rejection. `test_frontier` covers gap
detection, reach-ranked modes, the coverage report, uncommit, and notes.
