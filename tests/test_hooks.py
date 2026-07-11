"""Automatic session capture: transcript parsing, capture, settings installer."""

import json

from lemory.interfaces.hooks import (
    capture_session,
    install_claude_code,
    parse_transcript,
    uninstall_claude_code,
)


def _transcript(tmp_path, n_turns=6):
    p = tmp_path / "transcript.jsonl"
    lines = []
    for i in range(n_turns):
        lines.append(json.dumps({"type": "user", "message": {
            "role": "user", "content": f"결제 모듈 리팩터링 어떻게 할까? 배경 설명 {i} " + "x" * 80}}))
        lines.append(json.dumps({"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": f"Stripe 어댑터를 분리하기로 결정 {i} " + "y" * 80}]}}))
    lines.append(json.dumps({"type": "system", "subtype": "meta"}))  # ignored
    lines.append("not json at all")                                  # ignored
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def test_parse_transcript_extracts_dialogue(tmp_path):
    text = parse_transcript(_transcript(tmp_path))
    assert "USER: 결제 모듈" in text and "ASSISTANT: Stripe" in text
    assert "not json" not in text and "meta" not in text
    assert parse_transcript(tmp_path / "missing.jsonl") == ""


def test_capture_session_saves_memory(engine, vault, tmp_path):
    engine.index()
    t = _transcript(tmp_path)
    saved = capture_session(engine, {"transcript_path": str(t), "cwd": "/work/billing"})
    assert saved and saved.startswith("memories/sessions/")
    body = (vault / saved).read_text(encoding="utf-8")
    assert "source: claude-code session" in body
    # attributed in the middleware timeline
    evts = engine.store.events(kinds=["memory"])
    assert evts and evts[0]["client"] == "claude-code-hook"


def test_capture_skips_trivial_and_keyless(engine, tmp_path, monkeypatch):
    engine.index()
    tiny = tmp_path / "tiny.jsonl"
    tiny.write_text(json.dumps({"message": {"role": "user", "content": "hi"}}))
    assert capture_session(engine, {"transcript_path": str(tiny)}) is None
    assert capture_session(engine, {}) is None
    monkeypatch.setattr(type(engine), "keyless", property(lambda self: True))
    assert capture_session(engine, {"transcript_path": str(_transcript(tmp_path))}) is None


def test_installer_is_idempotent_and_preserves(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"model": "opus", "hooks": {
        "SessionEnd": [{"hooks": [{"type": "command", "command": "other-tool run"}]}]}}))
    install_claude_code(vault=tmp_path / "v", settings_path=sp)
    install_claude_code(vault=tmp_path / "v2", settings_path=sp)  # re-run updates in place
    data = json.loads(sp.read_text())
    assert data["model"] == "opus"                       # untouched settings
    cmds = [h["command"] for g in data["hooks"]["SessionEnd"] for h in g["hooks"]]
    assert "other-tool run" in cmds                      # other hooks preserved
    lemory_cmds = [c for c in cmds if "lemory hook claude-code" in c]
    assert len(lemory_cmds) == 1 and str(tmp_path / "v2") in lemory_cmds[0]
    assert sp.with_suffix(".json.bak").exists()

    assert uninstall_claude_code(settings_path=sp)
    data = json.loads(sp.read_text())
    cmds = [h["command"] for g in data["hooks"]["SessionEnd"] for h in g["hooks"]]
    assert cmds == ["other-tool run"]
    assert not uninstall_claude_code(settings_path=sp)   # nothing left to remove


def test_privacy_exclusion_frontmatter(engine, vault):
    engine.index()
    p = vault / "secret.md"
    p.write_text("---\nlemory: false\n---\n# secret\nthe launch code is 7742",
                 encoding="utf-8")
    engine.index()
    assert engine.store.get_doc_by_path("secret.md") is None
    assert all(h.path != "secret.md" for h in engine.search("launch code 7742", k=5))
    # flag added AFTER indexing removes it from the index
    p.write_text("# secret\nthe launch code is 7742", encoding="utf-8")
    engine.index()
    assert engine.store.get_doc_by_path("secret.md") is not None
    p.write_text("---\nlemory: false\n---\n# secret\nthe launch code is 7742",
                 encoding="utf-8")
    engine.index()
    assert engine.store.get_doc_by_path("secret.md") is None
