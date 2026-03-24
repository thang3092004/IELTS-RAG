#!/bin/bash
set -e

echo "==================================================="
echo "IELTS-RAG Representative Subset Runner (8.2 hours)"
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
fi

if [ -f ".env" ]; then
    echo "-> Loading environment variables from .env..."
    export $(cat .env | grep -v '^#' | xargs)
fi

# Step 1 & 2: Ingest and Query each collection sequentially
for col in "${COLLECTIONS[@]}"; do
    echo "---------------------------------------------------"
    echo "Processing Collection: $col"
    echo "---------------------------------------------------"
    
    echo "-> [Step 1] INGEST (Checking status or extracting features)..."
    python ielts_rag_longervideos.py --collection "$col" --mode ingest --cuda 0
    
    echo "-> [Step 2] QUERY (Checking status or generating answers)..."
    python ielts_rag_longervideos.py --collection "$col" --mode query --cuda 0
done


# Step 3: Evaluation Upload
echo "==================================================="
echo "[Step 3] Starting evaluation upload to OpenAI API..."
echo "==================================================="
cd reproduce/quantitative_comparison
python ielts_rag_eval_upload.py --run-time 1

echo "==================================================="
echo "Subset pipeline completed successfully!"
echo "Use batch_quant_eval_download.py later to parse scores."
echo "==================================================="
