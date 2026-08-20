# -*- coding: utf-8 -*-
"""Render the README demo GIFs (synthetic terminal frames, PIL).

Every output block below is a REAL capture from running the actual CLI on the
demo vault in this file's header comment · nothing is mocked, the animation is
just a re-typing of what the terminal actually printed. To re-capture:

    lemory index --vault <demovault>
    lemory search "결제 환불" --vault <demovault> --fast --k 3
    lemory conflicts --vault <demovault> --threshold 0.7
    lemory remember "..." --title "웹훅 서명 결정" --vault <demovault>   # memory_approval=true
    lemory pending / approve / drift / search "tag:회의록 예산" ...

Font: NanumGothicCoding (OFL) · download once:
    curl -sSLo NanumGothicCoding.ttf "https://fonts.gstatic.com/s/nanumgothiccoding/v27/8QIVdjzHisX_8vv59_xMxtPFW4IXROwsy6Q.ttf"

    python docs/assets/make_gifs.py [outdir]
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = Path(__file__).parent / "NanumGothicCoding.ttf"

W, PAD, LH, FS = 900, 26, 25, 16
BG, CHROME = (13, 17, 23), (22, 27, 34)
FG = (216, 222, 233)
DIM = (110, 118, 129)
GREEN = (126, 231, 135)
CYAN = (121, 192, 255)
YELLOW = (242, 204, 96)
RED = (255, 123, 114)
MAGENTA = (210, 168, 255)

_BOX = set("┏┓┗┛┳┻┣┫╋━┃┡┩╇│├┤┼─└┘┴┬┌┐╭╮╰╯╞╡═")

# NanumGothicCoding ships light box-drawing glyphs only — map rich's heavy
# variants onto them so table borders render solid instead of tofu
_LIGHTEN = str.maketrans("┏┓┗┛┳┻┣┫╋━┃┡┩╇╞╡═↩", "┌┐└┘┬┴├┤┼─│├┤┼├┤─↲")
# ↩ is also outside the font's coverage — ↲ is the covered equivalent


class Term:
    def __init__(self, title: str, rows: int):
        self.title, self.rows = title, rows
        self.h = 44 + rows * LH + PAD
        self.font = ImageFont.truetype(str(FONT_PATH), FS)
        self.lines: list[list[tuple[tuple, str]]] = []
        self.frames: list[Image.Image] = []
        self.durations: list[int] = []

    # box-drawing strokes: L/R half-horizontals, U/D half-verticals. Drawn as
    # vectors because the font's box glyphs are spotty (gaps at junctions).
    _STROKES = {"─": "LR", "│": "UD", "┌": "RD", "┐": "LD", "└": "RU",
                "┘": "LU", "├": "UDR", "┤": "UDL", "┬": "LRD", "┴": "LRU",
                "┼": "LRUD"}

    def _draw_boxchar(self, d, ch, x, y, w, color):
        cx, my = x + w / 2, y + LH / 2
        s = self._STROKES[ch]
        if "L" in s:
            d.line([x, my, cx, my], fill=color)
        if "R" in s:
            d.line([cx, my, x + w, my], fill=color)
        if "U" in s:
            d.line([cx, y, cx, my], fill=color)
        if "D" in s:
            d.line([cx, my, cx, y + LH], fill=color)

    # fixed cell grid, matching rich's column math (wcwidth): fullwidth CJK =
    # 2 cells, everything else (incl. …, ›, ·) = 1 cell. Drawing on the grid —
    # instead of at raw glyph advances — keeps every row's table border at the
    # same pixel column, so verbatim rich tables line up exactly.
    CELL = 8.5

    @staticmethod
    def _cells(ch: str) -> int:
        return 2 if unicodedata.east_asian_width(ch) in "WF" else 1

    def _render(self) -> Image.Image:
        im = Image.new("RGB", (W, self.h), BG)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, W, 34], fill=CHROME)
        for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            d.ellipse([14 + i * 22, 12, 26 + i * 22, 24], fill=c)
        d.text((W // 2 - self.font.getlength(self.title) / 2, 8), self.title,
               font=self.font, fill=DIM)
        y = 44
        for segs in self.lines[-self.rows:]:
            x = PAD
            for color, text in segs:
                for ch in text:
                    w = self.CELL * self._cells(ch)
                    if ch in self._STROKES:
                        self._draw_boxchar(d, ch, x, y, w, color)
                    else:
                        d.text((x, y), ch, font=self.font, fill=color)
                    x += w
            y += LH
        return im

    def snap(self, ms: int = 90):
        self.frames.append(self._render())
        self.durations.append(ms)

    def type_cmd(self, cmd: str, ms: int = 40, chunk: int = 3):
        prompt = [(GREEN, "$ ")]
        for i in range(0, len(cmd) + 1, chunk):
            cur = prompt + [(FG, cmd[:i]), (DIM, "▌")]
            if self.lines and self.lines[-1] and self.lines[-1][0][1] == "$ ":
                self.lines[-1] = cur
            elif self.lines and self.lines[-1][0][0] == GREEN and self.lines[-1][0][1] == "$ ":
                self.lines[-1] = cur
            else:
                self.lines.append(cur)
            self.snap(ms)
        self.lines[-1] = prompt + [(FG, cmd)]
        self.snap(220)

    def out(self, text: str, per_frame: int = 4, color_map=None, ms: int = 80):
        for raw in text.translate(_LIGHTEN).rstrip("\n").split("\n"):
            self.lines.append(self._colorize(raw, color_map or {}))
            if len(self.lines) % per_frame == 0:
                self.snap(ms)
        self.snap(ms)

    def blank(self):
        self.lines.append([(FG, "")])

    def _colorize(self, line: str, cmap: dict) -> list[tuple[tuple, str]]:
        for marker, color in cmap.items():
            if marker in line:
                return [(color, line)]
        segs, cur, box = [], "", None
        for ch in line:
            b = ch in _BOX
            if box is None or b == box:
                cur += ch
            else:
                segs.append((DIM if box else FG, cur))
                cur = ch
            box = b
        if cur:
            segs.append((DIM if box else FG, cur))
        return segs

    def hold(self, ms: int = 2600):
        self.snap(ms)

    def save(self, path: Path):
        pal = [f.quantize(colors=64, method=Image.MEDIANCUT) for f in self.frames]
        pal[0].save(path, save_all=True, append_images=pal[1:],
                    duration=self.durations, loop=0, optimize=True)
        print(f"{path.name}: {len(pal)} frames, {path.stat().st_size//1024} KB")


# ---------------------------------------------------------------- captured output
FAST_OUT = """\
┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #   ┃ note                       ┃ score    ┃ excerpt                    ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1   │ 결제 모듈 › ↩ context      │ 0.0131   │ tags: 프로젝트, 백엔드 ·   │
│     │                            │          │ date: 2026-07-15           │
│     │                            │          │ (2026-07-14 스프린트 회의… │
│     │                            │          │ - 결제 모듈 환불 처리:     │
│     │                            │          │ 비동기 큐 방식으로 합의    │
├─────┼────────────────────────────┼──────────┼────────────────────────────┤
│ 2   │ 2026-07-14 스프린트 회의 … │ 0.0129   │ - 결제 모듈 환불 처리:     │
│     │ 스프린트 회의              │          │ 비동기 큐 방식으로 합의 -  │
│     │                            │          │ 예산: 인프라 월 예산       │
│     │                            │          │ 80만원으로 증액 - 다음     │
│     │                            │          │ 데모는 금요일              │
├─────┼────────────────────────────┼──────────┼────────────────────────────┤
│ 3   │ 결제 모듈                  │ 0.0127   │ 김지수가 리드. PG사는      │
│     │                            │          │ 토스페이먼츠로 확정. 환불  │
│     │                            │          │ API는 비동기 큐로          │
│     │                            │          │ 처리하기로 결정            │
│     │                            │          │ (2026-07-15). 남은 일:     │
│     │                            │          │ 웹훅 서명 검증, 재시도     │
│     │                            │          │ 정책.                      │
└─────┴────────────────────────────┴──────────┴────────────────────────────┘"""

CONFLICTS_OUT = """\
┏━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 종류       ┃ sim   ┃ 노트 A / 노트 B ┃ 내용                              ┃
┡━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 숫자       │ 0.93  │ 요금메모        │ 0.05 vs 0.04                      │
│ 불일치     │       │ 요금정책        │ 컴퓨트 요금은 분당 0.05달러로     │
│            │       │                 │ 확정되었다. 파일럿 이후 결정.…    │
│            │       │                 │ 컴퓨트 요금은 분당 0.04달러로     │
│            │       │                 │ 확정되었다. 파일럿 이후 결정.…    │
├────────────┼───────┼─────────────────┼───────────────────────────────────┤
│ 부정 충돌  │ 0.73  │ 기능 메모       │ 한쪽이 주장을 부정함              │
│            │       │ 기능 플래그     │ 다크모드 기능은 iOS에서 지원되지  │
│            │       │                 │ 않는다.…                          │
│            │       │                 │ 다크모드 기능은 모든 플랫폼에서   │
│            │       │                 │ 지원된다.…                        │
├────────────┼───────┼─────────────────┼───────────────────────────────────┤
│ 중복 후보  │ 0.71  │ 김지수          │ 내용이 거의 동일함                │
│            │       │ 결제 모듈       │ 김지수는 백엔드 리드. 결제 모듈   │
│            │       │                 │ 담당. FoundationDB 팬.…           │
│            │       │                 │ 김지수가 리드. PG사는             │
│            │       │                 │ 토스페이먼츠로 확정.              │
│            │       │                 │ 환불 API는 비동기 큐로 처리하기 … │
│            │       │                 │ 결정 (2026-07-15).                │
│            │       │                 │ 남은 일: 웹훅 서명 검증, …        │
└────────────┴───────┴─────────────────┴───────────────────────────────────┘"""

PENDING_OUT = """\
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ path                         ┃ title            ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ memories/재시도 정책 결정.md │ 재시도 정책 결정 │
└──────────────────────────────┴──────────────────┘
1건 대기 · lemory approve <path> 로 승인"""

APPROVED_SEARCH = """\
┏━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #   ┃ note             ┃ score    ┃ excerpt                              ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1   │ 재시도 정책 결정 │ 0.0131   │ 환불 재시도는 지수 백오프 3회로 결정 │
└─────┴──────────────────┴──────────┴──────────────────────────────────────┘"""

DRIFT_OUT = """\
  깨진 위키링크 (1)   
┏━━━━━━━━━┳━━━━━━━━━━┓
┃ note    ┃ target   ┃
┡━━━━━━━━━╇━━━━━━━━━━┩
│ 독서.md │ 깨진링크 │
└─────────┴──────────┘
고치려면: lemory drift --prompt | (에이전트에 전달)"""

OPERATORS_OUT = """\
┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #   ┃ note                       ┃ score    ┃ excerpt                    ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1   │ 2026-06-02 킥오프 › 킥오프 │ 0.0131   │ - 인프라 월 예산           │
│     │                            │          │ 50만원으로 시작 - 스택:    │
│     │                            │          │ FastAPI + SQLite           │
├─────┼────────────────────────────┼──────────┼────────────────────────────┤
│ 2   │ 2026-07-14 스프린트 회의 … │ 0.0129   │ - 결제 모듈 환불 처리:     │
│     │ 스프린트 회의              │          │ 비동기 큐 방식으로 합의 -  │
│     │                            │          │ 예산: 인프라 월 예산       │
│     │                            │          │ 80만원으로 증액 - 다음     │
│     │                            │          │ 데모는 금요일              │
└─────┴────────────────────────────┴──────────┴────────────────────────────┘"""

TEMPORAL_OUT = """\
┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #   ┃ note                       ┃ score    ┃ excerpt                    ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1   │ 웹훅 서명 결정 › ↩ context │ 0.0210   │ date: 2026-07-18 · source: │
│     │                            │          │ assistant ·                │
│     │                            │          │ lemory_generated: True ·   │
│     │                            │          │ related: [[결제 모듈]]     │
└─────┴────────────────────────────┴──────────┴────────────────────────────┘"""

TYPO_OUT = """\
┏━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #   ┃ note   ┃ score    ┃ excerpt                                        ┃
┡━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1   │ 김지수 │ 0.0249   │ 김지수는 백엔드 리드. 결제 모듈 담당.          │
│     │        │          │ FoundationDB 팬.                               │
└─────┴────────┴──────────┴────────────────────────────────────────────────┘"""

SCALE_OUT = """\
corpus: 9663 paragraphs (ALL of KorQuAD train) · 60407 questions
indexed in 602s · 9747 chunks · 0 LLM calls
  [hybrid] 50000/60407 r@1=0.861 r@5=0.963
  [hybrid] 55000/60407 r@1=0.860 r@5=0.962
  [hybrid] 60000/60407 r@1=0.858 r@5=0.961
[hybrid] recall@1=0.8584 recall@5=0.9613 p50=90.5ms
[fast]   recall@1=0.8309 recall@5=0.9395 p50=29.9ms"""


def main(outdir: Path):
    # 1) fast mode — as-you-type instant lexical search
    t = Term("lemory · 즉답 검색 (fast: 임베딩 0회)", 27)
    t.type_cmd('lemory search "결제 환불" --fast')
    t.out(FAST_OUT, per_frame=3)
    t.out("3.8 ms · 쿼리 임베딩 없음 · KorQuAD recall@1 0.975 (113문단 하네스)",
          color_map={"ms": DIM})
    t.hold()
    t.save(outdir / "demo5_fast.gif")

    # 2) conflicts — the vault disagreeing with itself
    t = Term("lemory · 모순 탐지 (기억 vs 기억, LLM 0회)", 27)
    t.type_cmd("lemory conflicts --threshold 0.7")
    t.out(CONFLICTS_OUT, per_frame=3,
          color_map={"숫자": YELLOW, "부정 충돌": RED})
    t.hold()
    t.save(outdir / "demo6_conflicts.gif")

    # 3) approval workflow
    t = Term("lemory · AI 쓰기 승인 게이트 (memory_approval)", 24)
    t.type_cmd('lemory remember "환불 재시도는 지수 백오프 3회로 결정" --title "재시도 정책 결정"')
    t.out("saved memories/재시도 정책 결정.md\n  관련 기억: [[결제 모듈]] sim=0.625",
          color_map={"saved": GREEN, "관련 기억": DIM})
    t.blank()
    t.type_cmd("lemory pending")
    t.out(PENDING_OUT, per_frame=3, color_map={"1건 대기": YELLOW})
    t.blank()
    t.type_cmd('lemory approve "memories/재시도 정책 결정.md"')
    t.out("approved memories/재시도 정책 결정.md · 검색 가능해졌습니다",
          color_map={"approved": GREEN})
    t.blank()
    t.type_cmd('lemory search "재시도 정책 뭐로 했지?" --fast')
    t.out(APPROVED_SEARCH, per_frame=3)
    t.hold()
    t.save(outdir / "demo7_approval.gif")

    # 4) drift
    t = Term("lemory · 드리프트 감지 (기억 vs 현실)", 12)
    t.type_cmd("lemory drift")
    t.out(DRIFT_OUT, per_frame=2, color_map={"깨진 위키링크": RED, "고치려면": DIM})
    t.hold()
    t.save(outdir / "demo8_drift.gif")

    # 5) scoping operators
    t = Term("lemory · 스코프 연산자 (tag: / folder: / path:)", 17)
    t.type_cmd('lemory search "tag:회의록 예산" --fast')
    t.out(OPERATORS_OUT, per_frame=3)
    t.out("회의록 태그 안에서만 검색 · 50만원(킥오프) → 80만원(최근) 모두 찾음",
          color_map={"회의록": DIM})
    t.hold()
    t.save(outdir / "demo9_operators.gif")

    # 6) temporal
    t = Term("lemory · 시간 인지 검색", 12)
    t.type_cmd('lemory search "요새 작업하던 결제 관련 결정" --fast')
    t.out(TEMPORAL_OUT, per_frame=3)
    t.out('"요새"를 이해하고 최신 결정(7/15)을 1위로', color_map={"요새": DIM})
    t.hold()
    t.save(outdir / "demo10_temporal.gif")

    # 7) full-scale KorQuAD
    t = Term("KorQuAD 전량 · 9,663문단 × 60,407질문, 키리스 로컬", 12)
    t.type_cmd("python benchmarks/run_korquad_full.py")
    t.out(SCALE_OUT, per_frame=1, ms=350,
          color_map={"recall@1=0.8584": GREEN, "recall@1=0.8309": CYAN})
    t.hold(3200)
    t.save(outdir / "demo11_scale.gif")

    # 8) typo repair
    t = Term("lemory · 오타 교정 (로컬 did-you-mean)", 12)
    t.type_cmd('lemory search "FoundatoinDB 팬은 누구" --fast')
    t.out(TYPO_OUT, per_frame=3)
    t.out("FoundatoinDB → FoundationDB 자동 교정, API 0회", color_map={"자동 교정": DIM})
    t.hold()
    t.save(outdir / "demo12_typo.gif")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    main(out)
