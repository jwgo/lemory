# Lemory for Obsidian

볼트에게 직접 물어보세요 — 출처(클릭하면 해당 노트로 이동)와 날짜가 붙은 답이 사이드바에 뜹니다.
백엔드는 로컬에서 도는 `lemory serve` 하나면 됩니다.

## 설치 (2분)

```bash
# 1. 백엔드 (한 번만)
pip install lemory   # 또는: pipx install "git+https://github.com/jwgo/lemory"
lemory setup         # 볼트 경로 + Gemini 키 입력하면 끝
lemory serve         # 켜두면 인덱스가 실시간으로 따라옵니다

# 2. 플러그인 파일 복사
mkdir -p <볼트>/.obsidian/plugins/lemory
cp main.js manifest.json styles.css <볼트>/.obsidian/plugins/lemory/
```

Obsidian → 설정 → 커뮤니티 플러그인에서 **Lemory** 활성화.

## 사용

- 리본의 🧠 아이콘 또는 명령 팔레트 → **Lemory: Ask your vault**
- 사이드바 입력창에 질문 (Enter = LLM 답변+출처, 검색 버튼 = 관련 노트 즉시 나열)
- 에디터에서 텍스트 선택 후 **Search vault for selected text**

서버 주소가 다르면 플러그인 설정에서 변경 (기본 `http://127.0.0.1:8377`).

## 개발

```bash
npm install && npm run build   # main.ts -> main.js
```
