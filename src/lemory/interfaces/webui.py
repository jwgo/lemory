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
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, 'Apple SD Gothic Neo', 'Noto Sans KR', system-ui, sans-serif;
         max-width: 780px; margin: 0 auto; padding: 24px 16px; line-height: 1.55; }
  h1 { font-size: 1.4rem; margin: 0 0 4px; }
  #meta { opacity: .65; font-size: .85rem; margin-bottom: 20px; }
  form { display: flex; gap: 8px; margin-bottom: 8px; }
  input[type=text] { flex: 1; font-size: 1rem; padding: 10px 12px; border-radius: 10px;
         border: 1px solid color-mix(in srgb, currentColor 25%, transparent); background: transparent; }
  button { font-size: .95rem; padding: 10px 16px; border-radius: 10px; border: none;
         background: #6c5ce7; color: #fff; cursor: pointer; }
  button.secondary { background: transparent; color: inherit;
         border: 1px solid color-mix(in srgb, currentColor 25%, transparent); }
  #answer { white-space: pre-wrap; padding: 14px 16px; border-radius: 12px; margin: 14px 0;
         background: color-mix(in srgb, currentColor 7%, transparent); display: none; }
  .hit { padding: 10px 0; border-bottom: 1px solid color-mix(in srgb, currentColor 12%, transparent); }
  .hit .t { font-weight: 600; }
  .hit .d { opacity: .6; font-size: .8rem; margin-left: 6px; }
  .hit .x { opacity: .85; font-size: .9rem; margin-top: 2px; }
  .spin { display: none; opacity: .6; margin: 12px 0; }
  .hint { opacity: .55; font-size: .85rem; }
</style>
</head>
<body>
<h1>Lemory</h1>
<div id="meta">…</div>
<form id="f">
  <input id="q" type="text" placeholder="요새 내가 하던 그거 뭐였지?" autofocus autocomplete="off">
  <button type="submit">질문</button>
  <button type="button" class="secondary" id="searchBtn">검색만</button>
</form>
<div class="hint">Enter = 답변 생성(LLM) · 검색만 = 관련 노트 목록(로컬, 즉시)</div>
<div class="spin" id="spin">생각 중…</div>
<div id="answer"></div>
<div id="hits"></div>
<script>
const $ = id => document.getElementById(id);
async function j(url, opts) { const r = await fetch(url, opts); if (!r.ok) throw new Error(await r.text()); return r.json(); }
async function loadMeta() {
  try { const s = await j('/status');
    $('meta').textContent = `${s.vault} — 노트 ${s.documents} · 청크 ${s.chunks} · 링크 ${s.links}`;
  } catch (e) { $('meta').textContent = '서버 상태를 읽지 못했습니다'; }
}
function renderHits(hits) {
  $('hits').innerHTML = hits.map(h => `
    <div class="hit">
      <span class="t">${esc(h.title)}</span>
      ${h.date ? `<span class="d">${esc(h.date)}</span>` : ''}
      ${h.heading ? `<span class="d">› ${esc(h.heading)}</span>` : ''}
      <div class="x">${esc(h.text.slice(0, 220))}</div>
    </div>`).join('');
}
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function doSearch() {
  const q = $('q').value.trim(); if (!q) return;
  $('answer').style.display = 'none';
  renderHits(await j('/search?q=' + encodeURIComponent(q) + '&k=8'));
}
async function doAsk(ev) {
  ev.preventDefault();
  const q = $('q').value.trim(); if (!q) return;
  $('spin').style.display = 'block'; $('answer').style.display = 'none'; $('hits').innerHTML = '';
  try {
    const r = await j('/ask', {method: 'POST', headers: {'Content-Type': 'application/json'},
                               body: JSON.stringify({question: q, k: 8})});
    $('answer').textContent = r.answer; $('answer').style.display = 'block';
    renderHits(r.sources.map(s => ({...s, text: s.text || ''})));
  } catch (e) { $('answer').textContent = '오류: ' + e.message; $('answer').style.display = 'block'; }
  $('spin').style.display = 'none';
}
$('f').addEventListener('submit', doAsk);
$('searchBtn').addEventListener('click', doSearch);
loadMeta();
</script>
</body>
</html>"""
