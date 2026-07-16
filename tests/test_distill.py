"""`lemory distill` — chat sessions → fact-sheet notes inside the vault."""
from __future__ import annotations

from lemory.ingestion.distill import distill


def _chat_note(date: str, body: str) -> str:
    return (f"---\ndate: {date}\nsource: roleplay\ntags: [chat-import]\n---\n\n"
            f"# 대화 {date}\n\n{body}\n")


def _setup(engine, monkeypatch, llm_out: str):
    v = engine.cfg.resolved_vault()
    (v / "chats").mkdir(exist_ok=True)
    (v / "chats" / "2025-03-02 대화 a.md").write_text(
        _chat_note("2025-03-02", "**나**: 우리 여동생 이름은 김보람이야."),
        encoding="utf-8")
    (v / "chats" / "2025-03-09 대화 b.md").write_text(
        _chat_note("2025-03-09", "**나**: 나 복숭아 알레르기 있어."),
        encoding="utf-8")
    engine.index()
    monkeypatch.setattr(engine.llm, "generate", lambda *a, **k: llm_out)


def test_distill_writes_digest_and_indexes(engine, monkeypatch):
    _setup(engine, monkeypatch,
           "- 사용자의 여동생 이름은 김보람\n- 사용자는 복숭아 알레르기가 있다")
    written = distill(engine)
    assert len(written) == 1 and written[0].startswith("기억요약/")
    note = engine.cfg.resolved_vault() / written[0]
    body = note.read_text(encoding="utf-8")
    assert "- 사용자의 여동생 이름은 김보람" in body
    assert "[[2025-03-02 대화 a]]" in body  # provenance wikilinks
    assert "lemory_generated: true" in body
    # the digest is a plain note: immediately searchable
    hits = engine.search("여동생 이름", k=3)
    assert hits and any(h.title.startswith("기억 ") for h in hits)


def test_distill_skips_non_chat_notes(engine, monkeypatch):
    v = engine.cfg.resolved_vault()
    (v / "일반노트.md").write_text("# 일반\n여동생 얘기지만 채팅이 아님.",
                                  encoding="utf-8")
    engine.index()
    monkeypatch.setattr(engine.llm, "generate", lambda *a, **k: "- 뭔가")
    assert distill(engine) == []  # no chat-import notes -> nothing distilled


def test_distill_none_output_writes_nothing(engine, monkeypatch):
    _setup(engine, monkeypatch, "없음")
    assert distill(engine) == []
    assert not (engine.cfg.resolved_vault() / "기억요약").glob("*.md") or \
        not list((engine.cfg.resolved_vault() / "기억요약").glob("*.md"))


def test_distill_out_folder_clamped_inside_vault(engine, monkeypatch):
    _setup(engine, monkeypatch, "- 사실 하나")
    written = distill(engine, out_folder="../밖")
    assert written and written[0].startswith("기억요약/")
