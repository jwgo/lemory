"""`lemory graph` — the vault's knowledge graph as ONE self-contained HTML file.

The 2026 wave of graph tools (Graphify, Understand-Anything, OpenKB) builds
its graph with an LLM pipeline per file and ships an interactive graph.html
as the flagship artifact. Lemory's graph already exists — the user wrote it
as wikilinks, the indexer added unlinked mentions — so the same artifact
costs zero LLM calls and milliseconds: read the links table, embed the data
into a canvas-rendered force layout, done. Works offline, no CDN, no deps.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine import Engine

MAX_NODES = 4000  # beyond this a force layout is soup — keep top-degree nodes


def graph_data(engine: "Engine", max_nodes: int = MAX_NODES) -> dict:
    """Nodes + edges straight from the index. No LLM, no embedding reads."""
    store = engine.store
    docs = {d.id: d for d in store.all_docs()}
    degrees = store.link_degrees()

    keep = set(docs)
    truncated = False
    if len(docs) > max_nodes:
        truncated = True
        keep = set(sorted(docs, key=lambda i: -degrees.get(i, 0))[:max_nodes])

    edges = []
    seen = set()
    for src, dst, kind, w in store.all_links():
        if src not in keep or dst not in keep:
            continue
        key = (min(src, dst), max(src, dst), kind)
        if key in seen:
            continue
        seen.add(key)
        edges.append([src, dst, kind])

    nodes = []
    for did in keep:
        d = docs[did]
        folder = str(Path(d.path).parent)
        nodes.append({
            "id": did, "t": d.title, "p": d.path,
            "f": "" if folder == "." else folder,
            "deg": degrees.get(did, 0),
            "tags": d.tags[:4],
        })
    return {"nodes": nodes, "edges": edges, "truncated": truncated,
            "total_docs": len(docs)}


_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>__TITLE__ — Lemory graph</title>
<style>
:root{color-scheme:light dark}
body{margin:0;font:13px/1.4 -apple-system,'Segoe UI',sans-serif;display:flex;
     height:100vh;background:#111;color:#ddd;overflow:hidden}
#c{flex:1;cursor:grab}
#side{width:300px;padding:14px;overflow-y:auto;background:#1a1a1a;
      border-left:1px solid #333;display:flex;flex-direction:column;gap:8px}
#side h1{font-size:15px;margin:0}
#q{width:100%;padding:6px 8px;border-radius:6px;border:1px solid #444;
   background:#222;color:#eee;box-sizing:border-box}
#info{font-size:12px;color:#999}
#sel b{font-size:14px}
.nb{cursor:pointer;color:#8fbaff;display:block;padding:1px 0}
.nb:hover{text-decoration:underline}
.tag{display:inline-block;background:#2c3a55;border-radius:8px;
     padding:0 7px;margin:1px;font-size:11px}
</style></head><body>
<canvas id="c"></canvas>
<div id="side">
  <h1>__TITLE__</h1>
  <input id="q" placeholder="노트 검색 · search notes" autocomplete="off">
  <div id="info"></div>
  <div id="sel"></div>
</div>
<script>
const DATA = __DATA__;
const cv = document.getElementById('c'), cx = cv.getContext('2d');
const N = DATA.nodes, E = DATA.edges;
const byId = new Map(N.map(n => [n.id, n]));
const nbrs = new Map(N.map(n => [n.id, []]));
for (const [a, b] of E) {
  if (nbrs.has(a) && byId.has(b)) nbrs.get(a).push(b);
  if (nbrs.has(b) && byId.has(a)) nbrs.get(b).push(a);
}
// folder -> hue
const folders = [...new Set(N.map(n => n.f))].sort();
const hue = f => 210 + (folders.indexOf(f) * 137) % 360;
// init positions on a ring, then force iterations
N.forEach((n, i) => {
  const a = 2 * Math.PI * i / N.length, r = 200 + 40 * (i % 7);
  n.x = Math.cos(a) * r; n.y = Math.sin(a) * r;
  n.vx = 0; n.vy = 0; n.r = 2.5 + Math.min(9, Math.sqrt(n.deg));
});
const idx = new Map(N.map((n, i) => [n.id, i]));
function step(alpha) {
  // repulsion via a coarse grid (O(n) approx)
  const cell = 60, grid = new Map();
  for (const n of N) {
    const k = ((n.x / cell) | 0) + ':' + ((n.y / cell) | 0);
    (grid.get(k) || grid.set(k, []).get(k)).push(n);
  }
  for (const n of N) {
    const gx = (n.x / cell) | 0, gy = (n.y / cell) | 0;
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      const bucket = grid.get((gx + dx) + ':' + (gy + dy));
      if (!bucket) continue;
      for (const m of bucket) {
        if (m === n) continue;
        let ex = n.x - m.x, ey = n.y - m.y;
        let d2 = ex * ex + ey * ey || 1;
        if (d2 < 3600) { const f = alpha * 220 / d2; n.vx += ex * f; n.vy += ey * f; }
      }
    }
    // gravity
    n.vx -= n.x * alpha * 0.004; n.vy -= n.y * alpha * 0.004;
  }
  for (const [a, b] of E) {
    const na = byId.get(a), nb = byId.get(b);
    if (!na || !nb) continue;
    const ex = nb.x - na.x, ey = nb.y - na.y;
    // spring normalized by degree: hubs with dozens of edges would otherwise
    // accumulate unbounded force and the layout explodes on dense vaults
    const d = Math.sqrt(ex * ex + ey * ey) || 1;
    const f = alpha * (d - 46) / d * 0.02;
    na.vx += ex * f / Math.sqrt(na.deg || 1); na.vy += ey * f / Math.sqrt(na.deg || 1);
    nb.vx -= ex * f / Math.sqrt(nb.deg || 1); nb.vy -= ey * f / Math.sqrt(nb.deg || 1);
  }
  const MAXV = 24;
  for (const n of N) {
    n.vx = Math.max(-MAXV, Math.min(MAXV, n.vx * 0.85));
    n.vy = Math.max(-MAXV, Math.min(MAXV, n.vy * 0.85));
    n.x += n.vx; n.y += n.vy;
  }
}
let ticks = 0, maxTicks = Math.min(300, 60000 / Math.max(1, N.length) * 10 + 60);
let scale = 1, ox = 0, oy = 0, sel = null, match = null;
function resize() { cv.width = cv.clientWidth * devicePixelRatio; cv.height = cv.clientHeight * devicePixelRatio; }
window.addEventListener('resize', () => { resize(); draw(); });
function draw() {
  cx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  cx.clearRect(0, 0, cv.clientWidth, cv.clientHeight);
  cx.translate(cv.clientWidth / 2 + ox, cv.clientHeight / 2 + oy);
  cx.scale(scale, scale);
  cx.globalAlpha = 0.25; cx.strokeStyle = '#4a5568'; cx.lineWidth = 0.6 / scale;
  cx.beginPath();
  for (const [a, b, kind] of E) {
    const na = byId.get(a), nb = byId.get(b);
    if (!na || !nb) continue;
    cx.moveTo(na.x, na.y); cx.lineTo(nb.x, nb.y);
  }
  cx.stroke();
  cx.globalAlpha = 1;
  const selN = sel ? new Set([sel.id, ...nbrs.get(sel.id)]) : null;
  for (const n of N) {
    const dim = (match && !n._m) || (selN && !selN.has(n.id));
    cx.globalAlpha = dim ? 0.15 : 1;
    cx.fillStyle = `hsl(${hue(n.f)} 60% ${sel && n.id === sel.id ? 75 : 55}%)`;
    cx.beginPath(); cx.arc(n.x, n.y, n.r, 0, 7); cx.fill();
    if ((scale > 0.8 && n.deg > 8) || (selN && selN.has(n.id)) || n._m) {
      cx.fillStyle = '#ccc'; cx.font = `${11 / scale}px sans-serif`;
      cx.fillText(n.t.slice(0, 24), n.x + n.r + 2, n.y + 3);
    }
  }
  cx.globalAlpha = 1;
}
function loop() { if (ticks++ < maxTicks) { step(Math.max(0.02, 1 - ticks / maxTicks)); draw(); requestAnimationFrame(loop); } }
resize(); loop();
document.getElementById('info').textContent =
  `${N.length} notes · ${E.length} links` + (DATA.truncated ? ` (상위 ${N.length}/${DATA.total_docs})` : '');
// interactions
let drag = null, moved = false;
cv.addEventListener('mousedown', e => { drag = { x: e.clientX, y: e.clientY }; moved = false; });
window.addEventListener('mousemove', e => {
  if (!drag) return; moved = true;
  ox += e.clientX - drag.x; oy += e.clientY - drag.y;
  drag = { x: e.clientX, y: e.clientY }; draw();
});
window.addEventListener('mouseup', e => {
  if (drag && !moved) pick(e);
  drag = null;
});
cv.addEventListener('wheel', e => {
  e.preventDefault();
  scale = Math.max(0.1, Math.min(6, scale * (e.deltaY < 0 ? 1.12 : 0.89)));
  draw();
}, { passive: false });
function pick(e) {
  const rc = cv.getBoundingClientRect();
  const px = (e.clientX - rc.left - cv.clientWidth / 2 - ox) / scale;
  const py = (e.clientY - rc.top - cv.clientHeight / 2 - oy) / scale;
  sel = null;
  let best = 144;
  for (const n of N) {
    const d = (n.x - px) ** 2 + (n.y - py) ** 2;
    if (d < best) { best = d; sel = n; }
  }
  show(); draw();
}
function show() {
  const el = document.getElementById('sel');
  if (!sel) { el.innerHTML = ''; return; }
  const links = nbrs.get(sel.id).map(id => byId.get(id)).filter(Boolean)
    .sort((a, b) => b.deg - a.deg).slice(0, 20)
    .map(n => `<span class="nb" data-id="${n.id}">↳ ${n.t}</span>`).join('');
  el.innerHTML = `<b>${sel.t}</b><br><span style="color:#888">${sel.p}</span><br>` +
    sel.tags.map(t => `<span class="tag">#${t}</span>`).join('') +
    `<div style="margin-top:6px;color:#999">links: ${sel.deg}</div>${links}`;
  el.querySelectorAll('.nb').forEach(a => a.onclick = () => {
    sel = byId.get(+a.dataset.id);
    ox = -sel.x * scale; oy = -sel.y * scale; show(); draw();
  });
}
document.getElementById('q').addEventListener('input', e => {
  const q = e.target.value.trim().toLowerCase();
  match = q ? true : null;
  for (const n of N) n._m = q && n.t.toLowerCase().includes(q);
  draw();
});
</script></body></html>
"""


def render_graph_html(engine: "Engine", title: str = "") -> str:
    data = graph_data(engine)
    name = title or Path(str(engine.cfg.resolved_vault())).name
    return (_TEMPLATE
            .replace("__TITLE__", name)
            .replace("__DATA__", json.dumps(data, ensure_ascii=False)))
