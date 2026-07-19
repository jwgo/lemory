<div align="center">

# 🍋 Lemory

### 기억은 당신의 것이어야 합니다.
**남의 데이터베이스 행이 아니라, 당신 볼트 안의 마크다운 파일로.**
<sub>Your memory should belong to you · **[English README](README.en.md)**</sub>

[![CI](https://github.com/jwgo/lemory/actions/workflows/ci.yml/badge.svg)](https://github.com/jwgo/lemory/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Benchmarks](https://img.shields.io/badge/benchmarks-reproducible-orange.svg)](BENCHMARKS.md)
[![KorMapleQA](https://img.shields.io/badge/KorMapleQA-2%2C075%20questions-yellow.svg)](benchmarks/data/kormapleqa/README.md)

<img src="docs/assets/demo1_korean.gif" alt="실제 나무위키 1,469노트 볼트에서 한국어 질문이 ~0.1초 로컬 연산에 답변되고 오타가 자동 교정되는 실제 데모" width="840">

<sub>목업이 아닙니다. 실제 나무위키 1,469문서 / ~42,000청크 볼트에서 한국어
질문이 ~0.1초 로컬 연산에 답변되고, 오타는 API 없이 교정되는 장면입니다.
[`benchmarks/`](benchmarks/)로 재현됩니다.</sub>

</div>

---

**Lemory는 당신의 마크다운을 위한 로컬 메모리 미들웨어입니다.** 당신의 노트와
당신이 쓰는 모든 AI(Claude Desktop, Claude Code, Cursor, 직접 짠 스크립트)
사이에 앉아서, 당신이 적어둔 모든 것을 AI가 기억해내게 하고, 기억할 가치가
있는 것을 당신 소유의 마크다운 파일로 만들어 줍니다.

- **AI가 기억을 꺼냅니다**: 시맨틱 + 한국어 인지 키워드 + `[[위키링크]]`
  그래프 하이브리드 검색. 돌릴 수 있는 경쟁 제품 전부와 같은 하니스에서
  실측하고, 지는 항목도 공개합니다.
- **AI가 기억을 넣습니다**: 결정사항과 사실이 볼트 안의 순수 `.md` 노트로
  저장됩니다. 중복은 감지해 표시하고, 관련 기억은 `related:` 위키링크로
  연결합니다. 옵시디언에서 보이고, 버전 관리되고, `rm` 한 번이면 사라집니다.
  독점 스토어 없음, 내보내기 버튼 필요 없음, 탈출 비용 0.
- **미들웨어를 지켜봅니다**: 대시보드가 지나간 모든 것을 보여줍니다. 모든
  질의, AI가 적은 모든 노트(원클릭 되돌리기), 클라이언트별 사용량. 전부
  로컬, SQLite 파일 하나.

> **아무것도 Lemory를 "통해서" 넣을 필요가 없습니다.** 볼트는 그냥
> 파일입니다. 늘 하던 대로 노트를 쓰세요(옵시디언, 아무 편집기, 셸
> 스크립트). 워처가 1초 안에 색인합니다. `save_memory`와 `lemory remember`는
> *AI가* 쓸 때 출처 표시, 중복 검사, 되돌리기 버튼을 얻기 위한 경로일
> 뿐입니다. 관문이 아니라 예우용 출입구입니다.

업계의 메모리 제품들은 당신의 지식을 *자기들* 데이터베이스의 행으로
원합니다. 우리는 당신이 이미 소유한 파일이 더 나은 데이터베이스라고 믿고,
그 믿음이 정확도를 희생하지 않는다는 것을 벤치마크로 증명하는 데 시간을
썼습니다. 오히려 그 반대라는 게 측정 결과입니다.

## 증거부터 보여드립니다

모든 수치는 커밋된 코드와 공개 데이터에서 재생성됩니다. 방법론, 지는 축,
미해결 문제까지 [BENCHMARKS.md](BENCHMARKS.md)에 있습니다.

<div align="center">
<img src="docs/assets/chart_kormapleqa.svg" width="840" alt="KorMapleQA 순위">
<img src="docs/assets/chart_latency.svg" width="840" alt="지연시간 비교, 로그 스케일">
</div>

## 같은 질문, 실제 도구 3개, 라이브

<div align="center">
<img src="docs/assets/demo2_rivals.gif" width="840" alt="qmd는 0건, MemPalace는 노이즈, Lemory는 보스 노트를 1위로">
</div>

같은 볼트에서 [tobi/qmd](https://github.com/tobi/qmd)와 MemPalace가 실제로
도는 장면입니다(그들 문서의 스크린샷이 아닙니다). qmd의 BM25는 AND 결합이라
한국어 자연어 질문에 0건을 돌려주고, MemPalace는 영어 중심 임베더에 한국어
어휘 경로가 없습니다. Lemory는 보스 노트 자체를 1위로, ~0.1초에, LLM 0회로
돌려줍니다.

qmd가 로컬 LLM 풀파이프라인(질의 확장 + 리랭크)을 돌려도, 같은 329문항에서
Lemory의 LLM-프리 하이브리드보다 아래입니다 - 게다가 쿼리당 59.5초를 냅니다:

<div align="center">
<img src="docs/assets/chart_qmd_rematch.svg" width="840" alt="동일 329문항: Lemory 0.887@~0.11s vs qmd query 0.769@59.5s">
</div>

가장 스타가 많은 OSS 메모리 레이어 mem0와는 같은 코퍼스, 같은 Gemini 모델
엔드투엔드로:

<div align="center">
<img src="docs/assets/chart_mem0.svg" width="840" alt="같은 조건에서 Lemory vs mem0, 전 축">
</div>

## 명령 한 줄로 시작

```bash
pipx install "git+https://github.com/jwgo/lemory"
lemory up ~/Obsidian/MyVault     # 설정 → 색인 → 대시보드, 한 번에
lemory ask "요새 내가 하던 그 프로젝트 어디까지 했지?"
```

`lemory up`이 유일한 입구입니다 - 최적 모드를 알아서 고릅니다: Gemini 키가
있으면 클라우드(임베딩+답변), 없으면 **기본 탑재된 온디바이스 스택**(한국어
특화 e5-small-ko-v2 임베딩 + Gemma 4 답변, 키 없음, 데몬 없음)으로, 아무
설정 없이 검색이 됩니다. 그냥 `lemory up`만 치면 볼트를 물어보고, Gemini는
`--key <KEY>`로. 모델·검색 설정은 대시보드의 **설정** 탭에 있습니다.

그다음엔 **`lemory serve`를 계속 켜두세요**: 옵시디언 플러그인, Claude/MCP,
웹 대시보드가 붙는 상시 백엔드이고, 볼트를 편집하면 몇 초 안에 자동
재색인합니다. 일회성 `lemory ask "..."`는 서버 없이도 됩니다. 일상 흐름
전체(언제 켜두는지, 언제 재색인하는지)는
[가이드](docs/GUIDE.ko.md#4-쓰는-법--한-번-설정-그다음엔-계속)에 있습니다.

어느 모드든 인제스트에 LLM 파이프라인이 돌지 않습니다. **노트 1,000개 색인 =
LLM 호출 0회**, 수 초 안에 검색 가능 - 54노트 볼트에 ~45분의 LLM 그래프
구축이 필요한 경쟁 제품들과 비교하면:

<div align="center">
<img src="docs/assets/chart_ingest.svg" width="840" alt="1,469노트가 검색 가능해질 때까지 걸리는 시간">
</div>

**처음이라면 차근차근: [docs/GUIDE.ko.md](docs/GUIDE.ko.md) · 일상 루틴:
[docs/ROUTINE.ko.md](docs/ROUTINE.ko.md) (English: [docs/GUIDE.md](docs/GUIDE.md))**

## 어떤 AI에게든 기억을 주세요

```bash
claude mcp add lemory -- lemory mcp --vault ~/Obsidian/MyVault --client claude-desktop
lemory skill install claude-code    # 어시스턴트에게 사용법까지 가르치기
```

| 클라이언트 | 설정 |
|---|---|
| Claude Code / Desktop | `claude mcp add lemory -- lemory mcp --vault <vault> --client claude-code` |
| Cursor | `.cursor/mcp.json`에 추가: `{"lemory": {"command": "lemory", "args": ["mcp", "--vault", "<vault>", "--client", "cursor"]}}` |
| Windsurf / VS Code / Codex CLI / 아무 MCP 클라이언트 | 같은 stdio 명령: `lemory mcp --vault <vault> --client <name>` |
| 스크립트 / 자작 에이전트 | REST + `X-Lemory-Client` 헤더 (아래) |

`--client` 이름이 대시보드의 클라이언트별 사용량에 그대로 뜹니다. 누가 당신
기억을 읽고 쓰는지 항상 알 수 있습니다.

11개 툴(MCP 동작 어노테이션 포함 - 클라이언트가 뭐가 읽기 전용인지 압니다).
읽기: `search_notes` · `ask_notes` · `recent_notes` · `read_note` ·
`list_notes` · `related_notes` · `suggest_links`(연결 안 된 언급을 문장
증거와 함께 [[링크]] 제안으로) · `vault_status` · `vault_context`(세션
컨텍스트 한 방: 최근 활동, 핫 노트, 허브, 태그; Zep 스타일, ~ms, LLM 0회).
쓰기: `save_memory`(통합 포함: 관련 기억은 링크, 근접 중복은 플래그) ·
`append_note`(덮어쓰기 불가, 볼트 탈출 불가).

### 자동 세션 기억 (명령 하나)

```bash
lemory hooks install claude-code
```

SessionEnd 라이프사이클 훅이 등록됩니다: Claude Code 세션이 끝나면 기억할
가치가 있는 결정·사실·미결 스레드가 **날짜 붙은 마크다운 노트 하나**로
볼트에 요약됩니다. 성실함이 필요 없고, 훅 기반 메모리 도구들과 달리 모든
캡처가 출처 표시와 원클릭 되돌리기와 함께 대시보드 피드에 뜹니다. 수동
제어를 원하면 `CLAUDE.md` 지시 패턴도 그대로 됩니다:

```markdown
세션 시작 시 lemory의 vault_context를 한 번 불러 상황을 파악해라. 결정이나
기억할 사실, 선호가 정해지면 save_memory로 저장해라(간결하게, 노트당 기억
하나). 내 노트가 이미 답하는 것은 나에게 묻기 전에 search_notes로 검색해라.
```

**프라이버시는 파일 속성입니다**: 아무 노트 frontmatter에 `lemory: false`
한 줄이면 색인도, 검색도, 어떤 모델로도 전송되지 않습니다. 이미 색인된
노트라면 플래그가 제거합니다.

## 기억 루프: 한 번 말하면, 기억됩니다

<div align="center">
<img src="docs/assets/demo4_memoryloop.gif" width="840" alt="1일차: 대화가 세션 노트로 자동 저장. 30일차: 비서가 4ms에 출처와 함께 그 사실을 소환.">
</div>

비서는 대화 안에서 **읽고 씁니다**: "…라고 기억해줘"라고 말하면 그 자리에서
볼트 노트로 저장되고(승인제가 켜져 있으면 대기열로), "그건 언제였지?" 같은
후속 질문은 앞 질문과 묶어 검색합니다. 첫 턴엔 볼트 상황 요약이 자동
주입되고, `/검색` `/기억` `/최근` 명령도 됩니다.

콘솔 비서와의 대화는 `chats/`의 날짜 붙은 세션 노트로 자동 저장됩니다 -
열어보고, 고치고, 지울 수 있는 평범한 마크다운 파일(그 투명함이 곧 언두
버튼입니다). 한 달치 대화가 쌓인 뒤 "내 여동생 이름 뭐랬지?"는 출처와 함께
~ms에 돌아옵니다. 위 데모는 실제 파이프라인 출력의 재연입니다. 그 위의
선택 레이어 둘:

- **`lemory distill`** - 옵트인 사후 배치(온디바이스 Gemma, 키 0)로 대화를
  팩트시트 노트로 증류하고 출처를 [[위키링크]]로 남깁니다. 지저분한 채팅
  벤치 실측: rank-1 정답 존재율 +3.1pt; 프로파일과 한계는
  [BENCHMARKS §7e](BENCHMARKS.md).
- **스킬**(`lemory skill install`)은 외부 어시스턴트에게 같은 정책을
  가르칩니다: 세션이 끝나기 전에 `lemory remember`로 사실을 저장하라.

일반 에이전트 축도 측정돼 있습니다: **AgentMemQA**([§7f](BENCHMARKS.md)) -
12주치 업무 비서 세션(영한 혼용 기술 대화, 코드블록, 에러 트레이스)에
번복된-결정 함정을 채점으로 심은 벤치. 키리스 하이브리드 doc@1 **0.978**,
번복 함정 **0**, 자기 레그 모두 상회. 역발견도 정직하게: cross-encoder
리랭커는 시간맹이라 갱신된 사실에서 recency를 되돌립니다(decision
0.80→0.50; 사후 recency 블렌드까지 실측으로 반증) - 리랭커가 기본 off인
이유가 하나 더 늘었습니다.

실채팅의 지저분함도 가정이 아니라 측정입니다: RoleMemQA-messy가 번복·농담
페이크·어휘 오염 잡담을 심고, 전체 doc@1 0.836 vs 클린 0.977 - 그 격차를
줄인 Cerebras식 버스트 청킹의 승리/회귀 원장 전체가 [§7e](BENCHMARKS.md)에
공개돼 있습니다.

## 로그 파일이 아니라 세컨드브레인

<div align="center">
<img src="docs/assets/demo3_secondbrain.gif" width="840" alt="중복 기억이 위키링크로 표시되고, 연결 안 된 언급이 링크 제안으로 나온다">
</div>

사람이 쓴 노트에는 이 장치들이 전혀 필요 없습니다. 파일을 볼트에 떨어뜨리면
다음 질의에서 바로 검색됩니다. 아래 기능들은 *기계가* 쓰는 노트를 위한
것입니다.

- **`save_memory`가 통합합니다.** 새 기억을 저장할 때마다 볼트가 이미 아는
  것과 대조합니다: 근접 중복은 `possible_duplicate_of:` frontmatter로,
  관련 노트는 `related:` 위키링크로. mem0식 사실 업데이트에서 파괴적
  재작성을 뺀 것 - 우리는 연결하고, 결정은 당신이 하고, 위키링크는 그
  자체로 되돌리기 서사입니다.
- **`lemory suggest-links`**: 본문에서 서로를 언급하지만 연결된 적 없는
  노트들을 문장 증거와 함께 제안합니다. LLM 0회 - 색인이 이미 만든 그래프를
  읽을 뿐입니다.
- **`lemory graph`**: 볼트 전체를 자체완결 인터랙티브 HTML 하나로
  내보냅니다(force 레이아웃, 폴더 색, 검색, 클릭 탐색). 1,469노트
  24,850엣지가 약 1초, LLM 0회. 2026년의 그래프 도구 물결은 같은 산출물에
  파일마다 LLM을 태웁니다.
- **`lemory drift`**: "내 기억이 아직 현실과 맞나?"에 답합니다: 깨진
  [[위키링크]], 사라진 파일로 가는 링크, 아무도 해소하지 않은 중복 플래그.
  `--prompt`는 발견 사항을 에이전트용 수리 프롬프트 하나로 렌더링합니다.
  결정적, 토큰 0. (코딩 에이전트 스캐폴드의 드리프트 감지를 개척한
  [mex](https://github.com/mex-memory/mex)에 경의를 - mex는 랭킹 검색이
  없어 우리 표의 행이 아니라 우리가 흡수한 아이디어로 삽니다.)
- **`lemory conflicts`**: "내 기억이 서로 맞나?"에 답합니다: 거의 같은
  말을 하면서 숫자가 다르거나, 서로를 부정하거나, 아예 중복인 노트 쌍 -
  색인이 이미 가진 청크 행렬 위의 코사인으로 찾고 어휘적으로 분류합니다.
  LLM 0회. (`drift`는 기억-대-현실, `conflicts`는 기억-대-기억. Vestige가
  모순 감지를 간판으로 삼았죠 - 우리는 571ms/질의짜리 인지 파이프라인 없이
  아이디어만 이식했습니다.)
- **`lemory search --fast`** (`/search?mode=fast`): 즉답 경로 - 한글 바이그램
  BM25 + 오타 교정 + 제목/최신성/사용 이력 부스트, 질의 임베딩 없음. KorQuAD
  하니스 실측 recall@1 0.975 @ 3.8ms (하이브리드: 0.967 @ 21ms - 패러프레이즈,
  교차 언어, 멀티홉엔 벡터 레그가 필요해서 하이브리드가 기본입니다).
  타이핑 즉시 검색창과 에이전트 폴링 루프용.
- **시간 이해**: "요새 내가 하던 그거 뭐였지?"는 언급이 더 많은 옛 사실
  대신 현재 사실을 고르고, "3월에 읽던 책은?"은 과거에 닿습니다.

모든 쓰기는 대시보드의 **AI 메모리 피드**에 "누가 적었는지"와 되돌리기
버튼(`.trash`로 이동 - 옵시디언 자체 휴지통; 사람이 쓴 노트는 구조적으로
거부)과 함께 뜹니다. 모든 질의는 **최근 질의**에 상위 출처와 함께 뜹니다.
그게 미들웨어의 계약입니다: 아무것도 보이지 않게 지나가지 않습니다.

<img src="docs/assets/demo-write.gif" alt="Claude가 기억을 저장하면 claude-desktop 출처의 마크다운 파일로 피드에 뜨고 원클릭 되돌리기가 붙는다" width="820">

## 데모 갤러리 — 전부 실제로 도는 화면입니다

각 클립은 작은 한국어 데모 볼트 위 **실제 CLI 출력을 글자 그대로**(verbatim)
다시 타이핑한 것입니다 (재생성: `docs/assets/make_gifs.py`, 캡처 원문이
스크립트에 포함 - 목업 없음).

| | |
|---|---|
| **즉답 검색** `--fast` · 임베딩 0회, 3.8ms<br><img src="docs/assets/demo5_fast.gif" width="420"> | **모순 탐지** `lemory conflicts` · 기억 vs 기억<br><img src="docs/assets/demo6_conflicts.gif" width="420"> |
| **AI 쓰기 승인 게이트** pending → approve<br><img src="docs/assets/demo7_approval.gif" width="420"> | **드리프트 감지** `lemory drift` · 기억 vs 현실<br><img src="docs/assets/demo8_drift.gif" width="420"> |
| **스코프 연산자** `tag:` `folder:` `path:`<br><img src="docs/assets/demo9_operators.gif" width="420"> | **시간 인지** "요새 작업하던…" → 최신 결정 1위<br><img src="docs/assets/demo10_temporal.gif" width="420"> |
| **오타 교정** FoundatoinDB → FoundationDB<br><img src="docs/assets/demo12_typo.gif" width="420"> | **전량 스케일 검증** KorQuAD 9,663문단 × 60,407질문<br><img src="docs/assets/demo11_scale.gif" width="420"> |

## 대시보드

`lemory serve` → `127.0.0.1:8377`. 제2의 옵시디언이 아니라 *미들웨어*를 보는
화면입니다:

- **현황**: 타임라인. AI 메모리 피드(되돌리기 포함), 최근 질의와 그 출처,
  클라이언트별 사용량(`claude-desktop` vs `cursor` vs `cli`), 색인 활동,
  현재 벡터 인덱스 종류
- **지식**: 노트 상세. 색인된 청크, 들고나는 링크, 옵시디언 그래프가 못
  보는 *언급* 간선까지 그리는 로컬 그래프, 내용 기반 관련 노트, 참조 횟수
- **건강**: 승인 대기 기억, 모순 쌍, 드리프트, 링크 제안 - 기억의 정합성을
  한 화면에서 처리
- **검색**: 하이브리드/벡터/BM25 플레이그라운드, 점수 막대와 지연시간 표시
- **설정**: 라이브 적용되는 검색 노브. 타임라인 자체도 설정이고
  (`event_log`) 전부 로컬 SQLite 파일에 남습니다

<img src="docs/assets/console-knowledge.png" alt="지식: 노트 상세, 로컬 그래프, 관련 노트" width="820">

## 파일 vs 행: 개인 지식에서 이게 메모리 API를 이기는 이유

Lemory와 가장 가까운 것은 mem0의 OpenMemory(대시보드 딸린 로컬 MCP
메모리)입니다. 차이는 "기억"이 *무엇이냐*입니다:

| | **Lemory** | OpenMemory (mem0) | supermemory 셀프호스트 | basic-memory | qmd |
|---|---|---|---|---|---|
| 기억이란 | **당신 소유의 마크다운 파일** | Postgres+Qdrant의 행 | 전용 바이너리 스토어의 레코드 | 마크다운 파일 | (읽기 전용 인덱스) |
| 실행 형태 | 프로세스 1, SQLite 파일 1 | Docker: Postgres + Qdrant + UI | 바이너리 1 + 외부 임베딩 | pip 패키지 | bun CLI |
| 기존 노트 인제스트 | **네, 그게 존재 이유** | 아니오 (채팅 추출 기억) | 업로드 | 부분적 | 네 |
| 인제스트 LLM 호출 | **0** | 대화마다 추출 | API 쪽 | 0 | 0 |
| 대시보드 | 타임라인 + 되돌리기 + 클라이언트 | 기억 CRUD UI | 콘솔 | 없음 | 없음 |
| 검색 (직접 측정) | **멀티홉 1.000 · ~3 ms** | mem0 OSS: 0.579 · 212 ms | 0.579 · 327 ms | 측정 불가¹ | 0.526 · 0.6-59 s |
| 한국어 검색 | **CJK 바이그램 FTS + 오타 교정** | 영어 우선 | 영어 우선 | 영어 우선 | 영어 우선 |
| 떠날 때 비용 | 없음, 파일이 남음 | 내보내기/이전 | 내보내기/이전 | 없음 | 없음 |

<sub>¹ basic-memory는 그래프 탐색 우선이라 측정할 랭킹 검색이 없습니다.
측정된 모든 수치는 같은 하니스, 같은 모델, 같은 코퍼스:
[방법론](BENCHMARKS.md).</sub>

추출 기반 기억(행)은 당신이 말한 것의 *요약*입니다: 쓸 때 손실되고,
나중에 검증할 수 없습니다. 파일 기반 기억은 실제 노트를 날짜와 문맥과 함께
소환합니다. 검색 품질이 여기서 측정 가능한 이유이기도 합니다.

## 자작 합성 데이터가 아니라 실데이터 위의 증명

**사람들이 실제로 묻는 방식대로** (패러프레이즈, 영어 노트에 한국어 질문,
키워드 축약, 오타; full-support@8):

<div align="center">
<img src="docs/assets/chart_robustness.svg" width="840" alt="패러프레이즈, 한국어, 키워드, 오타 강건성">
</div>

**멀티홉, LLM 그래프 진영과 대결.** 당신의 `[[위키링크]]`와 연결 안 된 제목
언급이 *곧* 지식그래프입니다. 그걸 공짜로 읽는 쪽이, 경쟁 제품들이 LLM
파이프라인을 태워 만드는 그래프보다 높게 나왔습니다:

<div align="center">
<img src="docs/assets/chart_multihop.svg" width="840" alt="2-hop 질문: Lemory 1.000 vs LLM 그래프 파이프라인">
</div>

| | **Lemory** | LightRAG | MemPalace | mem0 | cognee | supermemory | LlamaIndex | qmd |
|---|---|---|---|---|---|---|---|---|
| 멀티홉 answer-in-context@8 | **1.000** | 0.807¹ | 0.596 | 0.579 | 0.561 | 0.579 | 0.649 | 0.526 |
| 2-hop 질문만 | **1.000** | 0.738 | 0.452 | 0.548 | 0.405 | - | 0.524 | 0.381 |
| 인제스트, 54노트 | **LLM 0회, ~30초** | 165회, 14분 | 로컬 임베딩 | 노트당 1-2회 | ~45분 | API 쪽 | 0 | 0 |
| 검색 지연 (p50) | **~3 ms** | 7.5 s² | ~1 s³ | 212 ms | ~5 s | 327 ms | 649 ms⁴ | 0.6-59 s |
| 한국어 질문 (full-support) | **0.950** | - | 0.350 | - | - | - | - | - |

<sub>¹ LightRAG에 후한 채점: 병합된 엔티티+관계+청크 컨텍스트 덩어리가 다른
시스템의 8청크보다 큽니다. LLM으로 지은 그래프는 진짜고, 경쟁 최고 2-hop
점수입니다. 다만 인제스트에도 질의에도 LLM 파이프라인 값을 냅니다.
² 무료 티어 제한 하의 질의당 LLM 키워드 추출 포함; 유료면 ~1-2초.
³ MemPalace CLI 벽시계(프로세스 기동 포함), sqlite_exact 백엔드, 그들이
내세우는 zero-API 구성. ⁴ LlamaIndex는 질의마다 API 임베딩, 캐시 없음;
로컬 전용이면 ~2 ms.</sub>

**업계가 보고하는 메모리 벤치마크.** LongMemEval_S 전체 500문항 리트리벌,
API 호출 0, 로컬 임베더:

<div align="center">
<img src="docs/assets/chart_longmemeval.svg" width="840" alt="LongMemEval 전체 500문항, API 0회">
</div>

헤드라인들이 쓰는 프로토콜에서 Recall@5 **0.983**, 그리고 우리는 더 엄격한
전-증거 수치(0.904)를 앞세웁니다 - 유리한 쪽만 인용하지 않습니다. 한국어
특화 e5 기본이 옛 MiniLM(0.972/0.857)을 둘 다 앞섭니다. LOCOMO LLM-judge
0.706 vs mem0 공개 수치 0.669 (키 없는 리트리벌 축에선 하이브리드 0.771
evidence-recall@10로 자기 레그 모두 상회); DMR(500문항) 0.694 vs 같은
하니스 naive RAG 0.668 ([§7b](BENCHMARKS.md)).

**롤플레잉 기억 - 캐릭터 챗이 진짜 필요로 하는 축.** 직접 만들어 공개한
**RoleMemQA**([§7e](BENCHMARKS.md)): 8 페르소나 × 30 날짜 세션, 단기/장기/
에피소드/선호-업데이트/시간/2홉/거절 144문항(코드 검증 골드). 키리스
Lemory가 "맞는 세션이 소환되는가"라는 기억 저장소의 본질 질문에 **doc@1
0.977** (업데이트형 1.000, 옛-선호 함정률 **0**), 자기 vector(0.938) ·
BM25(0.820) 레그를 모두 이기며 ~1ms. 이 벤치가 잡아낸 실결함 2건도 바로
고쳤습니다: recency는 벽시계가 아니라 기억 자체의 타임라인에 앵커해야
하고, 채팅 추임새가 렉시컬 레그를 점령하면 안 됩니다.

**[KorQuAD 1.0](https://korquad.github.io/)**, 실제 한국어 위키피디아 140
문서, 인간 작성 질문 400개 - 키리스 로컬(e5-small-ko-v2):

| System | Recall@1 | Recall@5 | MRR@10 |
|---|---|---|---|
| **Lemory** (hybrid+graph) | **0.930** | 0.980 | **0.951** |
| BM25 | 0.900 | **0.985** | 0.937 |
| Vector-only RAG | 0.840 | 0.953 | 0.887 |

<sub>이 표는 프로젝트 역사 대부분 동안 BM25가 이겼고 우리는 그 사실을
그대로 실었습니다 - SQuAD류 질문은 문단을 보면서 작성돼 어휘가 전부
겹치기 때문입니다. 2026-07 한국어 검색 라운드(IDF 가중 인용 감지, 자모
어간 매칭, 음절 오타 교정)가 드디어 뒤집었습니다. 400문항 표본은 동률
타이브레이크에 ±2문항 흔들립니다 - 10배 표본(4,000문항)에서 현행 코드가
r@1 0.9795로 우세함을 별도 실측했습니다(BENCHMARKS §7e). 옛 표는 git
히스토리에 남아 있고, 실제 기억 질의에 중요한 숫자는 위의 강건성
차트입니다.</sub>

**[KorMapleQA](benchmarks/data/kormapleqa/README.md)**는 우리가 돌려주는
기여입니다: 실제 나무위키 메이플스토리 도메인(1,469문서) 위의 2,075문항.
인포박스 사실, 엔티티 마스킹 지칭, 실링크 2-hop(지름길 차단 검증), 시간,
키워드/반말/오타 변형, 부재 검증 무응답 질문까지. 100% 코드 생성 + 기계
검증: API 키 0개로 재현되고 LLM 작성 편향이 없습니다. Gemini 생성기 e2e:
containment-EM 0.617, 무응답 8문항 중 7문항 정확 거절.

우리가 만들지 않은 실제 볼트도 스위트에 있습니다: Steph Ango(옵시디언
CEO)의 공개 볼트와 공식 Obsidian Help 볼트 ([§5d](BENCHMARKS.md)).

## 한국어가 1등 시민입니다

이 분야 대부분은 한국어를 나중 일로 취급합니다. Lemory는 벤치마크 스위트로
취급합니다:

- **한글 + 가나 + 한자 바이그램 색인**: 조사가 붙은 어절,
  `ナイトロード나이트로드` 같은 혼합 스크립트, JMS/CMS 표기 테이블까지
  전부 매칭됩니다. unicode61 토크나이저는 이걸 매칭 불가능한 토큰으로
  붙여버립니다; 바이그램이 고칩니다.
- **음절 단위 오타 교정**: `메플이스토리`가 메이플스토리를 찾습니다. 인접
  전위가 편집 1회(음절 Damerau-Levenshtein) - 한국어 오타가 실제로 나는
  방식대로. 첫음절 오타는 2차 문자 인덱스로 잡습니다.
- **형태론 인지 인용 감지**: 자모 수준 어간 매칭이 활용(`만든` ↔
  `만들었다`), ㄹ탈락, 띄어쓰기 변이를 버팁니다. 질문 장식(`~한 인물은?`)은
  커버리지 계산 전에 제거됩니다.
- 영어 노트에 한국어로 질문해도 full-support 0.950. BM25는 0.250,
  MemPalace는 0.350입니다.

## 이런 게 됩니다

```
$ lemory ask "3분기 킥오프에서 예산 얼마로 잡았지?"                 # 회의록
$ lemory ask "데이터플랫폼팀 리드가 누구고 무슨 일 하는 팀이지?"      # 조직/사람
$ lemory ask "재택근무 정책, 작년이랑 지금이랑 뭐가 달라졌지?"        # 시간 축 정책 비교
$ lemory ask "자바스크립트 이벤트 루프 뭐였지? 내 노트 기준으로"      # 공부 노트
$ lemory ask "카오스 벨룸 가기 전에 준비물 뭐라고 적어놨더라?"        # 게임 준비 노트
$ lemory ask "오사카에서 갔던 그 라멘집 이름이 뭐였지?"              # 여행 기록
```

순수 RAG가 구조적으로 못 하는 것들:

```
$ lemory ask "프로젝트 아틀라스 리드가 좋아하는 DB가 뭐더라?"
# 멀티홉: 아틀라스 노트 → [[리드]] 위키링크 → 그 사람 노트에 답이 있음

$ lemory ask "요새 내가 읽던 책 뭐였지?"
요즘 읽는 책은 어스시의 마법사이다 [1, 3].     # 시간: *현재* 책
$ lemory ask "3월에 읽던 책은?"                # 3월을 물으면 과거에 닿음

$ lemory search "tag:회의록 folder:2026 예산"   # 스코프 연산자, 전 모드
$ lemory remember "VPN 갱신은 매년 3월, 담당 김하늘" --tags ops   # CLI에서 기억 쓰기
$ lemory import-chats conversations.json        # ChatGPT/Claude 대화 → 검색되는 노트
$ lemory connect ./my_source.py                 # 커넥터 SDK: 아무 소스 → 볼트 노트
$ lemory graph --open                           # 볼트 전체를 인터랙티브 그래프로
$ lemory context                                # 에이전트용 볼트 요약 한 방
```

오타는 당신 볼트의 어휘를 기준으로 교정됩니다(API 없음). 이름 변경, 삭제,
별칭, 한국어 파일명: 워처가 실시간으로 따라갑니다. `default_scope` 설정을
두면 모든 질의가 기본으로 그 폴더/태그 범위 안에서 돌고(`scope:all`로 1회
해제), 질의에 연산자를 직접 쓰면 그게 항상 이깁니다.

## 왜 잘 나오나: 마법이 아니라 메커니즘

- **멀티홉 1.000 vs 0.53-0.81 (전원)**: 검색이 링크를 따라 1홉 확장하되,
  질의 유사도 AND 어휘 증거(BM25 목록에 이미 오른 이웃 청크가 질의의 잔여
  키워드를 지님)로 게이트하고, 직접 증거 아래로 캡핑합니다. 색인 시점에
  LLM 없이 채굴됩니다.
- **강건성 0.95+ vs 0.25-0.67**: 밀집 벡터와 BM25는 *다른 방식으로*
  실패합니다; 가중 RRF 융합이 둘을 덮습니다. 질의가 노트를 거의 그대로
  인용하면(IDF 가중 커버리지) BM25의 순서를 그대로 핀합니다 - 랭크만 보는
  융합은 결정적인 어휘 마진을 존중할 수 없습니다.
- **초가 아니라 밀리초**: 전부 인프로세스, SQLite FTS5 + numpy. 청크 2만
  개를 넘으면 벡터 쪽이 IVF-int8 인덱스로 자동 전환(여전히 numpy만):
  **청크 100만 = 5.9 ms/질의, 정확 검색 대비 recall@10 1.000, RAM 732 MB**
  ([§12b](BENCHMARKS.md)). SQLite를 *교체*하는 것(DuckDB, LanceDB)까지
  벤치마크하고 왜 안 했는지 공개했습니다 ([보고서](docs/STORAGE.md)).
- **0으로 수렴하는 비용**: 내용 주소 임베딩 캐시; Gemini 무료 티어로 하루
  ~250질문; 완전 온디바이스 모드(한국어 특화 e5 임베딩 + llama.cpp 위
  Gemma 4 답변, 데몬 없음)는 바이트 하나 나가면 안 되는 망분리 환경용.

## 개발자용

```python
import lemory
lemory.configure(vault="~/Obsidian/MyVault")
lemory.index()
print(lemory.ask("가격 정책 뭐라고 결정했더라?").text)
```

TypeScript/Node (Vercel AI SDK, LangChain.js, 순수 에이전트) - 의존성 0
클라이언트가 [`clients/js`](clients/js)에:
`new Lemory({client: "my-agent"}).search(...)`.

Python 프레임워크 - 기존 파이프라인에 볼트를 끼워 넣으세요
(`lemory.integrations`, soft deps, 둘 다 실제 프레임워크로 테스트됨):

```python
from lemory.integrations.langchain import LemoryRetriever     # langchain-core
from lemory.integrations.llamaindex import LemoryLlamaRetriever  # llama-index-core
```

셀프호스팅: `docker build -t lemory . && docker run -p 127.0.0.1:8377:8377
-v ~/vault:/vault lemory`. 뭔가 이상하면 `lemory doctor`가 볼트, 인덱스
정합성, FTS5, 임베더, 생성기를 한 방에 점검합니다 - 그 출력을 이슈에
붙여주세요.

[Cerebras의 사내 지식베이스 write-up](https://www.cerebras.ai/blog/how-we-built-our-knowledge-base)에서
가져온 것(mex처럼 출처 표기): **랭킹 후 이웃 확장** - 랭킹이 확정된 뒤 각
승자 청크에 앞뒤 청크의 꼬리/머리를 다시 붙여, 청킹이 갈라놓은 전제와
주의사항을 되살립니다(`context_neighbors`; 콘솔 비서에선 항상 on, ask()는
공개 e2e 수치를 보존하려 opt-in). **대화 버스트 청킹** - 같은 화자의 연속
발화 중 신호가 있는 것을 집중 청크로 추가 색인하되, 융합에선 자기 노트의
랭크를 올리는 별칭으로만 작동합니다(실측 원장 전체가 §7e에). 그들의 다른
핵심 수(어휘+벡터+최신성 RRF 융합, 소스별 결과 캡, 에이전트가 조율하는
LLM-프리 MCP 프리미티브, 스레드 증류)는 Lemory가 이미 출하하고 측정한
아키텍처입니다.

격차 분석이 요구해서 추가된 것들: `lemory ask --deep`(LLM이 어려운 질문을
하위 질의로 분해해 각각 검색, 증거 병합 - opt-in, 호출 1회 추가);
`lemory backup` / `restore`(인덱스 + 사용 상태; 노트는 이미 당신
파일입니다); `index_docx = true`(stdlib Word 텍스트 추출);
`lemory connect`(커넥터 SDK: pull(state) 증분 커서, 멱등 upsert - 외부
소스가 평범한 볼트 노트가 됩니다); `default_scope`(Cerebras 프로젝트식
기본 검색 범위); 그리고 **모바일**: `lemory serve --host 0.0.0.0` +
lemory.toml의 `api_token` → 폰/테일넷 클라이언트는
`Authorization: Bearer <token>`으로 인증하고 localhost는 무설정 그대로.

정책대로 공개하는 부정적 결과: **시맨틱 폴백 링크**(링크 없는 노트에
코사인 최근접 간선)는 만들고, 링크 제거 멀티홉 코퍼스에서 측정하고,
**반증됐습니다** - 제목 언급만으로 완전 복구(1.000)되는 반면 시맨틱 간선은
언급이 못 미치는 곳에서도 무그래프보다 낮습니다(`benchmarks/run_linkless.py`).
기본 off의 opt-in으로 출하; 정직한 교훈은 Lemory의 멀티홉이 언급 링크
덕분에 링크 없는 볼트에서도 이미 생존하며, 유사도 간선은 관계의 다리가
아니라는 것입니다. **리랭커의 시간맹**도 같은 정책으로: recency 블렌드
사후 보정까지 실제 Qwen3-Reranker 3팔 A/B로 측정해 반증하고 되돌렸습니다
(off 0.978 / on 0.889 / on+블렌드 0.867 - §7f).

`lemory serve`의 REST: `GET /search` · `POST /ask` · `GET /context` ·
`POST /memory` · `POST /append` · `POST /memory/trash` · `POST /index` ·
`GET /status`, 그리고 대시보드 API(`/api/events`, `/api/clients`,
`/api/notes`, `/api/related`, ...). `X-Lemory-Client` 헤더(또는
`lemory mcp --client <name>`)로 통합을 밝히면 대시보드 타임라인에 출처가
표시됩니다.

옵시디언 사이드바 플러그인(파일 3개 복사 설치), PDF 색인
(`pip install 'lemory[pdf]'`, `index_pdf = true`), 모든 검색 노브는
[`lemory.toml`](docs/GUIDE.ko.md), 엔지니어링 딥다이브는
[BENCHMARKS.md](BENCHMARKS.md) · [docs/STORAGE.md](docs/STORAGE.md) ·
[docs/COMPETITIVE.md](docs/COMPETITIVE.md).

## 작동 원리

```
 당신의 볼트 (*.md) ──감시──► 파싱: frontmatter · 태그 · [[링크]] · 날짜
                                 │
                                 ▼
              SQLite 파일 하나: 청크 · BM25 · 링크 그래프 · 임베딩 캐시
                              + 이벤트 타임라인      + IVF-int8 (큰 볼트)
                                 │
 질의 ─► 오타 교정 ─► 밀집 + 어휘 (RRF 융합) ─► 제목·최신성 부스트
                                 │
                        1홉 그래프 확장   ← 멀티홉 답은 여기서 나옵니다
                                 │
                                 ▼
              날짜와 출처가 붙은 컨텍스트 (~550토큰) ─► LLM ─► 답변 [n]

 save_memory ─► 중복 검사 ─► 볼트 안의 순수 .md ─► 다음 질문부터 검색됨
```

검색은 로컬이고 LLM-프리입니다(~3-13 ms). 질의당 임베딩 1회(캐시됨),
`ask()`당 생성 1회.

## 정직 섹션

- 문서를 그대로 인용하는 질문은 오랫동안 순수 BM25가 유리했고 우리는 그게
  사실인 동안 그대로 실었습니다. 2026-07 한국어 검색 라운드에서 뒤집혔고
  (위 KorQuAD 표), git 히스토리가 옛 수치를 보존합니다.
- qmd의 간판 모드에서도 이제 품질까지 앞섭니다: 동일 문항에서 0.875 vs
  0.769 (한국어 특화 e5 기본 적용 후; 옛 MiniLM에선 0.775 동률이었습니다).
  ~3,700배 지연 격차는 원래도 있었습니다.
- kepano의 작은 영어 볼트는 밀집 검색만으로 거의 포화됩니다; 거기선
  vector-only가 한 문제 차로 우리를 이기고 BENCHMARKS가 그렇게 적습니다.
- ~42k 청크 코퍼스의 2-hop full-support는 측정한 전원에게 어렵습니다; e5
  기본이 우리 로컬 수치를 0.477로 올렸고(MiniLM 0.141), 60초/질의를 내는
  qmd의 0.333보다 앞서지만, BENCHMARKS에 상시 도전 과제로 남습니다.
- LOCOMO/LongMemEval judged 수치는 API 예산에 맞춘 층화 표본입니다;
  `--all` 플래그가 풀셋을 돌립니다. 타 팀의 공개 수치는 다른 생성기/저지
  기준이라 맥락으로만 인용하지, 승리 선언으로 쓰지 않습니다. Zep은
  GPT-4급 구성으로 DMR 94.8을 보고합니다; 이겼다고 주장하지 않습니다.
- SQLite 자체를 교체하는 것도 벤치마크했습니다(DuckDB, LanceDB:
  [전체 보고서](docs/STORAGE.md)). LanceDB의 FTS는 최악 케이스 코퍼스에서
  우리 FTS5 경로보다 진짜로 ~5배 빠릅니다; 그걸 공개하고도 SQLite에
  남습니다. 나머지 네 축(증분 동기화 x82, PK 조회 x75, 2프로세스 접근,
  네이티브 의존성 0)은 SQLite가 이깁니다.
- mem0/cognee/supermemory/LightRAG의 KorMapleQA 비교는 라벨된 400노트
  서브코퍼스 프로토콜입니다 - 그들의 노트당 LLM 인제스트가 과금되기
  때문이고, 풀코퍼스 열은 누군가 API 비용을 대면 채워집니다.
- 버스트 청킹의 회귀도 원장에 있습니다: 클린 long 1문항(-0.8pt), messy
  번복 함정 1문항(융합 점수차 0.0001) - 고치는 패치가 joke 함정을 무너뜨려
  폐기했고, 이득과 회귀를 함께 공개합니다 (§7e).

## 로드맵

- [ ] PyPI (`pip install lemory`) · [ ] 옵시디언 커뮤니티 플러그인 등록
- [x] AI 쓰기 경로 + 되돌리기 있는 대시보드 타임라인 · [x] 클라이언트 출처 표시
- [x] 기억 통합 (중복 플래그 + 관련 링크)
- [x] 링크 제안 · [x] 인터랙티브 그래프 내보내기 · [x] 어시스턴트 스킬
- [x] PDF 색인 (opt-in) · [x] 100만 청크 볼트용 ANN 인덱스
- [x] 채팅 내보내기 임포트 (ChatGPT/Claude) · [x] KorMapleQA 벤치마크
- [x] 커넥터 SDK (`lemory connect`) · [x] 기본 검색 범위 (`default_scope`)
- [ ] 이미지 OCR / 오디오 전사 (opt-in extras) · [ ] 웹 클리퍼
- [ ] 멀티 볼트 프로필

## 기여

`uv venv && uv pip install -e ".[dev,mcp,local,pdf]" && pytest`: 400개
테스트, 완전 오프라인. [CONTRIBUTING.md](CONTRIBUTING.md) · 한국어 이슈/PR
환영합니다.

설계부터 로컬 우선입니다. 신뢰 모델, localhost 서버의 가드(CORS +
DNS-rebinding 대비 Host 허용목록), 취약점 신고 방법은
[SECURITY.md](SECURITY.md)에 있습니다.

**[English README](README.en.md)** · MIT
