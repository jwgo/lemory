"""Build a markdown vault + question set from SQuAD v2 dev (real external data).

One note per Wikipedia article (its paragraphs concatenated). Questions keep
their gold article title and answer aliases. Retrieval hit = returned chunk is
from the gold article AND contains a gold answer string.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from common import DATA, WORK, save_json

N_ARTICLES = 18
N_QUESTIONS = 300
SEED = 7


def main() -> None:
    src = DATA / "squad" / "dev-v2.0.json"
    data = json.loads(src.read_text())["data"]
    rng = random.Random(SEED)
    articles = rng.sample(data, N_ARTICLES)

    vault = WORK / "squad_vault"
    vault.mkdir(parents=True, exist_ok=True)
    for f in vault.glob("*.md"):
        f.unlink()

    questions = []
    for art in articles:
        title = art["title"].replace("_", " ")
        body_parts = []
        for p in art["paragraphs"]:
            body_parts.append(p["context"])
            for qa in p["qas"]:
                if qa["is_impossible"]:
                    continue
                golds = sorted({a["text"] for a in qa["answers"]})
                questions.append({"q": qa["question"], "article": title, "answers": golds})
        (vault / f"{title}.md").write_text("\n\n".join(body_parts), encoding="utf-8")

    rng.shuffle(questions)
    questions = questions[:N_QUESTIONS]
    save_json(WORK / "squad_questions.json", questions)
    print(f"vault: {vault} ({N_ARTICLES} notes)")
    print(f"questions: {len(questions)}")


if __name__ == "__main__":
    main()
