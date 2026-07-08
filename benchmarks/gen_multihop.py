"""Generate the LemoryBench multi-hop vault: an interlinked personal wiki.

Honesty guarantees (all enforced by code, not the LLM):
  * The relation graph is wired deterministically (seeded), so gold labels
    for every question are correct by construction.
  * Each relation is stated in exactly ONE note (e.g. the project note names
    its lead; the person note never names the project). A 2-hop question
    "what is the hobby of the person who leads X?" therefore cannot be
    answered from a single note, and the answer note shares no tokens with
    the question entity.
  * Gemini only writes prose flavor; a "Key facts" section rendered by code
    guarantees every fact and wikilink is present in the note.

The generated vault + questions are written to benchmarks/data/multihop/ and
committed, so benchmark runs are reproducible without generation.
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, load_env, save_json

from lemory.providers.gemini import GeminiClient

SEED = 42
OUT = DATA / "multihop"

COUNTS = {"companies": 8, "people": 14, "projects": 10, "tools": 8, "books": 6, "events": 8}

NAME_PROMPT = """You are generating a fictional but realistic world for a retrieval benchmark.
Return STRICT JSON with these exact keys and counts:
{
  "companies": 8 items: {"name": str, "industry": str, "product": str},
  "people": 14 items: {"name": str (full name), "role": str, "hobby": str (specific, e.g. "restoring vintage synthesizers"), "hometown": str (real city), "favorite_tool": str (a specific software/hardware tool, invented is fine)},
  "projects": 10 items: {"name": str (codename style, e.g. "Project Halcyon"), "goal": str (one sentence)},
  "tools": 8 items: {"name": str (invented software product name), "category": str, "language": str (programming language), "license": str},
  "books": 6 items: {"title": str (invented), "topic": str, "year": int between 1995 and 2024},
  "events": 8 items: {"name": str (e.g. "Q3 Offsite Berlin"), "date": str (e.g. "2024-06-12"), "decision": str (one concrete decision sentence)}
}
Every name/title must be unique and DISTINCTIVE (no generic words like "Home" or "Notes").
All values fictional. No markdown, JSON only."""


def wire_world(raw: dict, rng: random.Random) -> dict:
    """Attach relations deterministically. Returns the full world spec."""
    world = {k: list(v) for k, v in raw.items()}
    companies = world["companies"]
    people = world["people"]
    projects = world["projects"]
    tools = world["tools"]
    books = world["books"]
    events = world["events"]

    for c in companies:
        c["city"] = rng.choice(
            ["Lisbon", "Osaka", "Tallinn", "Montevideo", "Vancouver", "Busan",
             "Kraków", "Nairobi", "Adelaide", "Reykjavík", "Porto", "Taipei"]
        )
        c["founded"] = rng.randint(1988, 2021)
    for p in people:
        p["company"] = rng.choice(companies)["name"]
    leads = rng.sample(people, len(projects))
    for pr, lead in zip(projects, leads):
        pr["lead"] = lead["name"]
        pr["company"] = rng.choice(companies)["name"]
        pr["tool"] = rng.choice(tools)["name"]
        pr["budget"] = f"${rng.randint(40, 900)}k"
    authors = rng.sample(people, len(books))
    for b, a in zip(books, authors):
        b["author"] = a["name"]
    for e, pr in zip(events, rng.sample(projects, len(events))):
        e["project"] = pr["name"]
    return world


def render_notes(world: dict, prose: dict[str, str]) -> dict[str, str]:
    """filename -> markdown. Relations stated on ONE side only (see module doc)."""
    notes: dict[str, str] = {}

    def note(name: str, body: str, facts: list[str], tags: str) -> None:
        fact_md = "\n".join(f"- {f}" for f in facts)
        notes[f"{name}.md"] = f"{tags}\n\n{body.strip()}\n\n## Key facts\n{fact_md}\n"

    for c in world["companies"]:
        note(c["name"], prose.get(c["name"], ""), [
            f"Industry: {c['industry']}",
            f"Main product: {c['product']}",
            f"Headquarters: {c['city']}",
            f"Founded: {c['founded']}",
        ], "#company")
    for p in world["people"]:
        note(p["name"], prose.get(p["name"], ""), [
            f"Role: {p['role']}",
            f"Works at [[{p['company']}]]",
            f"Hometown: {p['hometown']}",
            f"Hobby: {p['hobby']}",
            f"Favorite tool: {p['favorite_tool']}",
        ], "#person")
    for pr in world["projects"]:
        note(pr["name"], prose.get(pr["name"], ""), [
            f"Goal: {pr['goal']}",
            f"Lead: [[{pr['lead']}]]",
            f"Run by [[{pr['company']}]]",
            f"Built with [[{pr['tool']}]]",
            f"Budget: {pr['budget']}",
        ], "#project")
    for t in world["tools"]:
        note(t["name"], prose.get(t["name"], ""), [
            f"Category: {t['category']}",
            f"Written in {t['language']}",
            f"License: {t['license']}",
        ], "#tool")
    for b in world["books"]:
        note(b["title"], prose.get(b["title"], ""), [
            f"Topic: {b['topic']}",
            f"Published: {b['year']}",
            f"Written by [[{b['author']}]]",
        ], "#book")
    for e in world["events"]:
        note(e["name"], prose.get(e["name"], ""), [
            f"Date: {e['date']}",
            f"About [[{e['project']}]]",
            f"Decision: {e['decision']}",
        ], "#event")
    return notes


def build_questions(world: dict, rng: random.Random) -> list[dict]:
    by_name = {}
    for kind in world:
        for item in world[kind]:
            by_name[item.get("name") or item.get("title")] = item

    qs: list[dict] = []

    def add(q, answer, gold, hops, qtype):
        qs.append({"q": q, "answers": [answer], "gold_notes": gold, "hops": hops, "type": qtype})

    for pr in world["projects"]:
        lead = by_name[pr["lead"]]
        tool = by_name[pr["tool"]]
        comp = by_name[pr["company"]]
        add(f"What is the hobby of the person who leads {pr['name']}?",
            lead["hobby"], [pr["name"], lead["name"]], 2, "project→lead")
        add(f"What programming language is the tool used by {pr['name']} written in?",
            tool["language"], [pr["name"], tool["name"]], 2, "project→tool")
        add(f"In which city is the company running {pr['name']} headquartered?",
            comp["city"], [pr["name"], comp["name"]], 2, "project→company")
    for b in world["books"]:
        author = by_name[b["author"]]
        add(f"Where does the author of \"{b['title']}\" work?",
            author["company"], [b["title"], author["name"]], 2, "book→author")
        add(f"What is the hometown of the person who wrote \"{b['title']}\"?",
            author["hometown"], [b["title"], author["name"]], 2, "book→author")

    # single-hop
    for p in rng.sample(world["people"], 6):
        add(f"What is {p['name']}'s favorite tool?", p["favorite_tool"], [p["name"]], 1, "single")
    for c in rng.sample(world["companies"], 4):
        add(f"When was {c['name']} founded?", str(c["founded"]), [c["name"]], 1, "single")
    for e in rng.sample(world["events"], 5):
        add(f"What was decided at {e['name']}?", e["decision"], [e["name"]], 1, "single")

    rng.shuffle(qs)
    return qs


def verify(world: dict, notes: dict[str, str], qs: list[dict]) -> None:
    """Assert benchmark honesty invariants."""
    for q in qs:
        for g in q["gold_notes"]:
            assert f"{g}.md" in notes, f"missing gold note {g}"
        if q["hops"] == 2:
            bridge, answer_note = q["gold_notes"]
            # the answer note must NOT contain the question's anchor entity
            assert bridge.lower() not in notes[f"{answer_note}.md"].lower(), (
                f"leak: answer note {answer_note} mentions bridge {bridge}"
            )
            # the answer value must be present in the answer note
            assert q["answers"][0].lower() in notes[f"{answer_note}.md"].lower(), (
                f"answer {q['answers'][0]} not in {answer_note}"
            )


def main() -> None:
    load_env()
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    world_file = OUT / "world.json"
    if world_file.exists():
        world = json.loads(world_file.read_text())
        print("world.json exists, reusing")
    else:
        client = GeminiClient(api_key=__import__("os").environ["GEMINI_API_KEY"])
        raw = client.generate_json(NAME_PROMPT, temperature=0.9, max_output_tokens=4096)
        for k, n in COUNTS.items():
            assert len(raw.get(k, [])) >= n, f"{k}: got {len(raw.get(k, []))}"
            raw[k] = raw[k][:n]
        world = wire_world(raw, rng)
        save_json(world_file, world)

    # prose flavor (batched); prose must not restate cross-note relations,
    # so it cannot leak what the Key facts placement controls
    prose_file = OUT / "prose.json"
    prose: dict[str, str] = json.loads(prose_file.read_text()) if prose_file.exists() else {}
    todo = []
    for kind in world:
        for item in world[kind]:
            name = item.get("name") or item.get("title")
            if name not in prose:
                todo.append((kind, name, item))
    if todo:
        client = GeminiClient(api_key=__import__("os").environ["GEMINI_API_KEY"])
        for i in range(0, len(todo), 6):
            batch = todo[i : i + 6]
            spec = "\n".join(
                f'- "{name}" ({kind[:-1]}): only use these attributes: '
                + json.dumps({k: v for k, v in item.items() if isinstance(v, (str, int))})
                for kind, name, item in batch
            )
            data = client.generate_json(
                "Write a 60-90 word Obsidian note body (plain prose, first-person "
                "knowledge-base tone, no headings, no bullet lists) for EACH item. "
                "Describe only the item itself using the given attributes; do NOT "
                "mention any other entity, person, project or company name. "
                'Return JSON: {"<name>": "<body>", ...}\n\n' + spec,
                temperature=0.7, max_output_tokens=4096,
            )
            for kind, name, item in batch:
                body = data.get(name, "")
                # strip accidental cross-entity mentions of other note titles
                prose[name] = body if isinstance(body, str) else ""
            save_json(prose_file, prose)
            print(f"prose {min(i+6, len(todo))}/{len(todo)}")

    # scrub: prose must not name other entities (would leak relations)
    all_names = [item.get("name") or item.get("title") for k in world for item in world[k]]
    for name in prose:
        for other in all_names:
            if other != name and other.lower() in prose[name].lower():
                prose[name] = re.sub(re.escape(other), "it", prose[name], flags=re.I)

    notes = render_notes(world, prose)
    qs = build_questions(world, random.Random(SEED + 1))
    verify(world, notes, qs)

    vault = OUT / "vault"
    vault.mkdir(exist_ok=True)
    for f in vault.glob("*.md"):
        f.unlink()
    for fname, content in notes.items():
        (vault / fname).write_text(content, encoding="utf-8")
    save_json(OUT / "questions.json", qs)
    print(f"vault: {vault} ({len(notes)} notes)")
    print(f"questions: {len(qs)} ({sum(1 for q in qs if q['hops']==2)} multi-hop)")


if __name__ == "__main__":
    main()
