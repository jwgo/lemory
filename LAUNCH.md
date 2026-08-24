# 런칭 체크리스트: 10k의 유통 절반

기술 절반은 저장소 안에 있다 (실측 벤치·데모 GIF·정직 섹션). 이 문서는 코드로
못 메우는 나머지 절반: 2026년에 이 카테고리에서 10k+로 간 저장소들(claude-mem
86.8k, MemPalace 57.2k, codebase-memory-mcp 29.9k, context-mode 18.8k)의 공통
플레이북을 Lemory에 맞게 옮긴 것.

## 저장소 설정 (GitHub UI에서, 5분)

- [ ] **Description에 숫자를 박는다.** 이 카테고리의 2026년 문법:
  > `Your Obsidian vault as every AI's memory. LongMemEval R@5 0.97 (full set, 0 API calls) · multi-hop 1.000 vs mem0 0.579 (same harness) · ~3ms · 0 LLM calls to index · MCP read+write · local-first SQLite`

  (LongMemEval 풀셋 any@5 0.972 = MemPalace 헤드라인 "96.6% R@5"와 같은 지표;
  strict all@5 0.857도 BENCHMARKS §7d에 함께 공개. 정직 섹션이 곧 논란 보험.)
- [ ] Topics: `obsidian` `mcp` `ai-memory` `agent-memory` `local-first` `rag`
  `knowledge-base` `markdown` `korean` `sqlite`
- [ ] Discussions 켜기 · `good first issue` 라벨로 이슈 3-4개 시딩
  (cognee가 이걸로 컨트리뷰터를 농사짓는다)
- [ ] Social preview 이미지 = demo-read.gif의 마지막 프레임

## 배포 (런칭 전 필수)

- [ ] **PyPI 등록**: `pip install lemory` 없이는 신뢰도에서 시작부터 잃는다.
  2026년 관례상 README 첫 명령은 `uv tool install lemory`로.
- [ ] 옵시디언 커뮤니티 플러그인 스토어 제출 (리뷰가 수 주 걸리므로 미리)
- [ ] Claude Code 플러그인 마켓플레이스 등록 검토

## 런칭 포스트

**Show HN 제목** (반대 명제 + 숫자, context-mode가 565포인트 받은 문법):
> Show HN: Your Obsidian wikilinks already are a knowledge graph; multi-hop
> retrieval 1.000 vs mem0 0.579, 57k-star MemPalace 0.596, same harness, 0 LLM
> calls to index

본문 요령:
- 정직 섹션을 **선제적으로** 링크한다 ("여기서 BM25한테 지고, LanceDB FTS가
  우리보다 빠른 것도 공개한다"). MemPalace가 벤치마크 논란에서 살아남은
  유일한 이유가 저장소 안의 재현 커맨드였다. 우리는 그걸 처음부터 들고 간다.
- 재현 커맨드를 포스트 안에 직접.
- 첫 댓글로 아키텍처 설명 (SQLite+numpy만으로 1M 청크, STORAGE.md 링크).

**채널 순서** (카테고리 실측):
1. HN (Show HN, 화-목 오전 미국시간): 인프라·명제형은 여기
2. Reddit r/ObsidianMD + r/LocalLLaMA: 코딩에이전트/옵시디언 도구는 레딧이
   HN보다 잘 먹힌다 (codebase-memory-mcp의 첫 달 데이터)
3. X 스레드: demo-read.gif 그대로 (5초, 자동재생)
4. **한국: GeekNews·디스콰이엇**은 별도 포스트, 별도 헤드라인:
   "한국어를 1급 시민으로 다루는 유일한 로컬 AI 메모리: KorQuAD·나무위키
   실측, 한국어 강건성 0.975 vs MemPalace 0.350" + 망분리 완전 오프라인 항목
5. 일주일 뒤 런칭 회고 블로그 (context-mode 패턴: 두 번째 파도가 온다)

## 런칭 후 첫 주

- [ ] 모든 이슈에 24시간 내 응답 (초기 이슈 응답 속도가 스타 곡선을 만든다)
- [ ] 벤치마크 이의 제기가 오면: 반박하지 말고 재현 커맨드부터. 재현되면
  같은 날 수정 커밋 + 감사 표시 (MemPalace의 생존 공식)
- [ ] star-history 차트를 README에 추가하는 건 1k 넘고 나서

## 하지 않는 것

- 유료 플랜/클라우드 배너를 README에 넣지 않는다 (basic-memory가 3.4k에서
  멈춘 이유 중 하나: 리드젠 저장소로 읽힌다)
- 자체 벤치만 내세우지 않는다. LongMemEval 풀셋 숫자를 앞에, LemoryBench는
  "방법론이 더 엄격한 보조 증거"로
