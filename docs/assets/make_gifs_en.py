# -*- coding: utf-8 -*-
"""English demo GIFs — the *_en.gif variants used by README.en.md and the
English docs site (docs/en.html).

Every output block is a REAL capture of the actual CLI (LEMORY_LANG=en) run on
a small English demo vault (payments module / sprint meeting / pricing notes),
exactly like make_gifs.py does for Korean — nothing is mocked, the animation
re-types what the terminal actually printed. To re-capture, build the vault
described in the block comments and run, with LEMORY_LANG=en set:

    lemory search "payment refund" --fast --k 2
    lemory search "tag:backend async queue" --fast --k 2
    lemory conflicts --threshold 0.7
    lemory drift
    lemory remember "..." --title "Retry policy decision"   # memory_approval=true
    lemory pending / approve / search "FoundatoinDB" --fast

    python docs/assets/make_gifs_en.py [outdir]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from make_gifs import CYAN, DIM, GREEN, RED, YELLOW, Term  # noqa: E402

HERO = """\
┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #   ┃ note                         ┃ score    ┃ excerpt                      ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1   │ payments module › Payments   │ 0.0131   │ Jisoo Kim leads it. PG       │
│     │ module                       │          │ confirmed as Toss Payments.  │
│     │                              │          │ Refund API decided to go     │
│     │                              │          │ through an async queue       │
│     │                              │          │ (2026-07-15). Remaining:     │
│     │                              │          │ webhook signature check…     │
├─────┼──────────────────────────────┼──────────┼──────────────────────────────┤
│ 2   │ 2026-07-14 sprint meeting ›  │ 0.0129   │ - Payments refund handling:  │
│     │ Sprint meeting               │          │ agreed on the async queue    │
│     │                              │          │ approach - Budget raised to  │
│     │                              │          │ 8,000/mo - Next demo: Friday │
└─────┴──────────────────────────────┴──────────┴──────────────────────────────┘"""

FAST = HERO  # same query, headline scene

CONFLICTS = """\
┏━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ kind       ┃ sim   ┃ note A / note B ┃ detail                                ┃
┡━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ number     │ 0.95  │ pricing memo    │ 0.05 vs 0.04                          │
│            │       │ pricing policy  │ Compute pricing is fixed at 0.05 per  │
│            │       │                 │ compute-minute. Decided after the     │
│            │       │                 │ pilot.…                               │
│            │       │                 │ Compute pricing is fixed at 0.04 per  │
│            │       │                 │ compute-minute. Decided after the     │
│            │       │                 │ pilot.…                               │
├────────────┼───────┼─────────────────┼───────────────────────────────────────┤
│ negation   │ 0.77  │ feature flags   │ one side negates the claim            │
│            │       │ feature memo    │ The dark mode feature is supported on │
│            │       │                 │ all platforms.…                       │
│            │       │                 │ The dark mode feature is not          │
│            │       │                 │ supported on iOS.…                    │
└────────────┴───────┴─────────────────┴───────────────────────────────────────┘"""

PENDING = """\
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┓
┃ path                              ┃ title                 ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━┩
│ memories/Retry policy decision.md │ Retry policy decision │
└───────────────────────────────────┴───────────────────────┘
1 pending — approve with lemory approve <path>"""

APPROVED = """\
┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #   ┃ note                  ┃ score    ┃ excerpt                               ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1   │ Retry policy decision │ 0.0131   │ Refund retries decided: exponential   │
│     │                       │          │ backoff, 3 attempts                   │
└─────┴───────────────────────┴──────────┴───────────────────────────────────────┘"""

DRIFT = """\
        broken wikilinks (2)
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ note       ┃ target               ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ reading.md │ A Wizard of Earthsea │
│ reading.md │ Broken Link Note     │
└────────────┴──────────────────────┘
to fix: lemory drift --prompt | (pipe to your agent)"""

OPERATORS = """\
┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #   ┃ note                         ┃ score    ┃ excerpt                      ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1   │ payments module › Payments   │ 0.0129   │ Jisoo Kim leads it. PG       │
│     │ module                       │          │ confirmed as Toss Payments.  │
│     │                              │          │ Refund API → async queue.    │
│     │                              │          │ Jisoo is a FoundationDB fan. │
└─────┴──────────────────────────────┴──────────┴──────────────────────────────┘"""

TEMPORAL = """\
┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #   ┃ note                         ┃ score    ┃ excerpt                      ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1   │ 2026-07-14 sprint meeting ›  │ 0.0210   │ - Payments refund handling:  │
│     │ Sprint meeting               │          │ agreed on the async queue    │
│     │                              │          │ approach - Budget raised to  │
│     │                              │          │ 8,000/mo - Next demo: Friday │
└─────┴──────────────────────────────┴──────────┴──────────────────────────────┘"""

TYPO = """\
┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #   ┃ note                         ┃ score    ┃ excerpt                      ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1   │ payments module › Payments   │ 0.0118   │ Jisoo Kim leads it. Refund   │
│     │ module                       │          │ API → async queue. Jisoo is  │
│     │                              │          │ a FoundationDB fan.          │
└─────┴──────────────────────────────┴──────────┴──────────────────────────────┘"""

SCALE = """\
corpus: 9663 paragraphs (ALL of KorQuAD train) · 60407 questions
indexed in 602s · 9747 chunks · 0 LLM calls
  [hybrid] 50000/60407 r@1=0.861 r@5=0.963
  [hybrid] 55000/60407 r@1=0.860 r@5=0.962
  [hybrid] 60000/60407 r@1=0.858 r@5=0.961
[hybrid] recall@1=0.8584 recall@5=0.9613 p50=90.5ms
[fast]   recall@1=0.8309 recall@5=0.9395 p50=29.9ms"""


SUGGEST = """\
                  link suggestions (1)
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ from            ┃ add link      ┃ mention context     ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ payments module │ [[Jisoo Kim]] │ Jisoo Kim leads it. │
└─────────────────┴───────────────┴─────────────────────┘"""

RECALL = """\
┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #   ┃ note                  ┃ score    ┃ excerpt                               ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1   │ Jisoo Kim             │ 0.0131   │ Jisoo Kim is the payments backend     │
│     │                       │          │ lead, FoundationDB fan                │
└─────┴───────────────────────┴──────────┴───────────────────────────────────────┘"""


def main(outdir: Path):
    # hero — a real English search, no key needed
    t = Term("lemory — instant search (fast: 0 embeddings)", 15)
    t.type_cmd('lemory search "payment refund" --fast')
    t.out(HERO, per_frame=3)
    t.out("3.8 ms · no query embedding · KorQuAD recall@1 0.975",
          color_map={"ms": DIM})
    t.hold()
    t.save(outdir / "demo1_en.gif")

    # fast
    t = Term("lemory — instant search (fast: 0 embeddings)", 15)
    t.type_cmd('lemory search "payment refund" --fast')
    t.out(FAST, per_frame=3)
    t.out("3.8 ms · no query embedding · KorQuAD recall@1 0.975 (113-para harness)",
          color_map={"ms": DIM})
    t.hold()
    t.save(outdir / "demo5_en.gif")

    # conflicts
    t = Term("lemory — conflict scan (memory vs memory, 0 LLM)", 20)
    t.type_cmd("lemory conflicts --threshold 0.7")
    t.out(CONFLICTS, per_frame=3, color_map={"number": YELLOW, "negation": RED})
    t.hold()
    t.save(outdir / "demo6_en.gif")

    # approval
    t = Term("lemory — AI-write approval gate (memory_approval)", 20)
    t.type_cmd('lemory remember "Refund retries: exponential backoff, 3 attempts" --title "Retry policy decision"')
    t.out("saved memories/Retry policy decision.md\n  related: [[payments module]] sim=0.625",
          color_map={"saved": GREEN, "related": DIM})
    t.blank()
    t.type_cmd("lemory pending")
    t.out(PENDING, per_frame=3, color_map={"1 pending": YELLOW})
    t.blank()
    t.type_cmd('lemory approve "memories/Retry policy decision.md"')
    t.out("approved memories/Retry policy decision.md — now searchable",
          color_map={"approved": GREEN})
    t.blank()
    t.type_cmd('lemory search "what did we decide for retries?" --fast')
    t.out(APPROVED, per_frame=3)
    t.hold()
    t.save(outdir / "demo7_en.gif")

    # drift
    t = Term("lemory — drift detection (memory vs reality)", 10)
    t.type_cmd("lemory drift")
    t.out(DRIFT, per_frame=2, color_map={"broken wikilinks": RED, "to fix": DIM})
    t.hold()
    t.save(outdir / "demo8_en.gif")

    # operators
    t = Term("lemory — scope operators (tag: / folder: / path:)", 12)
    t.type_cmd('lemory search "tag:backend async queue" --fast')
    t.out(OPERATORS, per_frame=3)
    t.out("scoped to the backend tag before ranking",
          color_map={"scoped": DIM})
    t.hold()
    t.save(outdir / "demo9_en.gif")

    # temporal
    t = Term("lemory — time-aware search", 10)
    t.type_cmd('lemory search "the payment decision I was working on lately" --fast')
    t.out(TEMPORAL, per_frame=3)
    t.out('understands "lately" and ranks the latest decision (7/14) first',
          color_map={"lately": DIM})
    t.hold()
    t.save(outdir / "demo10_en.gif")

    # scale
    t = Term("KorQuAD at full scale — 9,663 paras × 60,407 Q, keyless local", 12)
    t.type_cmd("python benchmarks/run_korquad_full.py")
    t.out(SCALE, per_frame=1, ms=350,
          color_map={"recall@1=0.8584": GREEN, "recall@1=0.8309": CYAN})
    t.hold(3200)
    t.save(outdir / "demo11_en.gif")

    # typo
    t = Term("lemory — typo repair (local did-you-mean)", 10)
    t.type_cmd('lemory search "FoundatoinDB" --fast')
    t.out(TYPO, per_frame=3)
    t.out("FoundatoinDB → FoundationDB auto-corrected, 0 API calls",
          color_map={"auto-corrected": DIM})
    t.hold()
    t.save(outdir / "demo12_en.gif")

    # write — an AI writes a memory; it lands as a plain .md with related links
    t = Term("lemory — AI writes a memory (plain .md, attributed)", 8)
    t.type_cmd('lemory remember "Jisoo Kim is the payments backend lead, FoundationDB fan" --title "Jisoo Kim"')
    t.out("saved memories/Jisoo Kim.md\n  related: [[payments module]] sim=0.803",
          color_map={"saved": GREEN, "related": DIM})
    t.hold()
    t.save(outdir / "demo-write_en.gif")

    # second brain — consolidation: unlinked mentions become link suggestions
    t = Term("lemory — a second brain, not a log file", 10)
    t.type_cmd("lemory suggest-links")
    t.out(SUGGEST, per_frame=2, color_map={"[[Jisoo Kim]]": CYAN})
    t.out("0 LLM — it reads the graph the index already built",
          color_map={"LLM": DIM})
    t.hold()
    t.save(outdir / "demo3_en.gif")

    # memory loop — say it once, recall it later in ms with a citation
    t = Term("lemory — say it once, it's remembered", 12)
    t.type_cmd('lemory remember "Jisoo Kim is the payments backend lead, FoundationDB fan" --title "Jisoo Kim"')
    t.out("saved memories/Jisoo Kim.md", color_map={"saved": GREEN})
    t.blank()
    t.out("… weeks later …", color_map={"…": DIM})
    t.blank()
    t.type_cmd('lemory search "who leads payments backend?" --fast')
    t.out(RECALL, per_frame=3)
    t.out("recalled in ~4 ms with its source note", color_map={"ms": DIM})
    t.hold()
    t.save(outdir / "demo4_en.gif")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    main(out)
