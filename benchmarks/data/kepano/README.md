# kepano vault — real-world Obsidian benchmark

Steph Ango (@kepano, Obsidian CEO)'s public personal vault, MIT-licensed:
https://github.com/kepano/kepano-obsidian (LICENSE included here).

This is deliberately the messy real thing — short reference notes, YAML
properties, stub pages, clippings — not a corpus written for retrieval.
Questions are LLM-drafted and CODE-VERIFIED (see gen_kepano_qa.py): the
answer string must appear in the gold note (and for 2-hop, ONLY in the
target note, with no title leakage in the question). Invalid drafts are
discarded.
