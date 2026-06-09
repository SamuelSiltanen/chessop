import { Chessground } from 'https://cdn.jsdelivr.net/npm/chessground@9/+esm';
import { Chess } from 'https://cdn.jsdelivr.net/npm/chess.js@1/+esm';

const game = new Chess();
let cg;

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
  document.getElementById('opening').textContent = data.opening || ' ';
  document.getElementById('sharp').classList.toggle('hidden', pending || !data.sharp);
  document.getElementById('turn').textContent = data.side_to_move + ' to move' + (pending ? ' · analyzing…' : '');

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
}

function renderPath() {
  const sans = game.history();
  const out = [];
  for (let i = 0; i < sans.length; i += 2) {
    const n = i / 2 + 1;
    out.push(`${n}.${sans[i]}${sans[i + 1] ? ' ' + sans[i + 1] : ''}`);
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
  // chess.js throws on an illegal SAN; ignore stray clicks.
  try { game.move(san); } catch { return; }
  refresh();
}

function onUserMove(orig, dest) {
  // Auto-queen on promotion; promotion UI is a later refinement.
  game.move({ from: orig, to: dest, promotion: 'q' });
  refresh();
}

// --- boot -------------------------------------------------------------------

cg = Chessground(document.getElementById('board'), {
  fen: game.fen(),
  movable: { free: false, color: turnColor(), dests: legalDests() },
  events: { move: onUserMove },
});

document.getElementById('back').addEventListener('click', () => {
  if (game.history().length) { game.undo(); refresh(); }
});
document.getElementById('reset').addEventListener('click', () => {
  game.reset(); refresh();
});

refresh();
