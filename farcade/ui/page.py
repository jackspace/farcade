"""The web UI: one self-contained page, no external assets, served by
the local API. Click a piece, click a square; legal targets highlight.
Connect four gets column buttons. Chat rides alongside.

Vanilla JS + 2 s polling — correspondence pace makes push unnecessary,
and this works in every browser on the LAN including the S24.
"""

PAGE_HTML = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Farcade</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin: 1rem; max-width: 760px; }
  h1 { font-size: 1.2rem; } h1 small { opacity:.6; font-weight: normal; }
  #games button { margin: .15rem; }
  .wrap { display: flex; flex-wrap: wrap; gap: 1rem; }
  table.board { border-collapse: collapse; touch-action: manipulation; }
  table.board td {
    width: 2.4rem; height: 2.4rem; text-align: center; font-size: 1.7rem;
    cursor: pointer; user-select: none; line-height: 1;
  }
  td.light { background: #eed9b6; } td.dark { background: #a97a4e; }
  td.sel { outline: 3px solid #2b7de9; outline-offset: -3px; }
  td.legal { box-shadow: inset 0 0 0 999px rgba(43,125,233,.35); }
  td.c4 { border: 1px solid #888; border-radius: 50%; width: 2.2rem; height: 2.2rem; }
  .meta { font-size: .9rem; opacity: .8; margin: .4rem 0; }
  #chatlog { border: 1px solid #8884; padding: .5rem; height: 12rem; overflow-y: auto;
             width: 16rem; font-size: .9rem; }
  #chatlog .us { color: #2b7de9; } #chatlog .them { color: #3aa14b; }
  .banner { padding:.4rem .6rem; border-radius:.4rem; background:#2b7de922; margin:.4rem 0; }
  input[type=text] { width: 11rem; }
</style>
</head>
<body>
<h1>Farcade <small>an arcade at a distance</small></h1>
<div id="games"></div>
<div id="banner" class="banner" style="display:none"></div>
<div class="wrap">
  <div id="board"></div>
  <div id="side" style="display:none">
    <div class="meta" id="meta"></div>
    <div id="chatlog"></div>
    <form id="chatform">
      <input type="text" id="chattext" placeholder="say something" maxlength="140">
      <button>send</button>
    </form>
    <p>
      <button id="resign">resign</button>
      <button id="drawoffer">offer draw</button>
      <button id="drawaccept" style="display:none">accept draw</button>
      <button id="nudgeb">nudge</button>
    </p>
  </div>
</div>
<script>
const PIECES = {P:"♙",N:"♘",B:"♗",R:"♖",Q:"♕",K:"♔",
                p:"♟",n:"♞",b:"♝",r:"♜",q:"♛",k:"♚"};
let gid = null, view = null, sel = null, lastEvent = 0;

async function j(url, opts) {
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { flash(data.error || r.status); throw new Error(data.error); }
  return data;
}
function flash(msg) {
  const b = document.getElementById("banner");
  b.textContent = msg; b.style.display = "block";
  setTimeout(() => b.style.display = "none", 4000);
}
async function loadGames() {
  const games = await j("/games");
  const div = document.getElementById("games");
  div.innerHTML = "";
  for (const g of games) {
    const btn = document.createElement("button");
    btn.textContent = `${g.game} ${g.gid.slice(0,6)} · ply ${g.ply}` +
                      (g.our_turn ? " · YOUR TURN" : "") +
                      (g.status !== "playing" ? ` · ${g.status}` : "");
    btn.onclick = () => { gid = g.gid; sel = null; refresh(); };
    div.appendChild(btn);
  }
  if (!gid && games.length) { gid = games[0].gid; refresh(); }
}
async function refresh() {
  if (!gid) return;
  view = await j(`/games/${gid}`);
  renderMeta(); renderChat();
  if (view.game === "chess") renderChess(); else if (view.game === "c4") renderC4();
  else document.getElementById("board").innerHTML = `<pre>${view.ascii||""}</pre>`;
  document.getElementById("side").style.display = "block";
}
function renderMeta() {
  let s = `you are ${view.seat} · ply ${view.ply} · ` +
          (view.our_turn ? "your move" : "waiting") + ` · trust: ${view.trust}`;
  if (view.outcome) s = `GAME OVER: ${view.outcome.winner} wins (${view.outcome.reason})`
      .replace("draw wins", "draw");
  document.getElementById("meta").textContent = s;
}
function renderChat() {
  const log = document.getElementById("chatlog");
  log.innerHTML = view.chat.map(c =>
    `<div class="${c.who}"><b>${c.who}</b>: ${esc(c.text)}</div>`).join("");
  log.scrollTop = log.scrollHeight;
}
const esc = t => t.replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

function renderChess() {
  const fen = view.model.fen.split(" ")[0];
  const rows = fen.split("/");
  const legal = view.model.legal || [];
  const board = document.getElementById("board");
  const tbl = document.createElement("table"); tbl.className = "board";
  const legalFrom = new Set(legal.map(m => m.slice(0,2)));
  const legalTo = sel
    ? new Set(legal.filter(m => m.startsWith(sel)).map(m => m.slice(2,4)))
    : new Set();
  for (let r = 0; r < 8; r++) {
    const tr = document.createElement("tr");
    let file = 0;
    for (const ch of rows[r]) {
      if (/\d/.test(ch)) {
        for (let i = 0; i < +ch; i++) { tr.appendChild(cell(r, file, "")); file++; }
      } else { tr.appendChild(cell(r, file, PIECES[ch] || "")); file++; }
    }
    tbl.appendChild(tr);
  }
  board.innerHTML = ""; board.appendChild(tbl);

  function cell(r, f, glyph) {
    const sq = "abcdefgh"[f] + (8 - r);
    const td = document.createElement("td");
    td.className = (r + f) % 2 ? "dark" : "light";
    td.textContent = glyph;
    if (sel === sq) td.classList.add("sel");
    if (legalTo.has(sq)) td.classList.add("legal");
    td.onclick = async () => {
      if (!view.our_turn) return;
      if (sel && legalTo.has(sq)) {
        let mv = sel + sq;
        const needsPromo = legal.includes(mv + "q");
        if (needsPromo) mv += (prompt("promote to (q/r/b/n)?", "q") || "q")[0];
        sel = null;
        await j(`/games/${gid}/move`, post({move: mv}));
        refresh();
      } else if (legalFrom.has(sq)) { sel = sq; renderChess(); }
      else { sel = null; renderChess(); }
    };
    return td;
  }
}
function renderC4() {
  const board = document.getElementById("board");
  const grid = view.model.grid, legal = new Set(view.model.legal || []);
  const tbl = document.createElement("table"); tbl.className = "board";
  const top = document.createElement("tr");
  for (let c = 0; c < 7; c++) {
    const td = document.createElement("td");
    if (legal.has(c) && view.our_turn) {
      const b = document.createElement("button");
      b.textContent = "▼";
      b.onclick = async () => { await j(`/games/${gid}/move`, post({move: c})); refresh(); };
      td.appendChild(b);
    }
    top.appendChild(td);
  }
  tbl.appendChild(top);
  for (let r = 5; r >= 0; r--) {
    const tr = document.createElement("tr");
    for (let c = 0; c < 7; c++) {
      const td = document.createElement("td"); td.className = "c4";
      const v = grid[c][r];
      td.textContent = v === "0" ? "\u{1F534}" : v === "1" ? "\u{1F7E1}" : "";
      tr.appendChild(td);
    }
    tbl.appendChild(tr);
  }
  board.innerHTML = ""; board.appendChild(tbl);
}
const post = body => ({method: "POST", headers: {"Content-Type": "application/json"},
                       body: JSON.stringify(body)});

document.getElementById("chatform").onsubmit = async e => {
  e.preventDefault();
  const t = document.getElementById("chattext");
  if (t.value.trim()) {
    await j(`/games/${gid}/chat`, post({text: t.value}));
    t.value = ""; refresh();
  }
};
document.getElementById("resign").onclick = () =>
  confirm("resign?") && j(`/games/${gid}/resign`, post({})).then(refresh);
document.getElementById("drawoffer").onclick = () =>
  j(`/games/${gid}/draw-offer`, post({})).then(() => flash("draw offered"));
document.getElementById("drawaccept").onclick = () =>
  j(`/games/${gid}/draw-accept`, post({})).then(refresh);
document.getElementById("nudgeb").onclick = () =>
  j(`/games/${gid}/nudge`, post({})).then(() => flash("nudged"));

setInterval(async () => {
  const evs = await j(`/events?since=${lastEvent}`).catch(() => []);
  if (evs.length) {
    lastEvent = evs[evs.length - 1].seq + 1;
    loadGames(); refresh();
    if (evs.some(e => e.kind === "draw_offered"))
      document.getElementById("drawaccept").style.display = "inline";
  }
}, 2000);
loadGames();
</script>
</body>
</html>
"""
