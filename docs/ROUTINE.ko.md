# 🍋 세컨드브레인 루틴

핵심 원칙: **캡처는 아무렇게나, 정리는 도구가, 검색은 대화로.**

## 1회 세팅 (10분)

```bash
lemory up ~/Obsidian/MyVault              # 색인 + 대시보드
claude mcp add lemory -- lemory mcp --vault ~/Obsidian/MyVault --client claude-code
lemory skill install claude-code          # Claude가 알아서 검색부터 하게
lemory hooks install claude-code          # 세션 끝나면 자동으로 기억 저장
```

민감한 노트(일기, 인사 정보)에는 frontmatter에 `lemory: false` 한 줄.
그 노트는 색인도, 어떤 모델로의 전송도 되지 않습니다.

## 매일: 사실상 0분 (습관만)

- **캡처는 평소처럼.** 옵시디언 데일리노트, 아무 편집기, 뭐든. Lemory를
  통할 필요가 없습니다. 워처가 알아서 색인합니다.
- **찾을 땐 검색하지 말고 물어보세요.** Claude에서 "지난주 회의에서 예산
  얼마로 정했지?"라고 하면 스킬이 search_notes를 먼저 부릅니다.
  터미널이면 `lemory ask`. 오타를 내도, 반말로 물어도 됩니다.
- **결정이 나오면 그 자리에서** "이거 기억해줘" 한 마디. save_memory가
  저장하면서 기존 기억과 겹치면 바로 알려줍니다. 잊어도 세션 종료 훅이
  요약을 남깁니다.
- **쓰는 요령 두 개**: 노트 제목은 엔티티 이름으로(사람, 프로젝트, 개념),
  본문에 [[링크]]를 아끼지 말 것. 그 링크가 멀티홉 질문("아틀라스 리드가
  좋아하는 DB는?")의 연료입니다.

## 매주: 5분 정원 가꾸기

```bash
lemory suggest-links      # 언급만 하고 링크 안 건 것들, 진짜만 [[링크]]로 승격
lemory drift              # 깨진 링크, 미해소 중복 점검
lemory drift --prompt     # 결과를 에이전트에 붙여넣으면 알아서 수리
```

대시보드(`lemory serve`) 피드도 한 번 훑으세요. AI가 이번 주에 뭘
적었는지 보이고, 이상한 건 undo 버튼 하나입니다. 링크를 승격할수록
그래프가 촘촘해지고, 그래프가 촘촘할수록 검색이 좋아집니다. 이 선순환이
이 도구의 요체입니다.

## 매달: 10분 조감

- `lemory graph --open`으로 볼트 전체를 봅니다. 고아 노트(연결 0)는
  링크를 걸거나 버리고, 뜻밖의 허브는 그 주제가 커지고 있다는 신호입니다.
- `lemory import-chats conversations.json`으로 ChatGPT/Claude 대화를
  백필하면 대화 속 결정들도 검색권에 들어옵니다.

## 질문 요령

- 시간 표현을 그대로: "요새", "지난주", "3월에". 파싱해서 반영합니다.
- 좁힐 땐 연산자: `lemory search "tag:회의록 folder:2026 예산"`.
- 답이 미심쩍으면 인용 [n]의 원 노트를 여세요. 근거가 없으면 "모른다"고
  답하도록 만들어져 있습니다.
