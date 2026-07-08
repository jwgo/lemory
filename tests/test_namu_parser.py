"""나무마크 파서 테스트 (실제 나무위키 문법 패턴 기반)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "benchmarks"))
from namu_parser import extract_categories, extract_links, namu_to_markdown

SAMPLE = """[[분류:메이플스토리/보스 몬스터]]
[include(틀:메이플스토리 보스)]
[목차]
= 개요 =
'''루시드'''는 [[메이플스토리]]의 [[아케인 리버]] 지역 [[레헬른]]의 보스이다.[* 꿈의 마녀라고도 불린다.]
== 공략 ==
{{{#!wiki style="border:1px"
입장 레벨은 220 이상이며, ~~쉽다~~ '''어렵다'''.}}}
 * [[루시드/패턴|패턴]]이 다양하다
 * 보상: [[아케인셰이드 무기]]
== 통계 ==
|| 난이도 || HP ||
|| 하드 || 60조 ||
[[https://example.com|외부 링크]]도 있다.
"""


def test_categories():
    assert extract_categories(SAMPLE) == ["메이플스토리/보스 몬스터"]


def test_headings_converted():
    md = namu_to_markdown(SAMPLE, "루시드")
    assert "# 개요" in md
    assert "## 공략" in md


def test_wikilinks_preserved_and_cleaned():
    md = namu_to_markdown(SAMPLE, "루시드")
    assert "[[메이플스토리]]" in md
    assert "[[레헬른]]" in md
    assert "[[루시드/패턴|패턴]]" in md  # alias kept, anchor-free
    assert "[[분류:" not in md            # category links stripped
    assert "외부 링크" in md and "https://example.com" not in md.split("외부 링크")[0][-30:]


def test_footnote_and_styles():
    md = namu_to_markdown(SAMPLE, "루시드")
    assert "(꿈의 마녀라고도 불린다.)" in md
    assert "**루시드**" in md
    assert "**어렵다**" in md
    assert "~~쉽다~~" not in md and "쉽다" in md


def test_brace_blocks_keep_content():
    md = namu_to_markdown(SAMPLE, "루시드")
    assert "입장 레벨은 220 이상" in md
    assert "{{{" not in md and "}}}" not in md


def test_tables_converted():
    md = namu_to_markdown(SAMPLE, "루시드")
    assert "| 난이도 | HP |" in md
    assert "| 하드 | 60조 |" in md


def test_bullets_and_macros():
    md = namu_to_markdown(SAMPLE, "루시드")
    assert "- [[루시드/패턴|패턴]]" in md
    assert "[include" not in md and "[목차]" not in md


def test_extract_links():
    md = namu_to_markdown(SAMPLE, "루시드")
    links = extract_links(md)
    assert "메이플스토리" in links and "레헬른" in links


def test_lemory_indexes_converted_note(tmp_path):
    """변환 결과가 Lemory 인제스트 파이프라인을 그대로 통과해야 한다."""
    from lemory.config import LemoryConfig
    from lemory.engine import Engine
    from tests.conftest import DIM, FakeGemini

    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "루시드.md").write_text(namu_to_markdown(SAMPLE, "루시드"), encoding="utf-8")
    (vault / "레헬른.md").write_text("아케인 리버의 다섯 번째 지역. 꿈의 도시.", encoding="utf-8")
    eng = Engine(LemoryConfig(vault=vault, data_dir=tmp_path / "d", embed_dim=DIM,
                              gemini_api_key="x"), llm=FakeGemini())
    rep = eng.index()
    assert rep.errors == [] and rep.added == 2
    docs = {d.title: d.id for d in eng.store.all_docs()}
    nbrs = eng.store.neighbors([docs["루시드"]])[docs["루시드"]]
    assert any(dst == docs["레헬른"] and k == "wiki" for dst, k, _ in nbrs)
    hits = eng.search("루시드 입장 레벨", k=3, mode="bm25")
    assert hits and hits[0].title == "루시드"
    eng.close()
