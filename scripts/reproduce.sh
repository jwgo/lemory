#!/usr/bin/env bash
# One-command reproduction of Lemory's key-free benchmark claims.
#
#   ./scripts/reproduce.sh            # quick tier (~15 min on a laptop CPU)
#   ./scripts/reproduce.sh --full     # everything key-free (hours: 60k questions,
#                                     # LongMemEval 470 haystacks)
#
# No API key is used anywhere in this script: every number comes from the
# keyless local stack (e5-small-ko-v2 ONNX on CPU). Datasets download
# themselves on first run (KorQuAD dev is committed; train/LOCOMO/LongMemEval
# fetch from their public sources). Compare your outputs against
# BENCHMARKS.md — if you get materially different numbers, please open an
# issue with your hardware + output; that is exactly the kind of third-party
# check this script exists to invite.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-python}

echo "== Lemory keyless reproduction =="
$PY -c "import lemory" 2>/dev/null || {
  echo "lemory not importable — run: pip install -e ." >&2; exit 1; }

echo
echo "-- [1/4] KorQuAD Korean retrieval (committed dev set, 400 questions) --"
$PY benchmarks/run_challengers_korean.py 400 || true   # competitor rows skip if not installed

echo
echo "-- [2/4] LOCOMO evidence recall (downloads locomo10.json once) --"
$PY benchmarks/prep_locomo.py
$PY benchmarks/run_locomo_retrieval.py

if [[ "${1:-}" == "--full" ]]; then
  echo
  echo "-- [3/4] KorQuAD FULL train: 9,663 paragraphs x 60,407 questions (~1-2h) --"
  test -f benchmarks/data/korquad/KorQuAD_v1.0_train.json || \
    curl -o benchmarks/data/korquad/KorQuAD_v1.0_train.json \
      https://korquad.github.io/dataset/KorQuAD_v1.0_train.json
  $PY benchmarks/run_korquad_full.py

  echo
  echo "-- [4/4] LongMemEval_S cleaned, all 470 evidence questions (~6h CPU) --"
  test -f benchmarks/data/longmemeval/longmemeval_s_cleaned.json || \
    $PY - <<'EOF'
from huggingface_hub import hf_hub_download
hf_hub_download("amyxu/longmemeval-cleaned", "longmemeval_s_cleaned.json",
                repo_type="dataset", local_dir="benchmarks/data/longmemeval")
EOF
  $PY benchmarks/run_longmemeval_full.py
else
  echo
  echo "-- quick tier done. Full-scale runs (60k questions, LongMemEval 470): --full"
fi

echo
echo "Numbers to compare against: BENCHMARKS.md §0 (market table), §6c (scale), §7 (memory)"
