<div align="center">

# 🍋 Lemory

### 기억은 당신의 것이어야 합니다.
**남의 데이터베이스 행이 아니라, 당신 볼트 안의 마크다운 파일로.**

<img src="docs/assets/demo1_korean.gif" alt="실제 나무위키 1,469노트 볼트에서 한국어 질문이 13ms에 답변되고 오타가 자동 교정되는 실제 데모" width="840">

<sub>목업이 아닙니다. 실제 나무위키 1,469문서 / 33,382청크 볼트에서 한국어
질문이 로컬 연산 13ms에 답변되고, 오타는 API 없이 교정되는 장면입니다.
[`benchmarks/`](benchmarks/)로 재현됩니다.</sub>

</div>

---

**Lemory는 당신의 마크다운을 위한 로컬 메모리 미들웨어입니다.** 당신의 노트와
당신이 쓰는 모든 AI(Claude Desktop, Claude Code, Cursor, 직접 짠 스크립트)
사이에 앉아서, 당신이 적어둔 모든 것을 AI가 기억해내게 하고, 기억할 가치가
있는 것을 당신 소유의 마크다운 파일로 만들어 줍니다.

- **AI가 기억을 꺼냅니다**: 시맨틱 + 한국어 인지 키워드 + 위키링크 그래프
  하이브리드 검색. 경쟁 제품 전부와 같은 조건에서 실측하고, 지는 항목도
  공개합니다.
- **AI가 기억을 넣습니다**: 결정사항과 사실이 볼트 안의 순수 `.md` 노트로
  저장됩니다. 중복은 감지해 표시하고, 관련 기억은 위키링크로 연결합니다.
  옵시디언에서 보이고, 버전 관리되고, `rm` 한 번이면 사라집니다.
- **미들웨어를 지켜봅니다**: 대시보드가 지나간 모든 것을 보여줍니다. 모든
  질의, AI가 적은 모든 노트(원클릭 되돌리기), 클라이언트별 사용량. 전부
  로컬, SQLite 파일 하나.

> **아무것도 Lemory를 "통해서" 넣을 필요가 없습니다.** 볼트는 그냥
> 파일입니다. 늘 하던 대로 노트를 쓰세요(옵시디언, 아무 편집기, 셸
> 스크립트). 워처가 1초 안에 색인합니다. `save_memory`와 `lemory remember`는
> *AI가* 쓸 때 출처 표시, 중복 검사, 되돌리기 버튼을 얻기 위한 경로일
> 뿐입니다. 관문이 아니라 예우용 출입구입니다.

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
도는 장면입니다. qmd의 BM25는 AND 결합이라 한국어 자연어 질문에 0건을
돌려주고, MemPalace는 영어 중심 임베더에 한국어 어휘 경로가 없습니다.
Lemory는 보스 노트 자체를 1위로, 13ms에, LLM 0회로 돌려줍니다.

qmd가 로컬 LLM 풀파이프라인(질의 확장 + 리랭크)을 돌리면 품질은 Lemory
수준에 도달합니다. 대신 쿼리당 59.5초를 냅니다:

<div align="center">
<img src="docs/assets/chart_qmd_rematch.svg" width="840" alt="동일 329문항: Lemory 0.775@20ms vs qmd query 0.769@59.5s">
</div>

가장 스타가 많은 OSS 메모리 레이어 mem0와는 같은 코퍼스, 같은 Gemini 모델
엔드투엔드로:

<div align="center">
<img src="docs/assets/chart_mem0.svg" width="840" alt="같은 조건에서 Lemory vs mem0, 전 축">
</div>

## 2분 시작

```bash
pipx install "git+https://github.com/jwgo/lemory"
lemory up ~/Obsidian/MyVault    # 딸깍: 키 감지, 모드 선택, 색인, 대시보드
lemory ask "요새 내가 하던 그 프로젝트 어디까지 했지?"
```

키가 없어도 됩니다. Gemini 키가 있으면 풀 모드, 없고 fastembed가 있으면
로컬 검색 모드, 둘 다 없으면 **키리스 모드**(BM25+링크 그래프, 그래도
유용하고 키를 넣으면 자동 업그레이드)로 알아서 동작합니다. 인제스트에
LLM이 돌지 않아서 **노트 1,000개 색인 = LLM 호출 0회**입니다:

<div align="center">
<img src="docs/assets/chart_ingest.svg" width="840" alt="1,469노트가 검색 가능해질 때까지 걸리는 시간">
</div>

**처음이라면: [docs/GUIDE.ko.md](docs/GUIDE.ko.md) · 일상 루틴: [docs/ROUTINE.ko.md](docs/ROUTINE.ko.md)**

## Claude에게 기억을 주기

```bash
claude mcp add lemory -- lemory mcp --vault ~/Obsidian/MyVault --client claude-desktop
lemory skill install claude-code    # 어시스턴트에게 사용법까지 가르치기
```

11개 툴: 읽기 9개(검색, 질문, 최근, 관련, 링크 제안, 컨텍스트 등) + 쓰기
2개(save_memory, append_note). Claude가 결정과 사실을 **볼트 안의 순수
마크다운 노트로** 저장합니다. 덮어쓰기 불가, 볼트 탈출 불가, 추가 전용.

```bash
lemory hooks install claude-code    # 세션이 끝나면 기억할 것들이 자동 저장
```

AI가 적은 모든 노트는 대시보드의 **AI 메모리 피드**에 "누가, 언제"와 함께
뜨고, 버튼 하나로 되돌립니다(`.trash`, 옵시디언 자체 휴지통. 사람이 쓴
노트는 구조적으로 거부). 아무것도 보이지 않게 지나가지 않습니다. 그게
미들웨어의 계약입니다.

노트 frontmatter에 `lemory: false` 한 줄이면 그 노트는 색인도, 검색도,
어떤 모델로도 전송되지 않습니다. **프라이버시가 파일 속성입니다.**

## 로그 파일이 아니라 세컨드브레인

<div align="center">
<img src="docs/assets/demo3_secondbrain.gif" width="840" alt="중복 기억이 위키링크로 표시되고, 연결 안 된 언급이 링크 제안으로 나온다">
</div>

사람이 쓴 노트에는 이 장치들이 전혀 필요 없습니다. 파일을 볼트에 떨어뜨리면
다음 질의에서 바로 검색됩니다. 아래 기능들은 *기계가* 쓰는 노트를 위한
것입니다.

- **save_memory가 통합합니다**: 새 기억을 저장할 때마다 볼트가 이미 아는
  것과 대조합니다. 근접 중복은 `possible_duplicate_of:`로 표시되고 관련
  노트는 `related:` 위키링크로 연결됩니다. mem0식 사실 업데이트에서 파괴적
  재작성을 뺀 것: 우리는 연결하고, 결정은 당신이 합니다.
- **`lemory suggest-links`**: 본문에서 서로를 언급하지만 연결된 적 없는
  노트들을 문장 증거와 함께 제안합니다. LLM 0회.
- **`lemory graph`**: 볼트 전체를 자체완결 인터랙티브 HTML 하나로
  내보냅니다. 1,469노트 24,850엣지가 약 1초, LLM 0회. 2026년의 그래프 도구
  물결은 같은 산출물에 파일마다 LLM을 태웁니다.
- **`lemory drift`**: "내 기억이 아직 현실과 맞나?"에 답합니다. 깨진
  [[위키링크]], 사라진 파일로 가는 링크, 아무도 해소하지 않은 중복 플래그를
  찾고, `--prompt`는 그걸 그대로 고치라는 에이전트용 수리 프롬프트로
  렌더링합니다. 결정적, 토큰 0. (코딩 에이전트 스캐폴드에서 드리프트 감지를
  개척한 [mex](https://github.com/mex-memory/mex)에 경의를. mex는 랭킹
  검색이 없어 우리 표의 행이 아니라 우리가 흡수한 아이디어로 삽니다.)
- **시간 이해**: "요새 내가 하던 그거 뭐였지?"는 언급이 더 많은 옛 사실
  대신 현재 사실을 고르고, "3월에 읽던 책은?"은 과거에 닿습니다.

## 한국어가 1등 시민입니다

- **한글 + 가나 + 한자 바이그램 색인**: 조사가 붙은 어절,
  `ナイトロード나이트로드` 같은 혼합 스크립트, JMS/CMS 표기 테이블까지
  전부 매칭됩니다.
- **음절 단위 오타 교정**: `메플이스토리`가 메이플스토리를 찾습니다. 인접
  전위가 편집 1회로 계산됩니다(음절 Damerau-Levenshtein). 첫음절 오타도
  2차 문자 인덱스로 잡습니다.
- **형태론 인지 인용 감지**: 자모 수준 어간 매칭이 활용(`만든` ↔
  `만들었다`), ㄹ탈락, 띄어쓰기 변이를 버팁니다. 질문 장식(`~한 인물은?`)은
  커버리지 계산에서 제외됩니다.
- 영어 노트에 한국어로 질문해도 full-support 0.950. BM25는 0.250,
  MemPalace는 0.350입니다.

<div align="center">
<img src="docs/assets/chart_robustness.svg" width="840" alt="패러프레이즈, 한국어, 키워드, 오타 강건성">
</div>

**KorQuAD 1.0** (실제 한국어 위키피디아, 인간 작성 질문 400개): recall@1
**0.940**으로 BM25(0.928)를 추월했습니다. 이 표는 오랫동안 BM25가 이겼고
우리는 그동안 그 사실을 그대로 실었습니다. 2026-07 한국어 검색 라운드가
드디어 뒤집었습니다.

**[KorMapleQA](benchmarks/data/kormapleqa/README.md)**: 실제 나무위키
메이플스토리 도메인 위의 2,075문항 벤치마크를 직접 만들어 공개합니다.
인포박스 사실, 엔티티 마스킹, 실링크 2-hop, 시간, 키워드/반말/오타 변형,
부재 검증 무응답까지. 100% 코드 생성, 기계 검증, API 키 0개로 재현.

## 멀티홉: 위키링크를 읽는 쪽이 LLM 그래프를 이깁니다

<div align="center">
<img src="docs/assets/chart_multihop.svg" width="840" alt="2-hop 질문: LLM 그래프 파이프라인 대비">
<img src="docs/assets/chart_longmemeval.svg" width="840" alt="LongMemEval 전체 500문항, API 0회">
</div>

LongMemEval_S 전체 500문항 리트리벌을 로컬 임베더만으로: Recall@5
**0.972**(any) / 0.857(strict). 헤드라인들이 쓰는 지표(any)에서 풀셋,
제로 API로 그 수준이고, 더 엄격한 숫자를 앞세워 둘 다 공개합니다.

## 이런 게 됩니다

```
$ lemory ask "3분기 킥오프에서 예산 얼마로 잡았지?"
$ lemory ask "프로젝트 아틀라스 리드가 좋아하는 DB가 뭐더라?"   # 멀티홉
$ lemory ask "요새 내가 읽던 책 뭐였지?"                        # 시간 이해
$ lemory search "tag:회의록 folder:2026 예산"                   # 스코프 연산자
$ lemory remember "VPN 갱신은 매년 3월, 담당 김하늘" --tags ops  # CLI에서 기억 쓰기
$ lemory import-chats conversations.json    # ChatGPT/Claude 대화, 검색되는 노트로
$ lemory graph --open                       # 볼트 전체를 인터랙티브 그래프로
$ lemory context                            # 에이전트용 볼트 요약 한 방
```

## 큰 볼트도, 망분리도 됩니다

- 나무위키 실문서 1,469편(청크 33,382개, 실제 위키링크 24,850개)을 그대로
  색인해 검증했습니다.
- 청크 2만 개를 넘으면 IVF-int8 인덱스로 자동 전환(여전히 numpy뿐):
  **청크 100만 개에서 5.9ms/질의, 정확 검색 대비 recall 1.000, RAM 4분의 1**.
- SQLite를 DuckDB/LanceDB로 바꾸는 것까지 실측해 보고서로 공개했습니다
  ([docs/STORAGE.md](docs/STORAGE.md)). 안 바꾸는 근거도 숫자입니다.
- 완전 오프라인 모드 2종: 외부로 나가는 바이트 0. 망분리, 폐쇄망에서
  그대로 돌아갑니다. PDF 색인은 opt-in.

## 대시보드

`lemory serve` → `127.0.0.1:8377`. 옵시디언을 복제한 화면이 아니라
**미들웨어를 지나간 것**을 보는 화면입니다: AI 메모리 피드(되돌리기 포함),
최근 질의와 출처, 클라이언트별 사용량, 색인 활동, 노트별 참조 횟수와 로컬
그래프(옵시디언 그래프에 없는 '언급' 간선까지), 관련 노트, 검색
플레이그라운드, 라이브 설정.

<img src="docs/assets/webui.png" alt="로컬 대시보드: 메모리 피드, 질의 로그, 클라이언트별 사용량" width="820">

## 정직 정책

공개한 숫자는 누군가 검증합니다. 그래서 비교한 모든 시스템의 하니스를
커밋하고, 경쟁 제품이 이기는 축(kepano 밀집 검색, qmd의 2-hop 문서
커버리지, Omnisearch의 키워드 홈그라운드)을 그대로 인쇄하고, 미해결
문제(33k 청크 코퍼스의 2-hop full-support는 우리 포함 전원이 어렵습니다)를
BENCHMARKS.md에 상시 게시합니다. 재현이 안 되는 숫자가 있으면 이슈를
열어주세요. 이슈가 아니라 숫자를 고치겠습니다.

MIT · 이슈/PR 환영 · **[English README](README.md)**
