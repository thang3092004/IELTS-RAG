#!/bin/bash
# =============================================================================
# compare_tvg_baseline.sh
# =============================================================================
# Chạy so sánh đối chứng 2 phiên bản EBR-RAG:
#   1. EBR-RAG Baseline (Có agent, không dùng TVG)
#   2. EBR-RAG + TVG (Có agent, dùng Temporal-Visual Graph)
#
# Ghi chú: Kết quả Naive RAG đã có sẵn trong hệ thống nên không chạy lại.
# =============================================================================

set -euo pipefail

COLLECTION=${1:-"0-fights-in-animal-kingdom"}
CUDA=${2:-"0"}

echo "============================================================"
echo "  EBR-RAG Comparison: Baseline vs TVG-only"
echo "  Collection: $COLLECTION"
echo "============================================================"

# 1. Run EBR-RAG Baseline
echo "🚀 [1/2] Running EBR-RAG Baseline (Graph + Visual)..."
python3 EBR_RAG_longervideos.py \
    --collection "$COLLECTION" \
    --mode query \
    --cuda "$CUDA" \
    --suffix baseline

# 2. Run EBR-RAG + TVG
echo "🚀 [2/2] Running EBR-RAG + TVG mode..."
python3 EBR_RAG_longervideos.py \
    --collection "$COLLECTION" \
    --mode query \
    --cuda "$CUDA" \
    --use-tvg-only \
    --suffix tvg-only

echo "============================================================"
echo "  Comparison Runs Complete!"
echo "  Kết quả mới đã được lưu tại:"
echo "    - Baseline : ./reproduce/all_answers/*/answers-EBR-RAG-baseline/"
echo "    - TVG-only : ./reproduce/all_answers/*/answers-EBR-RAG-tvg-only/"
echo ""
echo "  Bây giờ bạn có thể so sánh cả 3 (bao gồm Naive đã có sẵn):"
echo "    cd reproduce/quantitative_comparison/"
echo "    python3 EBR_RAG_eval_upload.py"
echo "============================================================"
