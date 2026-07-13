# KorMapleQA

**실제 나무위키 메이플스토리 도메인(1,469 문서, 45MB) 위의 결정적·코드검증
한국어 RAG/검색 벤치마크.** 2,075문항(질문 유형 7종 + 무응답 축).

기존 한국어·메모리 벤치마크가 안 다루는 것들을 정면으로 다룬다:

| 축 | KorQuAD 1.0 | LongMemEval | **KorMapleQA** |
|---|---|---|---|
| 언어 | 한국어(위키백과 문어) | 영어(대화) | **한국어(위키 문어+구어+속어)** |
| 문서 출처 | 위키백과 | 합성 대화 | **실사용자 작성 나무위키** (교착어·신조어·표·숫자) |
| 질문 생성 | 인간 | LLM | **100% 코드: API 키 없이 재현, 초안 편향 없음** |
| 정답 검증 | 스팬 존재 | LLM 채점 | **기계 검증 불변식** (아래) |
| 다중 홉 | ✗ | 세션 간 | **실제 위키링크 그래프** (지름길 차단 검증) |
| 엔티티 마스킹 | ✗ | ✗ | **유일 속성 지칭** (제목 부스트 무력화) |
| 구어체/오타 | ✗ | ✗ | **반말·속어·음절 전위 오타** (시드 고정) |
| 무응답 | v2.0에 있음 | 있음 | **덤프 이후 콘텐츠**, 부재를 코드로 검증 |

## 질문 유형 (2,075문항)

| 유형 | n | 내용 | 검증 불변식 |
|---|---|---|---|
| `single` | 981 | 인포박스/불릿 사실 ("윌의 테마곡은 무엇인가?") | 정답이 골드 문서에 존재, 문서당 ≤3, 동일 키 다중값 배제 |
| `masked` | 215 | 제목 대신 유일 속성으로 지칭 ("테마곡이 'Diffraction'인 보스의 제한 시간은?") | 식별값이 1,469문서 중 정확히 1곳, 질문에 제목 미포함 |
| `twohop` | 128 | A 인포박스의 링크 값 → B의 사실 ("거대 괴수 더스크가 위치한 지역의 적정 레벨은?") | 링크 실재, 정답이 B에만 존재(A에 없음, 지름길 차단) |
| `temporal` | 83 | 출시/등장/발생 날짜 ("NEO가 등장한 날짜는?") | 날짜+동사 인접 서술, 개요부 한정 |
| `kw` | 220 | 키워드형 ("스우 테마곡") | single과 동일 골드 |
| `casual` | 220 | 반말+게임 속어 ("스우 브금 뭐야?") | 〃 |
| `typo` | 220 | 음절 전위 오타 (시드 고정 재현) | 〃 |
| `abstention` | 8 | 덤프(2021-03-01) 이후 콘텐츠 (칼로스·6차 전직 등) | 식별자가 코퍼스 전체에 부재함을 검증 |

## 재현

```bash
# 1. 코퍼스 (2.0GB 공개 덤프에서 결정적 재구축, data/maple_real/README.md 참고)
python benchmarks/namu_filter.py && python benchmarks/namu_filter.py build
# 2. 문항 생성+검증 (API 키 불필요, 시드 고정)
python benchmarks/gen_kormapleqa.py
# 3. 평가
python benchmarks/run_kormapleqa.py              # lemory + 3 baselines
node benchmarks/run_omnisearch.mjs --kormapleqa  # Omnisearch(실제 MiniSearch)
python benchmarks/run_kormapleqa.py --smartconn  # Smart-Connections-class
```

## 지표

- `doc_hit@k`: 골드 문서가 top-k에 등장 (문서 단위 시스템과의 공정 비교)
- `ans_hit@k`: 골드 문서의 청크이면서 정답 문자열 포함 (생성 컨텍스트 자격)
- `full_support@8` (twohop): 두 골드 문서 모두 top-8
- abstention 문항은 별도 리포트 (e2e에서는 '모른다'가 정답)

## 라이선스·출처

원문: 나무위키 2021-03-01 공개 덤프 (CC BY-NC-SA 2.0 KR,
archive.org/details/namuwikidumps). 질문 텍스트는 코드 생성물이며 같은
라이선스로 배포. 게임 고유명사는 넥슨의 상표입니다 (비상업 연구용).
