/* Lemory console · vanilla JS SPA, no build step, no external deps. */
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
  if (!ts) return "-";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "방금 전";
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}일 전`;
  return new Date(ts * 1000).toLocaleDateString("ko-KR");
}
const shortPath = p => {
  if (!p) return "-";
  const home = (p.match(/^(\/(?:home|Users)\/[^/]+)/) || [])[1];
  let s = home ? "~" + p.slice(home.length) : p;
  if (s.length > 52) s = s.slice(0, 22) + "…" + s.slice(-27);
  return s;
};
const fmtBytes = b => b > 1048576 ? (b / 1048576).toFixed(1) + " MB"
  : b > 1024 ? (b / 1024).toFixed(0) + " KB" : b + " B";
const fmtN = n => (n ?? 0).toLocaleString("ko-KR");
// headings are stored as "Note Title > Section" breadcrumbs; showing the
// title twice next to the note name reads as noise · strip the prefix
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
  memory: { q: "", type: "", sel: null },
  search: { q: "", mode: "hybrid", graph: true, k: 8 },
};

async function loadNotes(force = false) {
  if (!S.notes || force) S.notes = await api("/api/notes");
  return S.notes;
}



/* -------------------------------------------------- global shortcuts (사용성) */
// One data table drives BOTH the key handler and the ? help overlay ·
// Tolaria's command-manifest pattern, console-sized. mod = ⌘ on mac, Ctrl elsewhere.
const SHORTCUTS = [
  { combo: "mod+K", disp: "⌘K", desc: "명령 팔레트 · 이동/검색", act: () => openPalette() },
  { combo: "mod+N", disp: "⌘N", desc: "새 노트 (제목은 나중에 바꿔도 됨)", act: () => {
      const t = new Date().toTimeString().slice(0, 8).replaceAll(":", "");
      createNoteFromPalette(`무제 ${t}`);
    } },
  ...["overview", "knowledge", "memory", "graph", "health", "search", "assistant", "settings"]
    .map((v, i) => ({ combo: `mod+${i + 1}`, disp: `⌘${i + 1}`,
                      desc: `${["현황","지식","기억","그래프","건강","검색","비서","설정"][i]} 뷰`,
                      act: () => go("#/" + v) })),
  { combo: "?", disp: "?", desc: "단축키 도움말", act: () => toggleShortcutHelp() },
  { combo: "j/k · ↑/↓", disp: "↑↓", desc: "지식 목록에서 노트 이동 (Enter로 열기)", help_only: true },
];

function toggleShortcutHelp() {
  const cur = $("#shortcutHelp");
  if (cur) { cur.remove(); return; }
  const el = document.createElement("div");
  el.id = "shortcutHelp";
  el.className = "sc-overlay";
  el.innerHTML = `<div class="sc-card">
    <div class="sc-title">단축키 <span class="view-sub" style="display:inline">? 또는 Esc로 닫기</span></div>
    ${SHORTCUTS.map(sc => `<div class="sc-row"><span class="sc-key">${esc(sc.disp)}</span>
      <span>${esc(sc.desc)}</span></div>`).join("")}
  </div>`;
  el.onclick = e => { if (e.target === el) el.remove(); };
  document.body.appendChild(el);
}

function inTextField(t) {
  return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
}

document.addEventListener("keydown", e => {
  const mod = e.metaKey || e.ctrlKey;
  if (e.key === "Escape") {
    const h = $("#shortcutHelp");
    if (h) { h.remove(); return; }
  }
  // bare-key shortcuts stay out of text fields; ⌘-combos work everywhere
  if (!mod && inTextField(e.target)) return;
  if (mod) {
    for (const sc of SHORTCUTS) {
      if (sc.help_only || !sc.combo.startsWith("mod+")) continue;
      const key = sc.combo.slice(4).toLowerCase();
      if (e.key.toLowerCase() === key) { e.preventDefault(); sc.act(); return; }
    }
    return;
  }
  if (e.key === "?") { e.preventDefault(); toggleShortcutHelp(); return; }
  // knowledge-list keyboard navigation (visible rows, wraps at the ends)
  if (location.hash.startsWith("#/knowledge") || location.hash === "" ) {
    const K = S.knowledge;
    if (!K.rows || !K.rows.length) return;
    const move = { ArrowDown: 1, j: 1, ArrowUp: -1, k: -1 }[e.key];
    if (move !== undefined) {
      e.preventDefault();
      const i = Math.max(0, K.rows.indexOf(K.sel));
      const next = K.rows[(i + move + K.rows.length) % K.rows.length];
      K.sel = next;
      drawNoteRows();
      const row = $(`.note-row[data-path="${CSS.escape(next)}"]`);
      if (row) row.scrollIntoView({ block: "nearest" });
      return;
    }
    if (e.key === "Enter" && K.sel) { e.preventDefault(); drawNoteDetail(K.sel); }
  }
});
window.addEventListener("beforeunload", () => {
  if (window.__edFlush) window.__edFlush();
});

/* ------------------------------------------------------------------- theme */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("lemory-theme", t);
  const b = $("#themeBtn");
  if (b) b.textContent = t === "light" ? "🌙" : "☀️";
}
function initTheme() {
  applyTheme(localStorage.getItem("lemory-theme") || "dark");
  const b = $("#themeBtn");
  if (b) b.onclick = () =>
    applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
}

/* ----------------------------------------------------------------- router */
const routes = {
  overview: renderOverview,
  knowledge: renderKnowledge,
  memory: renderMemory,
  graph: renderGraph,
  health: renderHealth,
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
// async fills write through put(): navigating away mid-fetch must be a
// no-op, not a null-crash (the tour that found this hit 4 of them)
const put = (sel, html) => { const el = $(sel); if (el) el.innerHTML = html; };

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
        <div class="card" id="memFeedCard" hidden><div class="card-head">AI 메모리 피드 <span style="font-weight:400;color:var(--text-3)">AI가 볼트에 적은 것 · 전부 마크다운 파일</span></div><div class="act-list" id="memFeed"></div></div>
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
    m.querySelector(".view").innerHTML += `<div class="empty">서버에 연결할 수 없습니다 · ${esc(e.message)}</div>`;
    return;
  }
  S.overview = o;
  S.vaultPath = o.vault;
  $("#vaultName").textContent = (o.vault || "").split("/").filter(Boolean).pop() || "볼트 미설정";
  setWatch(o.watcher_alive);
  $("#ovSub").textContent = o.last_sync ? `마지막 동기화 ${rel(+o.last_sync)}` : "";

  put("#tiles", [
    { n: fmtN(o.documents), l: "노트", s: `${fmtN(o.tags)}개 태그` },
    { n: fmtN(o.chunks), l: "청크", s: `임베딩 캐시 ${fmtN(o.cached_embeddings)}` },
    { n: fmtN(o.links), l: "그래프 링크", s: o.graph_expansion ? "그래프 확장 켜짐" : "그래프 확장 꺼짐" },
    { n: fmtBytes(o.db_bytes), l: "저장소", s: "SQLite 단일 파일" },
  ].map(t => `<div class="tile"><div class="num">${t.n}</div><div class="lbl">${t.l}</div><div class="sub">${esc(t.s)}</div></div>`).join(""));

  put("#acts", o.activity.length ? o.activity.map(a => `
    <div class="act-row">
      <span class="act-kind ${a.kind}">${{ startup: "시작", watch: "자동", manual: "수동" }[a.kind] || a.kind}</span>
      <span class="act-delta">+${a.added} ~${a.updated} −${a.removed}</span>
      <span class="act-delta" style="color:var(--text-3)">${a.chunks}청크 · ${a.embedded}임베딩 · ${a.seconds}s</span>
      <span class="act-time" title="${new Date(a.ts * 1000).toLocaleString("ko-KR")}">${rel(a.ts)}</span>
    </div>`).join("")
    : `<div class="empty">아직 색인 활동이 없습니다</div>`);

  // middleware timeline: AI writes (with undo), queries, per-client stats
  api("/api/events?limit=80").then(evts => {
    const clientChip = c => c ? `<span class="chip">${esc(c)}</span>` : "";
    const writes = evts.filter(e => e.kind === "memory" || e.kind === "append").slice(0, 6);
    if (writes.length) {
      $("#memFeedCard").hidden = false;
      put("#memFeed", writes.map(e => `
        <div class="act-row">
          <span class="act-kind ${e.kind === "memory" ? "manual" : "watch"}">${e.kind === "memory" ? "새 기억" : "덧붙임"}</span>
          <span style="font-weight:550;cursor:pointer" data-goto-note="${esc(e.path)}">${esc((e.detail && e.detail.title) || e.path)}</span>
          ${clientChip(e.client)}
          ${e.kind === "memory" ? `<button class="btn ghost" style="height:22px;padding:0 8px;font-size:11px" data-trash="${esc(e.path)}">휴지통</button>` : ""}
          <span class="act-time">${rel(e.ts)}</span>
        </div>`).join(""));
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
      put("#qlog", queries.map(e => `
        <div class="act-row">
          <span class="act-kind ${e.kind === "ask" ? "manual" : "startup"}">${e.kind === "ask" ? "질문" : "검색"}</span>
          <span style="font-weight:550;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:280px" title="${esc(e.query || "")}">${esc(e.query || "")}</span>
          ${clientChip(e.client)}
          <span class="act-time">${rel(e.ts)}</span>
        </div>`).join(""));
    }
  }).catch(() => {});
  api("/api/clients").then(rows => {
    if (!rows.length) return;
    $("#clientsCard").hidden = false;
    put("#clients", rows.map(r => `
      <div class="act-row">
        <span style="font-weight:550">${esc(r.client)}</span>
        <span class="act-delta">질의 ${r.queries || 0} · 쓰기 ${r.writes || 0}</span>
        <span class="act-time">${rel(r.last)}</span>
      </div>`).join(""));
  }).catch(() => {});

  loadNotes().then(notes => {
    const hot = [...notes].filter(n => n.hits > 0).sort((a, b) => b.hits - a.hits).slice(0, 6);
    if (hot.length) {
      $("#hotCard").hidden = false;
      put("#hot", hot.map(n => `
        <div class="act-row" style="cursor:pointer" data-path="${esc(n.path)}">
          <span style="font-weight:550">${esc(n.title)}</span>
          <span class="chip brand">🔥 ${n.hits}</span>
          <span class="act-time">${rel(n.last_hit)}</span>
        </div>`).join(""));
      $$("#hot .act-row").forEach(r =>
        r.onclick = () => go("#/knowledge/" + encodeURIComponent(r.dataset.path)));
    }
    const rec = [...notes].sort((a, b) => b.mtime - a.mtime).slice(0, 6);
    put("#recent", rec.length ? rec.map(n => `
      <div class="act-row" style="cursor:pointer" data-path="${esc(n.path)}">
        <span style="font-weight:550">${esc(n.title)}</span>
        ${n.tags.slice(0, 2).map(t => `<span class="chip">#${esc(t)}</span>`).join("")}
        <span class="act-time">${rel(n.mtime)}</span>
      </div>`).join("") : `<div class="empty">노트가 없습니다</div>`);
    $$("#recent .act-row").forEach(r =>
      r.onclick = () => go("#/knowledge/" + encodeURIComponent(r.dataset.path)));
  }).catch(() => {});

  put("#sys", [
    ["프로바이더", esc(o.provider || "-")],
    ["LLM", esc(o.llm_model || "-")],
    ["임베딩", esc(o.embed_model || "-")],
    ["벡터 인덱스", o.vector_index === "ivf-int8"
      ? 'IVF-int8 <span style="color:var(--text-3)">(대규모 자동 전환)</span>'
      : '정확 검색 <span style="color:var(--text-3)">(소규모 볼트 기본)</span>'],
    ["볼트", `<span class="kv-v mono" title="${esc(o.vault || "")}">${esc(shortPath(o.vault))}</span>`],
    ["DB", `<span class="kv-v mono" title="${esc(o.db || "")}">${esc(shortPath(o.db))}</span>`],
    ["볼트 감시", o.watcher_alive ? '<span style="color:var(--ok)">실시간 동기화 중</span>' : '<span style="color:var(--warn)">꺼짐</span>'],
    ["업타임", uptime(o.uptime_s)],
  ].map(([k, v]) => `<div class="kv-row"><span class="kv-k">${k}</span><span class="kv-v">${v}</span></div>`).join(""));
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
        + (plan.rate_measured ? "" : " (기본값 추정 · 첫 실행 후 실측치로 보정됩니다)");
      if (full && !confirm(`전체 재색인을 실행할까요?\n\n${msg}`)) {
        btn.disabled = false; btn.innerHTML = orig; return;
      }
      if (plan.embeds_needed > 0) toast(`색인 시작 · ${plan.eta} 예상`, "");
    }
  } catch { /* plan is best-effort; indexing proceeds regardless */ }
  btn.innerHTML = `${icoRefresh("spin-ico")} 색인 중…`;
  try {
    const r = await jpost("/index", { full });
    toast(`색인 완료 · +${r.added} ~${r.updated} −${r.removed} (${r.seconds.toFixed(1)}s)`, "ok");
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
        <button class="icon-btn" id="newNote" title="새 노트 (⌘N)${K.folder ? " · " + esc(K.folder) + "에" : ""}">${icoPlus()}</button>
      </div>
      <div class="note-rows" id="noteRows"></div>
    </div>
    <div class="kn-pane detail-pane" id="notePane">
      <div class="empty">${icoDoc()} 노트를 선택하세요<span class="empty-hint">↑ ↓ 이동 · Enter 열기</span></div>
    </div>
  </div></div>`;

  $("#noteSort").value = K.sort;
  $("#noteFilter").oninput = e => { K.filter = e.target.value; drawNoteRows(); };
  $("#noteSort").onchange = e => { K.sort = e.target.value; drawNoteRows(); };
  // new note lands in the folder you're browsing · zero-friction capture
  $("#newNote").onclick = () => newNoteHere(K.folder);

  try { await loadNotes(); } catch (e) {
    $("#noteRows").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }
  if (!S.tags) { try { S.tags = await api("/api/tags"); } catch { S.tags = []; } }

  drawTree();
  drawNoteRows();
  if (K.sel) drawNoteDetail(K.sel);
}

async function newNoteHere(folder) {
  const title = prompt(folder ? `새 노트 제목 (${folder}에 생성):` : "새 노트 제목:");
  if (!title || !title.trim()) return;
  const path = (folder ? folder + "/" : "") + title.trim();
  try {
    const r = await api("/api/note", { method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content: `# ${title.trim()}\n\n` }) });
    S.notes = null; S.titles = null;
    S.knowledge.tab = "edit";
    await renderKnowledge(r.saved);
    toast(`'${title.trim()}' 생성`, "ok");
  } catch (e) { toast(e.message, "err"); }
}

async function deleteNote(path) {
  if (!confirm(`'${path}' 을 휴지통으로 옮길까요?\n(.trash에서 복구 가능)`)) return;
  try {
    await api("/api/note/delete", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }) });
    S.notes = null; S.titles = null;
    if (S.knowledge.sel === path) S.knowledge.sel = null;
    await renderKnowledge();
    toast("휴지통으로 이동", "ok");
  } catch (e) { toast(e.message, "err"); }
}

async function renameNote(path) {
  const next = prompt("새 경로/제목:", path.replace(/\.md$/, ""));
  if (!next || !next.trim() || next.trim() === path.replace(/\.md$/, "")) return;
  try {
    const r = await api("/api/note/rename", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ src: path, dst: next.trim() }) });
    S.notes = null; S.titles = null;
    await renderKnowledge(r.renamed);
    toast("이름 변경", "ok");
  } catch (e) { toast(e.message, "err"); }
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
  K.rows = rows.map(n => n.path);   // keyboard nav operates on what's visible

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


/* ------------------------------------------------- markdown renderer (본문) */
// Small, self-contained renderer · no CDN (the console must work offline).
// Covers the markdown a vault actually uses; anything exotic degrades to
// escaped text, never to broken HTML.
function mdRender(src) {
  const wiki = t => t.replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]/g,
    (_, target, label) => `<a class="md-wiki" data-wiki="${esc(target.trim())}">${esc(label || target)}</a>`);
  const inline = t => {
    t = esc(t);
    t = t.replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`);
    t = wiki(t);
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
    t = t.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
    t = t.replace(/==([^=]+)==/g, "<mark>$1</mark>");
    return t;
  };
  const lines = src.replace(/\r/g, "").split("\n");
  // frontmatter: render as a folded meta block, not as body text
  let i = 0, fm = null;
  if (lines[0] === "---") {
    const end = lines.indexOf("---", 1);
    if (end > 0) { fm = lines.slice(1, end); i = end + 1; }
  }
  const out = [];
  if (fm && fm.length)
    out.push(`<details class="md-fm"><summary>frontmatter</summary><pre>${esc(fm.join("\n"))}</pre></details>`);
  let list = null, quote = false;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const closeQuote = () => { if (quote) { out.push("</blockquote>"); quote = false; } };
  while (i < lines.length) {
    const ln = lines[i];
    if (/^```/.test(ln)) {                       // fenced code
      closeList(); closeQuote();
      const buf = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(`<pre class="md-code"><code>${esc(buf.join("\n"))}</code></pre>`);
      continue;
    }
    const h = ln.match(/^(#{1,6})\s+(.*)$/);
    if (h) { closeList(); closeQuote();
      out.push(`<h${h[1].length + 1}>${inline(h[2])}</h${h[1].length + 1}>`); i++; continue; }
    if (/^\s*([-*+]|\d+\.)\s+/.test(ln)) {
      closeQuote();
      const ordered = /^\s*\d+\./.test(ln);
      const kind = ordered ? "ol" : "ul";
      if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
      const item = ln.replace(/^\s*([-*+]|\d+\.)\s+/, "");
      const task = item.match(/^\[([ xX])\]\s+(.*)$/);
      out.push(task
        ? `<li class="md-task"><input type="checkbox" disabled ${task[1] !== " " ? "checked" : ""}>${inline(task[2])}</li>`
        : `<li>${inline(item)}</li>`);
      i++; continue;
    }
    if (/^>\s?/.test(ln)) { closeList();
      if (!quote) { out.push("<blockquote>"); quote = true; }
      out.push(`<p>${inline(ln.replace(/^>\s?/, ""))}</p>`); i++; continue; }
    if (/^\s*(---|\*\*\*)\s*$/.test(ln)) { closeList(); closeQuote(); out.push("<hr>"); i++; continue; }
    if (/^\|.*\|\s*$/.test(ln)) {              // simple table
      closeList(); closeQuote();
      const rows = [];
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      const cells = r => r.replace(/^\||\|$/g, "").split("|").map(c => inline(c.trim()));
      const body = rows.filter(r => !/^\|[\s:|-]+\|$/.test(r));
      out.push('<div class="md-table"><table>' + body.map((r, ri) =>
        `<tr>${cells(r).map(c => ri === 0 ? `<th>${c}</th>` : `<td>${c}</td>`).join("")}</tr>`).join("") + "</table></div>");
      continue;
    }
    if (!ln.trim()) { closeList(); closeQuote(); i++; continue; }
    closeList(); closeQuote();
    out.push(`<p>${inline(ln)}</p>`); i++;
  }
  closeList(); closeQuote();
  return out.join("\n");
}

async function drawNoteDetail(path) {
  if (window.__edFlush) { window.__edFlush(); window.__edFlush = null; }
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

  const tab = S.knowledge.tab || "read";
  pane.innerHTML = `<div class="note-detail">
    <div class="nd-title">${esc(d.title)}</div>
    <div class="nd-path">${esc(d.path)}
      <span class="spacer"></span>
      <button class="icon-btn sm" id="ndRename" title="이름 변경">${icoRename()}</button>
      <button class="icon-btn sm" id="ndDelete" title="휴지통으로">${icoTrash()}</button>
      <a class="btn ghost" style="height:24px;padding:0 8px;font-size:11.5px" href="${obsidian}">${icoExt()} Obsidian에서 열기</a>
    </div>
    ${d.tags.length ? `<div class="nd-tags">${d.tags.map(t => `<span class="chip brand">#${esc(t)}</span>`).join("")}</div>` : ""}
    <div class="nd-meta">
      <span>수정 ${rel(d.mtime)}</span><span>색인 ${rel(d.indexed_at)}</span>
      <span>청크 ${d.chunks.length}</span>
      <span title="이 노트가 검색·질문 결과에 오른 횟수">참조 ${d.hits || 0}회${d.hits ? " · 마지막 " + rel(d.last_hit) : ""}</span>
    </div>
    <div class="seg nd-tabs" id="ndTabs">
      <button data-v="read">본문</button><button data-v="edit">편집</button><button data-v="meta">연결 · 색인</button>
    </div>
    <div id="ndBody"><div class="skel" style="height:80px"></div></div>
  </div>`;

  const paneMeta = `
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
        ${c.text.length > 400 ? `<div class="more">더 보기</div>` : ""}</div>`).join("")}</div>`;

  async function showTab(name) {
    if (window.__edFlush && S.knowledge.tab === "edit" && name !== "edit") {
      try { await window.__edFlush(); } catch { /* keepalive still delivered */ }
      window.__edFlush = null;
    }
    S.knowledge.tab = name;
    // edit mode is a writing surface · give it room by folding the tree+list
    // (a click on 본문/연결 brings them back). Without this the preview column
    // is ~230px and CJK wraps to one glyph per line · unreadable.
    const kn = $("#kn");
    if (kn) kn.classList.toggle("editing", name === "edit");
    $$("#ndTabs button", pane).forEach(b => b.classList.toggle("active", b.dataset.v === name));
    const body = $("#ndBody", pane);
    if (name === "meta") {
      body.innerHTML = paneMeta;
      wireMeta();
      return;
    }
    let raw;
    try { raw = await api("/api/raw?path=" + encodeURIComponent(path)); }
    catch (e) { body.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
    if (name === "read") {
      body.innerHTML = `<div class="md-body">${mdRender(raw.content)}</div>`;
      $$(".md-wiki", body).forEach(a => a.onclick = () => openByTitle(a.dataset.wiki));
      return;
    }
    // 편집: dirty tracking + ⌘S + optimistic concurrency + live preview +
    // [[wikilink]] autocomplete. A real authoring surface, not a text box.
    const split = S.knowledge.preview ?? true;
    body.innerHTML = `
      <div class="ed-bar">
        <span class="ed-state" id="edState">저장됨</span><span class="spacer"></span>
        <span class="switch-lbl">미리보기</span>
        <span class="switch sm ${split ? "on" : ""}" id="edPrev" title="편집·미리보기 나란히"></span>
        <button class="btn primary" id="edSave" disabled>저장 <span class="kbd">⌘S</span></button>
      </div>
      <div class="ed-split ${split ? "" : "solo"}" id="edSplit">
        <div class="ed-col"><textarea class="ed-area" id="edArea" spellcheck="false"></textarea></div>
        <div class="ed-col ed-preview md-body" id="edPreview"></div>
      </div>
      <div class="wl-menu" id="wlMenu" hidden></div>`;
    const area = $("#edArea", body), btn = $("#edSave", body), st = $("#edState", body);
    const preview = $("#edPreview", body);
    area.value = raw.content;
    let mtime = raw.mtime, dirty = false, autoTimer = null;
    const renderPreview = () => { preview.innerHTML = mdRender(area.value);
      $$(".md-wiki", preview).forEach(a => a.onclick = () => openByTitle(a.dataset.wiki)); };
    renderPreview();
    $("#edPrev", body).onclick = e => {
      const on = !e.target.classList.contains("on");
      e.target.classList.toggle("on", on);
      $("#edSplit", body).classList.toggle("solo", !on);
      S.knowledge.preview = on;
    };
    const mark = v => { dirty = v; btn.disabled = !v;
      st.textContent = v ? "수정됨 · 1.5초 뒤 자동 저장" : "저장됨";
      st.classList.toggle("dirty", v); };
    area.oninput = () => {                 // Tolaria-style autosave debounce
      mark(true);
      renderPreview();
      wlAuto();
      clearTimeout(autoTimer);
      autoTimer = setTimeout(() => save(true), 1500);
    };

    // ---- [[wikilink]] autocomplete: type '[[' and pick a note by title
    const wl = $("#wlMenu", body);
    let wlItems = [], wlSel = 0, wlStart = -1;
    async function wlAuto() {
      const c = area.value, p = area.selectionStart;
      const open = c.lastIndexOf("[[", p - 1);
      if (open < 0 || c.slice(open, p).includes("]]") || c.slice(open, p).includes("\n")) {
        wl.hidden = true; wlStart = -1; return;
      }
      wlStart = open;
      const q = c.slice(open + 2, p).toLowerCase();
      if (!S.titles) { try { S.titles = (await api("/api/titles")).titles; } catch { S.titles = []; } }
      wlItems = S.titles.filter(t => t.title.toLowerCase().includes(q)).slice(0, 8);
      if (!wlItems.length) { wl.hidden = true; return; }
      wlSel = 0;
      wl.innerHTML = wlItems.map((t, i) =>
        `<div class="wl-item ${i === 0 ? "sel" : ""}" data-i="${i}">${esc(t.title)}</div>`).join("");
      // position under the caret line (approximate · good enough, no lib)
      const rect = area.getBoundingClientRect(), lh = 22;
      const line = c.slice(0, p).split("\n").length;
      wl.style.left = rect.left + 14 + "px";
      wl.style.top = Math.min(rect.top + line * lh, rect.bottom - 40) + "px";
      wl.hidden = false;
      $$(".wl-item", wl).forEach(el => el.onclick = () => wlPick(+el.dataset.i));
    }
    function wlPick(i) {
      const t = wlItems[i]; if (!t) return;
      const p = area.selectionStart;
      area.setRangeText(t.title + "]]", wlStart + 2, p, "end");
      wl.hidden = true; mark(true); renderPreview();
      area.focus();
    }
    // leave-flush: switching tab/note or closing the page must not lose the
    // sub-1.5s tail of typing. keepalive lets the PUT finish during unload.
    window.__edFlush = () => {
      if (!dirty) return Promise.resolve();
      clearTimeout(autoTimer);
      dirty = false;
      // keepalive: the PUT survives page unload; tab switches AWAIT it so
      // the read view renders what was just typed, not a stale disk state
      return fetch("/api/note", { method: "PUT", keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, content: area.value, expect_mtime: mtime }) });
    };
    async function save(auto = false) {
      if (!dirty) return;
      clearTimeout(autoTimer);
      st.textContent = "저장 중…";
      try {
        const r = await api("/api/note", { method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path, content: area.value, expect_mtime: mtime }) });
        mtime = r.mtime; mark(false);
        if (!auto) toast("저장했습니다", "ok");   // autosave stays quiet
        S.notes = null;              // list stats refresh on next visit
      } catch (e) {
        mark(true);
        if (String(e.message).includes("conflict")) {
          toast("충돌: 디스크에서 노트가 바뀌었어요. 본문 탭에서 확인 후 다시 편집하세요", "err");
        } else toast(e.message, "err");
      }
    }
    btn.onclick = () => save();
    area.onkeydown = e => {
      if (!wl.hidden) {                       // wikilink menu owns arrows/enter
        if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault();
          wlSel = (wlSel + (e.key === "ArrowDown" ? 1 : wlItems.length - 1)) % wlItems.length;
          $$(".wl-item", wl).forEach((el, i) => el.classList.toggle("sel", i === wlSel));
          return; }
        if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); wlPick(wlSel); return; }
        if (e.key === "Escape") { wl.hidden = true; return; }
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); save(); }
      if (e.key === "Tab") { e.preventDefault();
        const p = area.selectionStart;
        area.setRangeText("  ", p, area.selectionEnd, "end"); mark(true); renderPreview(); }
    };
  }

  function wireMeta() {
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

  $$("#ndTabs button", pane).forEach(b => b.onclick = () => showTab(b.dataset.v));
  $("#ndRename", pane).onclick = () => renameNote(d.path);
  $("#ndDelete", pane).onclick = () => deleteNote(d.path);
  showTab(tab);
}

function openByTitle(title) {
  // wikilink navigation: resolve a note title to its path via the loaded list
  const t = title.toLowerCase();
  const hit = (S.notes || []).find(n => n.title.toLowerCase() === t)
    || (S.notes || []).find(n => n.title.toLowerCase().startsWith(t));
  if (hit) { S.knowledge.sel = hit.path; drawNoteRows(); drawNoteDetail(hit.path); }
  else toast(`'${title}' 노트를 찾지 못했어요`, "err");

}


/* ------------------------------------------------------------------ 그래프 */
function renderGraph() {
  const m = $("#main");
  m.innerHTML = `<div class="view wide" style="display:flex;flex-direction:column">
    <iframe id="graphFrame" src="/graph" style="flex:1;border:0;width:100%"
      title="볼트 전체 그래프"></iframe></div>`;
}

/* ----------------------------------------------------------------- health */
async function renderHealth() {
  const m = $("#main");
  m.innerHTML = `<div class="view">
    <div class="view-head"><div class="view-title">건강</div>
      <div class="view-sub">기억 vs 기억(모순) · 기억 vs 현실(드리프트) · AI 쓰기 승인 · 링크 제안 · 전부 로컬, LLM 0회</div></div>
    <div class="card"><div class="card-head">승인 대기 <span class="spacer"></span><span class="chip" id="pendCount"></span></div>
      <div id="pendBody" class="hl-body"><div class="skel" style="height:40px"></div></div></div>
    <div class="card"><div class="card-head">모순 (기억 vs 기억) <span class="spacer"></span><span class="chip" id="confCount"></span></div>
      <div id="confBody" class="hl-body"><div class="skel" style="height:40px"></div></div></div>
    <div class="card"><div class="card-head">드리프트 (기억 vs 현실) <span class="spacer"></span><span class="chip" id="driftCount"></span></div>
      <div id="driftBody" class="hl-body"><div class="skel" style="height:40px"></div></div></div>
    <div class="card"><div class="card-head">링크 제안 <span class="spacer"></span><span class="chip" id="sugCount"></span></div>
      <div id="sugBody" class="hl-body"><div class="skel" style="height:40px"></div></div></div>
  </div>`;

  const empty = (t) => `<div class="empty">${t}</div>`;

  // 승인 대기 (memory_approval mode)
  const drawPending = async () => {
    try {
      const rows = await api("/api/pending");
      $("#pendCount").textContent = rows.length ? `${rows.length}건` : "";
      $("#pendBody").innerHTML = rows.length ? rows.map(r => `
        <div class="hl-row">
          <div class="hl-main"><b>${esc(r.title)}</b><span class="hl-dim">${esc(r.path)}</span></div>
          <button class="btn sm primary" data-approve="${esc(r.path)}">승인</button>
          <button class="btn sm" data-reject="${esc(r.path)}">거절</button>
        </div>`).join("") : empty("승인 대기 없음 · memory_approval을 켜면 AI 쓰기가 여기서 대기합니다");
      $$("#pendBody [data-approve]").forEach(b => b.onclick = async () => {
        await jpost("/memory/approve", { path: b.dataset.approve }); drawPending();
      });
      $$("#pendBody [data-reject]").forEach(b => b.onclick = async () => {
        await jpost("/memory/trash", { path: b.dataset.reject }); drawPending();
      });
    } catch (e) { $("#pendBody").innerHTML = empty(esc(e.message)); }
  };

  const drawConflicts = async () => {
    try {
      const rows = await api("/api/conflicts?threshold=0.75&limit=20");
      const label = { number: "숫자 불일치", negation: "부정 충돌", duplicate: "중복 후보" };
      $("#confCount").textContent = rows.length ? `${rows.length}건` : "";
      $("#confBody").innerHTML = rows.length ? rows.map(c => `
        <div class="hl-row col">
          <div><span class="chip ${c.kind === "duplicate" ? "" : "warn"}">${label[c.kind]}</span>
            <span class="hl-dim">sim ${c.similarity}</span>
            ${c.detail ? `<span class="hl-dim">· ${esc(c.detail)}</span>` : ""}</div>
          <div class="hl-pair"><b>${esc(c.a.title)}</b> ↔ <b>${esc(c.b.title)}</b></div>
        </div>`).join("") : empty("모순 없음 · 노트들이 서로 일치합니다");
    } catch (e) { $("#confBody").innerHTML = empty(esc(e.message)); }
  };

  const drawDrift = async () => {
    try {
      const d = await api("/api/drift");
      const kinds = [["broken_wikilinks", "깨진 위키링크"], ["missing_file_links", "없는 파일 링크"],
                     ["unresolved_duplicates", "미해소 중복 플래그"]];
      const total = kinds.reduce((s, [k]) => s + (d[k] || []).length, 0);
      $("#driftCount").textContent = total ? `${total}건` : "";
      $("#driftBody").innerHTML = total ? kinds.filter(([k]) => (d[k] || []).length).map(([k, lab]) => `
        <div class="hl-row col"><div><span class="chip warn">${lab}</span></div>
          ${(d[k]).slice(0, 8).map(r => `<div class="hl-dim">${esc(r.note)} → ${esc(r.target || r.duplicate_of || "")}</div>`).join("")}
        </div>`).join("") : empty(`드리프트 없음 · 노트 ${d.notes_scanned ?? "?"}개 검사`);
    } catch (e) { $("#driftBody").innerHTML = empty(esc(e.message)); }
  };

  const drawSuggest = async () => {
    try {
      const rows = await api("/api/suggest_links?k=10");
      $("#sugCount").textContent = rows.length ? `${rows.length}건` : "";
      $("#sugBody").innerHTML = rows.length ? rows.map(s => `
        <div class="hl-row col">
          <div><b>${esc(s.from_title)}</b> → ${esc(s.suggestion)}</div>
          ${s.snippet ? `<div class="hl-dim">"${esc(s.snippet)}"</div>` : ""}
        </div>`).join("") : empty("연결 안 된 언급 없음");
    } catch (e) { $("#sugBody").innerHTML = empty(esc(e.message)); }
  };

  drawPending(); drawConflicts(); drawDrift(); drawSuggest();
}

/* ----------------------------------------------------------------- search */
// what people actually ask their vault · rotated so the empty state teaches range
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

/* ------------------------------------------------------------------ 기억 */
// The agent-memory view: what the AI pinned, what work is unfinished, and
// what it remembered. the three questions a hosted memory dashboard answers,
// answered here off the local vault with no account.

const FRAG_TYPES = [
  ["", "전체"], ["fact", "사실"], ["decision", "결정"], ["error", "오류"],
  ["preference", "선호"], ["procedure", "절차"], ["relation", "관계"],
  ["episode", "세션"],
];
const FRAG_LABEL = Object.fromEntries(FRAG_TYPES.map(([k, v]) => [k, v]));

async function renderMemory(selCase) {
  const M = S.memory;
  if (selCase) M.sel = selCase;
  const m = $("#main");
  m.innerHTML = `<div class="view">
    <div class="view-head"><div class="view-title">기억</div>
      <div class="view-sub">에이전트가 기억한 것 · 볼트 안 마크다운. 계정도, 쿼터도 없다</div>
      <div class="spacer"></div>
      <button class="btn" id="btnConsolidate" title="L1 아톰 → L2 장면 → L3 페르소나 승격">피라미드 통합</button></div>
    <div class="mem-grid">
      <div class="mem-col">
        <div class="mem-sec-head">🧠 페르소나 <span class="mem-hint">L3 · 모든 세션 시작에 주입</span></div>
        <div id="personaCard"><div class="skel" style="height:60px"></div></div>
        <div class="mem-sec-head">장면 <span class="mem-hint">L2 · 맥락별 살아있는 서사</span></div>
        <div id="sceneList"><div class="skel" style="height:48px"></div></div>
        <div class="mem-sec-head">📌 앵커 <span class="mem-hint">고정 주입</span></div>
        <div id="anchors"><div class="skel" style="height:48px"></div></div>
        <div class="mem-sec-head">케이스 <span class="mem-hint">진행 중인 작업 스레드</span></div>
        <div id="caseList"><div class="skel" style="height:64px"></div></div>
        <div class="mem-sec-head">스킬 <span class="mem-hint">끝난 케이스에서 추출한 재사용 절차</span></div>
        <div id="skillList"><div class="skel" style="height:40px"></div></div>
      </div>
      <div class="mem-col mem-main">
        <div class="search-box">
          <input id="memQ" type="text" placeholder="기억 검색 · 비워두면 최신순 목록" value="${esc(M.q)}" autocomplete="off">
          <button class="btn primary" id="btnRecall">회상</button>
        </div>
        <div class="search-ctl"><div class="grp"><span>종류</span><div class="seg" id="segType">
          ${FRAG_TYPES.map(([v, l]) => `<button data-v="${v}">${l}</button>`).join("")}
        </div></div></div>
        <div id="caseBrief"></div>
        <div class="hits" id="memHits"></div>
      </div>
    </div></div>`;

  const syncType = () => $$("#segType button").forEach(
    b => b.classList.toggle("active", b.dataset.v === M.type));
  syncType();
  $$("#segType button").forEach(b => b.onclick = () => {
    M.type = b.dataset.v; syncType(); doRecall();
  });
  $("#memQ").addEventListener("keydown", e => { if (e.key === "Enter") doRecall(); });
  $("#btnRecall").onclick = doRecall;
  $("#btnConsolidate").onclick = doConsolidate;

  drawPersona();
  drawScenes();
  drawAnchors();
  drawCases();
  drawSkills();
  if (M.sel) drawCaseBrief(M.sel); else doRecall();

  async function doConsolidate() {
    const btn = $("#btnConsolidate");
    btn.disabled = true; btn.textContent = "통합 중…";
    try {
      const r = await api("/memory/consolidate", { method: "POST" });
      if (r.atoms === 0) toast("승격할 새 기억 없음");
      else toast(`아톰 ${r.atoms}건 → 장면 ${r.scenes_created.length}생성/${r.scenes_updated.length}갱신` +
                 (r.persona ? " · 페르소나 갱신" : "") +
                 (r.used_llm ? "" : " (LLM 없이 폴백)"), "ok");
      drawPersona(); drawScenes();
    } catch (e) { toast(e.message, "err"); }
    btn.disabled = false; btn.textContent = "피라미드 통합";
  }

  async function doRecall() {
    M.q = $("#memQ").value.trim();
    $("#memHits").innerHTML = `<div class="skel" style="height:56px"></div>`;
    const p = new URLSearchParams({ q: M.q, k: "20" });
    if (M.type) p.set("type", M.type);
    if (M.sel) p.set("case", M.sel);
    try {
      drawFragments((await api(`/api/recall?${p}`)).results);
    } catch (e) { $("#memHits").innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }
}

function drawFragments(rows) {
  const box = $("#memHits");
  if (!box) return;
  if (!rows.length) {
    box.innerHTML = `<div class="empty">기억 없음. MCP <code>remember</code> 또는
      <code>lemory remember</code> 로 저장하세요</div>`;
    return;
  }
  box.innerHTML = rows.map(r => `<div class="hit mem-frag" data-path="${esc(r.path)}">
    <div class="row1">
      ${r.type ? `<span class="chip type-${esc(r.type)}">${esc(FRAG_LABEL[r.type] || r.type)}</span>` : ""}
      ${r.anchor ? `<span class="chip brand">📌</span>` : ""}
      <span class="title">${esc(r.note)}</span>
      ${r.case ? `<span class="chip">${esc(r.case)}</span>` : ""}
      ${r.status ? `<span class="chip st-${esc(r.status)}">${esc(r.status)}</span>` : ""}
    </div>
    <div class="snippet">${esc((r.text || "").slice(0, 240))}</div>
  </div>`).join("");
  $$(".mem-frag").forEach(el => el.onclick = () => go(`#/knowledge/${encodeURIComponent(el.dataset.path)}`));
}

async function drawPersona() {
  const box = $("#personaCard");
  if (!box) return;
  try {
    const p = await api("/api/persona");
    if (!p.exists) {
      box.innerHTML = `<div class="empty sm">아직 없음 · '피라미드 통합'으로 생성</div>`;
      return;
    }
    const short = p.body.length > 360 ? p.body.slice(0, 360) + "…" : p.body;
    box.innerHTML = `<div class="persona-card" data-path="${esc(p.path)}">
      <div class="persona-body">${esc(short)}</div>
      <div class="persona-foot">${esc(p.path)} · 클릭해서 전체 보기</div></div>`;
    $(".persona-card").onclick = () => go(`#/knowledge/${encodeURIComponent(p.path)}`);
  } catch (e) { box.innerHTML = `<div class="empty sm">${esc(e.message)}</div>`; }
}

async function drawScenes() {
  const box = $("#sceneList");
  if (!box) return;
  try {
    const rows = (await api("/api/scenes")).scenes;
    box.innerHTML = rows.length
      ? rows.map(s => `<div class="mem-row" data-path="${esc(s.path)}" title="${esc(s.summary)}">
          <span class="mem-row-title">${esc(s.title)}</span>
          <span class="chip heat">${s.heat >= 5 ? "🔥" : ""}${s.heat}</span>
        </div>`).join("")
      : `<div class="empty sm">장면 없음 · 기억이 쌓이면 통합으로 생겨요</div>`;
    $$("#sceneList .mem-row").forEach(el => el.onclick =
      () => go(`#/knowledge/${encodeURIComponent(el.dataset.path)}`));
  } catch (e) { box.innerHTML = `<div class="empty sm">${esc(e.message)}</div>`; }
}

async function drawSkills() {
  const box = $("#skillList");
  if (!box) return;
  try {
    const rows = (await api("/api/skills")).skills;
    box.innerHTML = rows.length
      ? rows.map(s => `<div class="mem-row" data-path="${esc(s.path)}">
          <span class="mem-row-title">${esc(s.name)}</span>
          ${s.case ? `<span class="chip">${esc(s.case)}</span>` : ""}
        </div>`).join("")
      : `<div class="empty sm">스킬 없음 · 완결된 케이스에서 추출돼요</div>`;
    $$("#skillList .mem-row").forEach(el => el.onclick =
      () => go(`#/knowledge/${encodeURIComponent(el.dataset.path)}`));
  } catch (e) { box.innerHTML = `<div class="empty sm">${esc(e.message)}</div>`; }
}

async function drawAnchors() {
  const box = $("#anchors");
  if (!box) return;
  try {
    const rows = (await api("/api/anchors")).anchors;
    box.innerHTML = rows.length
      ? rows.map(a => `<div class="mem-row" data-path="${esc(a.path)}">
          <span class="mem-row-title">${esc(a.title)}</span>
          ${a.type ? `<span class="chip dim">${esc(FRAG_LABEL[a.type] || a.type)}</span>` : ""}
        </div>`).join("")
      : `<div class="empty sm">고정된 기억 없음</div>`;
    $$("#anchors .mem-row").forEach(el => el.onclick =
      () => go(`#/knowledge/${encodeURIComponent(el.dataset.path)}`));
  } catch (e) { box.innerHTML = `<div class="empty sm">${esc(e.message)}</div>`; }
}

async function drawCases() {
  const box = $("#caseList");
  if (!box) return;
  try {
    const rows = (await api("/api/cases")).cases;
    box.innerHTML = rows.length
      ? rows.map(c => `<div class="mem-row case-row ${S.memory.sel === c.case ? "active" : ""}"
            data-case="${esc(c.case)}">
          <span class="mem-row-title">${esc(c.case)}</span>
          ${c.open ? `<span class="chip st-open">미해결 ${c.open}</span>` : ""}
          <span class="chip dim">${c.fragments}</span>
        </div>`).join("")
      : `<div class="empty sm">케이스 없음</div>`;
    $$("#caseList .case-row").forEach(el => el.onclick = () => {
      S.memory.sel = S.memory.sel === el.dataset.case ? null : el.dataset.case;
      renderMemory(S.memory.sel || undefined);
    });
  } catch (e) { box.innerHTML = `<div class="empty sm">${esc(e.message)}</div>`; }
}

async function drawCaseBrief(caseId) {
  const box = $("#caseBrief");
  if (!box) return;
  try {
    const t = await api(`/api/case?case=${encodeURIComponent(caseId)}`);
    const sec = (title, items, cls = "") => items.length
      ? `<div class="brief-sec"><div class="brief-h ${cls}">${title}</div>
         <ul>${items.map(i => `<li>${esc(i)}</li>`).join("")}</ul></div>` : "";
    box.innerHTML = `<div class="card brief">
      <div class="brief-title">${esc(t.case)}
        <span class="mem-hint">기록 ${t.found}건${t.phases?.length ? ` · ${t.phases.map(esc).join(" → ")}` : ""}</span></div>
      ${sec("다음 단계", t.next_steps || [], "next")}
      ${sec("미해결", (t.open || []).map(o => `[${o.status || "open"}] ${o.note}`), "open")}
      ${sec("결정", t.decisions || [])}
    </div>`;
  } catch (e) { box.innerHTML = `<div class="empty sm">${esc(e.message)}</div>`; }
  // the fragment list below the brief stays scoped to this case
  const p = new URLSearchParams({ q: S.memory.q, k: "20", case: caseId });
  if (S.memory.type) p.set("type", S.memory.type);
  try { drawFragments((await api(`/api/recall?${p}`)).results); } catch { /* brief still shown */ }
}


async function renderSearch() {
  const Q = S.search;
  const m = $("#main");
  const ph = EXAMPLE_QUERIES[Math.floor(Math.random() * EXAMPLE_QUERIES.length)];
  m.innerHTML = `<div class="view">
    <div class="view-head"><div class="view-title">검색</div>
      <div class="view-sub">하이브리드 검색은 로컬에서 수 ms · 질문은 LLM으로 출처 달린 답변</div></div>
    <div class="search-box">
      <input id="q" type="text" placeholder="${esc(ph)}" value="${esc(Q.q)}" autocomplete="off">
      <button class="btn primary" id="btnAsk">질문</button>
      <button class="btn" id="btnSearch">검색만</button>
    </div>
    <div class="search-ctl">
      <div class="grp"><span>모드</span><div class="seg" id="segMode">
        <button data-v="hybrid">하이브리드</button><button data-v="fast">즉답</button><button data-v="vector">벡터</button><button data-v="bm25">BM25</button></div></div>
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
  async function drawSearchIdle() {
    const box = $("#answerBox");
    if (!box) return;
    let tags = [], recent = [];
    try { tags = await api("/api/tags"); } catch {}
    try { recent = (await loadNotes()).slice().sort((a, b) => b.mtime - a.mtime).slice(0, 5); } catch {}
    const ex = EXAMPLE_QUERIES.slice().sort(() => Math.random() - 0.5).slice(0, 3);
    box.innerHTML = `<div class="search-idle">
      <div class="si-block"><div class="si-h">이렇게 물어보세요</div>
        <div class="si-chips">${ex.map(q =>
          `<button class="si-chip" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div></div>
      ${tags.length ? `<div class="si-block"><div class="si-h">태그로 좁히기</div>
        <div class="si-chips">${tags.slice(0, 8).map(t =>
          `<button class="si-chip dim" data-q="tag:${esc(t.tag)} ">#${esc(t.tag)} <span class="si-n">${t.count}</span></button>`).join("")}</div></div>` : ""}
      ${recent.length ? `<div class="si-block"><div class="si-h">최근 노트</div>
        <div class="si-recent">${recent.map(n =>
          `<div class="si-note" data-goto="${esc(n.path)}">${esc(n.title)}<span class="si-when">${rel(n.mtime)}</span></div>`).join("")}</div></div>` : ""}
      <div class="si-hint">Enter로 질문 · '검색만'은 LLM 없이 즉시 · 연산자 <code>tag: folder: type:</code> 지원</div>
    </div>`;
    $$(".si-chip", box).forEach(c => c.onclick = () => {
      input.value = c.dataset.q;
      if (c.dataset.q.endsWith(" ")) input.focus(); else doSearch();
    });
    $$(".si-note", box).forEach(el => el.onclick =
      () => go("#/knowledge/" + encodeURIComponent(el.dataset.goto)));
  }
  if (!Q.q) drawSearchIdle();      // empty state is the tutorial, filled from THIS vault
  // rotate example questions while the box is empty · the empty state is the tutorial
  const rot = setInterval(() => {
    if (!document.body.contains(input)) { clearInterval(rot); return; }
    if (!input.value) input.placeholder = EXAMPLE_QUERIES[Math.floor(Math.random() * EXAMPLE_QUERIES.length)];
  }, 4000);
  input.addEventListener("keydown", e => { if (e.key === "Enter") doAsk(); });
  $("#btnAsk").onclick = doAsk;
  $("#btnSearch").onclick = doSearch;

  // as-you-type instant results: every keystroke fires a mode=fast query
  // (lexical-only, no embedding · a few ms server-side), debounced just
  // enough to skip intermediate frames. Enter/버튼 still run the full
  // hybrid/ask paths; typing never does.
  let instantTimer = 0, instantSeq = 0;
  input.addEventListener("input", () => {
    clearTimeout(instantTimer);
    const q = input.value.trim();
    if (q.length < 2) return;
    instantTimer = setTimeout(async () => {
      const seq = ++instantSeq;
      const t0 = performance.now();
      try {
        const hits = await api(`/search?q=${encodeURIComponent(q)}&k=${Q.k}&mode=fast`);
        if (seq !== instantSeq || input.value.trim() !== q) return; // stale
        const ms = performance.now() - t0;
        $("#answerBox").innerHTML = "";
        $("#lat").hidden = false;
        $("#lat").textContent = `${hits.length}건 · ${ms.toFixed(0)}ms · 즉답(fast) · Enter로 정밀 검색`;
        drawHits(hits);
      } catch (_) { /* instant path is best-effort; Enter still works */ }
    }, 140);
  });

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
      $("#hits").innerHTML = `<div class="empty">답변 실패 · ${esc(e.message)}</div>`;
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
const ASSIST = { history: [], busy: false,
                 session: Math.random().toString(36).slice(2, 10) };

async function renderAssistant() {
  const m = $("#main");
  m.innerHTML = `<div class="view asst">
    <div class="view-head"><div class="view-title">비서</div>
      <div class="view-sub">지식베이스 기반 대화 · 로컬 모델로 스트리밍, 출처 인용</div>
      <div id="asstModel" class="asst-model"></div></div>
    <div id="asstGate"></div>
    <div id="asstWrap" hidden>
      <div class="asst-log" id="asstLog"></div>
      <div id="asstStatus" class="asst-status"></div>
      <div class="asst-input">
        <button class="btn asst-mic" id="asstMic" title="대화 모드 · 그냥 말하면 됩니다 (로컬 음성인식)" hidden>🎙</button>
        <textarea id="asstIn" rows="1" placeholder="물어보거나, '…기억해줘'로 저장 · /검색 /기억 /최근 명령도 됩니다"></textarea>
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
        <span class="kv-v mono">${esc(st.model || "gemma-4-E4B-it-Q4_K_M.gguf")} (llama.cpp)</span></div></div>
      <p style="color:var(--text-3)"><code>pip install "lemory[llama]"</code> 하면 같은 llama.cpp 엔진(GPU)으로 바로 답합니다. 음성까지 쓰려면 <code>lemory[assistant]</code>. 설치 후 <b>다시 확인</b>.</p>
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
      try { await jpost("/api/assistant/model", { size: b.dataset.size });
        toast(`비서 모델 → ${b.dataset.size}`, "ok"); renderAssistant(); }
      catch (e) { toast(e.message, "err"); }
    });
  }
  // preload on-device models once, with visible progress · the first turn used
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
    log.innerHTML = `<div class="asst-empty">무엇이든 물어보세요. 답변은 볼트의 노트에 근거하고, 아래에 출처를 답니다.<br><span style="color:var(--text-3)">예: "지난주에 정리한 결제 정책 요약해줘" · "환불은 비동기 큐로 하기로 했다고 기억해줘"</span></div>`;

  input.oninput = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; };
  input.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSend(); } };
  send.onclick = () => doSend();
  input.focus();

  /* ---- voice: natural conversation · local Whisper STT + streamed Supertonic TTS ---- */
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
    // is long enough · starts sound sooner without being choppy/char-by-char
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
      toast("음성 합성 실패: " + e.message, "err");     // Supertonic only · no browser fallback
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
      if (convo) { toast("대화 모드 · 그냥 말하면 돼요, 멈추면 자동 인식", "ok"); listen(); }
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

    // slash commands · instant local actions, no LLM round-trip
    if (text.startsWith("/")) {
      appendBubble(log, "user", text);
      const reply = (html) => { const b = appendBubble(log, "assistant", ""); b.querySelector(".asst-text").innerHTML = html; log.scrollTop = log.scrollHeight; };
      try {
        if (text.startsWith("/검색 ") || text.startsWith("/s ")) {
          const q = text.replace(/^\/(검색|s)\s+/, "");
          const hits = await api(`/search?q=${encodeURIComponent(q)}&k=5&mode=fast`);
          reply(hits.length ? hits.map(h => `<div><b>${esc(h.title)}</b> <span style="color:var(--text-3)">${esc(h.text.slice(0, 110))}…</span></div>`).join("")
                            : "검색 결과 없음");
        } else if (text.startsWith("/기억 ")) {
          const r = await jpost("/memory", { content: text.slice(4).trim() });
          reply(`기억했습니다 → <code>${esc(r.saved)}</code>`);
        } else if (text === "/최근" || text === "/컨텍스트") {
          const r = await api("/context?max_chars=1200");
          reply(`<pre style="white-space:pre-wrap;margin:0">${esc(r.context)}</pre>`);
        } else {
          reply("명령: <code>/검색 질의</code> · <code>/기억 내용</code> · <code>/최근</code>");
        }
      } catch (e) { reply("실패: " + esc(e.message)); }
      return;
    }

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
        body: JSON.stringify({ messages: ASSIST.history, session: ASSIST.session }),
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
// Frontend metadata for the on-device answer models (matches gemma.MODELS in
// providers/gemma.py). Kept here so the Models card can show specs without a
// backend round-trip; sizes/current come live from /api/assistant/status.
const ANSWER_MODELS = {
  E4B: { name: "Gemma 4 · E4B", tag: "기본 · 품질 우선", specs: "~4B(효율) · Q4_K_M ≈ 4.2 GB · 8K 컨텍스트" },
  E2B: { name: "Gemma 4 · E2B", tag: "가벼움 · 저사양/8GB↓", specs: "~2B(효율) · Q4 ≈ 1.7 GB · 8K 컨텍스트" },
};

// The Models card · the one place to see & pick every model in the stack:
// the on-device answer LLM (Gemma E4B/E2B, switched live via a dedicated
// endpoint), plus the resolved embedding and reranker identities. Answer-model
// selection was previously buried as a tiny toggle in the assistant view.
async function renderModelsCard(tunable, readonly) {
  let st;
  try { st = await api("/api/assistant/status"); }
  catch (e) { st = { available: false, reason: e.message, size: "E4B", sizes: ["E4B", "E2B"] }; }

  const sizes = st.sizes && st.sizes.length ? st.sizes : ["E4B", "E2B"];
  const picks = sizes.map(sz => {
    const spec = ANSWER_MODELS[sz] || { name: sz, tag: "", specs: "" };
    const on = sz === st.size;
    return `<button class="model-pick ${on ? "on" : ""}" data-size="${sz}" ${st.available ? "" : "disabled"}>
        <div class="mp-top"><span class="mp-name">${esc(spec.name)}</span>${
          on ? '<span class="mp-badge">사용 중</span>' : ""}</div>
        <div class="mp-tag">${esc(spec.tag)}</div>
        <div class="mp-specs">${esc(spec.specs)}</div></button>`;
  }).join("");

  const provider = String(readonly.provider ?? tunable.provider ?? "");
  const cloud = provider === "gemini" || provider === "openai";
  const availLine = st.available
    ? `<span class="mp-ok">● llama.cpp GPU 준비됨</span>`
    : `<span class="mp-off">● 미설치</span> <code>pip install "lemory[llama]"</code> · 검색·임베딩은 이것 없이도 동작`;

  // embedding identity
  const embName = esc(readonly.embed_model || "e5-small-ko-v2");
  const backend = String(tunable.local_embed_backend ?? "auto");
  const dim = readonly.embed_dim || (backend === "llamacpp" ? 1024 : 384);
  const embDetail = cloud
    ? `${dim}d · ${esc(provider)} 클라우드`
    : backend === "llamacpp" ? `${dim}d · llama.cpp GPU` : `${dim}d · fastembed · 무컴파일`;
  // reranker identity · the dedicated Qwen3 cross-encoder is the `reranker`
  // config flag (not the generic LLM `rerank` self-scoring pass)
  const rerankOn = !!readonly.reranker;

  return `<div class="card models-card">
    <div class="card-head">모델 <span class="spacer"></span>
      <span class="mp-hint">답변은 온디바이스, 임베딩·리랭커는 아래 항목에서 조정</span></div>

    <div class="model-group">
      <div class="mg-label">답변 LLM <span class="mg-sub">지식베이스 위에서 답을 생성 · 로컬 스트리밍</span></div>
      <div class="model-picks">${picks}</div>
      <div class="mp-avail">${availLine}</div>
      ${cloud ? `<div class="mp-note">클라우드 키(<b>${esc(provider)}</b>)가 설정돼 있어 <code>ask</code>는
        <b>${esc(readonly.llm_model || provider)}</b>로도 답할 수 있어요. 위 선택은 온디바이스(오프라인) 답변 모델입니다.</div>` : ""}
    </div>

    <div class="model-info">
      <div class="mi-row"><span class="mi-k">임베딩</span>
        <span class="mi-v">${embName} <span class="mi-d">${esc(embDetail)}</span></span></div>
      <div class="mi-row"><span class="mi-k">리랭커</span>
        <span class="mi-v">Qwen3-Reranker-0.6B
          <span class="mi-d ${rerankOn ? "mi-on" : ""}">${rerankOn ? "켜짐" : "꺼짐(기본) · 강한 임베더엔 측정상 도움 없음"}</span></span></div>
    </div>
  </div>`;
}

const SETTINGS_META = [
  ["임베딩 · 모델  ⟳ 저장 후 재시작 + 재색인 필요 (벡터 공간이 바뀝니다)", [
    ["provider", "프로바이더", "auto: 키 있으면 클라우드·없으면 로컬 / local: 로컬 임베딩(키 불필요) / gemini·openai: API 키 필요(.env)", "select", ["auto", "local", "gemini", "openai"]],
    ["local_embed_backend", "로컬 임베더", "auto: e5-small-ko-v2(384d, 측정상 최강·기본) / fastembed: 동일 e5-small-ko-v2 / llamacpp: 1024d Harrier 옵션 (lemory[llama])", "select", ["auto", "fastembed", "llamacpp"]],
  ]],
  ["검색 품질", [
    ["graph_expansion", "그래프 확장", "위키링크·언급 그래프로 1-hop 확장해 멀티홉 질문에 답합니다", "bool"],
    ["memory_approval", "AI 쓰기 승인제", "AI가 쓴 기억을 사람이 승인해야 검색에 편입됩니다 (건강 탭에서 승인)", "bool"],
    ["auto_consolidate", "피라미드 자동 통합", "서버가 켜져 있는 동안, 새 기억이 몇 분 조용해지면 장면·페르소나로 자동 승격합니다 (LLM 호출 발생)", "bool"],
    ["proxy_capture", "프록시 대화 캡처", "/v1 메모리 프록시를 지나간 대화를 chats/proxy/ 세션 노트로 저장합니다", "bool"],
    ["git_autocommit", "AI 쓰기 git 체크포인트", "볼트가 git 저장소면 AI가 쓴 노트마다 자동 커밋 · diff·되돌리기가 git 히스토리에 남아요", "bool"],
    ["semantic_links", "시맨틱 폴백 링크", "링크 없는 노트에 유사도 엣지 부여 · 실측에서 이득 없음이 확인돼 기본 꺼짐 (BENCHMARKS §12c)", "bool"],
    ["context_neighbors", "이웃 청크 복원", "랭킹 확정 후 앞뒤 청크의 꼬리/머리를 붙여 잘린 전제·주의를 복원 (Cerebras KB 방식) · 검색 지표엔 영향 없음", "bool"],
    ["usage_prior", "사용 이력 부스트", "자주 인용/열람한 노트가 동점을 이깁니다 (0=끔, 0.05-0.15 권장)", "float"],
    ["default_scope", "기본 검색 범위", "예: folder:프로젝트A tag:업무 · 명시 연산자 없는 모든 질의에 적용, scope:all 로 1회 해제, 비우면 전체", "str"],
    ["answer_n_ctx", "답변 모델 컨텍스트(토큰)", "온디바이스 답변 창 크기. 작을수록 메모리·지연 절감(RAM 부족 시 낮추기), 클수록 근거 노트를 더 많이 담음. 기본 4096", "int"],
    ["answer_gpu_layers", "답변 모델 GPU 레이어", "-1=전부 GPU(Metal/CUDA) · 0=CPU 전용 · N=부분 오프로드(통합메모리/VRAM 부족 시)", "int"],
    ["event_log", "미들웨어 타임라인", "질의·AI 쓰기 기록 (이 기기 SQLite에만 저장, 외부 전송 없음)", "bool"],
    ["graph_alpha", "그래프 강도", "이웃 노트 점수 계수 · 높을수록 연결 노트가 잘 올라옵니다", "float"],
    ["graph_sim_floor", "그래프 유사도 하한", "질의와 이 유사도 미만인 이웃은 무시 (노이즈 차단)", "float"],
    ["title_boost", "제목 부스트", "질의가 노트 제목과 겹치면 가산점", "float"],
    ["per_doc_cap", "노트당 결과 상한", "한 노트가 결과를 독점하지 않게 다양성 확보", "int"],
    ["k_vector", "벡터 후보 수", "융합 전 벡터 검색이 뽑는 후보 개수", "int"],
    ["k_bm25", "BM25 후보 수", "융합 전 키워드 검색이 뽑는 후보 개수", "int"],
  ]],
  ["질의 처리", [
    ["typo_correction", "오타 보정", "볼트 어휘 기반 로컬 did-you-mean (API 호출 없음)", "bool"],
    ["query_expansion", "질의 확장", "LLM으로 질의 변형 생성 · 질의당 LLM 1회 소모", "bool"],
    ["rerank", "LLM 리랭크", "상위 후보를 LLM으로 재채점 · 정밀도↑ 지연↑", "bool"],
    ["recency_boost", "최신성 부스트", "시간성 질의(\"지난주 회의\")에서 최근 노트 가중", "float"],
    ["recency_half_life_days", "최신성 반감기(일)", "최신성 가중치가 절반이 되는 기간", "float"],
  ]],
  ["답변 생성", [
    ["context_style", "컨텍스트 스타일", "full: 청크 원문 그대로 / compact: 팩트시트 압축", "select", ["full", "compact"]],
    ["context_order", "증거 배열 순서", "rank: 검색 점수순(기본) / curriculum: CDS식 매끄러운 궤적 순 · 실험적, KorQuAD A/B에서 이득 없음", "select", ["rank", "curriculum"]],
    ["assistant_log_sessions", "비서 대화 기억", "비서와의 대화를 볼트의 세션 노트(chats/)로 자동 저장 · 오늘 말한 게 내일 검색됩니다. 노트는 직접 보고 지울 수 있어요", "bool"],
  ]],
  ["색인", [
    ["mention_links", "언급 링크", "위키링크가 없어도 제목 언급을 그래프 간선으로", "bool"],
    ["enrich_entities", "LLM 개체 추출", "cognee식 개체 그래프 보강 · LLM 쿼터 소모", "bool"],
    ["chunk_chars", "청크 크기(자)", "재색인 후 적용", "int"],
    ["chunk_overlap", "청크 겹침(자)", "재색인 후 적용", "int"],
    ["chat_burst_chunking", "대화 버스트 청킹", "채팅 노트를 화자 버스트 단위로 색인 · 재색인 후 적용", "bool"],
    ["informativeness_prior", "정보량 prior", "어휘 변별력 0인 에피소드 질문에서만 벡터 레그를 희소 내용으로 재정렬 (필러 대신 진짜 팩트) · 0이면 끔 (BENCHMARKS §7e)", "float"],
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
  let html = await renderModelsCard(cur, cfg.readonly);
  for (const [section, rows] of SETTINGS_META) {
    html += `<div class="card"><div class="card-head">${section}</div>`;
    for (const [key, name, desc, type, options] of rows) {
      const v = cur[key];
      let ctl;
      if (type === "bool") ctl = `<span class="switch ${v ? "on" : ""}" data-key="${key}"></span>`;
      else if (type === "select") ctl = `<select data-key="${key}">${options.map(o =>
        `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select>`;
      else if (type === "str") ctl = `<input type="text" data-key="${key}" value="${esc(v ?? "")}" placeholder="비움 = 전체" spellcheck="false">`;
      else ctl = `<input type="number" data-key="${key}" value="${v}" step="${type === "float" ? "0.05" : "1"}">`;
      html += `<div class="set-row"><div class="set-info">
        <div class="set-name">${name} <span style="color:var(--text-3);font-size:11px;font-family:ui-monospace,monospace">${key}</span></div>
        <div class="set-desc">${desc}</div></div><div class="set-ctl">${ctl}</div></div>`;
    }
    html += `</div>`;
  }
  html += `<div class="card"><div class="card-head">읽기 전용 · 변경은 .env / lemory.toml 수정 후 재시작</div><div class="kv">${
    Object.entries(cfg.readonly).map(([k, v]) =>
      `<div class="kv-row"><span class="kv-k">${esc(k)}</span><span class="kv-v mono">${esc(v ?? "-")}</span></div>`).join("")
  }</div></div>`;
  grid.innerHTML = html;

  // answer-model (Gemma E4B/E2B) live switch · dedicated endpoint, persists to lemory.toml.
  // Update the picks in place rather than re-rendering the whole view, so any
  // unsaved edits in the other settings cards survive the switch.
  $$(".model-pick", grid).forEach(b => b.onclick = async () => {
    if (b.disabled || b.classList.contains("on")) return;
    try {
      await jpost("/api/assistant/model", { size: b.dataset.size });
      toast(`답변 모델 → ${b.dataset.size}`, "ok");
      $$(".model-pick", grid).forEach(x => {
        const on = x === b;
        x.classList.toggle("on", on);
        const badge = x.querySelector(".mp-badge");
        if (on && !badge) x.querySelector(".mp-top").insertAdjacentHTML("beforeend", '<span class="mp-badge">사용 중</span>');
        if (!on && badge) badge.remove();
      });
    } catch (e) { toast(e.message, "err"); }
  });

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
      toast("저장됨 · 볼트의 lemory.toml에 기록했습니다", "ok");
      renderSettings();
    } catch (e) { toast(`저장 실패: ${e.message}`, "err"); }
  };
}

/* ---------------------------------------------------------------- palette */
const PAL_VIEWS = [
  ["overview", "현황으로 이동", icoHome],
  ["knowledge", "지식으로 이동", icoFolder],
  ["memory", "기억으로 이동", icoDoc],
  ["graph", "그래프로 이동", icoFolder],
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

async function createNoteFromPalette(title) {
  try {
    const r = await api("/api/note", { method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: title, content: `# ${title}\n\n` }) });
    S.notes = null;
    S.knowledge.tab = "edit";        // land straight in the editor
    go("#/knowledge/" + encodeURIComponent(r.saved));
    toast(`'${title}' 노트를 만들었어요`, "ok");
  } catch (e) { toast(e.message, "err"); }
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
    // Tolaria's quick-open affordance: a query that matches nothing becomes
    // the new note's title · zero-friction capture from anywhere (⌘K → 제목 → Enter)
    if (q && !matches.length)
      palItems.push({
        label: `새 노트 "${q}" 만들기`, ico: icoDoc, sub: "지식에 생성 후 편집",
        act: () => createNoteFromPalette(q),
      });
  } catch { /* server down · views only */ }

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
// Obsidian's global graph is decoration; this is the RETRIEVAL graph · the
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
      <div class="lg-legend"><span style="color:#7ea6ff">· 위키링크</span>
        <span style="color:#c6a5ff">┄ 언급(옵시디언엔 없음)</span>
        <span style="color:#7fd8c3">· 개체</span>
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
function icoPlus() { return svg('<path d="M8 3v10M3 8h10"/>'); }
function icoTrash() { return svg('<path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5M6.5 7v4M9.5 7v4"/>'); }
function icoRename() { return svg('<path d="M2.5 11.5 10 4l2 2-7.5 7.5H2.5zM9 5l2 2M8.5 13.5h5"/>'); }

/* ------------------------------------------------------------------- boot */
async function boot() {
  initTheme();
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
