"""Memory pyramid: L1 atoms → L2 scene notes → L3 persona note.

TencentDB Agent Memory's four-tier design (L0 conversation → L1 atom →
L2 scenario → L3 persona), reimplemented on Lemory's substrate. Their own
architecture validates the substrate choice: TDBAM also stores L2/L3 as plain
Markdown files (`scene_blocks/*.md`, `persona.md`) · only the bottom tiers
live in SQLite. Lemory already had L0 (chat session notes) and L1
(`lemory distill` fact sheets); this module adds the top half:

  L2  scene notes (장면/*.md)   one living narrative per ongoing context ·
                                a work case, a relationship, a project
  L3  persona note (페르소나.md) one stable profile of the user, ≤2000 chars

Policies absorbed from their measured lessons (see docs/COMPETITIVE.md):
  * UPDATE-first: new atoms fold into an existing scene; creating a scene is
    the exception. A hard scene cap (cfg.scene_cap) forces consolidation ·
    when full, the coldest scene absorbs instead of a new file appearing.
  * heat: every update bumps the scene's heat; the boot context sorts by it.
  * persona hard cap (cfg.persona_max_chars) + "변경 없음" as a first-class
    LLM outcome + no-speculation guard.
  * cursor-based promotion: only atoms newer than the stored cursor are
    consolidated, so `lemory consolidate` is incremental and idempotent.

Where we deliberately differ:
  * Their distillation REQUIRES an OpenAI-compatible API (their "local mode"
    still calls a remote model). Ours degrades: with no LLM the scene body
    becomes a sectioned digest and the persona a ranked fact sheet ·
    structure without narrative, still searchable, still injectable.
  * Their default retrieval is FTS-only (embedder ships disabled). Scenes
    and persona here are ordinary vault notes: the full hybrid retriever
    (BM25 + vectors + graph + recency) sees them the moment they're written.
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger("lemory.pyramid")

_FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_BULLET_RE = re.compile(r"^\s*[-*•]\s*(.+)$")
_CURSOR_KEY = "pyramid_cursor"

_SCENE_PROMPT = (
    "너는 기억 통합 아키텍트다. 아래 '기존 장면 노트'에 '새 기억'을 녹여 "
    "장면 노트를 다시 써라.\n"
    "규칙:\n"
    "- 형태: 목록 나열이 아니라 연결된 서사. '## 핵심 서사'(무슨 일이 있었고 "
    "지금 어디까지 왔나, 400자 이내), '## 선호와 패턴', '## 전개'(큰 변화만 "
    "누적 기록, 덮어쓰지 마라), '## 미해결' 섹션을 쓴다.\n"
    "- 전체 1500자 이내. 새 기억과 모순되는 옛 내용은 최신 값으로 고치되, "
    "'## 전개'에 바뀐 흔적을 남겨라.\n"
    "- 기억에 없는 내용을 지어내지 마라.\n"
    "- 본문만 출력하라 (frontmatter 없이, '# 제목' 없이).\n\n"
    "[기존 장면 노트]\n{current}\n\n[새 기억]\n{atoms}\n"
)

_PERSONA_PROMPT = (
    "너는 페르소나 아키텍트다. 아래 '현재 페르소나'를 '새 기억'으로 점진 "
    "갱신하라.\n"
    "규칙:\n"
    "- 구조: 첫 줄은 사용자를 한 문장으로 요약한 원형(archetype). 이어서 "
    "'## 기본 정보', '## 선호', '## 대화 방식'(어떻게 말 걸어야 하는가, "
    "지뢰는 무엇인가), '## 판단 기준'(무엇을 중시해 결정하는가).\n"
    "- 전체 {cap}자 이내. 넘칠 것 같으면 덜 중요한 항목을 버려라.\n"
    "- 추측 금지: 기억에 근거 없는 성격 묘사를 쓰지 마라. 정보가 없는 "
    "섹션은 비워도 된다.\n"
    "- 새 기억이 기존 내용을 바꾸지 않으면 정확히 '변경 없음'만 출력하라.\n"
    "- 본문만 출력하라 (frontmatter 없이).\n\n"
    "[현재 페르소나]\n{current}\n\n[새 기억]\n{atoms}\n"
)


@dataclass
class Atom:
    """One promotable memory unit: an L1 digest bullet or a typed fragment."""
    text: str
    group: str          # scene binding key: case > digest group > 'general'
    kind: str           # fragment type or 'digest'
    mtime: float
    source: str = ""    # note title for provenance wikilinks


@dataclass
class ConsolidateReport:
    atoms: int = 0
    scenes_updated: list[str] = field(default_factory=list)
    scenes_created: list[str] = field(default_factory=list)
    scenes_absorbed: int = 0    # atoms folded into the coldest scene (cap hit)
    persona: str = ""           # written path, or "" (unchanged / no atoms)
    llm: bool = True            # False = deterministic fallback bodies


# ---------------------------------------------------------------- collection

def _read(vault: Path, rel: str) -> str:
    try:
        return (vault / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


def collect_atoms(engine, since: float) -> list[Atom]:
    """Atoms newer than the cursor, from both L1 surfaces:

    * 기억요약 digests (`memory-digest` tag): each bullet is an atom, grouped
      by the digest's slug (one digest group ≈ one relationship/context).
    * typed fragments (frontmatter `type:`): the fragment body is one atom,
      grouped by its `case` when present.

    Episodes are skipped · they are session records, and their durable content
    already exists as decisions/errors/next-steps fragments.
    """
    vault = engine.cfg.resolved_vault()
    meta = engine.store.docs_meta()
    out: list[Atom] = []
    for d in engine.store.all_docs():
        if d.mtime <= since:
            continue
        fm = meta.get(d.id, {})
        tags = d.tags or []
        if "memory-digest" in tags:
            body = _FM_RE.sub("", _read(vault, d.path))
            group = re.sub(r"^기억\s+", "", d.title)
            group = re.sub(r"\s+\d{4}-\d{2}$", "", group).strip() or "general"
            for line in body.splitlines():
                m = _BULLET_RE.match(line)
                if m and not m.group(1).startswith("출처"):
                    out.append(Atom(m.group(1).strip(), group, "digest",
                                    d.mtime, d.title))
            continue
        ftype = str(fm.get("type", "") or "")
        if ftype and ftype != "episode":
            body = _FM_RE.sub("", _read(vault, d.path)).strip()
            if not body:
                continue
            group = str(fm.get("case", "") or "").strip() or "general"
            out.append(Atom(body[:500], group, ftype, d.mtime, d.title))
    out.sort(key=lambda a: a.mtime)
    return out


# -------------------------------------------------------------------- scenes

def _scene_slug(group: str) -> str:
    s = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", group)
    return re.sub(r"\s+", " ", s).strip()[:60] or "general"


def load_scenes(engine) -> list[dict]:
    """Existing scene notes with their pyramid frontmatter."""
    folder = engine.cfg.scene_folder.strip("/")
    meta = engine.store.docs_meta()
    scenes = []
    for d in engine.store.all_docs():
        if not d.path.startswith(folder + "/"):
            continue
        fm = meta.get(d.id, {})
        scenes.append({
            "path": d.path, "title": d.title,
            "group": str(fm.get("scene_group", "") or d.title),
            "heat": int(fm.get("heat", 1) or 1),
            "summary": str(fm.get("summary", "") or ""),
            "mtime": d.mtime,
        })
    return scenes


def _fallback_scene_body(current_body: str, atoms: list[Atom]) -> str:
    """Keyless/no-LLM scene body: a sectioned digest. Structure without
    narrative · honest about what a zero-LLM pass can produce."""
    prefs = [a.text for a in atoms if a.kind in ("preference", "digest")]
    facts = [a.text for a in atoms if a.kind in ("fact", "relation")]
    work = [a.text for a in atoms if a.kind in ("decision", "error", "procedure")]
    today = datetime.now().date().isoformat()

    # carry forward the existing 전개 section so history accumulates
    trail = ""
    m = re.search(r"## 전개\n(.*?)(?=\n## |\Z)", current_body, re.DOTALL)
    if m:
        trail = m.group(1).strip()
    parts = []
    if prefs:
        parts.append("## 선호와 패턴\n" + "\n".join(f"- {p}" for p in prefs[:12]))
    if facts:
        parts.append("## 사실\n" + "\n".join(f"- {f}" for f in facts[:12]))
    if work:
        parts.append("## 진행\n" + "\n".join(f"- {w}" for w in work[:12]))
    trail_lines = ([trail] if trail else []) + [f"- {today}: 기억 {len(atoms)}건 통합"]
    parts.append("## 전개\n" + "\n".join(trail_lines[-8:]))
    return "\n\n".join(parts)


def _summary_of(body: str) -> str:
    """Scene index line: first non-heading sentence, clipped."""
    for line in body.splitlines():
        t = line.strip().lstrip("-#• ").strip()
        if len(t) > 8:
            return t[:80]
    return ""


def _write_scene(engine, rel: str, group: str, body: str, heat: int) -> None:
    vault = engine.cfg.resolved_vault()
    today = datetime.now().date().isoformat()
    summary = _summary_of(body)
    text = (
        f"---\ndate: {today}\nsource: consolidate\nlemory_generated: true\n"
        f'scene_group: "{group}"\nheat: {heat}\nsummary: "{summary}"\n'
        f"tags: [scene]\n---\n\n# {Path(rel).stem}\n\n{body.strip()}\n"
    )
    target = vault / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _update_scene(engine, scene: dict | None, group: str, atoms: list[Atom],
                  use_llm: bool) -> tuple[str, bool]:
    """Fold atoms into a scene (existing or new). Returns (rel_path, created)."""
    vault = engine.cfg.resolved_vault()
    folder = engine.cfg.scene_folder.strip("/")
    if scene:
        rel, heat = scene["path"], scene["heat"] + 1
        current = _FM_RE.sub("", _read(vault, rel)).strip()
        current = re.sub(r"^#\s.*\n", "", current).strip()
    else:
        rel, heat = f"{folder}/{_scene_slug(group)}.md", 1
        current = "(새 장면)"

    atom_lines = "\n".join(f"- [{a.kind}] {a.text}" for a in atoms[:30])
    body = ""
    if use_llm:
        try:
            out = engine.llm.generate(
                _SCENE_PROMPT.format(current=current[:3000], atoms=atom_lines),
                temperature=0.0, max_output_tokens=1024)
            body = str(out).strip()[:2400]
        except Exception as e:
            log.warning("scene generation failed for %s: %s", group, e)
    if not body:
        body = _fallback_scene_body(current, atoms)
    _write_scene(engine, rel, group, body, heat)
    return rel, scene is None


# ------------------------------------------------------------------- persona

def _fallback_persona(current: str, atoms: list[Atom], cap: int) -> str:
    """No-LLM persona: preference/fact atoms merged into the existing sheet,
    newest last, capped. A ranked fact sheet, not a narrative."""
    keep = [a.text for a in atoms if a.kind in ("preference", "digest", "fact")]
    if not keep:
        return ""
    lines = [ln for ln in current.splitlines()
             if ln.startswith("- ")] if current else []
    for k in keep:
        if f"- {k}" not in lines:
            lines.append(f"- {k}")
    body = "## 선호와 사실\n" + "\n".join(lines)
    return body[:cap]


def update_persona(engine, atoms: list[Atom], use_llm: bool) -> str:
    """Incrementally evolve the persona note. Returns the written vault-relative
    path, or "" when nothing changed ("변경 없음" is a first-class outcome)."""
    if not atoms:
        return ""
    vault = engine.cfg.resolved_vault()
    rel = engine.cfg.persona_note.strip("/")
    cap = engine.cfg.persona_max_chars
    current = _FM_RE.sub("", _read(vault, rel)).strip()
    current = re.sub(r"^#\s.*\n", "", current).strip()

    atom_lines = "\n".join(f"- [{a.kind}] {a.text}" for a in atoms[:60])
    body = ""
    if use_llm:
        try:
            out = str(engine.llm.generate(
                _PERSONA_PROMPT.format(current=current or "(비어 있음)",
                                       atoms=atom_lines, cap=cap),
                temperature=0.0, max_output_tokens=1200)).strip()
            if out == "변경 없음" or not out:
                return ""
            body = out[:cap]
        except Exception as e:
            log.warning("persona generation failed: %s", e)
    if not body:
        body = _fallback_persona(current, atoms, cap)
        if not body:
            return ""

    today = datetime.now().date().isoformat()
    target = vault / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"---\ndate: {today}\nsource: consolidate\nlemory_generated: true\n"
        f"tags: [persona]\n---\n\n# 페르소나\n\n{body.strip()}\n",
        encoding="utf-8",
    )
    return rel


# ----------------------------------------------------------------- top level

def consolidate(engine, use_llm: bool | None = None) -> ConsolidateReport:
    """One promotion pass: new atoms → scenes (UPDATE-first, capped) → persona.

    Incremental via a stored cursor; safe to run on every session end. The
    LLM is used when available (their pipeline REQUIRES one; ours prefers
    one), otherwise the deterministic fallback bodies keep the tiers alive.
    """
    if use_llm is None:
        use_llm = not engine.keyless
    cursor = float(engine.store.get_meta(_CURSOR_KEY) or 0.0)
    now = time.time()
    atoms = collect_atoms(engine, since=cursor)
    rep = ConsolidateReport(atoms=len(atoms), llm=use_llm)
    if not atoms:
        return rep

    scenes = load_scenes(engine)
    by_group: dict[str, list[Atom]] = defaultdict(list)
    for a in atoms:
        by_group[a.group].append(a)

    cap = max(1, engine.cfg.scene_cap)
    written: set[str] = set()
    for group, group_atoms in sorted(by_group.items()):
        target = next((s for s in scenes if s["group"] == group), None)
        if target is None and len(scenes) >= cap:
            # cap hit: the coldest scene absorbs instead of a new file
            # appearing (their red-tier rule, deterministic edition)
            target = min(scenes, key=lambda s: (s["heat"], s["mtime"]))
            rep.scenes_absorbed += len(group_atoms)
        rel, created = _update_scene(engine, target, group, group_atoms, use_llm)
        written.add(rel)
        (rep.scenes_created if created else rep.scenes_updated).append(rel)
        if created:
            scenes.append({"path": rel, "title": Path(rel).stem, "group": group,
                           "heat": 1, "summary": "", "mtime": now})

    persona_rel = update_persona(engine, atoms, use_llm)
    if persona_rel:
        rep.persona = persona_rel
        written.add(persona_rel)

    if written:
        engine.index(paths=written)
    engine.store.set_meta(_CURSOR_KEY, str(now))
    if engine.cfg.event_log:
        engine.store.log_event(
            "memory", client="consolidate", path=persona_rel or "",
            detail={"atoms": rep.atoms, "scenes": len(written)})
    return rep


def scene_index(engine, limit: int = 10) -> list[dict]:
    """The L2 navigation map: hot scenes first, one line each. This is what
    the boot context injects · cheap, cacheable, drill-down by read_note."""
    scenes = load_scenes(engine)
    scenes.sort(key=lambda s: (-s["heat"], -s["mtime"]))
    return [{"path": s["path"], "title": s["title"], "heat": s["heat"],
             "summary": s["summary"]} for s in scenes[:limit]]


def persona_block(engine, max_chars: int = 1200) -> str:
    """The L3 injection: persona body, clipped. Empty string when absent."""
    vault = engine.cfg.resolved_vault()
    body = _FM_RE.sub("", _read(vault, engine.cfg.persona_note.strip("/")))
    body = re.sub(r"^#\s.*\n", "", body.strip()).strip()
    return body[:max_chars]
