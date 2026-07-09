# maple_real — 실제 나무위키 메이플스토리 벤치마크

이 벤치마크의 볼트(1,469개 노트, 45MB)는 저장소에 포함되지 않으며,
공개 나무위키 DB 덤프에서 결정적으로 재현됩니다:

```bash
curl -L -o work/namudump/namuwiki210301.7z \
  "https://archive.org/download/namuwikidumps/namuwiki210301.7z"   # 2.0GB
python - <<'PY'
import py7zr
py7zr.SevenZipFile("work/namudump/namuwiki210301.7z").extractall("work/namudump/")
PY
python namu_filter.py          # 867k 문서 스캔 -> 메이플스토리 1,471건 추출
python namu_filter.py build    # -> data/maple_real/vault (1,469 notes)
```

선택 기준: 분류에 '메이플스토리'가 포함된 모든 문서(하위 분류 포함) + 제목 포함.
원문 라이선스: CC BY-NC-SA 2.0 KR (나무위키). 출처: namu.wiki, 2021-03-01 덤프
(archive.org/details/namuwikidumps). 벤치마크 질문(questions.json)은
gen_maple_real_qa.py가 생성하며 코드 검증 불변식(답이 정답 노트에만 존재,
질문에 정답 노트 제목 누출 금지)을 통과한 문항만 포함합니다.
