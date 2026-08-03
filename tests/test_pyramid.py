"""Memory pyramid: L1 atoms → L2 scenes → L3 persona (`lemory consolidate`)."""
from __future__ import annotations

import pytest

from lemory.ingestion.fragments import remember
from lemory.ingestion.pyramid import (
    collect_atoms,
    consolidate,
    persona_block,
    scene_index,
)


def _digest(engine, name: str, bullets: list[str]) -> None:
    v = engine.cfg.resolved_vault()
    (v / "기억요약").mkdir(exist_ok=True)
    (v / "기억요약" / f"기억 {name} 2026-07.md").write_text(
        "---\ndate: 2026-07-01\nsource: distill\nlemory_generated: true\n"
        "tags: [memory-digest]\n---\n\n# 기억 " + name + " 2026-07\n\n"
        + "\n".join(f"- {b}" for b in bullets) + "\n\n출처: [[대화]]\n",
        encoding="utf-8")
    engine.index()


def test_collect_atoms_from_digests_and_fragments(engine):
    engine.index()
    _digest(engine, "지훈", ["여동생 이름은 김보람", "복숭아 알레르기가 있다"])
    remember(engine, "배포 포트는 15000", type="fact", case="배포")
    remember(engine, "세션 요약", type="episode", case="배포")  # skipped

    atoms = collect_atoms(engine, since=0.0)
    texts = {a.text for a in atoms}
    assert "여동생 이름은 김보람" in texts
    assert "배포 포트는 15000" in texts
    assert "세션 요약" not in texts          # episodes are not atoms
    groups = {a.group for a in atoms}
    assert "지훈" in groups and "배포" in groups


def test_consolidate_fallback_writes_scene_and_persona(engine):
    """Keyless path: no LLM, still real scene + persona notes."""
    engine.index()
    _digest(engine, "지훈", ["복숭아 알레르기가 있다"])
    remember(engine, "답변은 항상 한국어로", type="preference", case="지훈")

    rep = consolidate(engine, use_llm=False)
    assert rep.atoms >= 2 and not rep.llm
    assert rep.scenes_created and rep.persona == "페르소나.md"

    v = engine.cfg.resolved_vault()
    scene = (v / rep.scenes_created[0]).read_text(encoding="utf-8")
    assert "scene_group:" in scene and "heat: 1" in scene
    assert "복숭아 알레르기" in scene
    persona = (v / "페르소나.md").read_text(encoding="utf-8")
    assert "한국어" in persona
    # both tiers are ordinary notes: immediately searchable
    assert any(h.path == "페르소나.md" for h in engine.search("한국어 답변 선호", k=5))


def test_consolidate_is_incremental(engine):
    engine.index()
    _digest(engine, "지훈", ["복숭아 알레르기가 있다"])
    assert consolidate(engine, use_llm=False).atoms >= 1
    # second run with nothing new: cursor makes it a no-op
    rep2 = consolidate(engine, use_llm=False)
    assert rep2.atoms == 0 and not rep2.scenes_updated and not rep2.persona


def test_consolidate_updates_existing_scene_and_bumps_heat(engine):
    engine.index()
    remember(engine, "포트는 15000", type="fact", case="배포")
    consolidate(engine, use_llm=False)
    remember(engine, "헬스체크는 /health", type="fact", case="배포")
    rep = consolidate(engine, use_llm=False)

    assert rep.scenes_updated and not rep.scenes_created
    idx = scene_index(engine)
    assert len(idx) == 1 and idx[0]["heat"] == 2
    body = (engine.cfg.resolved_vault() / idx[0]["path"]).read_text(encoding="utf-8")
    assert "헬스체크는 /health" in body


def test_scene_cap_absorbs_instead_of_creating(engine):
    engine.index()
    engine.cfg.scene_cap = 2
    for i, case in enumerate(["a안건", "b안건", "c안건"]):
        remember(engine, f"{case} 관련 사실 {i}", type="fact", case=case)
    rep = consolidate(engine, use_llm=False)
    assert len(scene_index(engine)) <= 2
    assert rep.scenes_absorbed >= 1


def test_consolidate_with_llm_narrative_and_persona_nochange(engine, monkeypatch):
    engine.index()
    remember(engine, "포트는 15000", type="fact", case="배포")

    calls = []
    def fake_generate(prompt, **k):
        calls.append(prompt)
        if "페르소나 아키텍트" in prompt:
            return "변경 없음"
        return ("## 핵심 서사\n배포 작업에서 포트를 15000으로 확정했다.\n\n"
                "## 전개\n- 2026-07: 포트 확정")
    monkeypatch.setattr(engine.llm, "generate", fake_generate)

    rep = consolidate(engine, use_llm=True)
    assert rep.llm and rep.scenes_created
    assert rep.persona == ""            # "변경 없음" is a first-class outcome
    body = (engine.cfg.resolved_vault() / rep.scenes_created[0]).read_text(
        encoding="utf-8")
    assert "핵심 서사" in body


def test_llm_failure_degrades_to_fallback(engine, monkeypatch):
    engine.index()
    remember(engine, "포트는 15000", type="fact", case="배포")
    monkeypatch.setattr(engine.llm, "generate",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("api down")))
    rep = consolidate(engine, use_llm=True)
    assert rep.scenes_created            # scene still written, fallback body
    body = (engine.cfg.resolved_vault() / rep.scenes_created[0]).read_text(
        encoding="utf-8")
    assert "포트는 15000" in body


def test_persona_hard_cap(engine):
    engine.index()
    for i in range(60):
        remember(engine, f"선호 항목 {i}: " + "아주 긴 설명 " * 10,
                 type="preference", title=f"선호 {i}")
    consolidate(engine, use_llm=False)
    body = persona_block(engine, max_chars=10_000)
    assert 0 < len(body) <= engine.cfg.persona_max_chars


def test_context_block_leads_with_persona_and_scenes(engine):
    from lemory.ingestion.memory import context_block

    engine.index()
    remember(engine, "답변은 한국어로", type="preference", case="스타일")
    consolidate(engine, use_llm=False)

    block = context_block(engine, max_chars=4000)
    assert "## Persona" in block and "## Scenes" in block
    assert block.index("## Persona") < block.index("## Scenes")
    assert block.index("## Scenes") < block.index("## Recent notes")


def test_scene_trail_accumulates_in_fallback(engine):
    """전개 section must accumulate, not overwrite (their evolution-trail rule)."""
    engine.index()
    remember(engine, "1차 사실", type="fact", case="누적")
    consolidate(engine, use_llm=False)
    remember(engine, "2차 사실", type="fact", case="누적")
    consolidate(engine, use_llm=False)
    body = (engine.cfg.resolved_vault() / scene_index(engine)[0]["path"]).read_text(
        encoding="utf-8")
    assert body.count("기억") >= 2 and "## 전개" in body


def test_persona_note_is_protected_by_trash_guard(engine):
    """persona is lemory_generated → undoable via the standard trash path."""
    from lemory.ingestion.memory import trash_ai_note

    engine.index()
    remember(engine, "한국어 선호", type="preference")
    consolidate(engine, use_llm=False)
    moved = trash_ai_note(engine, "페르소나.md")
    assert moved.startswith(".trash/")
