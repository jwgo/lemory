/* Lemory console — vanilla JS SPA, no build step, no external deps. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}
const jpost = (url, body, method = "POST") => api(url, {
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

function toast(msg, cls = "") {
  const el = document.createElement("div");
  el.className = `toast ${cls}`;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .25s"; }, 2600);
  setTimeout(() => el.remove(), 2950);
}

function rel(ts) {
  if (!ts) return "—";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "방금 전";
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}일 전`;
  return new Date(ts * 1000).toLocaleDateString("ko-KR");
}
const fmtBytes = b => b > 1048576 ? (b / 1048576).toFixed(1) + " MB"
  : b > 1024 ? (b / 1024).toFixed(0) + " KB" : b + " B";
const fmtN = n => (n ?? 0).toLocaleString("ko-KR");
// headings are stored as "Note Title > Section" breadcrumbs; showing the
// title twice next to the note name reads as noise — strip the prefix
const subHeading = (title, heading) => {
  if (!heading || heading === title) return "";
  return heading.startsWith(title + " > ") ? heading.slice(title.length + 3) : heading;
};

/* ------------------------------------------------------------------ state */
const S = {
  overview: null,
  notes: null,          // /api/notes rows
  tags: null,
  vaultPath: null,
  knowledge: { folder: "", filter: "", sort: "mtime", sel: null, open: new Set([""]) },
  search: { q: "", mode: "hybrid", graph: true, k: 8 },
};

async function loadNotes(force = false) {
  if (!S.notes || force) S.notes = await api("/api/notes");
  return S.notes;
}

/* ----------------------------------------------------------------- router */
const routes = {
  overview: renderOverview,
  knowledge: renderKnowledge,
  search: renderSearch,
  assistant: renderAssistant,
  settings: renderSettings,
};

function nav() {
  const h = location.hash.replace(/^#\/?/, "");
  const [view, ...rest] = h.split("/");
  const name = routes[view] ? view : "overview";
  $$(".nav-item").forEach(a => a.classList.toggle("active", a.dataset.view === name));
  routes[name](decodeURIComponent(rest.join("/") || ""));
}
window.addEventListener("hashchange", nav);

function go(hash) { if (location.hash === hash) nav(); else location.hash = hash; }

/* --------------------------------------------------------------- overview */
async function renderOverview() {
  const m = $("#main");
  m.innerHTML = `<div class="view">
    <div class="view-head">
      <div class="view-title">현황</div>
      <div class="view-sub" id="ovSub"></div>
      <div class="spacer"></div>
      <button class="btn" id="btnSync">${icoRefresh()} 증분 색인</button>
      <button class="btn ghost" id="btnFull">전체 재색인</button>
    </div>
    <div class="tiles" id="tiles">${'<div class="tile"><div class="skel" style="height:24px;width:70px"></div><div class="skel" style="height:12px;width:44px;margin-top:8px"></div></div>'.repeat(4)}</div>
    <div class="cols-2">
      <div style="display:flex;flex-direction:column;gap:12px">
        <div class="card" id="memFeedCard" hidden><div class="card-head">AI 메모리 피드 <span style="font-weight:400;color:var(--text-3)">AI가 볼트에 적은 것 — 전부 마크다운 파일</span></div><div class="act-list" id="memFeed"></div></div>
        <div class="card" id="qlogCard" hidden><div class="card-head">최근 질의 <span style="font-weight:400;color:var(--text-3)">이 메모리를 지나간 검색·질문</span></div><div class="act-list" id="qlog"></div></div>
        <div class="card"><div class="card-head">색인 활동</div><div class="act-list" id="acts"><div class="empty">불러오는 중…</div></div></div>
        <div class="card"><div class="card-head">최근 수정된 노트</div><div class="act-list" id="recent"></div></div>
        <div class="card" id="hotCard" hidden><div class="card-head">자주 참조되는 노트 <span style="font-weight:400;color:var(--text-3)">검색·질문에 오른 횟수</span></div><div class="act-list" id="hot"></div></div>
      </div>
      <div style="display:flex;flex-direction:column;gap:12px">
        <div class="card"><div class="card-head">시스템</div><div class="kv" id="sys"></div></div>
        <div class="card" id="clientsCard" hidden><div class="card-head">클라이언트 <span style="font-weight:400;color:var(--text-3)">최근 7일, 누가 이 메모리를 쓰는가</span></div><div class="act-list" id="clients"></div></div>
      </div>
    </div>
  </div>`;

  $("#btnSync").onclick = () => runIndex(false);
  $("#btnFull").onclick = () => runIndex(true);

  let o;
  try { o = await api("/api/overview"); } catch (e) {
    m.querySelector(".view").innerHTML += `<div class="empty">서버에 연결할 수 없습니다 — ${esc(e.message)}</div>`;
    return;
  }
  S.overview = o;
  S.vaultPath = o.vault;
  $("#vaultName").textContent = (o.vault || "").split("/").filter(Boolean).pop() || "볼트 미설정";
  setWatch(o.watcher_alive);
  $("#ovSub").textContent = o.last_sync ? `마지막 동기화 ${rel(+o.last_sync)}` : "";

  $("#tiles").innerHTML = [
    { n: fmtN(o.documents), l: "노트", s: `${fmtN(o.tags)}개 태그` },
    { n: fmtN(o.chunks), l: "청크", s: `임베딩 캐시 ${fmtN(o.cached_embeddings)}` },
    { n: fmtN(o.links), l: "그래프 링크", s: o.graph_expansion ? "그래프 확장 켜짐" : "그래프 확장 꺼짐" },
    { n: fmtBytes(o.db_bytes), l: "저장소", s: "SQLite 단일 파일" },
  ].map(t => `<div class="tile"><div class="num">${t.n}</div><div class="lbl">${t.l}</div><div class="sub">${esc(t.s)}</div></div>`).join("");

  $("#acts").innerHTML = o.activity.length ? o.activity.map(a => `
    <div class="act-row">
      <span class="act-kind ${a.kind}">${{ startup: "시작", watch: "자동", manual: "수동" }[a.kind] || a.kind}</span>
      <span class="act-delta">+${a.added} ~${a.updated} −${a.removed}</span>
      <span class="act-delta" style="color:var(--text-3)">${a.chunks}청크 · ${a.embedded}임베딩 · ${a.seconds}s</span>
      <span class="act-time" title="${new Date(a.ts * 1000).toLocaleString("ko-KR")}">${rel(a.ts)}</span>
    </div>`).join("")
    : `<div class="empty">아직 색인 활동이 없습니다</div>`;

  // middleware timeline: AI writes (with undo), queries, per-client stats
  api("/api/events?limit=80").then(evts => {
    const clientChip = c => c ? `<span class="chip">${esc(c)}</span>` : "";
    const writes = evts.filter(e => e.kind === "memory" || e.kind === "append").slice(0, 6);
    if (writes.length) {
      $("#memFeedCard").hidden = false;
      $("#memFeed").innerHTML = writes.map(e => `
        <div class="act-row">
          <span class="act-kind ${e.kind === "memory" ? "manual" : "watch"}">${e.kind === "memory" ? "새 기억" : "덧붙임"}</span>
          <span style="font-weight:550;cursor:pointer" data-goto-note="${esc(e.path)}">${esc((e.detail && e.detail.title) || e.path)}</span>
          ${clientChip(e.client)}
          ${e.kind === "memory" ? `<button class="btn ghost" style="height:22px;padding:0 8px;font-size:11px" data-trash="${esc(e.path)}">휴지통</button>` : ""}
          <span class="act-time">${rel(e.ts)}</span>
        </div>`).join("");
      $$("#memFeed [data-goto-note]").forEach(el =>
        el.onclick = () => go("#/knowledge/" + encodeURIComponent(el.dataset.gotoNote)));
      $$("#memFeed [data-trash]").forEach(btn => btn.onclick = async () => {
        if (!confirm(`"${btn.dataset.trash}" 노트를 볼트 휴지통(.trash)으로 옮길까요?`)) return;
        try {
          await jpost("/memory/trash", { path: btn.dataset.trash });
          toast("휴지통으로 이동했습니다", "ok");
          renderOverview();
        } catch (e) { toast(e.message, "err"); }
      });
    }
    const queries = evts.filter(e => e.kind === "search" || e.kind === "ask").slice(0, 6);
    if (queries.length) {
      $("#qlogCard").hidden = false;
      $("#qlog").innerHTML = queries.map(e => `
        <div class="act-row">
          <span class="act-kind ${e.kind === "ask" ? "manual" : "startup"}">${e.kind === "ask" ? "질문" : "검색"}</span>
          <span style="font-weight:550;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:280px" title="${esc(e.query || "")}">${esc(e.query || "")}</span>
          ${clientChip(e.client)}
          <span class="act-time">${rel(e.ts)}</span>
        </div>`).join("");
    }
  }).catch(() => {});
  api("/api/clients").then(rows => {
    if (!rows.length) return;
    $("#clientsCard").hidden = false;
    $("#clients").innerHTML = rows.map(r => `
      <div class="act-row">
        <span style="font-weight:550">${esc(r.client)}</span>
        <span class="act-delta">질의 ${r.queries || 0} · 쓰기 ${r.writes || 0}</span>
        <span class="act-time">${rel(r.last)}</span>
      </div>`).join("");
  }).catch(() => {});

  loadNotes().then(notes => {
    const hot = [...notes].filter(n => n.hits > 0).sort((a, b) => b.hits - a.hits).slice(0, 6);
    if (hot.length) {
      $("#hotCard").hidden = false;
      $("#hot").innerHTML = hot.map(n => `
        <div class="act-row" style="cursor:pointer" data-path="${esc(n.path)}">
          <span style="font-weight:550">${esc(n.title)}</span>
          <span class="chip brand">🔥 ${n.hits}</span>
          <span class="act-time">${rel(n.last_hit)}</span>
        </div>`).join("");
      $$("#hot .act-row").forEach(r =>
        r.onclick = () => go("#/knowledge/" + encodeURIComponent(r.dataset.path)));
    }
    const rec = [...notes].sort((a, b) => b.mtime - a.mtime).slice(0, 6);
    $("#recent").innerHTML = rec.length ? rec.map(n => `
      <div class="act-row" style="cursor:pointer" data-path="${esc(n.path)}">
        <span style="font-weight:550">${esc(n.title)}</span>
        ${n.tags.slice(0, 2).map(t => `<span class="chip">#${esc(t)}</span>`).join("")}
        <span class="act-time">${rel(n.mtime)}</span>
      </div>`).join("") : `<div class="empty">노트가 없습니다</div>`;
    $$("#recent .act-row").forEach(r =>
      r.onclick = () => go("#/knowledge/" + encodeURIComponent(r.dataset.path)));
  }).catch(() => {});

  $("#sys").innerHTML = [
    ["프로바이더", esc(o.provider || "—")],
    ["LLM", esc(o.llm_model || "—")],
    ["임베딩", esc(o.embed_model || "—")],
    ["벡터 인덱스", o.vector_index === "ivf-int8"
      ? 'IVF-int8 <span style="color:var(--text-3)">(대규모 자동 전환)</span>'
      : '정확 검색 <span style="color:var(--text-3)">(소규모 볼트 기본)</span>'],
    ["볼트", `<span class="kv-v mono">${esc(o.vault || "—")}</span>`],
    ["DB", `<span class="kv-v mono">${esc(o.db || "—")}</span>`],
    ["볼트 감시", o.watcher_alive ? '<span style="color:var(--ok)">실시간 동기화 중</span>' : '<span style="color:var(--warn)">꺼짐</span>'],
    ["업타임", uptime(o.uptime_s)],
  ].map(([k, v]) => `<div class="kv-row"><span class="kv-k">${k}</span><span class="kv-v">${v}</span></div>`).join("");
}

function uptime(s) {
  if (s < 3600) return `${Math.floor(s / 60)}분`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 ${Math.floor(s % 3600 / 60)}분`;
  return `${Math.floor(s / 86400)}일 ${Math.floor(s % 86400 / 3600)}시간`;
}

async function runIndex(full) {
  const btn = full ? $("#btnFull") : $("#btnSync");
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `${icoRefresh("spin-ico")} 예상 계산…`;
  try {
    const plan = await api(`/api/index_plan?full=${full}`);
    if (full || plan.to_process > 0) {
      const msg = `노트 ${plan.to_process}개 · 청크 ${plan.chunks_total}개 `
        + `(임베딩 필요 ${plan.embeds_needed}개)\n예상 시간: ${plan.eta}`
        + (plan.rate_measured ? "" : " (기본값 추정 — 첫 실행 후 실측치로 보정됩니다)");
      if (full && !confirm(`전체 재색인을 실행할까요?\n\n${msg}`)) {
        btn.disabled = false; btn.innerHTML = orig; return;
      }
      if (plan.embeds_needed > 0) toast(`색인 시작 — ${plan.eta} 예상`, "");
    }
  } catch { /* plan is best-effort; indexing proceeds regardless */ }
  btn.innerHTML = `${icoRefresh("spin-ico")} 색인 중…`;
  try {
    const r = await jpost("/index", { full });
    toast(`색인 완료 — +${r.added} ~${r.updated} −${r.removed} (${r.seconds.toFixed(1)}s)`, "ok");
    S.notes = null;
    renderOverview();
  } catch (e) {
    toast(`색인 실패: ${e.message}`, "err");
    btn.disabled = false; btn.innerHTML = orig;
  }
}

function setWatch(alive) {
  $("#watchDot").className = `dot ${alive ? "ok" : "warn"}`;
  $("#watchLabel").textContent = alive ? "볼트 실시간 감시 중" : "감시 꺼짐";
}

/* -------------------------------------------------------------- knowledge */
async function renderKnowledge(selPath) {
  const K = S.knowledge;
  if (selPath) K.sel = selPath;
  const m = $("#main");
  m.innerHTML = `<div class="view wide"><div class="kn" id="kn">
    <div class="kn-pane tree-pane">
      <div class="kn-pane-head"><span class="kn-pane-title">지식 계층</span></div>
      <div class="tree" id="tree"></div>
    </div>
    <div class="kn-pane list-pane">
      <div class="kn-pane-head">
        <input class="note-filter" id="noteFilter" type="text" placeholder="필터…" value="${esc(K.filter)}">
        <select class="note-sort" id="noteSort">
          <option value="mtime">최근 수정</option>
          <option value="title">제목</option>
          <option value="links">연결 많은 순</option>
          <option value="chunks">분량</option>
          <option value="hits">많이 찾은 순</option>
        </select>
      </div>
      <div class="note-rows" id="noteRows"></div>
    </div>
    <div class="kn-pane detail-pane" id="notePane">
      <div class="empty">${icoDoc()} 노트를 선택하세요</div>
    </div>
  </div></div>`;

  $("#noteSort").value = K.sort;
  $("#noteFilter").oninput = e => { K.filter = e.target.value; drawNoteRows(); };
  $("#noteSort").onchange = e => { K.sort = e.target.value; drawNoteRows(); };

  try { await loadNotes(); } catch (e) {
    $("#noteRows").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }
  if (!S.tags) { try { S.tags = await api("/api/tags"); } catch { S.tags = []; } }

  drawTree();
  drawNoteRows();
  if (K.sel) drawNoteDetail(K.sel);
}

function buildTree(notes) {
  const root = { name: "", children: new Map(), count: 0 };
  for (const n of notes) {
    root.count++;
    const parts = n.path.split("/").slice(0, -1);
    let cur = root, acc = "";
    for (const p of parts) {
      acc = acc ? `${acc}/${p}` : p;
      if (!cur.children.has(p)) cur.children.set(p, { name: p, full: acc, children: new Map(), count: 0 });
      cur = cur.children.get(p);
      cur.count++;
    }
  }
  return root;
}

function drawTree() {
  const K = S.knowledge;
  const tree = buildTree(S.notes);
  const el = $("#tree");
  let html = `<div class="tree-item ${K.folder === "" && !K.tag ? "active" : ""}" data-folder="">
    ${icoHome()}<span class="name">모든 노트</span><span class="cnt">${tree.count}</span></div>`;

  const walk = (node, depth) => {
    const kids = [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name, "ko"));
    let s = "";
    for (const k of kids) {
      const open = K.open.has(k.full);
      const hasKids = k.children.size > 0;
      s += `<div class="tree-item ${K.folder === k.full && !K.tag ? "active" : ""}" data-folder="${esc(k.full)}">
        <span class="tw ${open ? "open" : ""}" data-toggle="${esc(k.full)}" style="${hasKids ? "" : "visibility:hidden"}">${icoChev()}</span>
        ${icoFolder()}<span class="name">${esc(k.name)}</span><span class="cnt">${k.count}</span></div>`;
      if (hasKids && open) s += `<div class="tree-children">${walk(k, depth + 1)}</div>`;
    }
    return s;
  };
  html += walk(tree, 0);

  if (S.tags?.length) {
    html += `<div class="tree-sec">태그</div>`;
    for (const t of S.tags.slice(0, 30)) {
      html += `<div class="tree-item ${K.tag === t.tag ? "active" : ""}" data-tag="${esc(t.tag)}">
        ${icoTag()}<span class="name">#${esc(t.tag)}</span><span class="cnt">${t.count}</span></div>`;
    }
  }
  el.innerHTML = html;

  $$(".tree-item", el).forEach(item => {
    item.onclick = e => {
      const tg = e.target.closest("[data-toggle]");
      if (tg) {
        const f = tg.dataset.toggle;
        K.open.has(f) ? K.open.delete(f) : K.open.add(f);
        drawTree(); return;
      }
      if (item.dataset.tag !== undefined) { K.tag = item.dataset.tag; K.folder = ""; }
      else { K.folder = item.dataset.folder; K.tag = null; }
      drawTree(); drawNoteRows();
    };
  });
}

function drawNoteRows() {
  const K = S.knowledge;
  let rows = S.notes;
  if (K.tag) rows = rows.filter(n => n.tags.includes(K.tag));
  else if (K.folder) rows = rows.filter(n => n.path.startsWith(K.folder + "/"));
  if (K.filter) {
    const f = K.filter.toLowerCase();
    rows = rows.filter(n => n.title.toLowerCase().includes(f) || n.path.toLowerCase().includes(f));
  }
  const sorters = {
    mtime: (a, b) => b.mtime - a.mtime,
    title: (a, b) => a.title.localeCompare(b.title, "ko"),
    links: (a, b) => (b.links_in + b.links_out) - (a.links_in + a.links_out),
    chunks: (a, b) => b.chunks - a.chunks,
    hits: (a, b) => (b.hits || 0) - (a.hits || 0),
  };
  rows = [...rows].sort(sorters[K.sort]);

  $("#noteRows").innerHTML = rows.length ? rows.map(n => `
    <div class="note-row ${K.sel === n.path ? "active" : ""}" data-path="${esc(n.path)}">
      <div class="t">${esc(n.title)}</div>
      <div class="meta">
        <span>${rel(n.mtime)}</span><span>${n.chunks}청크</span>
        <span>↗${n.links_out} ↘${n.links_in}</span>
        ${n.hits ? `<span title="검색/질문에서 참조된 횟수">🔥${n.hits}</span>` : ""}
        ${n.tags.slice(0, 2).map(t => `<span>#${esc(t)}</span>`).join("")}
      </div>
    </div>`).join("")
    : `<div class="empty">해당하는 노트가 없습니다</div>`;

  $$("#noteRows .note-row").forEach(r => r.onclick = () => {
    K.sel = r.dataset.path;
    $$("#noteRows .note-row").forEach(x => x.classList.toggle("active", x === r));
    drawNoteDetail(K.sel);
  });
}

async function drawNoteDetail(path) {
  const pane = $("#notePane");
  if (!pane) return;
  pane.innerHTML = `<div class="note-detail"><div class="skel" style="height:22px;width:220px"></div>
    <div class="skel" style="height:12px;width:320px;margin-top:10px"></div></div>`;
  let d;
  try { d = await api("/api/note?path=" + encodeURIComponent(path)); }
  catch (e) { pane.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }

  const obsidian = S.vaultPath
    ? `obsidian://open?path=${encodeURIComponent(S.vaultPath.replace(/\/$/, "") + "/" + d.path)}`
    : `obsidian://open?file=${encodeURIComponent(d.path)}`;

  const linkPill = l => `<span class="link-pill" data-goto="${esc(l.path)}">
      <span class="k ${l.kind}">${{ wiki: "링크", mention: "언급", entity: "개체" }[l.kind] || l.kind}</span>${esc(l.title)}</span>`;

  pane.innerHTML = `<div class="note-detail">
    <div class="nd-title">${esc(d.title)}</div>
    <div class="nd-path">${esc(d.path)}
      <a class="btn ghost" style="height:24px;padding:0 8px;font-size:11.5px" href="${obsidian}">${icoExt()} Obsidian에서 열기</a>
    </div>
    ${d.tags.length ? `<div class="nd-tags">${d.tags.map(t => `<span class="chip brand">#${esc(t)}</span>`).join("")}</div>` : ""}
    <div class="nd-meta">
      <span>수정 ${rel(d.mtime)}</span><span>색인 ${rel(d.indexed_at)}</span>
      <span>청크 ${d.chunks.length}</span>
      <span title="이 노트가 검색·질문 결과에 오른 횟수">참조 ${d.hits || 0}회${d.hits ? " · 마지막 " + rel(d.last_hit) : ""}</span>
    </div>
    ${localGraphSVG(d)}
    <div class="nd-sec"><div class="nd-sec-title">나가는 연결 · ${d.links_out.length}</div>
      ${d.links_out.length ? `<div class="link-grid">${d.links_out.map(linkPill).join("")}</div>` : `<div class="view-sub">없음</div>`}</div>
    <div class="nd-sec"><div class="nd-sec-title">들어오는 연결 (백링크) · ${d.links_in.length}</div>
      ${d.links_in.length ? `<div class="link-grid">${d.links_in.map(linkPill).join("")}</div>` : `<div class="view-sub">없음</div>`}</div>
    <div class="nd-sec" id="relatedSec"><div class="nd-sec-title">관련 노트</div>
      <div class="view-sub">불러오는 중…</div></div>
    <div class="nd-sec"><div class="nd-sec-title">색인된 내용</div>
      ${d.chunks.map(c => `<div class="chunk">${subHeading(d.title, c.heading) ? `<div class="h">${esc(subHeading(d.title, c.heading))}</div>` : ""}
        <div class="x">${esc(c.text)}</div>
        ${c.text.length > 400 ? `<div class="more">더 보기</div>` : ""}</div>`).join("")}</div>
  </div>`;

  // related notes load async — content similarity, not just links
  api("/api/related?path=" + encodeURIComponent(path) + "&k=6").then(rel_ => {
    const sec = $("#relatedSec", pane);
    if (!sec) return;
    sec.innerHTML = `<div class="nd-sec-title">관련 노트 <span class="view-sub" style="display:inline">내용 유사도 기준</span></div>` +
      (rel_.length
        ? `<div class="link-grid">${rel_.map(r => `<span class="link-pill" data-goto="${esc(r.path)}">
             <span class="k entity">${(r.score * 100).toFixed(0)}%</span>${esc(r.title)}</span>`).join("")}</div>`
        : `<div class="view-sub">없음</div>`);
    $$("[data-goto]", sec).forEach(p => p.onclick = () => {
      S.knowledge.sel = p.dataset.goto;
      drawNoteRows();
      drawNoteDetail(p.dataset.goto);
    });
  }).catch(() => {});

  $$("[data-goto]", pane).forEach(p => p.onclick = () => {
    S.knowledge.sel = p.dataset.goto;
    drawNoteRows();
    drawNoteDetail(p.dataset.goto);
  });
  $$(".chunk .more", pane).forEach(btn => btn.onclick = () => {
    btn.previousElementSibling.classList.add("open");
    btn.remove();
  });
}

/* ----------------------------------------------------------------- search */
// what people actually ask their vault — rotated so the empty state teaches range
const EXAMPLE_QUERIES = [
  "3분기 킥오프에서 예산 얼마로 잡았지?",
  "재택근무 정책, 작년이랑 지금이랑 뭐가 달라졌지?",
  "데이터플랫폼팀 리드가 누구고 무슨 일 하는 팀이지?",
  "자바스크립트 이벤트 루프 뭐였지? 내 노트 기준으로",
  "카오스 벨룸 가기 전에 준비물 뭐라고 적어놨더라?",
  "알러지 올라올 때 대처 순서 뭐였지?",
  "전세 갱신 거절당하면 뭐부터 한다고 정리해놨지?",
  "그 프로젝트 리드가 좋아하는 DB가 뭐더라?",
  "오사카에서 갔던 그 라멘집 이름이 뭐였지?",
  "사피엔스 읽으면서 밑줄 친 문장 뭐가 있었지?",
  "김치찌개 황금비율, 내 레시피 노트 기준으로",
  "요새 내가 하던 그거 뭐였지?",
];

async function renderSearch() {
  const Q = S.search;
  const m = $("#main");
  const ph = EXAMPLE_QUERIES[Math.floor(Math.random() * EXAMPLE_QUERIES.length)];
  m.innerHTML = `<div class="view">
    <div class="view-head"><div class="view-title">검색</div>
      <div class="view-sub">하이브리드 검색은 로컬에서 수 ms — 질문은 LLM으로 출처 달린 답변</div></div>
    <div class="search-box">
      <input id="q" type="text" placeholder="${esc(ph)}" value="${esc(Q.q)}" autocomplete="off">
      <button class="btn primary" id="btnAsk">질문</button>
      <button class="btn" id="btnSearch">검색만</button>
    </div>
    <div class="search-ctl">
      <div class="grp"><span>모드</span><div class="seg" id="segMode">
        <button data-v="hybrid">하이브리드</button><button data-v="vector">벡터</button><button data-v="bm25">BM25</button></div></div>
      <div class="grp"><span>그래프 확장</span><span class="switch ${Q.graph ? "on" : ""}" id="swGraph"></span></div>
      <div class="grp"><span>결과 수</span><div class="seg" id="segK">
        <button data-v="4">4</button><button data-v="8">8</button><button data-v="16">16</button></div></div>
      <span class="chip lat-chip" id="lat" hidden></span>
    </div>
    <div id="answerBox"></div>
    <div class="hits" id="hits"></div>
  </div>`;

  const syncSeg = (id, val) => $$(`#${id} button`).forEach(b => b.classList.toggle("active", b.dataset.v === String(val)));
  syncSeg("segMode", Q.mode); syncSeg("segK", Q.k);
  $$("#segMode button").forEach(b => b.onclick = () => { Q.mode = b.dataset.v; syncSeg("segMode", Q.mode); });
  $$("#segK button").forEach(b => b.onclick = () => { Q.k = +b.dataset.v; syncSeg("segK", Q.k); });
  $("#swGraph").onclick = e => { Q.graph = !Q.graph; e.target.classList.toggle("on", Q.graph); };

  const input = $("#q");
  input.focus();
  // rotate example questions while the box is empty — the empty state is the tutorial
  const rot = setInterval(() => {
    if (!document.body.contains(input)) { clearInterval(rot); return; }
    if (!input.value) input.placeholder = EXAMPLE_QUERIES[Math.floor(Math.random() * EXAMPLE_QUERIES.length)];
  }, 4000);
  input.addEventListener("keydown", e => { if (e.key === "Enter") doAsk(); });
  $("#btnAsk").onclick = doAsk;
  $("#btnSearch").onclick = doSearch;

  async function doSearch() {
    Q.q = input.value.trim(); if (!Q.q) return;
    $("#answerBox").innerHTML = "";
    $("#hits").innerHTML = `<div class="skel" style="height:64px"></div><div class="skel" style="height:64px"></div>`;
    const t0 = performance.now();
    try {
      const hits = await api(`/search?q=${encodeURIComponent(Q.q)}&k=${Q.k}&mode=${Q.mode}&graph=${Q.graph}`);
      const ms = performance.now() - t0;
      $("#lat").hidden = false;
      $("#lat").textContent = `${hits.length}건 · ${ms < 100 ? ms.toFixed(0) : (ms / 1000).toFixed(2) + "s로 표기됨"}${ms < 100 ? "ms" : ""} · ${Q.mode}${Q.graph && Q.mode === "hybrid" ? "+그래프" : ""}`;
      drawHits(hits);
    } catch (e) { $("#hits").innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }

  async function doAsk() {
    Q.q = input.value.trim(); if (!Q.q) return;
    $("#answerBox").innerHTML = `<div class="answer-card"><div class="al">답변</div>
      <div class="skel" style="height:14px;width:80%"></div><div class="skel" style="height:14px;width:60%;margin-top:8px"></div></div>`;
    $("#hits").innerHTML = "";
    $("#lat").hidden = true;
    try {
      const r = await jpost("/ask", { question: Q.q, k: Q.k });
      $("#answerBox").innerHTML = `<div class="answer-card"><div class="al">답변</div>
        <div class="at">${esc(r.answer)}</div></div>`;
      drawHits(r.sources, true);
    } catch (e) {
      $("#answerBox").innerHTML = "";
      $("#hits").innerHTML = `<div class="empty">답변 실패 — ${esc(e.message)}</div>`;
    }
  }

  function drawHits(hits, cited = false) {
    if (!hits.length) { $("#hits").innerHTML = `<div class="empty">결과가 없습니다</div>`; return; }
    const max = Math.max(...hits.map(h => h.score), 1e-9);
    $("#hits").innerHTML = hits.map((h, i) => `
      <div class="hit" data-path="${esc(h.path)}">
        <div class="row1">
          <span class="rank">${cited ? "[" + (i + 1) + "]" : String(i + 1).padStart(2, "0")}</span>
          <span class="title">${esc(h.title)}</span>
          ${subHeading(h.title, h.heading) ? `<span class="hd">› ${esc(subHeading(h.title, h.heading))}</span>` : ""}
          ${h.date ? `<span class="chip date">${esc(h.date)}</span>` : ""}
        </div>
        <div class="snippet">${esc((h.text || "").slice(0, 300))}</div>
        <div class="scorebar"><i style="width:${Math.max(4, h.score / max * 100)}%"></i></div>
      </div>`).join("");
    $$("#hits .hit").forEach(el => el.onclick = () => go("#/knowledge/" + encodeURIComponent(el.dataset.path)));
  }
}

/* -------------------------------------------------------------- assistant */
const ASSIST = { history: [], busy: false };

async function renderAssistant() {
  const m = $("#main");
  m.innerHTML = `<div class="view asst">
    <div class="view-head"><div class="view-title">비서</div>
      <div class="view-sub">지식베이스 기반 대화 — 로컬 모델로 스트리밍, 출처 인용</div>
      <div id="asstModel" class="asst-model"></div></div>
    <div id="asstGate"></div>
    <div id="asstWrap" hidden>
      <div class="asst-log" id="asstLog"></div>
      <div id="asstStatus" class="asst-status"></div>
      <div class="asst-input">
        <button class="btn asst-mic" id="asstMic" title="대화 모드 — 그냥 말하면 됩니다 (로컬 음성인식)" hidden>🎙</button>
        <textarea id="asstIn" rows="1" placeholder="볼트에 대해 물어보세요… (Enter 전송, Shift+Enter 줄바꿈)"></textarea>
        <button class="btn primary" id="asstSend">전송</button>
      </div>
    </div></div>`;

  let st;
  try { st = await api("/api/assistant/status"); }
  catch (e) { st = { available: false, reason: e.message }; }

  if (!st.available) {
    $("#asstGate").innerHTML = `<div class="card asst-gate">
      <div class="card-head">비서 모드를 켜려면 온디바이스 모델이 필요합니다</div>
      <p>${esc(st.reason || "로컬 모델을 사용할 수 없습니다.")}</p>
      <div class="kv"><div class="kv-row"><span class="kv-k">브레인</span>
        <span class="kv-v mono">${esc(st.model || "gemma-4-E2B-it.litertlm")} (LiteRT-LM)</span></div></div>
      <p style="color:var(--text-3)"><code>pip install "lemory[assistant]"</code> 하면 데몬 없이 프로세스 안에서 바로 돕니다 (Ollama 불필요). 설치 후 <b>다시 확인</b>.</p>
      <button class="btn" id="asstRetry">다시 확인</button></div>`;
    $("#asstRetry").onclick = renderAssistant;
    return;
  }

  $("#asstWrap").hidden = false;
  if (st.sizes && st.sizes.length > 1) {
    const mb = $("#asstModel");
    mb.innerHTML = st.sizes.map(s =>
      `<button class="asst-size ${s === st.size ? "on" : ""}" data-size="${s}">${s}</button>`).join("");
    $$(".asst-size", mb).forEach(b => b.onclick = async () => {
      if (b.classList.contains("on")) return;
      try { await api("/api/assistant/model", { method: "POST", body: JSON.stringify({ size: b.dataset.size }) });
        toast(`비서 모델 → ${b.dataset.size}`, "ok"); renderAssistant(); }
      catch (e) { toast(e.message, "err"); }
    });
  }
  // preload on-device models once, with visible progress — the first turn used
  // to hang silently while several GB downloaded/loaded
  if (!ASSIST.warmed) {
    ASSIST.warmed = true;
    (async () => {
      const sEl = $("#asstStatus");
      try {
        const res = await fetch("/api/assistant/warmup");
        const reader = res.body.getReader(), dec = new TextDecoder(); let buf = "";
        for (;;) {
          const { value, done } = await reader.read(); if (done) break;
          buf += dec.decode(value, { stream: true }); let i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const line = buf.slice(0, i); buf = buf.slice(i + 2);
            if (!line.startsWith("data:")) continue;
            const d = JSON.parse(line.slice(5).trim());
            if (d.stage === "done") { if (sEl && sEl.textContent.startsWith("⏳")) sEl.textContent = ""; }
            else if (d.status === "loading" && sEl) sEl.textContent = "⏳ " + d.msg + " (첫 실행은 모델 다운로드로 몇 분 걸릴 수 있어요)";
          }
        }
      } catch (_) {}
    })();
  }
  const log = $("#asstLog"), input = $("#asstIn"), send = $("#asstSend");
  ASSIST.history.forEach(msg => appendBubble(log, msg.role, msg.content, msg.sources));
  if (!ASSIST.history.length)
    log.innerHTML = `<div class="asst-empty">무엇이든 물어보세요. 답변은 볼트의 노트에 근거하고, 아래에 출처를 답니다.<br><span style="color:var(--text-3)">예: "지난주에 정리한 결제 정책 요약해줘"</span></div>`;

  input.oninput = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; };
  input.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSend(); } };
  send.onclick = () => doSend();
  input.focus();

  /* ---- voice: natural conversation — local Whisper STT + streamed Supertonic TTS ---- */
  const mic = $("#asstMic"), statusEl = $("#asstStatus");
  const canVoice = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  let convo = false, speaking = false, recorder = null, micStream = null, audioCtx = null, vadRAF = 0;
  let ttsVoice = st.tts_voice || "f4";
  const setStatus = s => { if (statusEl) statusEl.textContent = s || ""; };

  // voice picker (Supertonic F1-F5 / M1-M5; pick your favorite)
  if (st.voices && st.voices.length) {
    const vp = document.createElement("select");
    vp.className = "asst-voice"; vp.title = "목소리";
    vp.innerHTML = st.voices.map(v => `<option ${v === ttsVoice ? "selected" : ""}>${v}</option>`).join("");
    vp.onchange = () => { ttsVoice = vp.value; };
    $("#asstModel").appendChild(vp);
  }

  // --- sentence-streamed TTS: speak each sentence the moment it completes,
  // pipelined, so speech starts after the first sentence (not the whole answer) ---
  const ttsQ = []; let ttsBusy = false, ttsBuf = "";
  function feedTTS(delta) {
    if (!convo) return;
    ttsBuf += delta;
    let m;
    // speak on a sentence end, or on a clause break (comma etc.) once the chunk
    // is long enough — starts sound sooner without being choppy/char-by-char
    while ((m = ttsBuf.match(/^([\s\S]*?[.!?。…\n])/)) ||
           (ttsBuf.length > 24 && (m = ttsBuf.match(/^([\s\S]*?[,、·:;])\s/)))) {
      enqueueSpeech(m[1]); ttsBuf = ttsBuf.slice(m[1].length);
    }
  }
  function flushTTS() { if (convo && ttsBuf.trim()) enqueueSpeech(ttsBuf); ttsBuf = ""; }
  function enqueueSpeech(text) {
    const t = text.replace(/\[\d+\]/g, "").trim();
    if (t) { ttsQ.push(t); pumpTTS(); }
  }
  async function pumpTTS() {
    if (ttsBusy || !convo) return;
    const t = ttsQ.shift(); if (t === undefined) return;
    ttsBusy = true; speaking = true; setStatus("🔊 말하는 중…");
    try {
      const res = await fetch("/api/assistant/tts", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: t, voice: ttsVoice }),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const url = URL.createObjectURL(await res.blob());
      const a = new Audio(url);
      await new Promise(done => { a.onended = a.onerror = () => { URL.revokeObjectURL(url); done(); }; a.play().catch(done); });
    } catch (e) {
      toast("음성 합성 실패: " + e.message, "err");     // Supertonic only — no browser fallback
    }
    ttsBusy = false;
    if (ttsQ.length) pumpTTS();
    else { speaking = false; if (convo && !ASSIST.busy) listen(); }   // your turn again
  }

  // --- STT: record a turn, auto-stop on silence (energy VAD), transcribe locally ---
  function stopVAD() { if (vadRAF) cancelAnimationFrame(vadRAF); vadRAF = 0; }
  function startVAD(stream, onEnd) {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const an = audioCtx.createAnalyser(); an.fftSize = 512;
    audioCtx.createMediaStreamSource(stream).connect(an);
    const buf = new Uint8Array(an.fftSize);
    let spoke = false, lastLoud = performance.now(), t0 = performance.now();
    const tick = () => {
      if (!convo) return;
      an.getByteTimeDomainData(buf);
      let sum = 0; for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
      const rms = Math.sqrt(sum / buf.length), now = performance.now();
      if (rms > 0.045) { spoke = true; lastLoud = now; }
      if ((spoke && now - lastLoud > 900) || now - t0 > 9000) { onEnd(); return; }  // silence or hard cap
      vadRAF = requestAnimationFrame(tick);
    };
    vadRAF = requestAnimationFrame(tick);
  }

  async function listen() {
    if (!convo || speaking || ASSIST.busy) return;
    try { micStream = micStream || await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch (_) { convo = false; mic.classList.remove("on"); setStatus(""); toast("마이크 권한이 필요합니다", "err"); return; }
    setStatus("🎙 말씀하세요…");
    const chunks = [];
    const rec = new MediaRecorder(micStream);
    rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      stopVAD();
      if (!convo) return;
      const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
      if (blob.size < 1600) { listen(); return; }               // too short → keep listening
      setStatus("받아쓰는 중…");
      try {
        const r = await fetch("/api/assistant/stt", { method: "POST", headers: { "Content-Type": blob.type }, body: blob });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const { text } = await r.json();
        if (text && text.trim()) doSend(text.trim()); else listen();
      } catch (e) { toast("음성 인식 실패: " + e.message, "err"); listen(); }
    };
    recorder = rec; rec.start();
    startVAD(micStream, () => { try { rec.stop(); } catch (_) {} });
  }

  if (canVoice) {
    mic.hidden = false;
    if (!st.stt || !st.tts) mic.title = '음성엔 pip install "lemory[assistant]" 필요 (로컬 STT+TTS)';
    mic.onclick = () => {
      convo = !convo; mic.classList.toggle("on", convo);
      if (convo) { toast("대화 모드 — 그냥 말하면 돼요, 멈추면 자동 인식", "ok"); listen(); }
      else {
        if (recorder) try { recorder.stop(); } catch (_) {}
        stopVAD(); ttsQ.length = 0; ttsBuf = ""; speaking = false;
        if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
        setStatus("");
      }
    };
  }

  async function doSend(voiceText) {
    const text = (voiceText != null ? voiceText : input.value).trim();
    if (!text || ASSIST.busy) return;
    input.value = ""; input.style.height = "auto";
    if (!ASSIST.history.length) log.innerHTML = "";
    ASSIST.busy = true; send.disabled = true; ttsBuf = ""; ttsQ.length = 0;
    if (convo) setStatus("생각 중…");
    ASSIST.history.push({ role: "user", content: text });
    appendBubble(log, "user", text);
    const bubble = appendBubble(log, "assistant", "");
    const body = bubble.querySelector(".asst-text");
    body.innerHTML = `<span class="asst-dots">···</span>`;
    let answer = "", sources = null;
    try {
      const res = await fetch("/api/assistant/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: ASSIST.history }),
      });
      if (!res.ok || !res.body) throw new Error("HTTP " + res.status);
      const reader = res.body.getReader(), dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const line = buf.slice(0, i); buf = buf.slice(i + 2);
          if (!line.startsWith("data:")) continue;
          const d = JSON.parse(line.slice(5).trim());
          if (d.sources) sources = d.sources;
          else if (d.delta) { answer += d.delta; body.textContent = answer; log.scrollTop = log.scrollHeight; feedTTS(d.delta); }
          else if (d.error) { body.innerHTML = `<span class="asst-err">${esc(d.error)}</span>`; }
        }
      }
      if (sources && sources.length) bubble.appendChild(sourceEl(sources));
      ASSIST.history.push({ role: "assistant", content: answer, sources });
      flushTTS();
    } catch (e) {
      body.innerHTML = `<span class="asst-err">응답 실패: ${esc(e.message)}</span>`;
    } finally {
      ASSIST.busy = false; send.disabled = false;
      log.scrollTop = log.scrollHeight;
      if (convo) { if (!ttsQ.length && !ttsBusy && !speaking) listen(); }  // resume the turn
      else input.focus();
    }
  }
}

function appendBubble(log, role, text, sources) {
  const el = document.createElement("div");
  el.className = "asst-msg " + role;
  el.innerHTML = `<div class="asst-role">${role === "user" ? "나" : "비서"}</div><div class="asst-text"></div>`;
  el.querySelector(".asst-text").textContent = text;
  if (sources && sources.length) el.appendChild(sourceEl(sources));
  log.appendChild(el); log.scrollTop = log.scrollHeight;
  return el;
}

function sourceEl(sources) {
  const el = document.createElement("div");
  el.className = "asst-src";
  el.innerHTML = "출처 " + sources.map(s =>
    `<a href="#/knowledge/${encodeURIComponent(s.path)}" title="${esc(s.snippet || "")}">[${s.n}] ${esc(s.title)}</a>`
  ).join(" ");
  return el;
}

/* --------------------------------------------------------------- settings */
const SETTINGS_META = [
  ["임베딩 · 모델  ⟳ 저장 후 재시작 + 재색인 필요 (벡터 공간이 바뀝니다)", [
    ["provider", "프로바이더", "auto: 키 있으면 클라우드·없으면 로컬 / local: 로컬 임베딩(키 불필요) / gemini·openai: API 키 필요(.env) / ollama: 로컬 데몬", "select", ["auto", "local", "gemini", "openai", "ollama"]],
    ["local_embed_backend", "로컬 임베더", "auto: llama 설치 시 Harrier(1024d)·아니면 MiniLM(384d) / llamacpp: Harrier 고품질 (lemory[llama]) / fastembed: MiniLM 경량·전 OS", "select", ["auto", "llamacpp", "fastembed"]],
  ]],
  ["검색 품질", [
    ["graph_expansion", "그래프 확장", "위키링크·언급 그래프로 1-hop 확장해 멀티홉 질문에 답합니다", "bool"],
    ["event_log", "미들웨어 타임라인", "질의·AI 쓰기 기록 (이 기기 SQLite에만 저장, 외부 전송 없음)", "bool"],
    ["graph_alpha", "그래프 강도", "이웃 노트 점수 계수 — 높을수록 연결 노트가 잘 올라옵니다", "float"],
    ["graph_sim_floor", "그래프 유사도 하한", "질의와 이 유사도 미만인 이웃은 무시 (노이즈 차단)", "float"],
    ["title_boost", "제목 부스트", "질의가 노트 제목과 겹치면 가산점", "float"],
    ["per_doc_cap", "노트당 결과 상한", "한 노트가 결과를 독점하지 않게 다양성 확보", "int"],
    ["k_vector", "벡터 후보 수", "융합 전 벡터 검색이 뽑는 후보 개수", "int"],
    ["k_bm25", "BM25 후보 수", "융합 전 키워드 검색이 뽑는 후보 개수", "int"],
  ]],
  ["질의 처리", [
    ["typo_correction", "오타 보정", "볼트 어휘 기반 로컬 did-you-mean (API 호출 없음)", "bool"],
    ["query_expansion", "질의 확장", "LLM으로 질의 변형 생성 — 질의당 LLM 1회 소모", "bool"],
    ["rerank", "LLM 리랭크", "상위 후보를 LLM으로 재채점 — 정밀도↑ 지연↑", "bool"],
    ["recency_boost", "최신성 부스트", "시간성 질의(\"지난주 회의\")에서 최근 노트 가중", "float"],
    ["recency_half_life_days", "최신성 반감기(일)", "최신성 가중치가 절반이 되는 기간", "float"],
  ]],
  ["답변 생성", [
    ["context_style", "컨텍스트 스타일", "full: 청크 원문 그대로 / compact: 팩트시트 압축", "select", ["full", "compact"]],
    ["context_order", "증거 배열 순서", "rank: 검색 점수순(기본) / curriculum: CDS식 매끄러운 궤적 순 — 실험적, KorQuAD A/B에서 이득 없음", "select", ["rank", "curriculum"]],
  ]],
  ["색인", [
    ["mention_links", "언급 링크", "위키링크가 없어도 제목 언급을 그래프 간선으로", "bool"],
    ["enrich_entities", "LLM 개체 추출", "cognee식 개체 그래프 보강 — LLM 쿼터 소모", "bool"],
    ["chunk_chars", "청크 크기(자)", "재색인 후 적용", "int"],
    ["chunk_overlap", "청크 겹침(자)", "재색인 후 적용", "int"],
  ]],
];

async function renderSettings() {
  const m = $("#main");
  m.innerHTML = `<div class="view"><div class="view-head">
    <div class="view-title">설정</div>
    <div class="view-sub">변경은 즉시 적용되고 볼트의 lemory.toml에 저장됩니다</div></div>
    <div class="set-grid" id="setGrid"></div>
    <div class="savebar" id="savebar">
      <span class="msg" id="saveMsg"></span><span class="spacer"></span>
      <button class="btn ghost" id="btnRevert">되돌리기</button>
      <button class="btn primary" id="btnSave">변경사항 저장</button>
    </div>
  </div>`;

  let cfg;
  try { cfg = await api("/api/config"); }
  catch (e) { $("#setGrid").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }

  const orig = { ...cfg.tunable };
  const cur = { ...cfg.tunable };

  const grid = $("#setGrid");
  let html = "";
  for (const [section, rows] of SETTINGS_META) {
    html += `<div class="card"><div class="card-head">${section}</div>`;
    for (const [key, name, desc, type, options] of rows) {
      const v = cur[key];
      let ctl;
      if (type === "bool") ctl = `<span class="switch ${v ? "on" : ""}" data-key="${key}"></span>`;
      else if (type === "select") ctl = `<select data-key="${key}">${options.map(o =>
        `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select>`;
      else ctl = `<input type="number" data-key="${key}" value="${v}" step="${type === "float" ? "0.05" : "1"}">`;
      html += `<div class="set-row"><div class="set-info">
        <div class="set-name">${name} <span style="color:var(--text-3);font-size:11px;font-family:ui-monospace,monospace">${key}</span></div>
        <div class="set-desc">${desc}</div></div><div class="set-ctl">${ctl}</div></div>`;
    }
    html += `</div>`;
  }
  html += `<div class="card"><div class="card-head">읽기 전용 — 변경은 .env / lemory.toml 수정 후 재시작</div><div class="kv">${
    Object.entries(cfg.readonly).map(([k, v]) =>
      `<div class="kv-row"><span class="kv-k">${esc(k)}</span><span class="kv-v mono">${esc(v ?? "—")}</span></div>`).join("")
  }</div></div>`;
  grid.innerHTML = html;

  const dirty = () => Object.keys(cur).filter(k => String(cur[k]) !== String(orig[k]));
  const syncBar = () => {
    const d = dirty();
    $("#savebar").classList.toggle("show", d.length > 0);
    $("#saveMsg").textContent = d.length ? `${d.length}개 설정 변경됨: ${d.join(", ")}` : "";
  };

  $$(".switch[data-key]", grid).forEach(sw => sw.onclick = () => {
    cur[sw.dataset.key] = !cur[sw.dataset.key];
    sw.classList.toggle("on", cur[sw.dataset.key]);
    syncBar();
  });
  $$("input[data-key], select[data-key]", grid).forEach(el => el.onchange = () => {
    cur[el.dataset.key] = el.type === "number" ? +el.value : el.value;
    syncBar();
  });

  $("#btnRevert").onclick = () => renderSettings();
  $("#btnSave").onclick = async () => {
    const patch = Object.fromEntries(dirty().map(k => [k, cur[k]]));
    try {
      await jpost("/api/config", patch, "PATCH");
      toast("저장됨 — 볼트의 lemory.toml에 기록했습니다", "ok");
      renderSettings();
    } catch (e) { toast(`저장 실패: ${e.message}`, "err"); }
  };
}

/* ---------------------------------------------------------------- palette */
const PAL_VIEWS = [
  ["overview", "현황으로 이동", icoHome],
  ["knowledge", "지식으로 이동", icoFolder],
  ["search", "검색으로 이동", icoSearch],
  ["settings", "설정으로 이동", icoGear],
];
let palSel = 0, palItems = [];

function openPalette() {
  $("#palette").hidden = false;
  const inp = $("#paletteInput");
  inp.value = ""; palSel = 0;
  drawPalette("");
  inp.focus();
}
function closePalette() { $("#palette").hidden = true; }

async function drawPalette(q) {
  q = q.trim().toLowerCase();
  palItems = [];
  for (const [view, label, ico] of PAL_VIEWS)
    if (!q || label.toLowerCase().includes(q))
      palItems.push({ label, ico, sub: "메뉴", act: () => go("#/" + view) });
  try {
    const notes = await loadNotes();
    const matches = q
      ? notes.filter(n => n.title.toLowerCase().includes(q) || n.path.toLowerCase().includes(q))
      : [...notes].sort((a, b) => b.mtime - a.mtime);
    for (const n of matches.slice(0, 9))
      palItems.push({
        label: n.title, ico: icoDoc, sub: n.path,
        act: () => go("#/knowledge/" + encodeURIComponent(n.path)),
      });
  } catch { /* server down — views only */ }

  palSel = Math.min(palSel, Math.max(0, palItems.length - 1));
  $("#paletteResults").innerHTML = palItems.length ? palItems.map((it, i) => `
    <div class="pal-item ${i === palSel ? "sel" : ""}" data-i="${i}">
      ${it.ico()}<span>${esc(it.label)}</span><span class="sub">${esc(it.sub)}</span></div>`).join("")
    : `<div class="pal-empty">결과 없음</div>`;
  $$(".pal-item").forEach(el => {
    el.onclick = () => { closePalette(); palItems[+el.dataset.i].act(); };
    el.onmousemove = () => { palSel = +el.dataset.i; markPal(); };
  });
}
function markPal() {
  $$(".pal-item").forEach((el, i) => el.classList.toggle("sel", i === palSel));
}

$("#paletteInput").addEventListener("input", e => drawPalette(e.target.value));
$("#paletteInput").addEventListener("keydown", e => {
  if (e.key === "ArrowDown") { e.preventDefault(); palSel = Math.min(palSel + 1, palItems.length - 1); markPal(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); palSel = Math.max(palSel - 1, 0); markPal(); }
  else if (e.key === "Enter" && palItems[palSel]) { closePalette(); palItems[palSel].act(); }
  else if (e.key === "Escape") closePalette();
});
$("#palette").addEventListener("mousedown", e => { if (e.target === $("#palette")) closePalette(); });
$("#paletteHint").onclick = openPalette;

document.addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#palette").hidden ? openPalette() : closePalette(); }
  else if (e.key === "Escape" && !$("#palette").hidden) closePalette();
  else if (e.key === "/" && !e.metaKey && !e.ctrlKey && document.activeElement.tagName !== "INPUT"
           && document.activeElement.tagName !== "SELECT") { e.preventDefault(); go("#/search"); }
});

/* ------------------------------------------------------- local ego graph */
// Obsidian's global graph is decoration; this is the RETRIEVAL graph — the
// edges (incl. unlinked mentions Obsidian can't see) that expansion walks.
function localGraphSVG(d) {
  // merge by note: the same neighbor can be both an out-link and a backlink
  const byPath = new Map();
  for (const l of d.links_out) byPath.set(l.path, { ...l, out: true, in: false });
  for (const l of d.links_in) {
    const e = byPath.get(l.path);
    if (e) { e.in = true; if (e.kind === "mention" && l.kind === "wiki") e.kind = "wiki"; }
    else byPath.set(l.path, { ...l, out: false, in: true });
  }
  const nbrs = [...byPath.values()].slice(0, 14).map(l => ({ ...l, dir: l.in ? "in" : "out" }));
  if (!nbrs.length) return "";
  const W = 560, H = Math.max(200, 60 + nbrs.length * 16), cx = W / 2, cy = H / 2;
  const R = Math.min(cx - 130, cy - 26);
  const kindColor = { wiki: "#7ea6ff", mention: "#c6a5ff", entity: "#7fd8c3" };
  let nodes = "", edges = "";
  nbrs.forEach((l, i) => {
    const ang = (2 * Math.PI * i) / nbrs.length - Math.PI / 2;
    const x = cx + R * Math.cos(ang), y = cy + R * Math.sin(ang);
    const col = kindColor[l.kind] || "#8a8f98";
    const dash = l.kind === "mention" ? 'stroke-dasharray="4 3"' : "";
    edges += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${col}" stroke-opacity="0.45" stroke-width="1.2" ${dash}/>`;
    if (l.dir === "in") {
      const mx = cx + (x - cx) * 0.28, my = cy + (y - cy) * 0.28;
      const a2 = Math.atan2(cy - y, cx - x);
      edges += `<path d="M ${mx} ${my} l ${8*Math.cos(a2+2.6)} ${8*Math.sin(a2+2.6)} M ${mx} ${my} l ${8*Math.cos(a2-2.6)} ${8*Math.sin(a2-2.6)}" stroke="${col}" stroke-opacity="0.6" stroke-width="1.2" fill="none"/>`;
    }
    const anchor = x < cx - 10 ? "end" : x > cx + 10 ? "start" : "middle";
    const tx = x + (anchor === "end" ? -8 : anchor === "start" ? 8 : 0);
    const ty = y + (Math.abs(x - cx) <= 10 ? (y < cy ? -10 : 16) : 4);
    nodes += `<g class="lg-node" data-goto="${esc(l.path)}" style="cursor:pointer">
      <circle cx="${x}" cy="${y}" r="5" fill="${col}"/>
      <text x="${tx}" y="${ty}" text-anchor="${anchor}" fill="var(--text-2)" font-size="11">${esc(l.title.length > 24 ? l.title.slice(0, 23) + "…" : l.title)}</text>
    </g>`;
  });
  const center = `<circle cx="${cx}" cy="${cy}" r="7" fill="var(--brand)"/>
    <text x="${cx}" y="${cy - 14}" text-anchor="middle" fill="var(--text)" font-size="12" font-weight="600">${esc(d.title.length > 30 ? d.title.slice(0, 29) + "…" : d.title)}</text>`;
  return `<div class="nd-sec"><div class="nd-sec-title">로컬 그래프 · 검색이 실제로 걷는 간선</div>
    <div class="local-graph card" style="padding:6px">
      <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}">${edges}${center}${nodes}</svg>
      <div class="lg-legend"><span style="color:#7ea6ff">— 위키링크</span>
        <span style="color:#c6a5ff">┄ 언급(옵시디언엔 없음)</span>
        <span style="color:#7fd8c3">— 개체</span>
        <span style="color:var(--text-3)">화살표 = 들어오는 링크</span></div>
    </div></div>`;
}

/* ------------------------------------------------------------------ icons */
function svg(d, extra = "") {
  return `<svg viewBox="0 0 16 16" ${extra} style="width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round">${d}</svg>`;
}
function icoHome() { return svg('<path d="M2 8.5 8 2.5l6 6M3.5 7.5v6h9v-6"/>'); }
function icoFolder() { return svg('<path d="M1.8 4.2a1 1 0 0 1 1-1h3l1.4 1.6h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H2.8a1 1 0 0 1-1-1z"/>'); }
function icoDoc() { return svg('<path d="M4 1.8h5.5L12.5 5v9.2h-8.5zM9.2 1.8V5h3.3M6 8h4M6 10.5h4"/>'); }
function icoTag() { return svg('<path d="M2 2h5.5L14 8.5 8.5 14 2 7.5zM5.5 5.5h.01"/>'); }
function icoSearch() { return svg('<circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3 3"/>'); }
function icoGear() { return svg('<circle cx="8" cy="8" r="2.2"/><path d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2M3.6 3.6 5 5M11 11l1.4 1.4M12.4 3.6 11 5M5 11l-1.4 1.4"/>'); }
function icoExt() { return svg('<path d="M6.5 3.5H3v9.5h9.5V9M9 2.5h4.5V7M13 3 7.5 8.5"/>'); }
function icoChev() { return svg('<path d="m6 3.5 4.5 4.5L6 12.5"/>'); }
function icoRefresh(cls = "") { return svg('<path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 1.8v2.7h-2.7"/>', `class="${cls}"`); }

/* ------------------------------------------------------------------- boot */
async function boot() {
  nav();
  // sidebar vault name + watcher dot even when landing on a non-overview view
  try {
    const o = await api("/api/overview");
    S.overview = o; S.vaultPath = o.vault;
    $("#vaultName").textContent = (o.vault || "").split("/").filter(Boolean).pop() || "볼트 미설정";
    setWatch(o.watcher_alive);
  } catch { $("#watchLabel").textContent = "서버 연결 안 됨"; }
  setInterval(async () => {
    try { const o = await api("/api/overview"); setWatch(o.watcher_alive); S.overview = o; }
    catch { $("#watchDot").className = "dot"; $("#watchLabel").textContent = "서버 연결 안 됨"; }
  }, 30000);
}
boot();
