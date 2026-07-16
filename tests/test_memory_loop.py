"""The write half of the memory loop: assistant conversations become dated
session notes in the vault (assistant_log_sessions), so what the user tells
the assistant today is retrievable tomorrow."""
from __future__ import annotations

import lemory.providers.gemma as gemma
from lemory.ingestion.chat_import import log_assistant_session


def test_log_assistant_session_writes_and_indexes(engine):
    engine.index()
    msgs = [{"role": "user", "content": "참, 우리 여동생 이름은 김보람이야."}]
    rel = log_assistant_session(engine, msgs, "기억할게요! 보람님이시군요.", session="abc123")
    assert rel and rel.startswith("chats/") and rel.endswith("abc123.md")
    note = engine.cfg.resolved_vault() / rel
    assert note.exists()
    body = note.read_text(encoding="utf-8")
    assert "**나**: 참, 우리 여동생 이름은 김보람이야." in body
    assert "**AI**: 기억할게요" in body
    assert "lemory_generated: true" in body
    # the fact is immediately retrievable — the loop is closed
    hits = engine.search("여동생 이름", k=3)
    assert hits and any("어시스턴트" in h.title for h in hits)


def test_log_assistant_session_upserts_same_conversation(engine):
    engine.index()
    msgs = [{"role": "user", "content": "오늘 마라탕 먹었어."}]
    rel1 = log_assistant_session(engine, msgs, "맛있었겠네요!", session="s1")
    msgs2 = msgs + [{"role": "assistant", "content": "맛있었겠네요!"},
                    {"role": "user", "content": "내일은 초밥 먹을 거야."}]
    rel2 = log_assistant_session(engine, msgs2, "좋은 계획이에요.", session="s1")
    assert rel1 == rel2  # same conversation, same note (rolling upsert)
    body = (engine.cfg.resolved_vault() / rel2).read_text(encoding="utf-8")
    assert body.count("마라탕") == 1 and "초밥" in body


def test_log_assistant_session_respects_toggle(engine):
    engine.cfg.assistant_log_sessions = False
    rel = log_assistant_session(engine, [{"role": "user", "content": "비밀이야."}],
                                "네.", session="off")
    assert rel is None
    assert not (engine.cfg.resolved_vault() / "chats").exists()


def test_log_folder_never_escapes_vault(engine):
    engine.cfg.assistant_log_folder = "../밖"
    rel = log_assistant_session(engine, [{"role": "user", "content": "테스트"}],
                                "네.", session="esc")
    assert rel.startswith("chats/")  # clamped back inside the vault


def test_assistant_chat_endpoint_logs_session(client, engine, monkeypatch):
    engine.index()
    monkeypatch.setattr(gemma, "chat_stream",
                        lambda *a, **k: iter(["기억", "했어요"]))
    r = client.post("/api/assistant/chat",
                    json={"messages": [{"role": "user", "content": "내 고향은 통영이야."}],
                          "session": "e2e1"})
    assert r.status_code == 200
    assert '"done": true' in r.text and "e2e1.md" in r.text  # logged path in final event
    chats = list((engine.cfg.resolved_vault() / "chats").glob("*e2e1.md"))
    assert len(chats) == 1
    assert "통영" in chats[0].read_text(encoding="utf-8")
