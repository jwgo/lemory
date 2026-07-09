"""Real-world scenario: a live watcher keeps up with a vault being edited.

Simulates a working session — notes created, edited, renamed, deleted (Korean
and English) while the watchdog watcher runs — and asserts retrieval reflects
every change. This is the "connect Obsidian and it just runs" contract.
"""

from __future__ import annotations

import threading
import time

import pytest

from lemory.ingestion import watch


def _wait(predicate, timeout=15.0, interval=0.2):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def watched(engine):
    t = threading.Thread(target=watch, args=(engine,), kwargs={"debounce": 0.4}, daemon=True)
    engine.index()
    t.start()
    time.sleep(0.3)  # let the observer arm
    yield engine
    # watcher thread is daemon; test process exit reaps it


def test_live_session(watched, vault):
    eng = watched

    # 1. new note appears -> searchable
    (vault / "Sourdough Experiments.md").write_text(
        "Third attempt at high-hydration sourdough. The poolish fermented 14 hours.",
        encoding="utf-8",
    )
    assert _wait(lambda: any(
        h.title == "Sourdough Experiments" for h in eng.search("sourdough poolish", k=5)
    )), "new note never became searchable"

    # 2. Korean note with Korean filename -> searchable via Korean query
    (vault / "김치 실험 일지.md").write_text(
        "배추김치 3차 담금. 이번에는 새우젓을 두 배로 넣었고 소금은 천일염을 썼다.",
        encoding="utf-8",
    )
    assert _wait(lambda: any(
        h.title == "김치 실험 일지" for h in eng.search("새우젓 김치", k=5)
    )), "korean note never became searchable"

    # 3. edit an existing note -> new content wins, stale content gone
    (vault / "Sourdough Experiments.md").write_text(
        "Fourth attempt. Switched to a stiff levain, 62% hydration, overnight retard.",
        encoding="utf-8",
    )
    assert _wait(lambda: any(
        "levain" in h.text for h in eng.search("stiff levain hydration", k=5)
    )), "edit never picked up"
    hits = eng.search("sourdough", k=8)
    assert not any("poolish" in h.text for h in hits), "stale chunk still indexed"

    # 4. rename -> old title disappears, new title searchable, links intact
    (vault / "Sourdough Experiments.md").rename(vault / "Bread Lab.md")
    assert _wait(lambda: any(
        h.title == "Bread Lab" for h in eng.search("stiff levain hydration", k=5)
    )), "renamed note not found under new title"
    assert not any(h.title == "Sourdough Experiments" for h in eng.search("levain", k=8))

    # 5. delete -> unreachable
    (vault / "김치 실험 일지.md").unlink()
    assert _wait(lambda: not any(
        h.title == "김치 실험 일지" for h in eng.search("새우젓 김치", k=8)
    )), "deleted note still retrievable"

    # 6. rapid successive edits collapse into a consistent final state
    p = vault / "Scratch.md"
    for i in range(5):
        p.write_text(f"draft {i} of the quarterly plan, revision token R{i}", encoding="utf-8")
        time.sleep(0.05)
    assert _wait(lambda: any(
        "R4" in h.text for h in eng.search("quarterly plan revision", k=5)
    )), "final rapid-edit state not indexed"
    final_hits = [h for h in eng.search("quarterly plan revision", k=8) if h.title == "Scratch"]
    assert final_hits and all("R4" in h.text for h in final_hits)


def test_wikilink_created_live(watched, vault):
    eng = watched
    (vault / "Trip Planning.md").write_text(
        "Booked flights for the workshop. Details in [[Dana Petrov]]'s itinerary note.",
        encoding="utf-8",
    )
    def linked():
        docs = {d.title: d.id for d in eng.store.all_docs()}
        if "Trip Planning" not in docs:
            return False
        nbrs = eng.store.neighbors([docs["Trip Planning"]]).get(docs["Trip Planning"], [])
        return any(dst == docs.get("Dana Petrov") for dst, _, _ in nbrs)
    assert _wait(linked), "live wikilink edge never appeared"
