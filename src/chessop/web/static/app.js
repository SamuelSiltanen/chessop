import { Chessground } from 'https://cdn.jsdelivr.net/npm/chessground@9/+esm';
import { Chess } from 'https://cdn.jsdelivr.net/npm/chess.js@1/+esm';

const game = new Chess();
let cg;

// --- named repertoires ------------------------------------------------------

let reps = [];           // [{id, name, color}]
let currentRepId = null;

const currentRep = () => reps.find((r) => r.id === currentRepId) || null;
const repId = () => currentRepId;
const repColor = () => (currentRep() ? currentRep().color : 'white');
const myColorChar = () => (repColor() === 'white' ? 'w' : 'b');
const repMode = () => document.getElementById('mode').value;

// Construction is asymmetric and line-based: you *browse* a line forward (it's
// tentative — nothing is written), then commit the whole line in one action.
// We track, per ply from the line's root, the reach probability (product of
// opponent move frequencies) and whether the line is still tentative — both
// drive the "commit line" hint.
let lineRoot = game.fen();
let reachByPly = [1.0];
let tentativeByPly = [false];
let lastCandidates = [];
// Move-number context for the path readout (a deep gap starts numbering from
// its real depth, not move 1).
let lineStartNumber = 1;
let lineStartWhite = true;

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

// A small bar showing how built-out the branch under a committed move is
// (0 = bare stub, full = built to where lines get rare).
function compBar(c) {
  if (c.completeness === null || c.completeness === undefined) return '';
  const p = Math.round(c.completeness * 100);
  return `<span class="cbar" title="branch ${p}% built"><span style="width:${p}%"></span></span>`;
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
    const committed = c.mine || c.covered;
    const tr = document.createElement('tr');
    tr.className = rowClass(c, pending);
    tr.innerHTML =
      `<td class="move">${c.san}${dots(c)}${compBar(c)}</td>` +
      `<td>${pending ? '…' : c.eval}</td>` +
      `<td>${pending || c.delta === null ? '' : c.delta}</td>` +
      `<td>${c.games ? c.games.toLocaleString() : ''}</td>` +
      `<td>${pct(c.score)}</td>` +
      `<td>${c.games ? pct(c.freq) : ''}</td>` +
      `<td class="flag">${pending ? '' : badge(c.flag)}</td>` +
      `<td class="act">${committed && repId() ? '<button class="rm" title="remove from repertoire">&#10005;</button>' : ''}</td>`;
    tr.addEventListener('click', () => playSan(c.san));
    const rm = tr.querySelector('.rm');
    if (rm) rm.addEventListener('click', (e) => { e.stopPropagation(); removeMove(c.san); });
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

  const fen = game.fen();
  const token = ++refresh.seq;
  const repQ = repId() ? '&rep=' + repId() : '';

  async function load(engine, pending) {
    const q = '/api/position?fen=' + encodeURIComponent(fen) + repQ + (engine ? '' : '&engine=0');
    const data = await (await fetch(q)).json();
    if (token !== refresh.seq) return;
    if (data.error) { console.error(data.error); return; }
    renderPanel(data, pending);
  }

  await load(false, true);
  await load(true, false);
}
refresh.seq = 0;

function playSan(san) {
  if (!applyMove(san)) return;
  refresh();
}

function onUserMove(orig, dest) {
  applyMove({ from: orig, to: dest, promotion: 'q' });
  refresh();
}

// --- repertoire management --------------------------------------------------

function renderRepSelect() {
  const sel = document.getElementById('rep');
  sel.innerHTML = '';
  for (const r of reps) {
    const o = document.createElement('option');
    o.value = r.id;
    o.textContent = `${r.name} — ${r.color}`;
    sel.appendChild(o);
  }
  if (currentRepId) sel.value = currentRepId;
  const have = reps.length > 0;
  for (const id of ['rep-rename', 'rep-delete', 'commit-line', 'next']) {
    document.getElementById(id).disabled = !have;
  }
}

async function loadReps(selectId) {
  reps = await (await fetch('/api/repertoires')).json();
  if (reps.length === 0) currentRepId = null;
  else if (selectId && reps.some((r) => r.id === selectId)) currentRepId = selectId;
  else if (!reps.some((r) => r.id === currentRepId)) currentRepId = reps[0].id;
  renderRepSelect();
}

function orientBoard() {
  cg.set({ orientation: repColor() });
}

async function switchRep(id) {
  currentRepId = id;
  game.reset();
  resetTracking();
  lineStartNumber = 1; lineStartWhite = true;
  orientBoard();
  await refresh();
  updateCoverage();
}

function createRep() {
  // A proper dialog so colour is an explicit choice (White or Black).
  const dlg = document.getElementById('new-rep');
  document.getElementById('nr-name').value = 'My repertoire';
  document.getElementById('nr-color').value = 'white';
  dlg.returnValue = '';
  dlg.showModal();
}

async function onNewRepClosed(dlg) {
  if (dlg.returnValue !== 'create') return;
  const name = document.getElementById('nr-name').value.trim() || 'Untitled';
  const color = document.getElementById('nr-color').value;
  const res = await fetch('/api/repertoires', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, color }),
  });
  if (!res.ok) { console.error(await res.text()); return; }
  const rep = await res.json();
  await loadReps(rep.id);
  switchRep(rep.id);
}

async function renameRep() {
  const r = currentRep();
  if (!r) return;
  const name = prompt('Rename repertoire:', r.name);
  if (!name) return;
  await fetch('/api/repertoires/' + r.id, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  await loadReps(r.id);
}

async function deleteRep() {
  const r = currentRep();
  if (!r) return;
  if (!confirm(`Delete repertoire "${r.name}"? This removes all its moves and notes.`)) return;
  await fetch('/api/repertoires/' + r.id, { method: 'DELETE' });
  await loadReps();
  switchRep(currentRepId);
}

// --- construction -----------------------------------------------------------

async function commitLine() {
  if (!repId()) { flashHint('create a repertoire first'); return; }
  const sans = game.history();
  if (!sans.length) { flashHint('nothing to commit — play a line first'); return; }
  const res = await fetch('/api/commit_line', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rep: repId(), root: lineRoot, sans }),
  });
  if (!res.ok) { console.error(await res.text()); flashHint('commit failed — see console'); return; }
  const out = await res.json();
  renderCoverage(out.coverage);
  tentativeByPly = tentativeByPly.map(() => false);
  await refresh();
  const s = out.summary;
  flashHint(`committed: ${s.my_moves} of your moves · ${s.covered_edges} replies covered`);
}

async function removeMove(san) {
  if (!repId()) return;
  if (!confirm(`Remove ${san} from "${currentRep().name}"? Any lines below it are pruned.`)) return;
  const res = await fetch('/api/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rep: repId(), fen: game.fen(), san }),
  });
  if (!res.ok) { console.error(await res.text()); return; }
  const out = await res.json();
  await refresh();
  updateCoverage();
  flashHint(`removed ${out.removed} edge${out.removed === 1 ? '' : 's'}`);
}

function renderCoverage(cov) {
  document.getElementById('coverage').textContent =
    `${repColor()}: ${(cov.prepared * 100).toFixed(0)}% of replies answered · ` +
    `${cov.move_gaps} move · ${cov.cover_gaps} cover gaps`;
}

async function updateCoverage() {
  if (!repId()) { document.getElementById('coverage').textContent = 'no repertoire — click + New'; return; }
  const data = await (await fetch(`/api/frontier?rep=${repId()}&mode=free`)).json();
  if (data.coverage) renderCoverage(data.coverage);
}

function gotoFen(f, reach, ply = 0) {
  lineStartNumber = Math.floor(ply / 2) + 1;
  lineStartWhite = ply % 2 === 0;
  const parts = f.split(' ');
  game.load(parts.length === 4 ? `${f} 0 ${lineStartNumber}` : f);
  resetTracking(reach ?? 1.0);
  refresh();
}

async function nextGap() {
  if (!repId()) { flashHint('create a repertoire first'); return; }
  const url = `/api/frontier?rep=${repId()}&mode=${repMode()}` +
    `&exclude=${encodeURIComponent(game.fen())}`;
  const data = await (await fetch(url)).json();
  if (data.coverage) renderCoverage(data.coverage);
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
document.getElementById('rep').addEventListener('change', (e) => switchRep(Number(e.target.value)));
document.getElementById('rep-new').addEventListener('click', createRep);
document.getElementById('new-rep').addEventListener('close', (e) => onNewRepClosed(e.target));
document.getElementById('rep-rename').addEventListener('click', renameRep);
document.getElementById('rep-delete').addEventListener('click', deleteRep);
document.getElementById('plan').addEventListener('blur', (e) => {
  if (!repId()) return;
  fetch('/api/note', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rep: repId(), fen: game.fen(), text: e.target.value }),
  });
});

(async function boot() {
  await loadReps();
  if (currentRepId) orientBoard();
  await refresh();
  updateCoverage();
})();
