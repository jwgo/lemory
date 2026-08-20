# 아키텍처: 엔진 / 데몬 / 인터페이스

세 층의 경계와 의존 규칙. 규칙은 문서가 아니라 **테스트가 지킨다**
(`tests/test_architecture.py` · import 위반은 CI 실패다).

```
┌─ 인터페이스 (어댑터 · 얇음) ──────────────────────────────────────┐
│  interfaces/cli.py       터미널                                    │
│  interfaces/http.py      REST + 콘솔 API (transport만)             │
│  interfaces/console/     웹 UI (SPA · /api/* 만 호출)              │
│  interfaces/mcp.py       MCP 툴 19개                               │
│  interfaces/proxy.py     OpenAI 호환 /v1 프록시                     │
│  interfaces/hooks.py     Claude Code 세션 훅                        │
│  obsidian-plugin/        옵시디언 (HTTP로만 접속)                   │
└────────────────────────────┬───────────────────────────────────────┘
                             │  Engine 파사드 메서드만 호출
┌─ 데몬 (수명주기) ──────────┼───────────────────────────────────────┐
│  daemon.py    start/stop/status/logs · pidfile · /health 프로브    │
│  serve 내부   워처 스레드 · auto-consolidate 틱 · graceful stop    │
└────────────────────────────┼───────────────────────────────────────┘
                             │
┌─ 엔진 (도메인 · 제품의 실체) ──────────────────────────────────────┐
│  engine.py    파사드: search/ask/remember/recall/consolidate/…     │
│  assistant.py 대화 서비스 (의도 감지 · 후속질문 보정 · 턴 조립)      │
│  ingestion/   파싱·청킹·색인·기억 쓰기·피라미드·스킬 추출            │
│  retrieval/   하이브리드 검색·회상·케이스·링크·시간·모순             │
│  storage/     SQLite 한 파일 + 벡터 행렬                            │
│  providers/   Gemini/OpenAI/로컬(e5·Gemma) 클라이언트               │
│  config.py    설정 (env < toml < kwargs)                           │
└────────────────────────────────────────────────────────────────────┘
```

## 규칙

1. **인터페이스는 엔진 파사드만 부른다.** `interfaces/*`에서
   `lemory.ingestion.*` / `lemory.retrieval.*`를 import하면 테스트가
   실패한다. 새 기능을 표면에 노출하려면 먼저 `Engine`에 동사를 추가하라 ·
   그 동사가 CLI/HTTP/MCP/프록시 전부의 계약이 된다.
2. **비즈니스 로직은 HTTP 핸들러에 살지 않는다.** 대화 로직은
   `assistant.py`, 기억 로직은 `ingestion/`, 검색 로직은 `retrieval/`.
   핸들러가 하는 일은 파싱→파사드 호출→직렬화, 그게 전부다.
3. **엔진은 인터페이스를 모른다.** `engine.py`·`ingestion/`·`retrieval/`
   어디에도 `interfaces` import가 없다 (역방향 규칙, 같은 테스트가 지킨다).
4. **데몬은 계약이 아니라 배선이다.** 워처·자동통합 스레드는 상태 관리와
   엔진 동사 호출만 한다. 프로세스 관리는 `daemon.py` · pidfile은 liveness
   확인과 함께만 신뢰하고, 죽은 pidfile은 자동 정리한다.

## 왜 이 모양인가

- 파사드 하나가 표면 다섯 개(CLI/HTTP/MCP/프록시/훅)의 드리프트를 막는다 ·
  같은 동사가 어디서나 같은 파이프라인(중복 검사, 승인 게이트, 이벤트
  로그, git 체크포인트)을 통과한다.
- 어댑터가 얇으면 표면 추가가 싸다. 봇/TUI/새 프로토콜은 파사드 호출
  묶음일 뿐이다.
- 데몬 분리는 "제품처럼 설치되고 관리되는가"의 문제다. `lemory daemon
  start`가 nohup보다 나은 이유는 실패가 침묵하지 않기 때문이다 · 시작
  실패 시 로그 꼬리를 에러에 담아 보여준다.

## 프로세스 모델

`lemory serve`(또는 `daemon start`) 프로세스 하나가 전부다: FastAPI +
콘솔 정적 파일 + MCP는 별도 stdio 프로세스(`lemory mcp`) + 워처·자동통합은
데몬 스레드. 상태는 SQLite 한 파일(WAL)이라 SIGKILL에도 안전하고,
그래서 `daemon stop`의 최후 수단 KILL이 데이터를 걸지 않는다.
