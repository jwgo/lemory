"""Connector SDK: user-owned scripts → ordinary vault notes."""

import json

from lemory.ingestion.connectors import run_connector

FETCH_SRC = '''
def fetch():
    return [
        {"title": "주간 회의", "body": "예산은 300만원으로 확정.", "date": "2026-07-01",
         "tags": ["회의"]},
        {"title": "빈 항목", "body": ""},  # skipped: no body
    ]
'''

PULL_SRC = '''
def pull(state):
    seen = state.get("cursor", 0)
    items = [{"id": f"item-{i}", "title": f"항목 {i}", "body": f"내용 {i}번."}
             for i in range(seen, 3)]
    return items, {"cursor": 3}
'''

EVIL_SRC = '''
def fetch():
    return [{"id": "../../밖으로", "title": "탈출 시도", "body": "x"}]
'''


def test_fetch_connector_writes_and_indexes(engine, tmp_path):
    script = tmp_path / "meetings.py"
    script.write_text(FETCH_SRC, encoding="utf-8")
    rep = run_connector(engine, script)
    assert rep.written == ["가져옴/meetings/주간 회의.md"]
    assert rep.skipped == 1
    note = engine.cfg.resolved_vault() / rep.written[0]
    text = note.read_text(encoding="utf-8")
    assert "source: connector:meetings" in text and "date: 2026-07-01" in text
    hits = engine.search("주간 회의 예산", k=3)
    assert hits and hits[0].title == "주간 회의"
    # idempotent: re-run overwrites, no duplicates
    rep2 = run_connector(engine, script)
    assert rep2.written == rep.written


def test_pull_connector_persists_state(engine, tmp_path):
    script = tmp_path / "feed.py"
    script.write_text(PULL_SRC, encoding="utf-8")
    rep = run_connector(engine, script)
    assert len(rep.written) == 3
    state = json.loads(engine.store.get_meta("connector_state:feed"))
    assert state == {"cursor": 3}
    # second run starts from the cursor — nothing new
    rep2 = run_connector(engine, script)
    assert rep2.written == []


def test_connector_path_escape_is_blocked(engine, tmp_path):
    script = tmp_path / "evil.py"
    script.write_text(EVIL_SRC, encoding="utf-8")
    rep = run_connector(engine, script)
    # the unsafe id is sanitized into a safe filename INSIDE the vault
    assert all(p.startswith("가져옴/evil/") for p in rep.written)
    vault = engine.cfg.resolved_vault()
    outside = vault.parent / "밖으로.md"
    assert not outside.exists()
