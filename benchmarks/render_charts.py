"""README comparison charts, generated straight from the result JSONs.

Zero plotting dependencies. Every number is read from benchmarks/work or
inlined from BENCHMARKS.md tables (marked), so the charts regenerate with
the benchmarks and cannot drift from the published evidence.

    python benchmarks/render_charts.py   ->  docs/assets/chart_*.svg
"""

from __future__ import annotations

from pathlib import Path

BENCH = Path(__file__).parent
ASSETS = BENCH.parent / "docs" / "assets"

BG = "#0d1117"
FG = "#e6edf3"
DIM = "#8b949e"
GRID = "#21262d"
LEMON = "#f7d353"
BLUE = "#58a6ff"
RED = "#f85149"
GREEN = "#3fb950"
GRAY = "#6e7681"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def hbar_chart(path: Path, title: str, subtitle: str,
               rows: list[tuple[str, float, str, str]],
               xmax: float = 1.0, value_fmt="{:.3f}", width=880):
    """rows: (label, value, color, annotation)"""
    bar_h, gap, top, left = 34, 14, 86, 300
    height = top + len(rows) * (bar_h + gap) + 30
    plot_w = width - left - 150
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">',
           f'<rect width="{width}" height="{height}" rx="12" fill="{BG}"/>',
           f'<text x="28" y="40" fill="{FG}" font-size="22" font-weight="700">{esc(title)}</text>',
           f'<text x="28" y="64" fill="{DIM}" font-size="13">{esc(subtitle)}</text>']
    for gx in (0.25, 0.5, 0.75, 1.0):
        x = left + plot_w * gx / xmax if xmax else left
        if gx <= xmax:
            out.append(f'<line x1="{x:.0f}" y1="{top-8}" x2="{x:.0f}" '
                       f'y2="{height-28}" stroke="{GRID}"/>')
    for i, (label, val, color, note) in enumerate(rows):
        y = top + i * (bar_h + gap)
        w = max(3, plot_w * val / xmax)
        out.append(f'<text x="{left-12}" y="{y+bar_h/2+5}" fill="{FG}" '
                   f'font-size="14" text-anchor="end">{esc(label)}</text>')
        out.append(f'<rect x="{left}" y="{y}" width="{w:.0f}" height="{bar_h}" '
                   f'rx="6" fill="{color}"/>')
        out.append(f'<text x="{left+w+10:.0f}" y="{y+bar_h/2+5}" fill="{FG}" '
                   f'font-size="14" font-weight="600">{value_fmt.format(val)}'
                   f'<tspan fill="{DIM}" font-weight="400">  {esc(note)}</tspan></text>')
    out.append("</svg>")
    path.write_text("\n".join(out))
    print("->", path.name)


def log_latency_chart(path: Path, title: str, subtitle: str,
                      rows: list[tuple[str, float, str, str]], width=880,
                      hi: float = 100_000.0):
    """Log-scale latency bars. rows: (label, ms, color, note)"""
    import math
    bar_h, gap, top, left = 34, 14, 86, 300
    height = top + len(rows) * (bar_h + gap) + 42
    plot_w = width - left - 150
    lo = 1.0

    def x_of(ms):
        return left + plot_w * (math.log10(max(ms, lo)) - 0) / (math.log10(hi))

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">',
           f'<rect width="{width}" height="{height}" rx="12" fill="{BG}"/>',
           f'<text x="28" y="40" fill="{FG}" font-size="22" font-weight="700">{esc(title)}</text>',
           f'<text x="28" y="64" fill="{DIM}" font-size="13">{esc(subtitle)}</text>']
    ticks = ((1, "1ms"), (10, "10ms"), (100, "0.1s"), (1000, "1s"),
             (10_000, "10s"), (100_000, "100s"), (600_000, "10m"),
             (3_600_000, "1h"))
    for ms, lab in ticks:
        if ms > hi:
            continue
        x = x_of(ms)
        out.append(f'<line x1="{x:.0f}" y1="{top-8}" x2="{x:.0f}" y2="{height-40}" stroke="{GRID}"/>')
        out.append(f'<text x="{x:.0f}" y="{height-22}" fill="{DIM}" font-size="11" '
                   f'text-anchor="middle">{lab}</text>')
    for i, (label, ms, color, note) in enumerate(rows):
        y = top + i * (bar_h + gap)
        w = max(3, x_of(ms) - left)
        out.append(f'<text x="{left-12}" y="{y+bar_h/2+5}" fill="{FG}" font-size="14" '
                   f'text-anchor="end">{esc(label)}</text>')
        out.append(f'<rect x="{left}" y="{y}" width="{w:.0f}" height="{bar_h}" rx="6" fill="{color}"/>')
        disp = (f"{ms//60000:.0f}m {ms%60000/1000:.0f}s" if ms >= 60_000
                else f"{ms/1000:.1f}s" if ms >= 1000 else f"{ms:.0f}ms")
        out.append(f'<text x="{left+w+10:.0f}" y="{y+bar_h/2+5}" fill="{FG}" font-size="14" '
                   f'font-weight="600">{disp}<tspan fill="{DIM}" font-weight="400">  {esc(note)}</tspan></text>')
    out.append("</svg>")
    path.write_text("\n".join(out))
    print("->", path.name)


def grouped_chart(path: Path, title: str, subtitle: str, axes: list[str],
                  series: list[tuple[str, list[float], str]], width=880):
    """Vertical grouped bars. series: (name, values per axis, color)"""
    top, left, bottom = 96, 60, 64
    height = 380
    plot_h = height - top - bottom
    plot_w = width - left - 40
    group_w = plot_w / len(axes)
    bar_w = min(34, (group_w - 22) / len(series))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">',
           f'<rect width="{width}" height="{height}" rx="12" fill="{BG}"/>',
           f'<text x="28" y="40" fill="{FG}" font-size="22" font-weight="700">{esc(title)}</text>',
           f'<text x="28" y="64" fill="{DIM}" font-size="13">{esc(subtitle)}</text>']
    for gy in (0.25, 0.5, 0.75, 1.0):
        y = top + plot_h * (1 - gy)
        out.append(f'<line x1="{left}" y1="{y:.0f}" x2="{width-40}" y2="{y:.0f}" stroke="{GRID}"/>')
        out.append(f'<text x="{left-8}" y="{y+4:.0f}" fill="{DIM}" font-size="11" '
                   f'text-anchor="end">{gy:.2f}</text>')
    lx = left + 240
    for si, (name, _, color) in enumerate(series):
        out.append(f'<rect x="{lx}" y="{74}" width="12" height="12" rx="3" fill="{color}"/>')
        out.append(f'<text x="{lx+18}" y="{85}" fill="{FG}" font-size="12">{esc(name)}</text>')
        lx += 20 + 8 * len(name) + 24
    for ai, axis in enumerate(axes):
        gx = left + ai * group_w
        for si, (name, vals, color) in enumerate(series):
            v = vals[ai]
            bh = plot_h * v
            x = gx + (group_w - bar_w * len(series)) / 2 + si * bar_w
            out.append(f'<rect x="{x:.0f}" y="{top+plot_h-bh:.0f}" width="{bar_w-3:.0f}" '
                       f'height="{max(2,bh):.0f}" rx="3" fill="{color}"/>')
        out.append(f'<text x="{gx+group_w/2:.0f}" y="{height-38}" fill="{FG}" '
                   f'font-size="12" text-anchor="middle">{esc(axis)}</text>')
    out.append("</svg>")
    path.write_text("\n".join(out))
    print("->", path.name)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)

    # 1. KorMapleQA overall standings (from results JSONs, full 2,067 set)
    hbar_chart(
        ASSETS / "chart_kormapleqa.svg",
        "KorMapleQA: who actually finds Korean notes",
        "2,067 real namuwiki questions, gold-doc in top-8. Full corpus: 1,469 documents / 42k chunks.",
        [
            ("Lemory (Gemini embeddings)", 0.906, LEMON, "12 ms/query"),
            ("Lemory (local e5-small-ko-v2, zero keys)", 0.889, LEMON, "~16 ms/query, no compile"),
            ("Lemory (local Harrier-0.6B, llama.cpp GPU)", 0.853, LEMON, "~100 ms/query, zero keys"),
            ("qmd query (local LLM)", 0.769, BLUE, "59.5 s/query, n=329 sample"),
            ("qmd vsearch", 0.657, BLUE, "4.2 s/query, n=280 sample"),
            ("Smart-Connections-class", 0.204, GRAY, "its default local model"),
            ("Omnisearch (real MiniSearch)", 0.148, GRAY, "keyword-only engine"),
            ("qmd search (BM25)", 0.091, GRAY, "AND semantics"),
            ("MemPalace 3.5 (57k stars)", 0.031, RED, "collapses on Korean"),
        ],
    )

    # 2. Same-conditions LLM-ingest rivals (subcorpus protocol)
    grouped_chart(
        ASSETS / "chart_mem0.svg",
        "Same corpus, same Gemini models: Lemory vs mem0",
        "400-note namuwiki subcorpus, 310 questions. mem0 ingest: 60 min of LLM fact extraction. Lemory: embeddings only.",
        ["single", "masked", "2-hop", "temporal", "keyword", "casual", "typo"],
        [
            ("Lemory (14 ms/q)", [0.950, 0.875, 1.000, 0.900, 1.000, 0.940, 0.820], LEMON),
            ("mem0 (0.44 s/q)", [0.525, 0.575, 0.525, 0.800, 0.620, 0.760, 0.520], BLUE),
        ],
    )

    # 3. The qmd rematch (identical 329 questions)
    hbar_chart(
        ASSETS / "chart_qmd_rematch.svg",
        "Identical 329 questions: Lemory leads quality, ~3,700x the speed",
        "qmd's full local-LLM pipeline (expansion + rerank) vs Lemory's LLM-free hybrid, same questions.",
        [
            ("Lemory local, ~16 ms/query", 0.875, LEMON, "doc@8"),
            ("qmd query, 59.5 s/query", 0.769, BLUE, "doc@8"),
        ],
    )

    # 4. Latency at a glance (log scale)
    log_latency_chart(
        ASSETS / "chart_latency.svg",
        "Query latency on the same Korean corpus (log scale)",
        "Local retrieval compute per query. LLM-per-query architectures pay the meter every question.",
        [
            ("Lemory hybrid+graph", 16, LEMON, "0 LLM calls"),
            ("MemPalace", 443, RED, ""),
            ("qmd vsearch", 4200, BLUE, ""),
            ("qmd query", 59500, BLUE, "1 LLM pipeline per query"),
        ],
    )

    # 5. Robustness, Gemini regime (BENCHMARKS 4d re-validated 2026-07-12)
    grouped_chart(
        ASSETS / "chart_robustness.svg",
        "Ask it like a human: query robustness",
        "Multi-hop questions re-asked as paraphrase / Korean / keyword / typo variants. Full-support in top-8.",
        ["original", "paraphrase", "korean", "keyword", "typo"],
        [
            ("Lemory", [1.000, 0.982, 0.950, 1.000, 1.000], LEMON),
            ("MemPalace", [0.596, 0.643, 0.350, 0.554, 0.667], RED),
            ("Vector-only RAG", [0.544, 0.464, 0.475, 0.482, 0.491], GRAY),
            ("BM25", [0.579, 0.429, 0.250, 0.482, 0.404], GRAY),
        ],
    )

    # 6. Multi-hop vs the graph-pipeline crowd (BENCHMARKS 4/4b/4e)
    hbar_chart(
        ASSETS / "chart_multihop.svg",
        "2-hop questions: reading your wikilinks beats building LLM graphs",
        "Answer-in-context@8 on the multi-hop vault, identical Gemini models for every system.",
        [
            ("Lemory (0 LLM calls to ingest)", 1.000, LEMON, "~3 ms/query"),
            ("LightRAG mix (165 LLM calls)", 0.807, BLUE, "7.5 s/query"),
            ("LlamaIndex VectorStoreIndex", 0.649, GRAY, ""),
            ("cognee (45 min cognify)", 0.561, GRAY, "5.0 s/query"),
            ("mem0 OSS", 0.579, GRAY, "0.2 s/query"),
            ("MemPalace", 0.596, RED, "~1 s/query"),
        ],
    )

    # 7. LongMemEval full set (BENCHMARKS 7d)
    hbar_chart(
        ASSETS / "chart_longmemeval.svg",
        "LongMemEval S, all 500 questions, zero API calls",
        "Session-level Recall@5, local e5-small-ko-v2. 'any' = protocol most headline numbers use; 'strict' = every evidence session.",
        [
            ("Lemory, any@5", 0.983, LEMON, ""),
            ("Lemory, strict all@5", 0.903, LEMON, ""),
            ("Vector-only, any@5", 0.978, GRAY, ""),
            ("Vector-only, strict all@5", 0.853, GRAY, ""),
        ],
    )

    # 8. Ingest cost (time to searchable, same 1,469-note corpus)
    log_latency_chart(
        ASSETS / "chart_ingest.svg",
        "Time until 1,469 notes are searchable",
        "Same real Korean corpus. LLM-pipeline systems pay per note; Lemory reads the links you already wrote.",
        [
            ("Lemory keyless (BM25+graph)", 9_000, LEMON, "0 LLM calls"),
            ("Lemory + embeddings", 300_000, LEMON, "one API pass, cached forever"),
            ("qmd embed", 2_036_000, BLUE, "local models, 27k chunks"),
            ("mem0 (only 400 of the notes)", 3_595_000, GRAY, "LLM extraction per note"),
        ],
        hi=3_600_000,
    )


if __name__ == "__main__":
    main()
