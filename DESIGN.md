# chessop — Design Document

A tool for interactively building a chess opening repertoire by fusing four
information sources at every position:

1. **Stockfish 18** — objective evaluation and candidate moves.
2. **Lichess opening explorer** — how humans actually play, with results by rating.
3. **Verbal explanations** — prose that makes positions and moves memorable.
4. **Your own preference** — the move you commit to, and your notes.

Status: design agreed; no code yet. Tunable parameters are marked **[TUNABLE]**
and given starting defaults — expect to adjust them once we see real output.

---

## 1. Core model

A repertoire is a **graph of positions**, not a move list.

- A **node** is a position, keyed by its normalized FEN.
- An **edge** is a legal move from one position to another, carrying the
  fused data and (for committed moves) your choice and notes.

Keying by FEN — rather than storing a PGN move tree — means **transpositions
are handled natively**: the same position reached by different move orders is a
single node, so coverage and notes never drift out of sync. It also makes
**look-alike detection** (Section 5) cheap, because every position is already a
comparable object.

The graph is the source of truth. PGN is an **export format**, not the storage
format.

---

## 2. Storage (SQLite)

```
positions(
    fen            TEXT PRIMARY KEY,   -- normalized FEN (see note)
    side_to_move   TEXT,               -- 'w' | 'b'
    opening_eco    TEXT,               -- from Lichess, nullable
    opening_name   TEXT,               -- from Lichess, nullable
    plan_note      TEXT,               -- Layer-1 explanation (Section 5)
    analyzed_depth INTEGER             -- engine depth this node was analyzed at
)

edges(
    from_fen       TEXT,               -- parent position
    san            TEXT,               -- move in SAN
    to_fen         TEXT,               -- resulting position
    is_mine        INTEGER,            -- 1 = the move I committed to play
    is_covered     INTEGER,            -- 1 = an opponent reply I've addressed
    why_note       TEXT,               -- Layer-2 explanation (verified)
    PRIMARY KEY (from_fen, san)
)

engine_cache(
    fen   TEXT, depth INTEGER, multipv INTEGER,
    san   TEXT, cp INTEGER, mate INTEGER,
    PRIMARY KEY (fen, depth, multipv)
)

lichess_cache(
    fen TEXT, params TEXT,             -- params = rating bands + speeds used
    json TEXT, fetched_at TEXT,
    PRIMARY KEY (fen, params)
)

confusable_pairs(
    fen_a TEXT, fen_b TEXT,
    distance INTEGER,                  -- visual similarity score
    cue_a TEXT, cue_b TEXT,            -- discriminative cues (Section 5)
    PRIMARY KEY (fen_a, fen_b)
)
```

**Normalized FEN**: drop the halfmove-clock and fullmove-number fields (they
don't change the position's identity for repertoire purposes); keep
side-to-move, castling rights, and en-passant square. This is the key that makes
transpositions collapse correctly.

**Caching is mandatory, not an optimization.** The Lichess explorer is free but
rate-limited, so every response is cached. Stockfish results are cached by
`(fen, depth, multipv)` — which is only sound because analysis is reproducible
(Section 4).

---

## 3. The candidate scorer

The heart of the tool. Given a position, it produces a ranked, annotated list of
candidate moves. Every feature in the UI is a view or filter over this one row
shape:

```
CandidateMove {
    san
    cp / mate              # engine eval, from the side-to-move's perspective
    eval_delta             # cp(best) - cp(this), so 0 = the best move
    sound                  # eval_delta <= DELTA_SOUND
    sharp                  # set on the position: exactly one sound move
    lichess_games          # sample size at the selected rating/speed
    win / draw / loss       # for the side to move, as fractions
    frequency              # share of games in this position playing this move
}
```

**[TUNABLE]** `DELTA_SOUND = 40 cp` — a move is "sound"/equal-ish if within this
of the best move. Measured *relative to the best available move*, never relative
to 0.00 (otherwise a lost position looks fine because its moves are all equally
bad).

**[TUNABLE]** `DELTA_SHARP = 80 cp` — used for the sharpness/extension rule
(Section 4): the position is "sharp" (effectively one good move) when the
second-best move is at least this much worse than the best.

The scorer runs in **two asymmetric modes** depending on whose turn it is.

### 3a. Your move — pick one to commit

1. Keep only **sound** moves (`eval_delta <= DELTA_SOUND`).
2. Rank them by **human results for your side** at your rating band.
3. Surface the eval-vs-results 2×2 so you can spot the sweet spot: a move that is
   objectively equal *and* scores well for humans. You will play equal-ish lines
   that score well — but never objectively dubious ones, however well they score.
4. You click one move → the edge is marked `is_mine`.

### 3b. Opponent's move — decide what to cover

The opponent is not you, so the filter is different. You will **face** common bad
moves and want prepared answers, so coverage is:

> **sound OR popular**, gated by the cumulative-frequency floor (Section 4).

- **Sound replies** above the floor: standard theory you must meet.
- **Unsound-but-popular replies** above the floor: you specifically want the
  **refutation**, because people keep playing these against you and that's where
  you score points. The "why this move" note for your reply (Section 5, Layer 2)
  captures the punishment line.

Each opponent reply you address is marked `is_covered`.

---

## 4. Breadth and depth: the stopping rule

Opponent branching is what makes opening trees explode, so the tool enforces an
explicit stopping rule rather than expanding everything.

**Cumulative-frequency floor [TUNABLE] `COVERAGE = 0.90`.** At an opponent
position, sort replies by frequency and cover them until their cumulative share
reaches `COVERAGE`. This adapts automatically: sharp positions need few replies,
quiet positions need more. (The "sound OR popular" rule of 3b decides *which* of
those covered replies also need a refutation.)

**Sharpness extension.** Independently of the floor: if a position has exactly
one sound move (second-best is `>= DELTA_SHARP` worse), the line is **forced** —
there is no breadth to memorize, only a single narrow path, and that path is
exactly where a wrong move loses. So **keep extending** such lines regardless of
the frequency floor.

**Engine analysis budget — reproducibility.** Because evals are cached by
position, analysis must be deterministic. Stockfish at fixed *time* is not
reproducible; fixed **depth** is. So:

- Analyze at **[TUNABLE]** fixed `DEPTH = 24`, `multipv = 5`.
- `DEPTH` is part of the cache key, so re-analyzing deeper later never collides
  with old entries.

---

## 5. The explanation layer

Verbal explanations exist primarily to aid **memory** — above all to
disambiguate positions that look alike but need different moves. Three layers,
each with a different source of truth and reliability story.

### Layer 1 — Node "plan" note (understanding)
Thematic prose: what each side wants, pawn breaks, piece routes. Generated by
Claude from FEN + opening name + pawn structure + top moves. Low stakes
(background reading, not drilled). Stored in `positions.plan_note`.

### Layer 2 — Edge "why this move" note (justification)
**Derived from data you already computed, not free-form generated** — which is
what keeps it from hallucinating. The eval gaps and the refutation lines already
contain the reason a move is best (e.g. *"only move — everything else drops the
d-pawn to ...Qxd5"*). Claude's job is just to phrase the mechanical fact.

**Always verified against Stockfish before being shown.** Any tactical claim
("this stops Ng5", "otherwise loses a pawn") is checked by having the engine
evaluate the alternative — if the claim doesn't hold up in the eval, it is not
shown. This is the one layer where a wrong explanation would actively corrupt
your memory, so reliability beats speed here. Stored in `edges.why_note`.

### Layer 3 — Discriminative cue for confusable positions (recall)
The novel part, enabled by the FEN graph. The tool **proactively** scans the
repertoire for positions that are **visually similar but have divergent chosen
moves** — exactly the pairs that will confuse you at the board — and generates a
cue tying them apart.

Similarity metrics (all cheap on FENs):
- **Piece-placement distance** — number of squares that differ; small = look-alike.
- **Same pawn skeleton, different piece** — identical pawn structure, one minor
  piece elsewhere (the classic "which knight goes where").
- **Transpositions that branch to different plans.**

Found pairs go in `confusable_pairs` and become a **disambiguation worklist**
(Section 6). Each cue must **anchor to a concrete visible feature present in this
position but absent in its look-alike** — e.g. *"like the move-6 Italian, but
here Black's bishop is already on g4, so Nbd2 first to unpin, not c3."* A feature
you can *see* is the recall hook; an abstraction ("most accurate") is not.

### Authoring model for all layers
**Claude drafts; you write the final wording.** The generation effect — you
remember what you phrase yourself far better than what you read — means your edit
*is* the act of learning. The tool is a draft-and-confirm assistant, not an
oracle.

### Free-internet sources
Lowest priority. Generic opening prose is the low-value Layer-1 content, and the
high-value content (Layers 2–3) comes from your own data and graph. So treat
internet sources as optional enrichment attached by opening name / ECO (e.g. a
Wikipedia opening summary, or a link/quote you paste onto a node) — not a
pipeline to engineer.

---

## 6. Session workflow

The tool drives you via a **frontier worklist**: it knows the highest-value
position still needing a decision, drops you there with the fusion panel ready,
you decide, it recurses, the queue shrinks. Three selectable modes — the same
queue under different orderings (plus a no-queue mode):

- **Largest gap (impact-first):** rank uncovered positions by **reach
  probability** = the product of opponent-move frequencies along the path from
  root to the gap (your own moves count as ~certain). Surfaces the gap you are
  statistically most likely to actually reach, so practical coverage climbs
  fastest.
- **Ordered traversal (opening-complete):** depth-first under a chosen root, so
  one opening becomes fully trustworthy before moving to the next.
- **Free roaming:** no queue; click any position and build there.

Beside the coverage queue sits the **disambiguation worklist** (Section 5,
Layer 3) — a separate review mode entered to harden memory rather than extend
coverage.

---

## 7. Coverage / completeness report

Because the frontier is computable, so is completeness. Reported as **percentage
coverage** — the intuitive metric:

> "Your White repertoire covers **94%** of opponent replies to depth 12 at your
> rating; 3 gaps remain; 5 confusable clusters need cues."

Percentage = share of opponent reach-probability mass that is addressed, to a
given depth, for each colour.

---

## 8. Data sources — integration notes

- **Stockfish 18** — local engine at `C:\stockfish_18`, driven over UCI via
  `python-chess`. Fixed depth, `multipv = 5` (Section 4).
- **Lichess explorer** — free, unauthenticated public API
  (`explorer.lichess.ovh`). **[TUNABLE]** select rating bands and speeds to match
  the opponents you actually face; use the `lichess` database for rating-filtered
  human results and `masters` for cleaner theory. All responses cached.
- **Claude API** — drafts explanation Layers 1–3, grounded in FEN + opening name
  + top engine/human moves (+ the look-alike position for Layer 3). Use the
  latest capable model. Layer 2 output is Stockfish-verified before display.
- **Export** — annotated **PGN with comments**, which imports directly into a
  Lichess Study and from there into Chessable / Anki. Authoring now, drilling
  later, elsewhere.

---

## 9. Tech stack

- **Python** + **python-chess** (engine UCI, PGN, FEN, legal moves).
- **SQLite** for the graph and caches.
- **Web UI**: lightweight backend (Flask) serving a board (**chessground**,
  Lichess's own board widget) with the fusion panel beside it; JSON over HTTP.
- **httpx** (or similar) for the Lichess and Claude calls.

---

## 10. Phased build plan

1. **Engine + explorer spike** — script: given a FEN, print Stockfish lines and
   Lichess stats side by side, with caching. Proves the two integrations and the
   reproducible-analysis assumption. No UI.
2. **Storage layer** — the SQLite schema above; add/commit-move operations;
   transposition detection (FEN collision).
3. **Web board** — chessground board, click to navigate, fusion panel rendering
   the scorer's output live.
4. **Construction workflow** — "my move" commits, the coverage frontier and its
   three modes, notes editing, the coverage report.
5. **Explanations + export** — Layer 1–3 generation with Stockfish verification,
   proactive confusable-pair scan, annotated-PGN export.

This front-loads the riskiest integrations; you have something playable by
phase 3.

---

## Open tuning parameters (defaults to revisit with real data)

| Parameter      | Default | Meaning                                            |
|----------------|---------|----------------------------------------------------|
| `DELTA_SOUND`  | 40 cp   | within this of best ⇒ "sound"/equal-ish            |
| `DELTA_SHARP`  | 80 cp   | 2nd-best worse than this ⇒ position is "sharp"      |
| `COVERAGE`     | 0.90    | cumulative opponent frequency to cover per node    |
| `DEPTH`        | 24      | fixed Stockfish analysis depth (cache key)         |
| `multipv`      | 5       | candidate lines per position                       |
| Lichess bands  | TBD     | rating bands + speeds matching your real opponents |
