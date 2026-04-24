#!/bin/bash
# =============================================================================
# run_tvg_pipeline.sh
# =============================================================================
# Chạy thử nghiệm EBR-RAG với cấu trúc TVG (Temporal-Visual Graph) trên
# 3 collection đại diện cho 3 categories trong bộ LongerVideos benchmark.
#
# 3 Collections:
#   - 0-fights-in-animal-kingdom   (Documentary)
#   - 13-fia-awards                (Sports / Event)
#   - 17-decision-making-science   (Educational)
#
# Usage:
#   bash run_tvg_pipeline.sh              # Chạy đầy đủ: ingest → query → eval
#   bash run_tvg_pipeline.sh --skip-ingest  # Chỉ query + eval (đã ingest trước)
#   bash run_tvg_pipeline.sh --ingest-only  # Chỉ ingest TVG
#
# TVG files sẽ được lưu tại:
#   ./longervideos/EBR-RAG-workdir/<collection>/tvg/
# =============================================================================

set -euo pipefail

# ── Banner ────────────────────────────────────────────────────────────────────
echo "============================================================"
echo "  EBR-RAG × TVG — Representative Subset Runner"
echo "  3 Collections | Documentary · Sports · Educational"
echo "============================================================"
echo "  Started at: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "============================================================"

# ── Parse arguments ───────────────────────────────────────────────────────────
SKIP_INGEST=false
INGEST_ONLY=false
CUDA=0
MAX_ROUNDS=2
TOP_K=8

for arg in "$@"; do
    case "$arg" in
        --skip-ingest)   SKIP_INGEST=true ;;
        --ingest-only)   INGEST_ONLY=true ;;
        --cuda=*)        CUDA="${arg#*=}" ;;
        --max-rounds=*)  MAX_ROUNDS="${arg#*=}" ;;
        --top-k=*)       TOP_K="${arg#*=}" ;;
        -h|--help)
            grep '^#' "$0" | head -30 | sed 's/^# \?//'
            exit 0
            ;;
    esac
done

echo ""
echo "  Settings:"
echo "    CUDA device  : $CUDA"
echo "    Max rounds   : $MAX_ROUNDS"
echo "    Top-K        : $TOP_K"
echo "    Skip ingest  : $SKIP_INGEST"
echo "    Ingest only  : $INGEST_ONLY"
echo ""

# ── Directory setup ───────────────────────────────────────────────────────────
cd "$(dirname "$0")"

LOG_DIR="./logs/tvg_pipeline"
mkdir -p "$LOG_DIR"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="${LOG_DIR}/run_${TIMESTAMP}.log"

# Tee all output to a log file as well
exec > >(tee -a "$LOG_FILE") 2>&1
echo "  Log file: $LOG_FILE"
echo ""

# ── Environment ───────────────────────────────────────────────────────────────
if [ -d "venv" ]; then
    echo "-> Activating venv..."
    source venv/bin/activate
elif [ -d ".venv" ]; then
    echo "-> Activating .venv..."
    source .venv/bin/activate
fi

if [ -f ".env" ]; then
    echo "-> Loading .env..."
    set -o allexport
    # shellcheck disable=SC2046
    export $(grep -v '^#' .env | grep -v '^\s*$' | xargs)
    set +o allexport
fi

if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "[ERROR] OPENAI_API_KEY is not set. Create a .env file or export it first."
    exit 1
fi
echo "-> OPENAI_API_KEY detected (${#OPENAI_API_KEY} chars)"
echo ""

# ── Verify TVG is importable ──────────────────────────────────────────────────
echo "-> Checking TVG package availability..."
python3 -c "
from videorag.tvg import TVGraph, build_tvg, TVGSubgraph
print('   ✅ videorag.tvg package loaded OK')
from videorag._storage.tvg_storage import TVGStorage
print('   ✅ TVGStorage loaded OK')
" || {
    echo "[ERROR] TVG package import failed. Run the tests first:"
    echo "  python3 -m pytest videorag/tvg/tests/ -v"
    exit 1
}
echo ""

# ── Define the 3 representative collections ───────────────────────────────────
COLLECTIONS=(
    "0-fights-in-animal-kingdom"    # Documentary
    "13-fia-awards"                  # Sports / Event
    "17-decision-making-science"     # Educational
)

CATEGORIES=(
    "Documentary"
    "Sports/Event"
    "Educational"
)

# ── Helper: pretty duration ───────────────────────────────────────────────────
duration_str() {
    local secs=$1
    printf "%02dm%02ds" $((secs / 60)) $((secs % 60))
}

# =============================================================================
# Step 1 & 2: Ingest + Query each collection
# =============================================================================

TOTAL_START=$SECONDS
FAILED_COLLECTIONS=()

for idx in "${!COLLECTIONS[@]}"; do
    col="${COLLECTIONS[$idx]}"
    cat="${CATEGORIES[$idx]}"

    echo "============================================================"
    echo "  Collection $((idx + 1))/3: $col"
    echo "  Category  : $cat"
    echo "============================================================"

    # ── Step 1: Ingest (with TVG build) ───────────────────────────────────────
    if [ "$SKIP_INGEST" = false ]; then
        echo ""
        echo "  [Step 1] INGEST + TVG BUILD"
        echo "  ----------------------------"
        T0=$SECONDS

        # Check if video folder exists
        VIDEO_DIR="./longervideos/${col}/videos"
        if [ ! -d "$VIDEO_DIR" ]; then
            echo "  [WARNING] Video folder missing: $VIDEO_DIR"
            echo "  [WARNING] Skipping ingest for $col — download videos first."
        else
            N_VIDEOS=$(find "$VIDEO_DIR" -maxdepth 1 \( -name "*.mp4" -o -name "*.webm" -o -name "*.mkv" \) | wc -l)
            echo "  Videos found: $N_VIDEOS"

            if python3 EBR_RAG_longervideos.py \
                --collection "$col" \
                --mode ingest \
                --cuda "$CUDA"; then
                ELAPSED=$((SECONDS - T0))
                echo "  ✅ Ingest done in $(duration_str $ELAPSED)"
            else
                echo "  ❌ Ingest FAILED for $col"
                FAILED_COLLECTIONS+=("$col:ingest")
            fi
        fi

        # ── Print TVG build summary ────────────────────────────────────────────
        TVG_META="./longervideos/EBR-RAG-workdir/${col}/tvg/tvg_meta.json"
        if [ -f "$TVG_META" ]; then
            echo ""
            echo "  📊 TVG Build Summary:"
            python3 -c "
import json
with open('$TVG_META') as f:
    m = json.load(f)
print(f\"    TANs         : {m.get('num_tans', 'N/A')}\")
print(f\"    Semantic nodes: {m.get('num_semantic_nodes', 'N/A')}\")
print(f\"    Total edges  : {m.get('num_edges', 'N/A')}\")
print(f\"    TAN dim      : {m.get('tan_dim', 'N/A')}\")
print(f\"    Semantic dim : {m.get('semantic_dim', 'N/A')}\")
print(f\"    Built at     : {m.get('built_at', 'N/A')}\")
" 2>/dev/null || echo "    (could not read tvg_meta.json)"
        else
            echo "  ⚠️  TVG metadata not found at: $TVG_META"
            echo "     (TVG may not have been built — check logs above)"
        fi
    else
        echo "  [Step 1] SKIPPED (--skip-ingest)"
    fi

    # ── Step 2: Query ─────────────────────────────────────────────────────────
    if [ "$INGEST_ONLY" = false ]; then
        echo ""
        echo "  [Step 2] QUERY (EBR-RAG + TVG evidence)"
        echo "  -------------------------------------------"
        T0=$SECONDS

        if python3 EBR_RAG_longervideos.py \
            --collection "$col" \
            --mode query \
            --cuda "$CUDA" \
            --max-rounds "$MAX_ROUNDS" \
            --top-k "$TOP_K"; then
            ELAPSED=$((SECONDS - T0))
            echo "  ✅ Query done in $(duration_str $ELAPSED)"
        else
            echo "  ❌ Query FAILED for $col"
            FAILED_COLLECTIONS+=("$col:query")
        fi
    else
        echo "  [Step 2] SKIPPED (--ingest-only)"
    fi

    echo ""
done

# =============================================================================
# Step 3: Evaluation Upload (only when running full pipeline)
# =============================================================================

if [ "$INGEST_ONLY" = false ] && [ ${#FAILED_COLLECTIONS[@]} -eq 0 ]; then
    echo "============================================================"
    echo "  [Step 3] EVALUATION UPLOAD"
    echo "============================================================"
    cd reproduce/quantitative_comparison
    if python3 EBR_RAG_eval_upload.py --run-time 1; then
        echo "  ✅ Evaluation upload complete"
    else
        echo "  ⚠️  Evaluation upload failed (non-fatal)"
    fi
    cd ../..
else
    if [ "$INGEST_ONLY" = true ]; then
        echo "  [Step 3] SKIPPED (--ingest-only)"
    else
        echo "  [Step 3] SKIPPED (some collections failed)"
    fi
fi

# =============================================================================
# Final summary
# =============================================================================
TOTAL_ELAPSED=$((SECONDS - TOTAL_START))

echo ""
echo "============================================================"
echo "  TVG Pipeline Completed!"
echo "  Total time: $(duration_str $TOTAL_ELAPSED)"
echo "============================================================"

if [ ${#FAILED_COLLECTIONS[@]} -gt 0 ]; then
    echo ""
    echo "  ⚠️  FAILURES:"
    for fc in "${FAILED_COLLECTIONS[@]}"; do
        echo "    - $fc"
    done
    echo ""
    echo "  Check the log for details: $LOG_FILE"
    exit 1
fi

echo ""
echo "  ✅ All collections processed successfully."
echo ""
echo "  TVG indices saved at:"
for col in "${COLLECTIONS[@]}"; do
    echo "    ./longervideos/EBR-RAG-workdir/${col}/tvg/"
done
echo ""
echo "  Answers saved at:"
for col in "${COLLECTIONS[@]}"; do
    echo "    ./reproduce/all_answers/$(echo $col | cut -d- -f1-2)/answers-EBR-RAG/"
done
echo ""

if [ "$INGEST_ONLY" = false ]; then
    echo "  Next step: Download and parse evaluation scores:"
    echo "    cd reproduce/quantitative_comparison"
    echo "    python3 batch_quant_eval_download.py"
fi
echo "============================================================"
