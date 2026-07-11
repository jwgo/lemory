# 냉정한 경쟁력 평가 (2026-07 기준)

스스로에게 유리하게 채점하지 않기 위한 문서. 별점은 "10k-star OSS가 되기 위한 기준" 대비.

## 실측으로 증명된 강점 ★★★★★

| 축 | 근거 |
|---|---|
| 멀티홉 검색 | full-support@8 1.000 — mem0 0.579 / cognee 0.561 / supermemory 0.579 / qmd 0.526이 같은 벽(~0.5)에 막힘. 위키링크를 공짜 그래프로 쓰는 설계가 원인 제공 |
| 시간 인지 | 경쟁 제품 중 "요새/어제/지난주/3월에" + 최신값 우선을 검색층에서 하는 것은 없음. 시나리오 hit@1 1.000 |
| 한국어 | 유니그램+바이그램 인덱싱, 조사 내성, 크로스링구얼 0.975 — 한국 옵시디언 커뮤니티라는 미점유 세그먼트 |
| 운영 단순성 | SQLite 1파일 + numpy. cognee(4개 저장소)·mem0(벡터DB)·supermemory(호스팅) 대비 설치 마찰 최소 |
| 표면 | CLI/웹/HTTP/MCP(6툴)/옵시디언 플러그인 — qmd(CLI/MCP), mem0(SDK/API) 대비 최다 |

## 정직한 약점

| 약점 | 심각도 | 완화 |
|---|---|---|
| PyPI 미배포 — `pip install lemory` 불가 | 높음 | git+https 설치는 동작. 배포는 메인테이너 계정 필요 (로드맵 1순위) |
| 옵시디언 플러그인 스토어 미등록 (수동 복사 설치) | 높음 | 등록 절차는 외부 리뷰 필요. 파일 3개 복사로 우회 가능 |
| md 전용 — PDF/첨부파일 미인덱싱 | 중간 | 옵시디언 포지셔닝으로는 허용. 로드맵 |
| LOCOMO/LME는 층화 샘플(160/100) | 중간 | `--all` 지원, 방법론 공개. 풀셋 재실행 비용은 API 예산 문제 |
| DMR 절대값(0.694)이 Zep 발표치(94.8)와 큰 격차 | 중간 | 셋업이 다름(GPT-4급 생성기+자체 저지). 동일 하네스 내 우위(+4.6pt)는 성립. 과장하지 말 것 |
| ask() 지연은 LLM 왕복(~1-2초)이 지배 | 낮음 | 검색 자체는 3ms. 생성 모델 선택의 문제 |
| 단일 사용자 설계 (멀티테넌트 없음) | 낮음 | 개인 KB 포지셔닝상 의도된 것 |

## 10k 스타 관점 갭 분석

스타는 대개 (1) 3초 안에 이해되는 데모, (2) 마찰 없는 설치, (3) 공유하고 싶은 비교표에서
나온다. 기술 격차보다 유통 격차가 크다.

- ✅ 히어로 스크린샷(실측 장면), 비교표, 영/한 README, CI 배지, 재현 가능한 벤치
- ⬜ PyPI + 옵시디언 스토어 (외부 절차 — 최우선)
- ⬜ 데모 GIF/영상 (스크린샷보다 강함)
- ⬜ HN/레딧(r/ObsidianMD)/한국 커뮤니티 론칭 포스트 — "요새 그거 뭐였지 데모"가 후크
- ⬜ 이슈 템플릿, 디스커션 개설

## 포지셔닝 한 줄

> "mem0/supermemory는 앱에 넣는 메모리 API고, cognee는 파이프라인 프레임워크다.
> Lemory는 **이미 존재하는 당신의 옵시디언 볼트**를 그대로 답하게 만드는 로컬 백엔드다 —
> 그리고 그 검색이 그들보다 정확하다는 걸 같은 하네스에서 측정해서 보여준다."

---

# 확장 조사 (2026-07-11): 19개 시스템, 그중 6개 실측

README/논문 정독 후 "본받을 점"을 추출하고, 채택은 벤치마크 승리를 조건으로
걸었다 (measured, not adopted 원칙).

## 실측 완료 (6)

mem0 · cognee · supermemory · LlamaIndex · qmd — 수치는 BENCHMARKS.md.
KorQuAD의 BM25 열세(0.908 vs 0.923)도 계속 공개 유지.

## 아이디어 조사 (13)

| 시스템 | 형태 | 가장 강한 아이디어 | 채택 |
|---|---|---|---|
| **HippoRAG** (OSU) | 연구 라이브러리 | **KG 위 Personalized PageRank — LLM 없는 원패스 멀티홉** | ✅ `graph_hops` 다중 홉 전파 |
| Smart Connections | 옵시디언 플러그인 | 블록 단위 임베딩 + pin/hide 피드백을 랭킹 prior로 | 부분 (헤딩 청킹 기존); 피드백 prior 로드맵 |
| obsidian-copilot | 옵시디언 플러그인 | 임베딩 없이도 동작하는 강등 경로; 링크 중첩도 점수화 | 기존 보유 (키 없이 BM25+링크) |
| khoj | 셀프호스트/클라우드 | `date:`/`file:` 질의 연산자 사전 필터 | temporal 기존; tag/folder 연산자 로드맵 |
| reor | 로컬 노트앱 | 현재 노트를 질의로 쓰는 수동 관련노트 (LLM 0회) | `/api/related` 후보 |
| graphiti (Zep) | 시간형 KG 서버 | 앵커 노드로부터 그래프 거리 리랭크; 엣지 유효기간 | 앵커 리랭크 로드맵 (MCP 문맥) |
| letta (MemGPT) | 상태형 에이전트 | 항상-인-컨텍스트 core memory 분리 | 볼트 요약 core 블록 로드맵 |
| txtai | 임베딩 DB | 희소 볼트에 kNN 유사도 추론 엣지 밀도 보강 | 스텁 보강과 함께 평가 (아래) |
| basic-memory | MCP 마크다운 메모리 | 마크다운 관습에서 타입드 관계·frontmatter 스키마 추론 | ✅ frontmatter 평탄화 색인 (아래) |
| ragflow | 엔터프라이즈 RAG | 문서 타입별 청킹 템플릿 | 폴더/속성 인지 청킹 로드맵 |
| anything-llm | 프라이빗 ChatGPT | 워크스페이스 단위 검색 네임스페이스 | 멀티볼트 프로파일 로드맵 |
| microsoft graphrag | 배치 KG 파이프라인 | Leiden 커뮤니티 계층 (LLM-free 부분) | 토픽 클러스터 로드맵 |
| onyx (Danswer) | 엔터프라이즈 챗+RAG | 커넥터 함대, 학습형 리랭커 | 범위 밖 (조직 규모) |

## 실세계 데이터가 가르쳐준 것

실제 공개 옵시디언 볼트(kepano — MIT)를 벤치마크로 만들면서 확인한 패턴:
**진짜 볼트는 스텁 노트 투성이다** — 3줄짜리 레퍼런스 노트는 BM25에도
임베딩에도 거의 안 보이는데, 위키링크 대부분이 그런 노트를 향한다. 이번
라운드의 채택 두 건이 정확히 이걸 겨냥한다:

1. **스텁 보강** (basic-memory/앵커텍스트식): 본문이 짧은 노트의 색인 표현에
   frontmatter 속성 평탄화 + **백링크 문맥**을 결정적으로 추가.
   → **실측 승리**: kepano 실볼트 2-hop full-support 0.500 → 1.000 (기본값 ON).
2. **그래프 확장 재설계** (HippoRAG PPR의 재료들: 허브-임계 차수 정규화 +
   유사도 가중 확장 예산 + 시드 부스트 자격): help 볼트 recall@1 +5.5pt,
   MRR +2pt, 강건성 paraphrase +3.6pt/korean +2.5pt, 허브 그래프 침수 방어.
   full-support는 이전과 동률 — 첫 구현은 오히려 회귀(0.836→0.600)했고
   기준선 실측이 그걸 잡았다. 과정 전체를 BENCHMARKS §5d에 공개.
3. **다중 홉 전파** (`graph_hops=2`): 모든 코퍼스에서 이득 0 → 기본값 1 유지,
   opt-in으로만 제공. measured, not adopted.

측정 결과(안 된 것 포함)는 BENCHMARKS.md §5d에.

---

# 3차: 상용 솔루션 정면 비교 (2026-07-11)

2026년 7월 기준 상용/활발한 제품들을 다시 조사했다 (supermemory 셀프호스트
바이너리·mem0 4월 알고리즘 리라이트·Zep Smart Context Assembly·cognee 1.0
Postgres 단일화·Khoj Cloud 종료·Rewind/Limitless 메타 인수 후 셧다운·Claude
메모리 무료화). 결론 두 가지:

1. **검색 품질은 이제 테이블 스테이크다.** 2025-26 승자들(mem0, supermemory,
   basic-memory, Letta)은 전부 대화에서 기억을 **자동으로 쓰는(write)** 쪽으로
   이동했다. 읽기 전용 인덱스는 반쪽짜리다.
2. **로컬-퍼스트가 다시 차별화 요소가 됐다.** Rewind 사망, Khoj Cloud 사망,
   메타의 인수 — 프라이버시 사용자들이 갈 곳을 잃었고, 클라우드-네이티브인
   supermemory조차 로컬 바이너리를 냈다.

## 이번 라운드에 이식한 것 (전부 로컬-퍼스트 재해석)

| 갭 (원조) | Lemory 구현 | 차별점 |
|---|---|---|
| 쓰기 경로 (mem0 add / basic-memory write_note) | save_memory·append_note (MCP/HTTP/CLI) | 기억이 독점 저장소의 행이 아니라 **볼트 안의 순수 마크다운** — Obsidian에서 보이고, 버전 관리되고, 락인 없음 |
| 사전 조립 컨텍스트 (Zep get_user_context, ~50ms) | vault_context / GET /context / `lemory context` | LLM 0회·결정적·로컬 ~ms. 세션 시작 시 한 콜 |
| 질의 연산자 (khoj date:/file:) | tag:/folder:/path: + 기존 시간 연산 | 전 모드(vector/bm25 포함) 동작, 빈 질의 = 스코프 목록 |
| 관련 노트 (reor) | /api/related + MCP + 콘솔 관련 노트 | 노트 자체가 질의 — LLM 0, 신규 임베딩 0 |
| 대화 이력 자산화 (Claude Memory Import 역방향) | `lemory import-chats` (ChatGPT/Claude 내보내기) | 멱등 재실행, 날짜 보존 → 시간 질의로 검색 가능 |
| 멀티모달 (supermemory/mymind) | PDF 인덱싱 opt-in (`lemory[pdf]`) | 이미지 OCR·오디오는 로드맵 (의존성 무게 때문에 opt-in 원칙) |
| 사용신호 자기개선 (cognee memify) | usage_prior 설정 (기본 OFF) | 개인 사용 신호는 오프라인 벤치마크가 불가능 — 정직하게 기본 꺼짐 |
| 대규모 스케일 (전용 벡터DB들) | IVF-int8 자동 전환 (§12b) | numpy만으로 1M 청크 5.9ms·recall 1.000·RAM 4분의 1 — "SQLite가 발목" 반박을 실측으로 |

## "시장 3위 안"이라는 질문에 대한 정직한 답

전체 "AI 메모리" 시장(mem0 60k스타·supermemory 28k스타·SaaS 매출)에서
스타 수나 매출로 3위라고 주장하는 건 거짓말이다. 그건 유통(distribution)의
게임이고 Lemory는 아직 PyPI에도 없다.

측정 가능한 것으로 좁히면 얘기가 다르다. **"내 마크다운 볼트를 그대로 답하게
만드는 로컬-퍼스트 백엔드"** 세그먼트(경쟁: basic-memory, khoj(셀프호스트),
Smart Connections/Copilot, qmd, memory-vault류 MCP 서버들)에서:

- **검색 품질**: 같은 하네스에서 실측한 6개 시스템 중 멀티홉·강건성·시간
  인지 전부 1위 (mem0 0.579 / cognee 0.561 / supermemory 0.579 / qmd 0.526 /
  LlamaIndex 0.649 vs **1.000**). 세그먼트 밖 상용까지 포함해도 이 수치를
  같은 조건에서 이기는 공개 측정은 없다.
- **기능 커버리지**: 위 표 이후 읽기+쓰기+컨텍스트+연산자+관련노트+가져오기
  +PDF+시각화+히트추적 — basic-memory(쓰기 중심, 검색 약함)와
  khoj(검색+챗, 쓰기 없음)의 합집합에 해당. 빠진 것: 이미지 OCR, 웹클리퍼,
  스케줄 자동화.
- **운영 단순성**: SQLite 1파일+numpy로 1M 청크까지 실측 완주. 경쟁 제품 중
  이 풋프린트로 이 수치를 내는 것 없음 (cognee=Postgres, mem0=벡터DB,
  supermemory=바이너리+외부 임베딩).

이 세그먼트 기준 기술 지표로는 1-2위 주장이 가능하고, 그 근거 전부가 이
저장소 안에서 재현 가능하다. **아직 아닌 것**: PyPI/옵시디언 스토어 등록,
커뮤니티, 데모 영상 — 유통 갭은 코드로 못 메운다 (외부 절차, 로드맵 최상단).

## 이번 라운드에 하지 않은 것 (근거 포함)

- **호스티드 클라우드/모바일 동기화** — Khoj Cloud의 죽음이 경제성을 증언.
  Obsidian Sync/Syncthing 문서화가 80%를 커버.
- **풀 챗 어시스턴트 UI** — 시장은 Claude/ChatGPT **안의** 메모리로 이동했다.
  Lemory는 MCP로 그 안에 들어가는 쪽.
- **바이-템포럴 사실 무효화 (Graphiti)** — 노트 기반 볼트에는 "사실 행"이
  없다. 시간 질의 이해 + 최신값 우선(§10)이 같은 사용자 문제를 푼다.
  사실 단위 스토어를 도입하는 순간 "순수 마크다운" 포지셔닝이 죽는다.
- **스토리지 엔진 교체 (DuckDB / LanceDB)** — "SQLite가 발목이면 바꿔라"까지
  열어놓고 실측했다. 결과는 [docs/STORAGE.md](STORAGE.md): Lemory의 실제
  워크로드(증분 FTS·노트 단위 upsert·PK 배치·2프로세스)에서 SQLite가 4/5 축
  승리, DuckDB는 전 축 탈락(증분 FTS 부재), LanceDB는 FTS만 5배 빠르고(정직하게
  기록) 벡터·PK·운영 축에서 열세. 교체 근거 없음 — 재검토 트리거만 명시.
