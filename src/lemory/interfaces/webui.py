"""Built-in web UI: a single self-contained page served at `/`.

No build step, no dependencies, works offline against the local API — so a
non-CLI user can point their browser at http://127.0.0.1:8377 and use their
vault like a service: ask questions, search, see what changed recently.
"""

PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lemory</title>
<style>
  :root {
    --bg: #0e1013; --panel: #16191e; --panel2: #1c2027;
    --text: #e8eaed; --muted: #8b93a1; --line: #262b33;
    --accent: #f5c518; --accent2: #ffd75e; --accent-ink: #1a1a1a;
    color-scheme: dark;
  }
  @media (prefers-color-scheme: light) {
    :root { --bg: #faf9f7; --panel: #ffffff; --panel2: #f4f2ee;
            --text: #1c1e21; --muted: #6b7280; --line: #e5e2db;
            --accent: #e0a800; --accent2: #f5c518; color-scheme: light; }
  }
  * { box-sizing: border-box; margin: 0; }
  body { font-family: -apple-system, 'Apple SD Gothic Neo', 'Pretendard',
         'Noto Sans KR', system-ui, sans-serif; background: var(--bg);
         color: var(--text); max-width: 860px; margin: 0 auto;
         padding: 40px 20px 80px; line-height: 1.6; }
  header { display: flex; align-items: baseline; gap: 14px; margin-bottom: 6px; }
  h1 { font-size: 1.7rem; letter-spacing: -0.02em; }
  h1 .lemon { margin-right: 6px; }
  #meta { color: var(--muted); font-size: .85rem; display: flex; gap: 8px;
          flex-wrap: wrap; margin-bottom: 26px; }
  #meta .chip { background: var(--panel2); border: 1px solid var(--line);
          border-radius: 999px; padding: 1px 10px; }
  form { display: flex; gap: 10px; }
  input[type=text] { flex: 1; font-size: 1.05rem; padding: 14px 18px;
          border-radius: 14px; border: 1px solid var(--line);
          background: var(--panel); color: var(--text); outline: none;
          transition: border-color .15s, box-shadow .15s; }
  input[type=text]:focus { border-color: var(--accent);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent); }
  button { font-size: .95rem; font-weight: 600; padding: 0 22px;
          border-radius: 14px; border: none; cursor: pointer;
          background: linear-gradient(135deg, var(--accent), var(--accent2));
          color: var(--accent-ink); }
  button.secondary { background: var(--panel); color: var(--text);
          border: 1px solid var(--line); font-weight: 500; }
  .hint { color: var(--muted); font-size: .82rem; margin: 10px 4px 0; }
  #answer { display: none; margin: 26px 0 8px; padding: 18px 20px;
          border-radius: 16px; background: var(--panel);
          border: 1px solid var(--line); white-space: pre-wrap;
          font-size: 1.02rem; }
  #answer::before { content: "답변"; display: block; font-size: .72rem;
          letter-spacing: .12em; color: var(--accent); margin-bottom: 8px;
          font-weight: 700; }
  .srclabel { color: var(--muted); font-size: .78rem; letter-spacing: .1em;
          margin: 22px 4px 10px; font-weight: 600; }
  .hit { padding: 14px 16px; border-radius: 14px; background: var(--panel);
          border: 1px solid var(--line); margin-bottom: 10px;
          transition: border-color .15s; }
  .hit:hover { border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); }
  .hit .row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .hit .n { color: var(--accent); font-weight: 700; font-size: .85rem; }
  .hit .t { font-weight: 650; cursor: pointer; }
  .hit .t:hover { text-decoration: underline; }
  .hit .d { color: var(--muted); font-size: .78rem; background: var(--panel2);
          border-radius: 999px; padding: 0 9px; border: 1px solid var(--line); }
  .hit .x { color: var(--muted); font-size: .9rem; margin-top: 5px;
          display: -webkit-box; -webkit-line-clamp: 2;
          -webkit-box-orient: vertical; overflow: hidden; }
  .spin { display: none; color: var(--muted); margin: 22px 4px; }
  .spin::before { content: "🍋"; display: inline-block; margin-right: 8px;
          animation: roll 1.2s linear infinite; }
  @keyframes roll { to { transform: rotate(360deg); } }
  .error { color: #ff7b72; margin: 20px 4px; white-space: pre-wrap; }
</style>
</head>
<body>
<header><h1><span class="lemon">🍋</span>Lemory</h1></header>
<div id="meta">…</div>
<form id="f">
  <input id="q" type="text" placeholder="요새 내가 하던 그거 뭐였지?" autofocus autocomplete="off">
  <button type="submit">질문</button>
  <button type="button" class="secondary" id="searchBtn">검색만</button>
</form>
<div class="hint">Enter → 출처 달린 답변 (LLM) &nbsp;·&nbsp; 검색만 → 관련 노트 즉시 나열 (로컬, ~3ms)</div>
<div class="spin" id="spin">볼트를 뒤지는 중…</div>
<div id="answer"></div>
<div id="out"></div>
<script>
const $ = id => document.getElementById(id);
async function j(url, opts) { const r = await fetch(url, opts); if (!r.ok) throw new Error(await r.text()); return r.json(); }
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function loadMeta() {
  try { const s = await j('/status');
    const name = (s.vault || '').split('/').filter(Boolean).pop() || 'vault';
    $('meta').innerHTML =
      `<span class="chip">📂 ${esc(name)}</span>` +
      `<span class="chip">노트 ${s.documents}</span>` +
      `<span class="chip">청크 ${s.chunks}</span>` +
      `<span class="chip">링크 ${s.links}</span>`;
  } catch (e) { $('meta').textContent = '서버 연결 대기 중…'; }
}
function renderHits(hits, withLabel) {
  const out = $('out'); out.innerHTML = '';
  if (withLabel && hits.length) out.insertAdjacentHTML('beforeend', '<div class="srclabel">출처</div>');
  for (let i = 0; i < hits.length; i++) {
    const h = hits[i];
    const el = document.createElement('div'); el.className = 'hit';
    el.innerHTML = `<div class="row"><span class="n">[${i+1}]</span>` +
      `<span class="t">${esc(h.title)}${h.heading && h.heading !== h.title ? ' › ' + esc(h.heading) : ''}</span>` +
      (h.date ? `<span class="d">${esc(h.date)}</span>` : '') + `</div>` +
      (h.text ? `<div class="x">${esc(h.text.slice(0, 260))}</div>` : '');
    el.querySelector('.t').addEventListener('click', () =>
      window.open('obsidian://open?file=' + encodeURIComponent(h.path), '_self'));
    out.appendChild(el);
  }
}
async function doSearch() {
  const q = $('q').value.trim(); if (!q) return;
  $('answer').style.display = 'none'; $('spin').style.display = 'block';
  try { renderHits(await j('/search?q=' + encodeURIComponent(q) + '&k=8'), false); }
  catch (e) { $('out').innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
  $('spin').style.display = 'none';
}
async function doAsk(ev) {
  ev.preventDefault();
  const q = $('q').value.trim(); if (!q) return;
  $('spin').style.display = 'block'; $('answer').style.display = 'none'; $('out').innerHTML = '';
  try {
    const r = await j('/ask', {method: 'POST', headers: {'Content-Type': 'application/json'},
                               body: JSON.stringify({question: q, k: 8})});
    $('answer').textContent = r.answer.replace(/^\s*[\*\-]\s+/gm, '\u2022 '); $('answer').style.display = 'block';
    renderHits(r.sources ?? [], true);
  } catch (e) { $('out').innerHTML = '<div class="error">lemory serve가 켜져 있나요?\\n' + esc(e.message) + '</div>'; }
  $('spin').style.display = 'none';
}
$('f').addEventListener('submit', doAsk);
$('searchBtn').addEventListener('click', doSearch);
loadMeta();
</script>
</body>
</html>"""
