import { Chessground } from 'https://cdn.jsdelivr.net/npm/chessground@9/+esm';
import { Chess } from 'https://cdn.jsdelivr.net/npm/chess.js@1/+esm';

const game = new Chess();
let cg;

// Construction is asymmetric and line-based: you *browse* a line forward (it's
// tentative — nothing is written), then commit the whole line in one action.
// Committing sets your single move at each of your nodes and fans out every
// frequent reply at each opponent node. So we track, per ply from the line's
// root, the reach probability (product of opponent move frequencies) and whether
// the line is still tentative — both drive the "commit line" hint.
let lineRoot = game.fen();      // where the current browsed line starts
let reachByPly = [1.0];         // reach[k] = reach after k plies
let tentativeByPly = [false];   // tentative[k] = any uncommitted edge so far
let lastCandidates = [];        // candidates of the position currently shown
// Move-number context for the path readout. Jumping to a gap deep in the tree
// starts numbering from the gap's real depth, not from move 1.
let lineStartNumber = 1;        // fullmove number at the line root
let lineStartWhite = true;      // is the line root a white-to-move position?

const repColor = () => document.getElementById('color').value;
const repMode = () => document.getElementById('mode').value;
const myColorChar = () => (repColor() === 'white' ? 'w' : 'b');

// --- chess.js -> chessground helpers ---------------------------------------

function turnColor() {
  return game.turn() === 'w' ? 'white' : 'black';
}

function legalDests() {
  const dests = new Map();
  for (const m of game.moves({ verbose: true })) {
    if (!dests.has(m.from)) dests.set(m.from, []);
    dests.get(m.from).push(m.to);
  }
  return dests;
}

function lastMove() {
  const h = game.history({ verbose: true });
  if (!h.length) return undefined;
  const last = h[h.length - 1];
  return [last.from, last.to];
}

// --- line tracking ----------------------------------------------------------

function trackPush(san, mover) {
  const c = lastCandidates.find((x) => x.san === san);
  const f = c ? c.freq || 0 : 0;
  const prevReach = reachByPly[reachByPly.length - 1];
  // Your own moves are ~certain; only opponent moves shrink reach.
  reachByPly.push(mover !== myColorChar() ? prevReach * f : prevReach);
  const prevTent = tentativeByPly[tentativeByPly.length - 1];
  const committed = c ? c.mine || c.covered : false;
  tentativeByPly.push(prevTent || !committed);
}

function resetTracking(reach = 1.0) {
  lineRoot = game.fen();
  reachByPly = [reach];
  tentativeByPly = [false];
}

// Apply a move (SAN string or {from,to,promotion}) and update tracking.
function applyMove(mv) {
  const mover = game.turn();      // side to move *before* the move
  let res;
  try { res = game.move(mv); } catch { return false; }
  if (!res) return false;
  trackPush(res.san, mover);
  return true;
}

// --- rendering --------------------------------------------------------------

function pct(x) {
  return x === null || x === undefined ? '' : (x * 100).toFixed(1) + '%';
}

// Row tint reflects soundness only; the flag is shown as a separate badge so
// "surprise" (a sound move) no longer collides with the plain "sound" tint.
function rowClass(c, pending) {
  if (pending) return '';
  if (c.flag === 'dubious-pop') return 'dubious';
  if (c.flag === 'rare') return 'rare';
  if (c.sound) return 'sound';
  return '';
}

function badge(flag) {
  if (!flag) return '';
  const cls = { 'surprise': 'b-surprise', 'dubious-pop': 'b-dubious', 'rare': 'b-rare' }[flag] || '';
  return `<span class="badge ${cls}">${flag}</span>`;
}

function dots(c) {
  let s = '';
  if (c.mine) s += '<span class="dot mine" title="your move">&#9679;</span>';
  if (c.covered) s += '<span class="dot covered" title="covered reply">&#9679;</span>';
  return s;
}

function renderPanel(data, pending) {
  document.getElementById('opening').textContent = data.opening || ' ';
  document.getElementById('sharp').classList.toggle('hidden', pending || !data.sharp);
  document.getElementById('turn').textContent = data.side_to_move + ' to move' + (pending ? ' · analyzing…' : '');

  const plan = document.getElementById('plan');
  if (document.activeElement !== plan) plan.value = data.plan_note || '';

  const tbody = document.querySelector('#candidates tbody');
  tbody.innerHTML = '';
  for (const c of data.candidates) {
    const tr = document.createElement('tr');
    tr.className = rowClass(c, pending);
    tr.innerHTML =
      `<td class="move">${c.san}${dots(c)}</td>` +
      `<td>${pending ? '…' : c.eval}</td>` +
      `<td>${pending || c.delta === null ? '' : c.delta}</td>` +
      `<td>${c.games ? c.games.toLocaleString() : ''}</td>` +
      `<td>${pct(c.score)}</td>` +
      `<td>${c.games ? pct(c.freq) : ''}</td>` +
      `<td class="flag">${pending ? '' : badge(c.flag)}</td>`;
    tr.addEventListener('click', () => playSan(c.san));
    tbody.appendChild(tr);
  }

  lastCandidates = data.candidates;
  if (!pending) updateLineHint(data);
}

function updateLineHint(data) {
  const el = document.getElementById('line-hint');
  if (!game.history().length) { el.textContent = ''; el.classList.remove('met'); return; }
  const reach = reachByPly[reachByPly.length - 1];
  const tent = tentativeByPly[tentativeByPly.length - 1];
  const floor = data.reach_floor ?? 0.01;
  const r = (reach * 100).toFixed(1) + '%';

  let text, met = false;
  if (data.in_repertoire && tent) {
    text = '↩ transposes into your repertoire — commit line';
    met = true;
  } else if (data.sharp && reach < floor) {
    text = `sharp: one sound move — keep extending (reach ${r})`;
  } else if (reach < floor) {
    text = `stopping rule met (reach ${r}) — commit line`;
    met = true;
  } else {
    text = `reach ${r}`;
  }
  el.textContent = text;
  el.classList.toggle('met', met);
}

function flashHint(text) {
  const el = document.getElementById('line-hint');
  el.textContent = text;
  el.classList.remove('met');
}

function renderPath() {
  const sans = game.history();
  const out = [];
  let num = lineStartNumber;
  let i = 0;
  // A line that starts with Black to move opens with "N...<black>".
  if (!lineStartWhite && sans.length) {
    out.push(`${num}...${sans[0]}`);
    i = 1;
    num++;
  }
  for (; i < sans.length; i += 2) {
    out.push(`${num}.${sans[i]}${sans[i + 1] ? ' ' + sans[i + 1] : ''}`);
    num++;
  }
  document.getElementById('path').textContent = out.join('  ');
}

// --- state flow -------------------------------------------------------------

async function refresh() {
  cg.set({
    fen: game.fen(),
    turnColor: turnColor(),
    lastMove: lastMove(),
    movable: { color: turnColor(), dests: legalDests() },
  });
  renderPath();

  // Two-phase: paint the human data instantly, then fill in the engine eval.
  // A request token guards against fast navigation showing stale results.
  const fen = game.fen();
  const token = ++refresh.seq;

  async function load(engine, pending) {
    const q = '/api/position?fen=' + encodeURIComponent(fen) + (engine ? '' : '&engine=0');
    const data = await (await fetch(q)).json();
    if (token !== refresh.seq) return;           // a newer navigation won
    if (data.error) { console.error(data.error); return; }
    renderPanel(data, pending);
  }

  await load(false, true);   // fast: Lichess only
  await load(true, false);   // full: Stockfish merged in
}
refresh.seq = 0;

function playSan(san) {
  if (!applyMove(san)) return;   // ignore stray clicks on illegal SAN
  refresh();
}

function onUserMove(orig, dest) {
  // Auto-queen on promotion; promotion UI is a later refinement.
  applyMove({ from: orig, to: dest, promotion: 'q' });
  refresh();
}

// --- repertoire construction ------------------------------------------------

async function commitLine() {
  const sans = game.history();
  if (!sans.length) { flashHint('nothing to commit — play a line first'); return; }
  const res = await fetch('/api/commit_line', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root: lineRoot, sans, color: repColor() }),
  });
  if (!res.ok) { console.error(await res.text()); flashHint('commit failed — see console'); return; }
  const out = await res.json();
  renderCoverage(out.coverage);
  tentativeByPly = tentativeByPly.map(() => false);   // the whole line is committed now
  await refresh();                                    // repaint committed dots
  const s = out.summary;
  flashHint(`committed: ${s.my_moves} of your moves · ${s.covered_edges} replies covered`);
}

function renderCoverage(cov) {
  document.getElementById('coverage').textContent =
    `${repColor()}: ${(cov.prepared * 100).toFixed(0)}% of replies answered · ` +
    `${cov.move_gaps} move · ${cov.cover_gaps} cover gaps`;
}

async function updateCoverage() {
  const data = await (await fetch(`/api/frontier?color=${repColor()}&mode=free`)).json();
  renderCoverage(data.coverage);
}

function gotoFen(f, reach, ply = 0) {
  // Number the path from the gap's real depth. Root is the start position
  // (White, ply 0), so after `ply` half-moves it's White to move iff ply is
  // even, at fullmove ply//2 + 1.
  lineStartNumber = Math.floor(ply / 2) + 1;
  lineStartWhite = ply % 2 === 0;
  const parts = f.split(' ');
  game.load(parts.length === 4 ? `${f} 0 ${lineStartNumber}` : f);
  // The gap is an existing, committed node: a fresh line root at its own reach.
  resetTracking(reach ?? 1.0);
  refresh();
}

async function nextGap() {
  const url = `/api/frontier?color=${repColor()}&mode=${repMode()}` +
    `&exclude=${encodeURIComponent(game.fen())}`;
  const data = await (await fetch(url)).json();
  renderCoverage(data.coverage);
  if (data.gap) gotoFen(data.gap.fen, data.gap.reach, data.gap.ply ?? 0);
  else document.getElementById('coverage').textContent += '  — no gaps for this mode';
}

// --- boot -------------------------------------------------------------------

cg = Chessground(document.getElementById('board'), {
  fen: game.fen(),
  movable: { free: false, color: turnColor(), dests: legalDests() },
  events: { move: onUserMove },
});

document.getElementById('back').addEventListener('click', () => {
  if (game.history().length) {
    game.undo();
    if (reachByPly.length > 1) { reachByPly.pop(); tentativeByPly.pop(); }
    refresh();
  }
});
document.getElementById('reset').addEventListener('click', () => {
  game.reset(); resetTracking();
  lineStartNumber = 1; lineStartWhite = true;
  refresh();
});
document.getElementById('commit-line').addEventListener('click', commitLine);
document.getElementById('next').addEventListener('click', nextGap);
document.getElementById('color').addEventListener('change', () => { updateCoverage(); refresh(); });
document.getElementById('plan').addEventListener('blur', (e) => {
  fetch('/api/note', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fen: game.fen(), text: e.target.value }),
  });
});

refresh();
updateCoverage();
