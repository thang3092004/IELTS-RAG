"""
IELTS-RAG Smoke Test — uses 2 RAG-lecture videos already present in longervideos/4-rag-lecture/videos/

Usage:
    # Step 1: Ingest videos (only needed once)
    python test_ielts_rag_smoke.py --phase ingest

    # Step 2: Run queries with ielts_rag
    python test_ielts_rag_smoke.py --phase query

    # Step 3: Compare side-by-side with standard videorag
    python test_ielts_rag_smoke.py --phase compare

Set your OpenAI API key in OPENAI_API_KEY env var before running.
"""
import os
import json
import logging
import warnings
import multiprocessing
import argparse

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

os.environ["CUDA_VISIBLE_DEVICES"] = "0"  # RTX 4050

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if not os.getenv("OPENAI_API_KEY"):
    import sys
    print("Please set your OPENAI_API_KEY in a .env file or environment variable.")
    sys.exit(1)

from videorag._llm import openai_4o_mini_config
from videorag.videorag import VideoRAG, QueryParam

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WORKING_DIR = "./test-ielts-workdir"

# Use just 2 small videos from 4-rag-lecture for a quick smoke test
VIDEO_PATHS = [
    "./longervideos/4-rag-lecture/videos/DI9Q60T_054.mp4",  # ~22 MB
    "./longervideos/4-rag-lecture/videos/W-iUd_pjOQA.mp4",  # ~28 MB
    "./longervideos/4-rag-lecture/videos/rhJJynv47Pw.mp4",  # ~25 MB
]

# Representative questions from the rag-lecture dataset (collection 4)
TEST_QUERIES = [
    {
        "id": 0,
        "question": "Describe the main differences between the two RAG systems mentioned in the video (text-based and vision-based).",
    },
    {
        "id": 4,
        "question": "Describe the core difference between traditional RAG and Agentic RAG, highlighting the role of agents.",
    },
    {
        "id": 10,
        "question": "How does LightRAG compare to GraphRAG in terms of cost and performance?",
    },
]

# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

def phase_ingest():
    """Ingest the 2-3 test videos into the working directory."""
    print("\n=== PHASE: INGEST ===")
    vr = VideoRAG(llm=openai_4o_mini_config, working_dir=WORKING_DIR)
    for p in VIDEO_PATHS:
        if not os.path.exists(p):
            print(f"[SKIP] File not found: {p}")
            continue
    vr.insert_video(video_path_list=[p for p in VIDEO_PATHS if os.path.exists(p)])
    print("Ingestion complete.")


def phase_query():
    """Run all test queries using ielts_rag and print results."""
    print("\n=== PHASE: QUERY (ielts_rag) ===")

    vr = VideoRAG(llm=openai_4o_mini_config, working_dir=WORKING_DIR)
    vr.load_caption_model(debug=True)  # Optimized: skip heavy models during query

    results = []
    for q in TEST_QUERIES:
        print(f"\n{'='*60}")
        print(f"Q{q['id']}: {q['question']}")
        print('='*60)

        param = QueryParam(
            mode="ielts_rag",
            ielts_top_k=8,
            max_rounds=1,
            return_detailed=True,
        )
        resp = vr.query(q["question"], param=param)

        print(f"\nAnswer:\n  {resp['answer']}")
        print(f"\nConfidence: {resp['confidence']:.2f}")
        print(f"Rounds: {resp['rounds_run']}  |  Tool calls: {resp['tool_calls_made']}")
        print(f"Evidence pool: {len(resp['evidence'])} items")
        print(f"\nCitations ({len(resp['citations'])}):")
        for c in resp["citations"]:
            status = "✓" if c.get("validated") else "✗ (INVALID)"
            print(f"  [{status}] {c.get('evidence_id')} | {c.get('video_name')} @ {c.get('time_range')}")

        results.append({"query_id": q["id"], "question": q["question"], "response": resp})

    # Save results
    out_path = os.path.join(WORKING_DIR, "ielts_rag_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            [{**r, "response": {k: v for k, v in r["response"].items() if k != "transcript"}} for r in results],
            f, ensure_ascii=False, indent=2
        )
    print(f"\n\nResults saved to: {out_path}")


def phase_compare():
    """Run same queries with standard videorag for side-by-side comparison."""
    print("\n=== PHASE: COMPARE (videorag vs ielts_rag) ===")

    vr = VideoRAG(llm=openai_4o_mini_config, working_dir=WORKING_DIR)
    vr.load_caption_model(debug=True)

    for q in TEST_QUERIES[:2]:   # compare first 2 queries only (faster)
        print(f"\n{'='*60}\nQ{q['id']}: {q['question']}\n{'='*60}")

        # Standard videorag
        param_std = QueryParam(mode="videorag", top_k=10)
        param_std.wo_reference = True
        std_answer = vr.query(q["question"], param=param_std)

        # IELTS-RAG
        param_ielts = QueryParam(mode="ielts_rag", ielts_top_k=5, max_rounds=2, return_detailed=True)
        ielts_resp = vr.query(q["question"], param=param_ielts)

        print(f"\n[VideoRAG]\n{std_answer}\n")
        print(f"[IELTS-RAG]\n{ielts_resp['answer']}")
        print(f"  Confidence: {ielts_resp['confidence']:.2f} | "
              f"Rounds: {ielts_resp['rounds_run']} | "
              f"Tool calls: {ielts_resp['tool_calls_made']}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")

    parser = argparse.ArgumentParser(description="IELTS-RAG smoke test")
    parser.add_argument(
        "--phase", choices=["ingest", "query", "compare"], default="query",
        help="ingest=process videos, query=run ielts_rag, compare=ielts_rag vs videorag"
    )
    args = parser.parse_args()

    if args.phase == "ingest":
        phase_ingest()
    elif args.phase == "query":
        phase_query()
    elif args.phase == "compare":
        phase_compare()
