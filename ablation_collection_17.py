import os
from dotenv import load_dotenv
load_dotenv()
import json
import asyncio
from pathlib import Path
from videorag.videorag import VideoRAG, QueryParam
from videorag._llm import openai_4o_mini_config

# =======================================================
# ABLATION RUNNER FOR COLLECTION 17:
# "17-decision-making-science"
# 
# Constraints:
# 1. EBR-RAG Context: 2 initial + 3 tool calls * 2 data = ~8 max
# 2. Video-RAG Context: Statically boosted to exactly 8 (baseline matched to IELTS max)
# =======================================================

async def main():
    # 1. Define collection and paths
    collection_name = "17-decision-making-science"
    dataset_path = "longervideos/dataset.json"
    
    # 2. Load dataset to get questions for this collection
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    if isinstance(dataset, dict):
        collection_data = dataset.get("17", [None])[0]
    else:
        collection_data = next((c for c in dataset if str(c.get("id", "")) == "17"), None)
        
    if not collection_data:
        print("Collection 17 not found!")
        return

    questions = collection_data.get("questions", collection_data.get("qa", []))
    print(f"Loaded Collection 17. Found {len(questions)} queries.")

    # 3. Setup LLM configuration (standard GPT-4o-mini baseline used in the repo)
    llm_cfg = openai_4o_mini_config

    if not os.environ.get("OPENAI_API_KEY"):
        print("WARNING: OPENAI_API_KEY might not be set in your terminal!")

    # 4. Initialize VideoRAG instances for baseline DB and ielts db
    # We assume you've already run "ingest" on collection 17 at least once.
    # The default DB dir for ielts is: "longervideos/EBR-RAG-workdir/17-decision-making-science"
    work_dir = os.path.join("longervideos", "EBR-RAG-workdir", collection_name)
    
    print(f"Loading Index from: {work_dir}...")
    vrag = VideoRAG(working_dir=work_dir, llm=llm_cfg)
    
    # Pre-warm vision models/connections if needed for QA parsing 
    vrag.load_caption_model(debug=False) 

    # 5. Run the ablation test on a subset of questions (e.g. the first 2 questions)
    test_questions = questions[:2]  # Just taking first 2 for quick direct comparison

    for idx, q_obj in enumerate(test_questions):
        q_id = q_obj["id"]
        q_text = q_obj["question"]
        
        print("\n" + "="*80)
        print(f"QUESTION {q_id}: {q_text}")
        if "options" in q_obj:
            print(f"OPTIONS: {q_obj['options']}")
        print("="*80)

        # -------------------------------------------------------------
        # RUN BASELINE: VideoRAG (With context artificially boosted to 8)
        # -------------------------------------------------------------
        print("\n--- Running Baseline VideoRAG (Context=8) ---")
        # EXPLANATION OF 8:
        # EBR-RAG initially gets 2 data per type. With 3 tool calls (each retrieving 2 max),
        # an agent could theoretically retrieve 2 + (3 * 2) = 8 max objects of a single type.
        # Thus, we set all Baseline limits (text chunks, graph entities, graph expansion chunks, visual) to 8.
        vrag_param = QueryParam(
            mode="videorag_multiple_choice" if "options" in q_obj else "videorag",
            wo_reference=True,  # Standard for VideoRAG
            top_k=8             # Controls initial Graph Entities & initial dense Text Chunks
        )
        # Ensure Graph Expansion and Visual Segments are also exactly 8
        vrag.retrieval_topk_chunks = 8 
        vrag.segment_retrieval_top_k = 8
        
        baseline_resp = await vrag.aquery(q_text, param=vrag_param)
        baseline_ans = baseline_resp.get("answer", baseline_resp) if isinstance(baseline_resp, dict) else str(baseline_resp)
        print(f"[VideoRAG Output]:\n{baseline_ans}\n")

        # -------------------------------------------------------------
        # RUN ABLATION: EBR-RAG (Starts with 2, crawls up to 8 max via 3 calls)
        # -------------------------------------------------------------
        print("\n--- Running EBR-RAG Ablation (Context=2, Max Rounds=3) ---")
        ielts_param = QueryParam(
            mode="EBR_RAG", 
            ielts_top_k=2,    # Passed to EBR_RAG.py (overrides default 10)
            max_rounds=3      # Tells it to debate up to 3 times
        )
        
        ielts_resp = await vrag.aquery(q_text, param=ielts_param)
        ielts_ans = ielts_resp.get("answer", "") if isinstance(ielts_resp, dict) else str(ielts_resp)
        
        # Try to pull some telemetry to prove the ablation worked
        tool_calls = ielts_resp.get("tool_calls_made", "?") if isinstance(ielts_resp, dict) else "?"
        evidence_len = len(ielts_resp.get("evidence", [])) if isinstance(ielts_resp, dict) else "?"
        
        print(f"[EBR-RAG Output]:\n{ielts_ans}")
        print(f"\n[EBR-RAG Telemetry]:")
        print(f" - Tool Calls Made: {tool_calls} (Target limit was 3)")
        print(f" - Final Evidence Chunks Gathered: {evidence_len} (Should be <= 8 baseline items)")

if __name__ == "__main__":
    asyncio.run(main())
