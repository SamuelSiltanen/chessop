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
      `<td class="flag">${pending ? '' : badge(c.flag)}</td>` +
      `<td class="act"><button class="add">${c.mine || c.covered ? '−' : '+'}</button></td>`;
    tr.addEventListener('click', () => playSan(c.san));
    tr.querySelector('.add').addEventListener('click', (e) => {
      e.stopPropagation();
      toggleCommit(c.san, c.mine || c.covered);
    });
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

// --- repertoire construction ------------------------------------------------

const repColor = () => document.getElementById('color').value;
const repMode = () => document.getElementById('mode').value;

async function toggleCommit(san, committed) {
  const url = committed ? '/api/uncommit' : '/api/commit';
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fen: game.fen(), san, color: repColor() }),
  });
  if (!res.ok) { console.error(await res.text()); return; }
  await refresh();
  updateCoverage();
}

function renderCoverage(cov) {
  document.getElementById('coverage').textContent =
    `${repColor()}: ${(cov.opponent_coverage * 100).toFixed(0)}% replies covered · ` +
    `${cov.move_gaps} move · ${cov.cover_gaps} cover gaps`;
}

async function updateCoverage() {
  const data = await (await fetch(`/api/frontier?color=${repColor()}&mode=free`)).json();
  renderCoverage(data.coverage);
}

function gotoFen(f) {
  const parts = f.split(' ');
  game.load(parts.length === 4 ? f + ' 0 1' : f);
  refresh();
}

async function nextGap() {
  const url = `/api/frontier?color=${repColor()}&mode=${repMode()}` +
    `&exclude=${encodeURIComponent(game.fen())}`;
  const data = await (await fetch(url)).json();
  renderCoverage(data.coverage);
  if (data.gap) gotoFen(data.gap.fen);
  else document.getElementById('coverage').textContent += '  — no gaps for this mode';
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
document.getElementById('next').addEventListener('click', nextGap);
document.getElementById('color').addEventListener('change', updateCoverage);
document.getElementById('plan').addEventListener('blur', (e) => {
  fetch('/api/note', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fen: game.fen(), text: e.target.value }),
  });
});

refresh();
updateCoverage();
