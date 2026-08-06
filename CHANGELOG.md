# Changelog

All notable changes to Lemory. Dates are the merge date of the release.

## Unreleased · gap audit vs Tolaria: trash bin · drag-move · saved views

An honest re-audit of "did we really absorb them?" found three console gaps
that couldn't be excused as editor-only territory. All three closed:

- **Trash bin with restore**: `.trash` was a one-way street (files moved,
  origin forgotten, no UI). Now a meta-table remembers each file's home
  folder; the 지식 tree gets a 휴지통 section listing entries (origin, age,
  size) with 복구 (back to its home folder · never clobbers, suffixes on
  conflict) and 영구 삭제 (the only destructive verb in the write surface,
  path-guarded to never reach outside `.trash`). Engine verbs
  `list_trash`/`restore_note`/`purge_note` + HTTP `/api/trash{,/restore,/purge}`.
- **Drag a note onto a tree folder to move it** · rename under the hood, so
  both paths reindex and wikilinks keep resolving; drop-target highlight,
  same-folder no-op.
- **Saved views** (Tolaria's Saved Views, console-sized): bookmark the
  current folder/tag/filter/sort as a named view pinned at the top of the
  tree · click applies, × deletes, persisted per browser.
- Fixed live: `.prop-new { display:flex }` was overriding the `[hidden]`
  attribute, showing the add-property inputs uninvited.
- docs/COMPETITIVE.md Tolaria section updated with the console-shell absorb
  table and the (still deliberate) non-absorptions.
- Verified in-browser: delete → bin shows origin → restore lands back in
  리서치/ → drag-move to 회의록 confirmed on disk → view save/apply/delete.
  JS errors 0; engine/HTTP tests added (roundtrip, no-clobber restore,
  purge guard).

## Unreleased · property inspector · list snippets · palette chord fix

- **Frontmatter property inspector** (본문 탭 상단): flat `key: value` /
  `key: [list]` frontmatter renders as an editable panel · click a value to
  edit inline, tag lists are chips with ×-remove and a +input, `+ 속성` adds
  a new key (comma value → list). Saves go through the same optimistic-
  concurrency PUT as the editor (409 on disk conflict) and round-trip the
  YAML byte-cleanly. Nested YAML we can't round-trip safely stays as the
  read-only folded block · the inspector never guesses.
- **Note list snippets**: every row now carries a one-line content preview
  (first real chunk, headings/frontmatter stripped, server-side in
  `doc_overview_rows`) · scanning the list stops requiring opening notes.
- **⌘K/Ctrl+K fix** (found live): the palette chord was bound in TWO keydown
  handlers, so one keypress opened and instantly closed it — on every OS.
  The SHORTCUTS table is now the only owner (and toggles).
- Verified in-browser end to end: add/edit/remove property → disk YAML
  checked → cleanup; snippet rows on all 11 notes; Ctrl+K opens. JS errors
  0; 494 tests pass (new store-level snippet test included).

## Unreleased · design system v2: the console gets a real visual language

A token-first redesign of the whole console (app.css rewritten around a
single ramp) · every color, size, shadow and motion now comes from :root
tokens, so components stop inventing values and both themes derive from the
same semantics.

- **Tokens**: layered graphite palette (chrome darker than canvas, cards
  above both), hairline rgba borders, semantic hue set (ok/warn/danger/info/
  purple/teal/pink + soft variants) that chips, badges and link-kinds all
  share, type scale (10.5–26px), elevation levels (card sheen + e1–e3),
  motion tokens, and a global `:focus-visible` ring for keyboard users.
- **Note detail header**: restructured to a desktop-app pattern · breadcrumb
  + actions on top, 20px title, meta line with inline tags, and **underline
  tabs** instead of a pill group. The whole header is **sticky** inside the
  pane, so title/tabs stay in reach on long notes (TOC scroll-spy verified
  against it).
- **Sidebar**: brand mark in a lemon tile, active nav with surface+sheen,
  hover reveals each view's ⌘n shortcut (data-kbd), footer reorganized
  (palette hint, then watch-dot + theme toggle in one row).
- **Primary buttons** get a subtle gradient + inner highlight; inputs sit in
  inset wells; palette/overlays gained blur + pop-in motion; empty count
  chips vanish (`:empty`) instead of rendering as gray dots (found live).
- Light theme re-derived token-by-token (own scrollbars, shadows, hues).
- Verified hands-on across all 8 views + palette + both themes; JS errors 0;
  493 tests pass.

## Unreleased · desktop-grade console shell: 하이라이트 편집기 · 리사이즈 · 상태바 · TOC

Closing the visible gap to desktop knowledge tools (Tolaria-class shells):

- **Syntax-highlighted editor**: the edit tab now colors markdown source ·
  headings, bold, inline/fenced code, `[[wikilinks]]`, links, tags, quotes,
  frontmatter. Zero libraries: a transparent-text textarea sits over an
  identically-metriced highlight layer; the textarea auto-grows instead of
  scrolling internally, so the two layers can never drift. Color-only tokens
  (no weight changes · bold shifts CJK fallback glyph widths and would
  desync the caret). Both themes get their own token palette.
- **Resizable columns**: drag the gutters between 계층/목록/본문 to set pane
  widths (clamped 180–420 / 230–540), persisted in localStorage, double-click
  to reset. Small screens and focus-editing override the custom widths.
- **Bottom status bar**: vault · 노트/청크/연결 counts · watcher dot ·
  마지막 색인 age · provider · version, refreshed on the existing 30s poll.
  Answers "is it alive, is it indexed" from every view.
- **본문 목차 (TOC)**: notes with 3+ headings get a sticky outline next to
  the body · click scrolls, scroll-spy highlights the section you're reading.
- **Clickable breadcrumb**: the note path renders as folder segments · click
  one to scope the note list to that folder (tree opens the branch).
- Verified hands-on in the browser (drag, type, click-through, both themes):
  highlight/textarea alignment measured at 0px drift, JS errors 0.

## Unreleased · direct authoring: the console writes notes now, production-grade

The console stops being read-mostly · you author notes in it, like Almanac's
viewer-plus and Tolaria's editor, at web-console cost.

- **New note, folder-aware**: a `+` in the note list (and ⌘N) creates a note
  in the folder you're browsing and drops you in the editor.
- **Rename / delete** from the note detail header · rename moves the file
  and reindexes both paths (wikilinks target titles, so they keep resolving);
  delete trashes to `.trash` (recoverable). A new `human=True` path lets the
  user delete their OWN note through their OWN console · the AI-write trash
  guard (lemory_generated marker) still protects them from the *agent*, never
  from themselves.
- **Live preview**: edit tab is a split · markdown source left, rendered
  preview right, updating as you type (frontmatter folds, wikilinks click
  through). Toggle with the 미리보기 switch.
- **`[[wikilink]]` autocomplete**: type `[[`, get a title picker (↑↓ Enter),
  backed by `GET /api/titles`. No CDN, no editor library.
- **Focus editing**: entering the edit tab folds the tree+note-list so the
  editor+preview get the full width · found live: without it the preview
  column was ~230px and CJK wrapped to one glyph per line (unreadable). Also
  fixed the preview inheriting `.ed-col`'s flex, which laid its headings out
  as flex items.
- Backend: engine `write_note`/`rename_note`/`trash_note(human=)`/`read_note`
  facade verbs; HTTP `PUT /api/note`, `POST /api/note/rename` (409 on
  clobber), `POST /api/note/delete`, `GET /api/titles`. All browser-verified
  end to end (create → type → live preview → wikilink autocomplete → rename
  → delete), JS errors 0.

## Unreleased · dogfood UX pass: touched every screen, fixed the friction

Walked all eight views + palette as a real user (screenshot → critique →
fix → re-verify), not a scripted check. What the walkthrough caught:

- **A live race crash** (`Cannot set innerHTML of null`): navigating away
  from 현황 mid-fetch hit a detached node · 4 times in one tour. All async
  overview fills now go through a `put()` guard that no-ops on a gone node;
  a test pins that they never regress to a bare assignment.
- **검색 empty state was a blank screen** · the one place a new user stalls.
  It is now a tutorial built from THIS vault: 3 rotating example questions,
  the real tag histogram (click to scope with `tag:`), the 5 most-recent
  notes (click to open), and an operator hint. Idle is the tutorial.
- **회상 list noise**: every plain note carried a meaningless "전체" type
  chip · the chip now shows only for real typed fragments.
- **현황 system card** dumped full absolute vault/DB paths (line-wrapped and
  ugly) · home-shortened to `~/…` with the full path on hover.
- **지식 empty pane** now shows `↑ ↓ 이동 · Enter 열기` so the keyboard
  navigation built last pass is discoverable instead of hidden.
- Re-verified live after each fix; JS errors 0 across the whole tour.

## Unreleased · usability pass: shortcuts everywhere, nothing ever lost

- **Data-driven shortcuts + ? help**: one table drives the key handler AND
  the ?-overlay (Tolaria's command-manifest pattern, console-sized). ⌘1-8
  jump between the eight views, ⌘N creates an Untitled note and lands in the
  editor, ⌘K stays the palette, Esc closes overlays. Bare keys never fire
  inside text fields.
- **Keyboard-first knowledge list**: ↑/↓ (or j/k) walk the visible note rows
  with wrap-around and scroll-into-view, Enter opens the note · the mouse
  becomes optional.
- **Leave-flush**: switching tab/note or closing the page inside the 1.5s
  autosave window no longer loses the typing tail · tab switches AWAIT the
  flush (so the read view shows what you just typed), page unload uses
  fetch keepalive.
- **Daemon adopts no strangers** (found live, again): a stale server already
  on the port made `daemon start` report success while the new process died
  on bind. /health now reports its pid and start() verifies the responder IS
  its own child · a foreign pid fails loudly with "port in use by pid N".
- All five flows browser-verified end-to-end (keynav-open, ⌘4 graph, ?
  overlay open/close, ⌘N-to-editor, leave-flush), JS errors 0.

## Unreleased · desktop-grade console: editor, wikilink nav, themes, graph

**The console stops being a dashboard and starts being a workspace** · the
Tolaria (Tauri/React desktop KB) UI was read at source level (504 component
tests, 145 e2e specs · the shortlist is in the commit) and codealmanac's
wiki viewer alongside; what fits a memory engine's console was absorbed, at
web-console cost instead of a desktop stack:

- **Note body + editor tabs** (지식 상세: 본문 | 편집 | 연결·색인). 본문 is
  rendered markdown from a small self-contained renderer (no CDN · headings,
  lists, task boxes, tables, fenced code, quotes, ==mark==, frontmatter as a
  folded block) with **clickable wikilinks** that navigate in-console. 편집
  is a real editor: ⌘S, Tab-indent, dirty state, **1.5s autosave debounce**
  (Tolaria's number), and **optimistic concurrency** · the mtime token from
  open travels back on save, a disk change under the editor 409s instead of
  being clobbered. Server side is one facade verb (`engine.write_note`) with
  path guard, git checkpoint, instant reindex, event-log entry.
- **⌘K create-from-query** (their quick-open affordance): a palette query
  matching nothing becomes the new note's title · Enter creates it and lands
  straight in the editor.
- **Light/dark theme toggle**, persisted, same semantic-token design system
  (one `:root[data-theme=light]` block · the variables were the theme system
  all along).
- **그래프 view**: the whole-vault interactive graph (`lemory graph`'s HTML)
  embedded as a console route (`GET /graph`).
- Backend: `GET /api/raw`, `PUT /api/note` (409 on stale token), engine verbs
  `read_note`/`write_note`. Everything browser-verified live: render →
  wikilink nav → edit → autosave → theme → graph, JS errors 0.
- Deliberately NOT absorbed (their desktop-app territory, our engine focus):
  BlockNote WYSIWYG, spreadsheets, whiteboards, multi-window. The console
  edits honestly in markdown source · Obsidian stays the rich editor.

## Unreleased · production architecture: engine / daemon / interfaces, enforced

**The layers are now real, and a test keeps them real** (docs/ARCHITECTURE.md).

- **Engine facade:** ~30 verbs on `Engine` (remember/recall/resume_case/
  consolidate/extract_skills/context/persona/…) are now the ONLY way the
  CLI, HTTP server, MCP, proxy and hooks reach domain logic. Every deep
  `from ..ingestion/..retrieval import` in the interface layer was removed
  (40+ call sites), including the private-helper leak
  (`_safe_target` → `engine.safe_path`, `_has_module` → `config.has_module`).
- **tests/test_architecture.py:** four boundary rules that fail CI on
  violation · interfaces call only the facade, the engine side never
  imports interfaces, daemon.py stays process-level (talks HTTP like any
  client), no private names cross module lines. The checker caught a real
  leak on its first run.
- **lemory.assistant:** the conversation service extracted out of the HTTP
  handlers (remember-intent, anaphora repair, grounded-turn assembly,
  proxy preamble) · the /api/assistant/chat handler is transport only now,
  and any future surface (TUI, bot) reuses the same service.
- **`lemory daemon start|stop|status|logs`:** a managed background server
  with pidfile + liveness (stale pidfiles after crash/reboot are detected
  and cleaned, never trusted), startup failure surfaces the log tail in
  the error, SIGTERM-then-KILL stop (WAL keeps the DB safe). Verified
  live: start → healthy in ~1s → logs → stop.
- **GET /health:** liveness+readiness in one call (version, watcher,
  auto-consolidate, proxy readiness, index counts, uptime) · the daemon's
  probe target, and anyone's monitoring hook.
- Found live during the smoke test: loopback probes must bypass
  HTTP(S)_PROXY env vars (ProxyHandler({})) · in proxy environments the
  daemon looked dead while uvicorn was up.

## Unreleased · competitiveness sweep: 103 review passes, 6 fixes (docs/REVIEW.md)

A full self-audit against the current market, item by item, with verdicts and
receipts · 72 fresh checkpoints plus the 31 regression-tested findings from
the previous passes. Ledger committed as docs/REVIEW.md. Fixed this pass:

- **Auto-consolidate (the #1 gap vs TDBAM's automatic pipeline):**
  `auto_consolidate = true` makes `lemory serve` promote new atoms up the
  pyramid on its own once they sit quiet for a few minutes · idle-debounce
  predicate unit-tested (burst→wait, idle→run, cursor→no-op), toggle read
  per tick so flipping it in Settings needs no restart, failures never kill
  the loop. Off by default: LLM spend stays an explicit opt-in.
- Scene naming: `general`/`undated` artifacts → `일반`, month tails stripped.
- Fully-local proxy documented: point `proxy_upstream` at Ollama's /v1 and
  the memory proxy runs with zero remote calls, model included.
- CLI Rich-markup injection: note titles/snippets in 4 more tables are now
  escaped (`[WIP] 설계` no longer breaks rendering).
- `proxy_capture`/`auto_consolidate` joined the console Settings (live PATCH).
- ROUTINE.ko: pyramid promotion added to the daily-routine doc.

## Unreleased · every surface gets the pyramid: proxy, panel UI, skills

**The pivot finishes only when the new memory reaches every place agents
actually live.** Three TDBAM territories absorbed, verified end-to-end:

- **Memory proxy (their MemoryProxy):** `lemory serve` now exposes an
  OpenAI-compatible `/v1/chat/completions` (+`/v1/models`). Change a baseURL
  and any SDK/script/IDE plugin gets memory: the pyramid boot (persona +
  scene map) and this turn's hybrid recall are injected as a system message,
  and the exchange is captured as a `chats/proxy/` session note that the
  next consolidate promotes. Streaming passes through (capture re-assembled
  from SSE deltas best-effort). The upstream key comes from config only ·
  a client's Authorization header is never forwarded. Live-verified against
  real OpenAI: a vanilla API call answered "배포 포트 15000, 8080은 사내
  프록시" from vault memory, and the capture note landed.
- **Skill extraction (their Skill asset):** `lemory skills extract` / MCP
  `extract_skills` runs finished cases (zero open errors) through their
  acceptance gate · recurring task class, executable by a stranger,
  transferable steps, otherwise write NOTHING. Passing cases become
  `스킬/<kebab-name>.md` with When-to-use/Workflow/Pitfalls sections,
  case-bound for incremental updates ("변경 없음" respected). Gate verified
  live: a thin 2-fragment case was correctly judged 없음 by the real model.
  Keyless mode extracts nothing by design · the judgment IS the feature.
- **Panel UI (their MemoryPanel):** the console 기억 view now shows the
  whole pyramid · persona card (L3), scene list with heat (L2), anchors,
  cases, skills, plus a "피라미드 통합" button that runs consolidate and
  reports what moved. New HTTP surface: `/api/persona`, `/api/scenes`,
  `/api/skills`, `POST /memory/consolidate`, `POST /memory/skills-extract`.
- MCP grows to 19 tools (`extract_skills` joins `consolidate_memory`).

## Unreleased · identity pivot: the memory pyramid (L2 scenes + L3 persona)

**Lemory is now, first, a long-term memory engine for AI agents.** The vault
stays the substrate; Obsidian becomes one integration among several.

The prompt was TencentDB Agent Memory (11.3k★). We cloned it and read the
pipeline at source level (785 files) instead of the marketing: their L2/L3
are Markdown files too, their retrieval routing is a tool budget rather than
a router, their "local mode" still requires a remote OpenAI-compatible model,
and their embedder ships disabled (FTS-only default). Full analysis in
docs/COMPETITIVE.md. What their design validated, we absorbed; where their
floor is weak, we differ:

- **`lemory consolidate` / MCP `consolidate_memory`:** one incremental pass
  promotes new L1 atoms (fact-sheet bullets + typed fragments) into L2
  **scene notes** (`장면/*.md` · scene_group/heat/summary frontmatter,
  UPDATE-first, `scene_cap` default 12 · at the cap the coldest scene
  absorbs instead of a new file appearing) and the L3 **persona note**
  (`페르소나.md` · 2000-char hard cap, incremental evolution, "변경 없음"
  respected as a first-class LLM outcome, no-speculation guard). Cursor-based
  (`pyramid_cursor` meta), so running it every session end is cheap and
  idempotent.
- **Offline floor they don't have:** with no LLM the scene body degrades to a
  deterministic sectioned digest (the `## 전개` trail still accumulates,
  never overwrites) and the persona to a ranked fact sheet. Their pipeline
  hard-requires a remote model; ours prefers one.
- **Top-down boot:** `vault_context` now leads with persona → scene map
  (heat-sorted, one line each) → anchors → open cases, and the MCP tool
  doc carries the drill-down budget (~3 searches/turn, then answer from what
  you have) · their auto-recall guide, absorbed as guidance instead of
  infrastructure.
- Scenes and persona are ordinary vault notes: hybrid retrieval, the link
  graph, the trash guard and the dashboard feed all see them with zero new
  storage paths.
- New bench `benchmarks/run_pyramid.py` (RoleMemQA, gpt-4o-mini pipeline,
  BENCHMARKS §14): always-on boot context 1,345 tokens = 1/48.8 of the raw
  dump, covering 0.347 of persona-fact questions by itself; one scene
  drill-down 0.667 @ 2,084 tokens; the search layer stays 1.000. Their
  PersonaMem +59% claim has no harness in their repo; every number here
  regenerates from this script.
- `mcp` extra pinned `<2` (mcp 2.0 moved `mcp.server.fastmcp`; the 1.x
  FastMCP surface is what `lemory mcp` targets).

## Unreleased · agent working memory: typed fragments, anchors, work threads

**An agent stops starting over, and the memory stays in your vault.**

The head-to-head prompt was AnchorMind (anchormind.net), a hosted long-term
memory MCP server for coding agents. Its fragment taxonomy is good, so it was
adopted verbatim rather than reinvented: an agent that learned
`type="decision"` elsewhere keeps the habit here, and fragment exports map
1:1. Everything underneath is ours. Full head-to-head in COMPETITIVE.

- **Typed fragments:** `remember(type=...)` writes one of `fact` ·
  `decision` · `error` · `preference` · `procedure` · `relation` ·
  `episode` as a Markdown note in the vault: visible in Obsidian
  immediately, hand-editable, git-diffable, deletable without an API call.
  An `error` is born `status: open`, so forgetting to mark it defaults to
  "still broken", which is the useful direction to be wrong in. No account,
  no fragment quota (AnchorMind caps at 5,000/account).
- **Scoped recall:** `type:`/`case:`/`status:`/`topic:` join `tag:`/`folder:`
  as ordinary search operators, backed by frontmatter, so the same scoping
  works from MCP, the CLI and the web search box. The narrowing selects
  candidates; the full hybrid retriever (BM25 + vectors + RRF + link graph +
  recency) still ranks them, rather than a lone pgvector cosine.
- **Work threads:** `case`/`phase`/`status` group fragments across sessions,
  and `resume_case` *reconstructs* the thread (timeline, decisions so far,
  still-unresolved errors, and the next steps the last session recorded)
  instead of just filtering rows. `list_cases` answers "what was I in the
  middle of?".
- **`reflect`:** session close-out writes one `episode` note whose touched
  notes become [[wikilinks]], making it a real node in the graph the
  retriever already walks.
- **Anchors:** `anchor_note` pins a note as core memory, and `vault_context`
  now leads with pinned anchors and open cases before the derived sections,
  because those two describe the *work* while the rest describes the vault.
- Surfaces: 6 new MCP tools (17 total), CLI `recall`/`case`/`cases`/`anchor`
  and a typed `remember`, HTTP `/memory/fragment` · `/api/recall` ·
  `/api/cases` · `/api/case` · `/memory/anchor` · `/api/anchors`, and a new
  **기억** console view (anchors, cases, case brief, typed recall).
- Fixes found while building it: recall returned the same fragment once per
  chunk; `open_cases` blanked a case's phase when the newest fragment omitted
  it; fragment excerpts showed flattened frontmatter ("date: ... source:
  assistant ...") because short notes rank via the enrichment pseudo-chunk,
  so display paths now ask for the prose; `lemory case` lost its `[open]`
  markers to Rich markup parsing.
- `meta` on the write path cannot forge `lemory_generated`/`lemory_pending`,
  so the trash guard and the approval gate stay honest.

## Unreleased · the memory loop closes: auto-remember, distill, messy-chat bench

**A conversation is now a memory without anyone doing anything.**

- **Session auto-save (write half of the loop):** every console-assistant
  conversation persists as a dated session note in `chats/` - a plain,
  visible, editable Markdown file. Toggle: `assistant_log_sessions`
  (console: 답변 생성 › 비서 대화 기억). The skill teaches external
  assistants the same policy via `lemory remember`.
- **`lemory distill` (opt-in):** chat sessions → fact-sheet notes
  (기억요약/) with [[wikilink]] provenance, on-device Gemma, retraction-
  aware. Measured honestly on the messy bench: +3.1pt answer-presence at
  rank 1, mixed elsewhere - profile in BENCHMARKS §7e; stays opt-in.
- **RoleMemQA-messy:** retractions, joke-fakes, and vocabulary-poisoning
  small talk, all code-verified. Keyless hybrid: retraction recall 1.000
  (zero stale traps), overall doc@1 0.820 vs 0.984 clean - the honest cost
  of noise, and the target the loop features are measured against.
- **AgentMemQA:** the general-agent memory axis (work/coding assistant, 5
  projects x 12 weeks, mixed KR/EN tech sessions, scored reversed-decision
  traps). Hybrid doc@1 0.956 > vector 0.911 > bm25 0.889. Drove two fixes:
  최종/결국 join the recency lexicon, and the corpus-wide vague-recency
  multiplier is gentler (0.6x) while the pin choice keeps full strength.
  Counter-finding: the reranker is temporally blind (decision 0.80 -> 0.50
  with it ON) - documented in BENCHMARKS §7f.
- New demo: `demo4_memoryloop.gif` - day-1 fact, day-30 recall in 4ms with
  citation, replayed from real pipeline output.

## Unreleased · roleplay memory, exact-recall vectors, linear mention pass

**Lemory measured as a roleplay long/short-term memory store, and two silent
recall taxes removed.**

- **RoleMemQA (new benchmark, §7e):** 8 personas × 30 dated chat sessions,
  144 code-verified questions over 7 memory types (short/long/episodic/
  preference-update/temporal/2-hop/abstention). Keyless hybrid **doc@1 0.984**
  (update-type 1.000 with zero stale-preference traps), above its own vector
  (0.938) and BM25 (0.820) legs; opt-in reranker 0.992.
- **Memory-timeline recency:** vague-recency queries ("요즘 ...") now anchor at
  the vault's newest note instead of the wall clock, and the verbatim-pin
  choice is recency-weighted - an archival or resumed chat vault keeps its
  internal order (RoleMemQA update doc@1 0.625 → 1.000).
- **Boilerplate-aware fusion:** when every query content token is
  corpus-common (chat greetings/reactions), the verbatim machinery abstains
  and BM25 is damped in fusion (`common_bm25_damp`, vector leg required).
- **Exact-recall vectors by default up to 60k chunks:** IVF at the old 20k
  threshold silently cost -4.5 pt vector doc@8 at 42k chunks (0.900 vs 0.945
  exact) and varied between builds. `ann_threshold` 20k → 60k, `ann_nprobe`
  48 → 256 past it. KorMapleQA doc@8 **0.889 → 0.899**, doc@1 0.628 → 0.641
  (masked +6.5 pt); the honest cost is ~0.11 s/query at 42k chunks.
- **Linear mention detection:** unlinked-mention scanning replaced the
  per-title regex loop (O(text × titles) - hours at 57k docs) with a
  pure-Python Aho-Corasick automaton with identical word-boundary semantics
  (~24 s for the same corpus). BEIR-scale ingests no longer appear to hang.
- **Dated daily notes get the title boost:** numeric date-stamp tokens no
  longer veto title-boost coverage ("2023-09-12 Meeting with Steph").
- LOCOMO gains a key-free retrieval table (§7, hybrid 0.771 evidence-recall);
  BEIR §4i and the qmd-329 rematch re-measured under the exact regime
  (rematch 0.875 → 0.887 vs qmd's 0.769).

## 0.3.0 · Korean-tuned e5 default (0.889 doc@8), one-command setup, on-device Gemma, no Ollama

**Better retrieval, simpler stack, one way in.** The keyless local default is now a
Korean-tuned e5 embedder that measures **hybrid doc@8 0.889 on KorMapleQA** -
above the old MiniLM default (0.788) and the llama.cpp Harrier tier
(0.853), second only to the Gemini config (0.906). Onboarding collapsed to a
single command (`lemory up`). On-device answers moved to
Gemma 4 on llama.cpp (GPU everywhere: Metal / CUDA / Vulkan / CPU offload), now
selectable in the web dashboard. A dedicated reranker is available but ships
**off** - measured, a small reranker doesn't help a strong embedder (details
below). Ollama and LiteRT-LM are gone.

### Local embeddings

- **The default local embedder is dragonkue's Korean-tuned
  `multilingual-e5-small-ko-v2`** (fastembed, 384d), replacing MiniLM. Registered
  from a community ONNX export so it stays pure-Python and torch-free, ~9 ms/embed,
  no native compile. Measured **hybrid doc@8 0.889 on the full KorMapleQA v2**
  (2,067) - above MiniLM's 0.788 **and the 1024-d Harrier's 0.853**, and it never
  lost to Harrier on the English/long-doc corpora tested. `local_embed_backend =
  "auto"` picks it everywhere.
- **Chunk size tuned to the embedder's window: `chunk_chars` 1400 → 882.**
  882 characters ≈ 512 tokens of Korean (measured 1.70 char/token), exactly the
  e5-small-ko-v2 context window - the largest chunk it encodes in full, so no
  content is truncated before embedding while each chunk stays maximally coherent.
  A full sweep on KorMapleQA (700–2200 chars) showed note-level doc@8 is flat
  within noise across the range (the 1024-token BM25 leg covers whatever the
  vector leg truncates), so we picked the principled point; 1400 happened to sit
  at the sweep's low. e5's Korean re-measurement lifts the local dense leg sharply
  - vector-only doc@8 0.149 → 0.863, masked-entity 0.461 → 0.777, 2-hop
  full-support 0.141 → 0.477 (now ahead of qmd's 0.333).
- **Harrier-OSS-0.6B is now an option, not the default.** The in-process
  llama.cpp Qwen3-based embedder (doc@8 0.853) measured *below* e5-small-ko-v2 and
  is heavier (~640 MB GGUF, ~100 ms/query), so it is demoted to an explicit
  choice (`local_embed_backend = "llamacpp"`); llama.cpp's job in the best-local
  stack is now the Gemma 4 *answer* model, not embeddings.

### Retrieval quality

- **Dedicated cross-encoder reranker** (`reranker = true`) - available but
  **off by default, and here is the honest reason.** On the full KorMapleQA v2
  over the e5 default (chunk 882): no reranker doc@1 0.628 / doc@8 0.889 (~16 ms/q);
  Qwen3-Reranker-0.6B doc@1 **0.605** (it *hurt* - a 0.6B reranker second-guessing
  an already-correct top result) at ~1.9 s/q. (An earlier fastembed jina-reranker-v2
  path, since retired, bought ~+1 pt doc@8 at ~40x latency.) A strong embedder +
  BM25 + link-graph fusion already ranks well, so retrieval ships without a
  reranker; `reranker` stays an opt-in precision knob.

### On-device answers & assistant

- **Local answers with no key, no daemon.** `lemory ask` and the web console's
  search view answer fully on-device via **Gemma 4** on llama.cpp (Q4_K_M GGUF -
  E4B default, switch to the lighter E2B in the console; `pip install
  "lemory[llama]"`). The answer model shares the engine with the embedder and
  reranker; it runs with an 8192-token context and the RAG prompt is fit to it.
- **Voice assistant mode** in the web console: grounded chat over the vault with
  local STT (faster-whisper) and on-device neural TTS (Supertonic), streamed
  sentence-by-sentence - no cloud round-trip. `pip install "lemory[assistant]"`.
### Onboarding & web console

- **One command to start: `lemory up`.** Onboarding was scattered across three
  overlapping commands - `init` (config only), `setup` (interactive wizard), and
  `up` (auto). Now there is one way: `lemory up` prompts for the vault when run
  bare, `lemory up ~/Vault` runs zero-question for scripts, `--key <KEY>` selects
  Gemini. It auto-detects the best mode and offers to install `lemory[llama]` for
  Gemma answers; the old number-menu is gone. `init`/`setup` remain as hidden
  deprecated aliases that forward to `up`.
- **Pick the answer model in the dashboard.** Settings gained a **Models** card -
  the one place to see and switch the on-device answer LLM (Gemma 4 E4B ⇄ E2B,
  with size/context/GPU shown) and read the resolved embedding and reranker
  identities. Previously the model toggle was buried in the assistant view - and
  silently broken: its switch request omitted the JSON `Content-Type`, so the
  server rejected it with 422. Fixed.

### Removed

- **Ollama is gone entirely.** No server to install, run, or `pull` from - the
  `ollama` provider, the `ollama_*` config keys, and the Ollama setup mode were
  removed.
- **LiteRT-LM dropped for a single llama.cpp engine.** An earlier build ran
  answers on Google's LiteRT-LM; consolidating on llama.cpp gives one GPU
  runtime for embeddings + reranker + answers across Mac/Linux/Windows, and
  retired the fastembed ONNX reranker path too.

### Benchmark

- **KorMapleQA v2**: question phrasing de-monotonized (the share ending in the
  identical `~은 무엇인가?` dropped 72% to 12%, varied by answer type) and the
  seeded typo now lands on the entity rather than the question word. Every
  zero-key system re-measured; ranking and story unchanged (all moved
  <2.5 doc@8 points). Published at github.com/jwgo/KorMapleQA.

## 0.2.0 · Korean-first retrieval, second-brain behaviors, KorMapleQA

### Retrieval quality (Korean)

- **CJK bigram indexing.** The Hangul bigram machinery now also covers kana
  and CJK ideographs, so mixed-script runs (`ナイトロード나이트로드`) and
  JMS/CMS name tables match instead of collapsing into one unmatchable token.
- **Morphology-aware verbatim detection.** IDF-weighted coverage over a
  top-8 BM25 window lets a quoted rare identifier carry the verbatim gate;
  jamo-level stem matching survives conjugation and 띄어쓰기 variation;
  question furniture (`~한 인물은?`) is stripped before scoring.
- **Reciting pin + covering-chunk anchor.** When a query recites a note,
  BM25's own top-3 ordering is preserved and the single best-covering chunk
  is pinned to the top wherever BM25 ranked it (masked-entity identifiers
  often sit at rank 4-8).
- **Syllable-level Korean typo repair.** `메플이스토리` corrects to
  메이플스토리 (Damerau-Levenshtein over syllables); first-syllable typos are
  reached via a second-character index. Corrections apply as spans over the
  original query so they can never corrupt a longer indexed word.
- **Lexical-evidence graph expansion.** A linked neighbor whose chunk already
  ranks in BM25 survives the expansion ceiling and gets the boost, gated by
  the stronger of cosine or BM25 rank.
- KorQuAD 1.0 recall@1 is now 0.940, ahead of pure BM25 (0.928) for the first
  time. Big Korean corpora: the BM25 leg is ~5.6x faster after dropping
  interior query unigrams.

### Second-brain behaviors

- **`save_memory` consolidation.** Every new memory is checked against the
  vault; related notes get `related:` wikilinks and near-duplicates get a
  `possible_duplicate_of:` flag. Links, does not rewrite.
- **`lemory suggest-links`** (+ MCP `suggest_links`): unlinked mentions as
  actionable `[[link]]` proposals with the mention's sentence.
- **`lemory graph`**: the whole vault as one self-contained interactive HTML
  knowledge graph, ~1s for 1,469 notes, zero LLM calls.
- **`lemory skill install claude-code|codex|cursor`**: writes a SKILL.md so
  the assistant treats the vault as long-term memory.
- **`lemory drift`**: broken wikilinks, dead file links, and unresolved
  duplicate flags, with `--prompt` rendering an agent-ready repair prompt.

### Benchmarks

- **KorMapleQA** (`benchmarks/data/kormapleqa/`): a new 2,075-question,
  100%-code-generated, machine-verified Korean RAG benchmark over the real
  namuwiki MapleStory domain (1,469 documents). Seven question types plus
  verified-absent abstention.
- Measured the memory-system field on it: qmd (3 modes), MemPalace, mem0,
  Smart-Connections-class, Omnisearch. On identical questions Lemory ties
  qmd's headline local-LLM mode at ~3,000x the speed and beats mem0 on every
  axis with an embeddings-only ingest.

### Fixes (from a high-effort review of the release diff)

- Korean typo replacement is span-based (no more corrupting a longer word
  that shares a substring).
- `lemory graph` HTML-escapes note-derived strings and splits `</` in the
  inline JSON (a note titled `</script>` can no longer break the export).
- `save_memory` YAML-escapes titles in the frontmatter it writes.
- `lemory skill` rejects unknown actions instead of silently installing.
- The graph sim-floor gates on max(cosine, BM25-rank), so a tail hit can't
  push an unrelated linked note into results.
- Lexical structures are background-warmed at index time on large vaults, so
  the first search doesn't pay a full-vocabulary scan inline.

## 0.1.0 · Initial

Local memory middleware: hybrid retrieval (vector + BM25 + wikilink graph)
on a SQLite + numpy stack, MCP read/write tools, dashboard with the AI
memory feed and undo, keyless / local / Gemini / Ollama modes, IVF-int8 for
million-chunk vaults, and the reproducible benchmark suite in BENCHMARKS.md.
