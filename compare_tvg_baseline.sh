#!/bin/bash
# =============================================================================
# compare_tvg_baseline.sh
# =============================================================================
# Chạy so sánh đối chứng 2 phiên bản IELTS-RAG:
#   1. IELTS-RAG Baseline (Có agent, không dùng TVG)
#   2. IELTS-RAG + TVG (Có agent, dùng Temporal-Visual Graph)
#
# Ghi chú: Kết quả Naive RAG đã có sẵn trong hệ thống nên không chạy lại.
# =============================================================================

set -euo pipefail

COLLECTION=${1:-"0-fights-in-animal-kingdom"}
CUDA=${2:-"0"}

echo "============================================================"
echo "  IELTS-RAG Comparison: Baseline vs TVG-only"
echo "  Collection: $COLLECTION"
echo "============================================================"

# 1. Run IELTS-RAG Baseline
echo "🚀 [1/2] Running IELTS-RAG Baseline (Graph + Visual)..."
python3 ielts_rag_longervideos.py \
    --collection "$COLLECTION" \
    --mode query \
    --cuda "$CUDA" \
    --suffix baseline

# 2. Run IELTS-RAG + TVG
echo "🚀 [2/2] Running IELTS-RAG + TVG mode..."
python3 ielts_rag_longervideos.py \
    --collection "$COLLECTION" \
    --mode query \
    --cuda "$CUDA" \
    --use-tvg-only \
    --suffix tvg-only

echo "============================================================"
echo "  Comparison Runs Complete!"
echo "  Kết quả mới đã được lưu tại:"
echo "    - Baseline : ./reproduce/all_answers/*/answers-ielts-rag-baseline/"
echo "    - TVG-only : ./reproduce/all_answers/*/answers-ielts-rag-tvg-only/"
echo ""
echo "  Bây giờ bạn có thể so sánh cả 3 (bao gồm Naive đã có sẵn):"
echo "    cd reproduce/quantitative_comparison/"
echo "    python3 ielts_rag_eval_upload.py"
echo "============================================================"
