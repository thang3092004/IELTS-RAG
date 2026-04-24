#!/bin/bash
set -e

echo "==================================================="
echo "EBR-RAG Ablation Pipeline Runner (3 Collections)"
echo "==================================================="

cd "$(dirname "$0")"

# Define the 3 representative collections across all domains
COLLECTIONS=(
    "0-fights-in-animal-kingdom"
    "13-fia-awards"
    "17-decision-making-science"
)

# Step 0: Environment Setup
if [ -d ".venv" ]; then
    echo "-> Activating virtual environment..."
    source .venv/bin/activate
elif [ -d ".conda" ]; then
    echo "-> Remember to activate your conda environment manually if needed."
fi

if [ -f ".env" ]; then
    echo "-> Loading environment variables from .env..."
    export $(cat .env | grep -v '^#' | xargs)
fi

# Step 1, 2, 3: Ingest, Query, and Ablation
export LD_LIBRARY_PATH="/usr/local/lib/python3.12/dist-packages/nvidia/cudnn/lib:/usr/local/lib/python3.12/dist-packages/nvidia/cublas/lib:$LD_LIBRARY_PATH"
export PYTHONPATH="$(pwd):$PYTHONPATH"
for col in "${COLLECTIONS[@]}"; do
    echo ""
    echo "---------------------------------------------------"
    echo "Processing Collection: $col"
    echo "---------------------------------------------------"
    
    echo "-> [Step 1] INGEST (Checking status or nạp video)..."
    /usr/bin/python3 EBR_RAG_longervideos.py --collection "$col" --mode ingest --cuda 0
    echo "==================================================="
    
    echo "-> [Step 2] FULL PIPELINE QUERY (EBR-RAG)..."
    /usr/bin/python3 EBR_RAG_longervideos.py --collection "$col" --mode query --cuda 0
    echo "==================================================="
    
    echo "-> [Step 3] ABLATION QUERIES (3 scenarios)..."
    /usr/bin/python3 reproduce/ablation/run_ablation_collections.py --collection "$col" --cuda 0
    echo "==================================================="
done

echo "==================================================="
echo "[Step 4] Starting real-time API evaluation..."
echo "==================================================="
cd reproduce/quantitative_comparison
/usr/bin/python3 ablation_eval_realtime.py --concurrency 20

echo "==================================================="
echo "Ablation and Full Framework Evaluation Complete!"
echo "Check ablation_summary.json and the printed table for results."
echo "==================================================="
