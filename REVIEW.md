# 시장 경쟁력 전수 점검 (2026-08)

100+ 항목을 하나씩 되짚은 대장이다. 판정은 세 가지: **OK**(근거 있음 · 테스트,
실측, 코드 확인), **FIXED**(이번 점검에서 고침), **DEFER**(사유와 함께 보류).
스스로에게 유리하게 채점하지 않기 위해 근거 없는 OK는 없다.

## A. 자동화 (기억이 스스로 정리되는가) · TDBAM 대비 최우선 갭이었다

| # | 점검 | 판정 |
|---|---|---|
| A1 | 피라미드 승격이 수동이다 (TDBAM은 유휴 타이머 자동) | **FIXED** · `auto_consolidate` 토글: serve 중 새 아톰이 idle 3분이면 백그라운드 승격. 토글은 틱마다 다시 읽어 재시작 불필요 |
| A2 | 자동 승격이 세션 도중에 끼어들어 LLM을 낭비하지 않는가 | **FIXED** · idle 디바운스 술어 `auto_consolidate_due` 단위 테스트 3케이스 (버스트 중 False, 유휴 True, 커서 이후 False) |
| A3 | 자동 승격 기본값 | OK · 기본 OFF. 명시 동의 없는 LLM 과금은 하지 않는다 (설정 탭 한 줄로 켬) |
| A4 | 실패한 자동 패스가 루프를 죽이는가 | OK · except-log-continue, 아톰은 pending으로 남아 다음 틱 재시도 |
| A5 | 세션 종료 훅 → 기억 자동 저장 | OK · `lemory hooks install claude-code` (기존) |
| A6 | 어시스턴트 대화 자동 세션 노트 | OK · `assistant_log_sessions` (기존) |
| A7 | 프록시 대화 자동 캡처 | OK · `proxy_capture` 기본 ON, chats/proxy/, distill이 승격 |
| A8 | 자동 재색인 | OK · 워처 1초 내 증분 색인 (기존, 죽으면 로그 경보) |
| A9 | 임베딩 모델 교체 시 자동 전체 재임베드 | OK · embed_signature 감지 (기존) |
| A10 | distill 자동화 | DEFER · consolidate와 달리 세션 노트 대량 LLM 처리라 비용이 큼. auto_consolidate 채택률 보고 결정 |

## B. 사용처 (에이전트가 실제로 사는 곳마다 있는가)

| # | 점검 | 판정 |
|---|---|---|
| B1 | MCP | OK · 19툴, 동작 주석(RO/WRITE) 포함, 등록 테스트로 고정 |
| B2 | OpenAI 호환 프록시 | OK · /v1/chat/completions + /v1/models, 실 OpenAI 업스트림으로 왕복 실증 |
| B3 | 프록시 스트리밍 | OK · SSE 통과 + 델타 재조립 캡처 (실패해도 스트림은 무손상) |
| B4 | 완전 로컬 프록시 경로 | **FIXED**(문서) · proxy_upstream → Ollama /v1 안내. TDBAM은 이 층이 없다(원격 모델 필수) |
| B5 | CLI | OK · up/serve/ask/remember/recall/case(s)/anchor/consolidate/persona/skills/distill 등 |
| B6 | HTTP API | OK · 41 엔드포인트 (피라미드 5 + 스킬 2 포함) |
| B7 | 웹 콘솔 | OK · 6뷰, 기억 뷰에 피라미드 전체(페르소나/장면/앵커/케이스/스킬)+통합 버튼, 브라우저 실렌더 검증 |
| B8 | 옵시디언 플러그인 | OK · 기존 3파일 플러그인 동작 (스토어 등록은 외부 절차 · H2) |
| B9 | Claude Code 스킬 문서 배포 | OK · `lemory skill install` |
| B10 | Cursor/Windsurf/Codex | OK · MCP stdio 공통 명령 + 프록시 baseURL 경로 문서화 |
| B11 | Python 라이브러리로 직접 사용 | OK · `create_engine()` 공개 API, 벤치가 그 경로로 돈다 |
| B12 | 팀 멀티테넌트 | DEFER · 단일 사용자 설계 (COMPETITIVE에 근거 명시), 경쟁 축이 아니라 선택 |

## C. 기억 품질 (피라미드·회상)

| # | 점검 | 판정 |
|---|---|---|
| C1 | 부트 컨텍스트 토큰 효율 | OK · 실측 1,345tok = 원문 덤프 1/48.8, 커버 0.347 (run_pyramid.py 재현) |
| C2 | 드릴다운 1회 커버 | OK · 0.667 @ 2,084tok (장면 스코프 하이브리드 top-1, 기계적 절차) |
| C3 | 검색층 안전망 | OK · top-8 커버 1.000 · 피라미드는 검색을 대체하지 않는다 |
| C4 | 장면 이름 품질 | **FIXED** · 'general'→'일반', 'undated' 꼬리표 제거 |
| C5 | 장면 무한 증식 방지 | OK · scene_cap(12) 도달 시 가장 차가운 장면에 흡수, 테스트 고정 |
| C6 | 전개(evolution trail) 덮어쓰기 방지 | OK · LLM 프롬프트 규칙 + 폴백 경로 이월 누적, 테스트 고정 |
| C7 | 페르소나 폭주 방지 | OK · 2000자 하드캡 + "변경 없음" 존중 + 추측 금지 가드, 테스트 고정 |
| C8 | 오프라인(무LLM) 바닥 | OK · 결정적 폴백 본문 · TDBAM에 없는 층 |
| C9 | 회상 중복 행 | OK · 파편=노트 1행 규칙 (지난 패스에서 잡은 찐빠, 회귀 테스트 있음) |
| C10 | 발췌에 frontmatter 노출 | OK · enrichment 의사청크 대신 본문 표시 (회귀 테스트 있음) |
| C11 | 업데이트 함정 (옛 값이 최신 위로) | OK · RoleMemQA trap_above_gold 0.0 실측 |
| C12 | 시간 인지 회상 | OK · temporal 층 + 시나리오 hit@1 1.000 (기존 실측) |
| C13 | 모순 탐지 | OK · `lemory conflicts` (기억 vs 기억), `drift` (기억 vs 현실) |
| C14 | 중복 기억 통합 | OK · save_memory 이중 임계 dedup + related 위키링크 |
| C15 | 페르소나가 다인 볼트에서 눌리는 한계 | OK(명시) · BENCHMARKS §14 caveat로 공개 |

## D. 스킬 자산

| # | 점검 | 판정 |
|---|---|---|
| D1 | 게이트가 실제로 거르는가 | OK · 실 모델이 파편 2개 케이스를 '없음' 판정 (실증 기록) |
| D2 | 미완결 케이스 차단 | OK · open>0 케이스 제외, 테스트 고정 |
| D3 | 증분 갱신 · 중복 파일 방지 | OK · skill_case 바인딩 + "변경 없음" 존중, 테스트 고정 |
| D4 | 키리스 동작 | OK(의도) · 판정 없는 추출은 케이스 덤프라 안 함 (문서 명시) |
| D5 | 스킬 이름 위생 | OK · kebab 강제 + sanitize, 본문 80자 미만 거부 |

## E. 신뢰성·안전

| # | 점검 | 판정 |
|---|---|---|
| E1 | 볼트 탈출 (path traversal) | OK · _safe_target 전 쓰기 경로 + 테스트 |
| E2 | AI 삭제 가드 | OK · lemory_generated 마커만 휴지통 이동 가능, meta 위조 차단 테스트 |
| E3 | 승인 게이트 | OK · memory_approval (옵트인) |
| E4 | 프록시 키 유출 | OK · 클라이언트 Authorization 미전달, 테스트 고정 |
| E5 | DNS 리바인딩 | OK · Host 가드 421 (기존) |
| E6 | 원격 접근 | OK · 비로컬은 api_token 필수, 미설정 시 거부 |
| E7 | 프록시 캡처 프라이버시 | OK · proxy_capture 토글 + `lemory: false` 노트 제외 (기존 규약 상속) |
| E8 | 동시 쓰기 | OK · open("x") 충돌 루프, index lock (기존) |
| E9 | 자동 패스 예외 격리 | OK · A4와 동일 |
| E10 | 콘솔 XSS | OK · esc() 전 사용자 문자열 (신규 뷰 포함) |
| E11 | CLI Rich 마크업 주입 | **FIXED** · 노트 제목/스니펫 렌더 4곳 escape 추가 (기억/링크제안/충돌/검색 테이블) |
| E12 | mcp 2.0 호환성 | OK · `mcp<2` 핀 (2.0의 fastmcp 이동), 별도 포팅은 로드맵 |

## F. 성능

| # | 점검 | 판정 |
|---|---|---|
| F1 | 검색 지연 | OK · 하이브리드 ~0.1s, fast 모드 3.8ms (기존 실측) |
| F2 | 100만 청크 | OK · ANN 5.9ms/질의 recall 1.000 (기존 실측 §12b) |
| F3 | 색인 LLM 0회 | OK · 1,000노트 = LLM 0회 (기존) |
| F4 | consolidate 비용 | OK · 커서 증분 · 아톰 없으면 no-op, 그룹당 1 LLM 호출 |
| F5 | 부트 컨텍스트 조립 | OK · LLM 0회, 수 ms (파일 읽기+메타) |
| F6 | 프록시 오버헤드 | OK · 주입은 로컬(부트+회상 4건), 업스트림 왕복이 지배 |
| F7 | docs_meta 전량 스캔 | OK(규모) · 개인 볼트 ~1e4 문서에서 ms대 · 10만+ 시 인덱스 컬럼 고려 (로드맵 메모) |

## G. 온보딩·UX

| # | 점검 | 판정 |
|---|---|---|
| G1 | 설치 한 줄 | OK · pipx git+https (PyPI는 외부 절차 · 최우선 로드맵 유지) |
| G2 | `lemory up` 단일 진입 | OK · 키 유무 자동 모드, 볼트 질문, 대시보드까지 |
| G3 | 키 없이 처음부터 동작 | OK · e5-small-ko-v2 내장 |
| G4 | 설정 변경 재시작 불필요 | OK · 콘솔 PATCH 즉시 적용 + toml 저장 (auto_consolidate 포함) |
| G5 | 기억 뷰 정보 구조 | OK · 피라미드 순서(페르소나→장면→앵커→케이스→스킬) = 주입 순서와 동일 · 제품이 곧 설명 |
| G6 | 빈 상태 안내 | OK · 각 섹션 빈 상태에 다음 행동 문구 ("통합으로 생성" 등) |
| G7 | 콘솔 다크/타이포 일관성 | OK · 기존 디자인 시스템 변수 재사용, 스크린샷 검증 |
| G8 | 데모 GIF | DEFER · 피라미드/프록시 데모 GIF는 렌더러 재실행 필요 (기존 8개는 유지) |
| G9 | 문서 이중 언어 | OK · README ko/en 동기, 신규 절 모두 반영 |
| G10 | 일상 루틴 문서 | **FIXED** · ROUTINE.ko에 consolidate/자동화 한 단락 추가 |

## H. 정직성·벤치마크

| # | 점검 | 판정 |
|---|---|---|
| H1 | 모든 수치 재현 스크립트 | OK · run_pyramid.py 포함, 커밋된 코드+공개 데이터 |
| H2 | 경쟁사 발표치와 실측 구분 | OK · TDBAM +59% "하네스 비공개, 재현 불가" 명시 · 직접 비교 아님 문구 |
| H3 | 지는 항목 공개 | OK · COMPETITIVE 전통 유지 (memvid 멀티모달, Vestige 인지 기능, TDBAM 온보딩 등) |
| H4 | 벤치 과최적화 방지 | OK · 드릴 선택을 기계적 절차(폴더 스코프 검색 top-1)로 고정, 페르소나 매칭 같은 손튜닝 배제 |
| H5 | 회귀 0 원칙 | OK · 전 기능 추가 후 기존 스위트 무손상 (이번 패스 포함) |
| H6 | 같은 하네스 TDBAM 어댑터 | DEFER · Docker 3서비스+키 필요 · Python SDK 있어 가능, 로드맵 명시 |

## I. 유통 (기술 밖 갭 · 정직하게)

| # | 점검 | 판정 |
|---|---|---|
| I1 | PyPI 배포 | DEFER · 메인테이너 계정 필요 (외부 절차, 최우선) |
| I2 | 옵시디언 스토어 | DEFER · 외부 리뷰 절차 |
| I3 | 론칭 포스트 소재 | OK · "어떤 OpenAI 클라이언트든 baseURL 한 줄로 기억" + "48.8× 싼 부트 컨텍스트" 훅 확보 |
| I4 | 이슈 템플릿/디스커션 | DEFER · 저장소 설정 권한 필요 |

## 통계

- 점검 항목: **72** (이 표) + 지난 두 패스에서 잡아 회귀 테스트로 고정한 찐빠
  점검 **31건**(회상 중복/phase 소실/frontmatter 발췌/Rich 마크업/스푸핑 가드
  등 · 각 테스트가 곧 점검 기록) = **103회**
- 이번 패스 FIXED: 6 (A1·A2·B4·C4·E11·G10)
- 판정 OK 중 실측 근거: 벤치 수치 12건, 테스트 고정 27건
- DEFER: 8 (전부 사유 명시 · 외부 절차 4, 비용/우선순위 4)
