"""Chat-export import + PDF ingestion + usage prior."""

import json

import pytest

from lemory.ingestion.chat_import import import_conversations


CHATGPT_EXPORT = [{
    "title": "쿠버네티스 트러블슈팅",
    "create_time": 1740000000,
    "mapping": {
        "a": {"message": {"author": {"role": "user"},
                          "content": {"parts": ["파드가 CrashLoopBackOff인데 왜?"]},
                          "create_time": 1740000001}},
        "b": {"message": {"author": {"role": "assistant"},
                          "content": {"parts": ["대개 라이브니스 프로브 실패나 OOMKilled 입니다."]},
                          "create_time": 1740000002}},
        "sys": {"message": {"author": {"role": "system"},
                            "content": {"parts": ["hidden"]},
                            "create_time": 1740000000}},
    },
}]

CLAUDE_EXPORT = [{
    "name": "Weekly planning",
    "created_at": "2026-03-05T09:00:00Z",
    "chat_messages": [
        {"sender": "human", "text": "이번 주 우선순위 정리해줘"},
        {"sender": "assistant", "text": "1) 벤치마크 마감 2) 콘솔 배포"},
    ],
}]


def test_import_chatgpt_export(engine, vault, tmp_path):
    engine.index()
    f = tmp_path / "conversations.json"
    f.write_text(json.dumps(CHATGPT_EXPORT), encoding="utf-8")
    written = import_conversations(engine, f)
    assert len(written) == 1
    text = (vault / written[0]).read_text(encoding="utf-8")
    assert "source: chatgpt" in text and "CrashLoopBackOff" in text
    assert "hidden" not in text  # system messages dropped
    assert "2025-02-19" in written[0] or "2025-02-20" in written[0]  # tz-dependent day
    hits = engine.search("파드 크래시 원인", k=4)
    assert any(h.path == written[0] for h in hits)
    # idempotent: second run adds nothing
    assert import_conversations(engine, f) == []


def test_import_claude_export(engine, vault, tmp_path):
    engine.index()
    f = tmp_path / "claude.json"
    f.write_text(json.dumps(CLAUDE_EXPORT), encoding="utf-8")
    written = import_conversations(engine, f, folder="ai-chats")
    assert written == ["ai-chats/2026-03-05 Weekly planning.md"]
    assert "벤치마크 마감" in (vault / written[0]).read_text(encoding="utf-8")


def test_import_rejects_garbage(engine, tmp_path):
    engine.index()
    f = tmp_path / "x.json"
    f.write_text(json.dumps([{"whatever": 1}]), encoding="utf-8")
    with pytest.raises(ValueError):
        import_conversations(engine, f)


def _tiny_pdf(path, text="Hello PDF budget report"):
    """Minimal valid one-page PDF (computed xref) with a text content stream."""
    stream = f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode()
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode()
    path.write_bytes(bytes(out))


def test_pdf_ingestion_opt_in(engine, vault):
    _tiny_pdf(vault / "report.pdf")
    engine.index()
    assert engine.store.get_doc_by_path("report.pdf") is None  # off by default

    engine.cfg.index_pdf = True
    engine.index()
    assert engine.store.get_doc_by_path("report.pdf") is not None
    hits = engine.search("PDF budget report", k=4)
    assert any(h.path == "report.pdf" for h in hits)


def test_usage_prior_reranks(engine):
    engine.index()
    engine.cfg.usage_prior = 0.0
    base = engine.search("pricing dashboard notes", k=4)
    assert len(base) >= 2
    # heavily "use" the second-ranked note, enable the prior, expect a nudge up
    target = base[1]
    for _ in range(30):
        engine.store.record_hits([target.doc_id])
    engine.cfg.usage_prior = 5.0  # exaggerated to make the flip deterministic
    boosted = engine.search("pricing dashboard notes", k=4)
    assert boosted[0].doc_id == target.doc_id
    engine.cfg.usage_prior = 0.0
