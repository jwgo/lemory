"""Skill extraction: finished work threads → reusable SKILL.md notes.

TDBAM's third memory asset. Their measured lessons, absorbed:

  * "Doing nothing is a first-class, correct outcome" · most passes should
    write nothing. The LLM must answer 없음 unless the thread clears a gate.
  * The gate (their acceptance rules, condensed): a skill must name a
    RECURRING class of task (never `fix-issue-1234`), be executable by a
    future agent that never saw this conversation, and abstract transferable
    steps · a chat summary or a project diary is not a skill.
  * Class-level kebab-case names, one file per skill, incremental update
    with "변경 없음" respected · same policy as the persona note.

Lemory's substrate twist: the evidence is the case system. A case whose
errors are all resolved IS a completed workflow with its decisions, failures
and fixes already structured as typed fragments · far cleaner input than raw
chat. Output lands in `스킬/*.md` (frontmatter `skill: true`), indexed like
any note, so recall/search find skills the moment they exist.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

log = logging.getLogger("lemory.skills")

_FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_NAME_RE = re.compile(r"^[a-z0-9가-힣][a-z0-9가-힣-]{2,60}$")

_PROMPT = (
    "너는 스킬 큐레이터다. 아래는 한 작업 스레드(케이스)의 기록이다. 이 "
    "스레드에서 '미래의 에이전트가 재사용할 수 있는 스킬'이 나오는지 판정하고, "
    "나오면 SKILL 문서를 써라.\n"
    "게이트 (하나라도 아니면 스킬이 아니다):\n"
    "- 반복되는 종류의 작업인가? (일회성 사건이면 아님)\n"
    "- 이 대화를 못 본 에이전트가 문서만 보고 실행할 수 있는가?\n"
    "- 구체 값이 아니라 옮겨 쓸 수 있는 절차·판단 규칙을 담는가?\n"
    "채팅 요약, 프로젝트 일지, 상태 보고는 스킬이 아니다.\n\n"
    "스킬이 아니면 정확히 '없음'만 출력하라.\n"
    "스킬이면 첫 줄에 'name: <클래스 수준 kebab-case 이름>' (예: "
    "port-conflict-triage · 'fix-issue-1234'류 금지), 그 다음 줄부터 본문:\n"
    "## 언제 쓰나\n## 언제 쓰지 않나\n## 절차\n(번호 매긴 구체 단계)\n"
    "## 판단 규칙\n## 함정\n"
    "전체 1200자 이내.{current}\n\n[케이스 기록]\n{evidence}\n"
)

_CURRENT_HINT = (
    "\n\n[기존 스킬 문서] · 이미 같은 스킬이 있다. 새 기록이 문서를 실질적으로 "
    "개선할 때만 갱신하고, 아니면 정확히 '변경 없음'만 출력하라:\n{body}"
)


def _case_evidence(engine, case: str) -> tuple[str, list[str]]:
    """One case's fragments as gate-ready evidence text + source titles."""
    from ..retrieval.recall import resume_case

    thread = resume_case(engine, case)
    lines = [f"케이스: {case}"]
    if thread["decisions"]:
        lines.append("결정:\n" + "\n".join(f"- {d}" for d in thread["decisions"]))
    vault = engine.cfg.resolved_vault()
    titles = []
    for f in thread["fragments"]:
        titles.append(f["note"])
        try:
            body = _FM_RE.sub("", (vault / f["path"]).read_text(encoding="utf-8"))
        except OSError:
            continue
        lines.append(f"[{f['type'] or 'note'}] {body.strip()[:500]}")
    return "\n\n".join(lines)[:6000], titles


def _sanitize_name(raw: str) -> str:
    s = raw.strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9가-힣-]", "", s).strip("-")[:60]
    return s if _NAME_RE.match(s) else ""


def extract_skills(engine, cases: list[str] | None = None,
                   out_folder: str = "스킬") -> list[str]:
    """Run the gate over cases (default: every case with ≥2 fragments and no
    open errors · a thread still failing is not a finished workflow yet).
    Returns vault-relative paths written. Requires an LLM: a skill without
    the judgment pass would just be a case dump, and a case dump is exactly
    what the gate exists to reject · so keyless mode extracts nothing."""
    from ..retrieval.recall import open_cases

    if engine.keyless:
        log.info("skill extraction skipped: no LLM available (the gate IS the feature)")
        return []
    if cases is None:
        cases = [c["case"] for c in open_cases(engine, limit=50)
                 if c["fragments"] >= 2 and c["open"] == 0]
    if not cases:
        return []

    vault = engine.cfg.resolved_vault()
    base = vault / out_folder
    if not base.resolve().is_relative_to(vault.resolve()):
        out_folder, base = "스킬", vault / "스킬"

    written: list[str] = []
    for case in cases:
        evidence, titles = _case_evidence(engine, case)
        if not titles:
            continue
        existing = _existing_skill_for(engine, case, out_folder)
        current = ""
        if existing:
            try:
                body = (vault / existing).read_text(encoding="utf-8")
                current = _CURRENT_HINT.format(body=_FM_RE.sub("", body)[:2000])
            except OSError:
                pass
        try:
            out = str(engine.llm.generate(
                _PROMPT.format(evidence=evidence, current=current),
                temperature=0.0, max_output_tokens=1024)).strip()
        except Exception as e:
            log.warning("skill extraction failed for case %s: %s", case, e)
            continue
        if out in ("없음", "변경 없음") or not out:
            continue
        m = re.match(r"name:\s*(.+)", out)
        if not m:
            continue
        name = _sanitize_name(m.group(1))
        if not name:
            continue
        body = out[m.end():].strip()[:2400]
        if len(body) < 80:  # a gate pass with no substance is a gate failure
            continue
        rel = existing or f"{out_folder}/{name}.md"
        today = datetime.now().date().isoformat()
        sources = " ".join(f"[[{t}]]" for t in dict.fromkeys(titles[:8]))
        base.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_text(
            f"---\ndate: {today}\nsource: skill-extract\nlemory_generated: true\n"
            f'skill: true\nskill_case: "{case}"\ntags: [skill]\n---\n\n'
            f"# {name}\n\n{body}\n\n출처: {sources}\n",
            encoding="utf-8",
        )
        written.append(rel)
    if written:
        engine.index(paths=set(written))
        if engine.cfg.event_log:
            for rel in written:
                engine.store.log_event("memory", client="skill-extract", path=rel,
                                       detail={"skill": True})
    return written


def _existing_skill_for(engine, case: str, folder: str) -> str:
    """The skill note already bound to this case, if any (incremental update
    beats a second file with a synonymous name)."""
    meta = engine.store.docs_meta()
    for d in engine.store.all_docs():
        if not d.path.startswith(folder + "/"):
            continue
        fm = meta.get(d.id, {})
        if str(fm.get("skill_case", "") or "").strip().lower() == case.strip().lower():
            return d.path
    return ""


def list_skills(engine, folder: str = "스킬") -> list[dict]:
    meta = engine.store.docs_meta()
    out = []
    for d in engine.store.all_docs():
        if not d.path.startswith(folder + "/"):
            continue
        fm = meta.get(d.id, {})
        if fm.get("skill"):
            out.append({"path": d.path, "name": d.title,
                        "case": str(fm.get("skill_case", "") or "")})
    return sorted(out, key=lambda s: s["name"])
