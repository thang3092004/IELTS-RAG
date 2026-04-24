"""
EBR-RAG Full Dataset Runner — mirrors videorag_longervideos.py exactly.

Usage:
    # Step 1: Ingest all videos for a collection
    python EBR_RAG_longervideos.py --collection 4-rag-lecture --mode ingest --cuda 0

    # Step 2: Generate EBR-RAG answers (saves to reproduce/all_answers/<id>-<name>/answers-EBR-RAG/)
    python EBR_RAG_longervideos.py --collection 4-rag-lecture --mode query --cuda 0

    # Step 3: Ingest + query ALL collections (runs sequentially)
    python EBR_RAG_longervideos.py --mode all --cuda 0
"""
import os
import json
import logging
import warnings
import multiprocessing
import argparse

warnings.filterwarnings("ignore")
logging.getLogger("httpx").setLevel(logging.WARNING)

parser = argparse.ArgumentParser(description="EBR-RAG on LongerVideos benchmark")
parser.add_argument('--collection', type=str, default=None, help="Collection subfolder e.g. '4-rag-lecture'. Required unless --mode all.")
parser.add_argument('--cuda', type=str, default='0')
parser.add_argument('--mode', choices=['ingest', 'query', 'all', 'naive'], default='query')
parser.add_argument('--max-rounds', type=int, default=2, help="Number of debate rounds (1 is fast; 2 for higher quality)")
parser.add_argument('--top-k', type=int, default=8, help="Top-K evidence items per retrieval")
parser.add_argument('--use-tvg-only', action='store_true', help="Ablation: Only use TVG evidence, skipping baseline Graph/Visual")
parser.add_argument('--suffix', type=str, default=None, help="Suffix for the answer directory name")
args = parser.parse_args()

os.environ["CUDA_VISIBLE_DEVICES"] = args.cuda

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if not os.getenv("OPENAI_API_KEY"):
    import sys
    print("Please set your OPENAI_API_KEY in a .env file or environment variable.")
    sys.exit(1)

from videorag._llm import LLMConfig, openai_embedding, gpt_4o_mini_complete
from videorag.videorag import VideoRAG, QueryParam

# Same LLM config as the original paper
longervideos_llm_config = LLMConfig(
    embedding_func_raw=openai_embedding,
    embedding_model_name="text-embedding-3-small",
    embedding_dim=1536,
    embedding_max_token_size=8192,
    embedding_batch_num=32,
    embedding_func_max_async=4,  # Reduced from 16 to 4 to fix rate limits
    query_better_than_threshold=0.2,
    best_model_func_raw=gpt_4o_mini_complete,
    best_model_name="gpt-4o-mini",
    best_model_max_token_size=32768,
    best_model_max_async=4,       # Reduced from 16 to 4 to fix rate limits
    cheap_model_func_raw=gpt_4o_mini_complete,
    cheap_model_name="gpt-4o-mini",
    cheap_model_max_token_size=32768,
    cheap_model_max_async=4,      # Reduced from 16 to 4 to fix rate limits
)

ANSWER_DIR_NAME = "answers-EBR-RAG"
WORKDIR_BASE = "./longervideos/EBR-RAG-workdir"


def run_ingest(collection: str):
    """Ingest all videos in a collection into the EBR-RAG working directory."""
    print(f"\n{'='*60}")
    print(f"[INGEST] Collection: {collection}")
    print(f"{'='*60}")

    video_base_path = f"./longervideos/{collection}/videos/"
    if not os.path.exists(video_base_path):
        print(f"[WARNING] Videos folder not found: {video_base_path}")
        return

    video_files = sorted(os.listdir(video_base_path))
    video_paths = [os.path.join(video_base_path, f) for f in video_files if f.lower().endswith(('.mp4', '.mkv', '.webm'))]
    if not video_paths:
        print(f"[WARNING] No video files found in {video_base_path}")
        return

    print(f"[INGEST] Found {len(video_paths)} video(s)")
    workdir = os.path.join(WORKDIR_BASE, collection)
    videorag = VideoRAG(llm=longervideos_llm_config, working_dir=workdir)
    videorag.insert_video(video_path_list=video_paths)
    print(f"[INGEST] Done. Working dir: {workdir}")


def run_query(collection: str):
    """Run EBR-RAG on all questions for a collection and save answers as .md files."""
    print(f"\n{'='*60}")
    print(f"[QUERY] Collection: {collection}")
    print(f"{'='*60}")

    with open('./longervideos/dataset.json', 'r') as f:
        longervideos = json.load(f)

    # collection id is the number before the first dash (e.g., "4" from "4-rag-lecture")
    collection_id = collection.split('-')[0]
    if collection_id not in longervideos:
        print(f"[ERROR] Collection ID '{collection_id}' not found in dataset.json")
        return

    # Resolve the description for directory naming (matches author format)
    description = longervideos[collection_id][0]['description']
    
    dir_name = ANSWER_DIR_NAME
    if args.suffix:
        dir_name = f"{ANSWER_DIR_NAME}-{args.suffix}"
    elif args.use_tvg_only:
        dir_name = f"{ANSWER_DIR_NAME}-tvg-only"

    answer_folder = os.path.join(
        './reproduce/all_answers',
        f'{collection_id}-{description}',
        dir_name,
    )
    os.makedirs(answer_folder, exist_ok=True)

    workdir = os.path.join(WORKDIR_BASE, collection)
    videorag = VideoRAG(llm=longervideos_llm_config, working_dir=workdir)
    # Skip loading heavy MiniCPM-V during query (uses pre-built ImageBind index)
    videorag.load_caption_model(debug=True)

    queries = longervideos[collection_id][0]['questions']
    print(f"[QUERY] {len(queries)} question(s) to answer")

    for i, q in enumerate(queries):
        query_id = q['id']
        query = q['question']
        out_path = os.path.join(answer_folder, f'answer_{query_id}.md')

        # Skip if already answered
        if os.path.exists(out_path):
            print(f"[SKIP] Q{query_id} already exists: {out_path}")
            continue

        print(f"\n[Q{query_id}/{len(queries)-1}] {query[:80]}...")
        if args.mode == "naive":
            # Standard VideoRAG (Baseline without agents)
            param = QueryParam(mode="videorag")
            param.wo_reference = True
        else:
            # EBR-RAG (with agents)
            param = QueryParam(
                mode="EBR_RAG",
                ielts_top_k=args.top_k,
                max_rounds=args.max_rounds,
                return_detailed=False,
                ielts_use_tvg_only=args.use_tvg_only,
            )
        response = videorag.query(query=query, param=param)
        print(f"  -> {str(response)[:120]}...")

        with open(out_path, 'w', encoding='utf-8') as f:
            if isinstance(response, dict):
                f.write(response.get("answer", ""))
            else:
                f.write(str(response))
        print(f"  Saved: {out_path}")

    print(f"\n[QUERY] Done. Answers saved to: {answer_folder}")


if __name__ == '__main__':
    multiprocessing.set_start_method('spawn')

    with open('./longervideos/dataset.json', 'r') as f:
        all_collections_raw = json.load(f)

    # Build list of all collection folder names
    all_collections = []
    for cid in sorted(all_collections_raw.keys(), key=lambda x: int(x)):
        desc = all_collections_raw[cid][0]['description']
        all_collections.append(f"{cid}-{desc}")

    if args.mode == 'all':
        # Process every collection
        for col in all_collections:
            run_ingest(col)
            run_query(col)
    elif args.mode == 'ingest':
        if not args.collection:
            print("[ERROR] --collection is required for --mode ingest or query")
            exit(1)
        run_ingest(args.collection)
    elif args.mode == 'query' or args.mode == 'naive':
        if not args.collection:
            print("[ERROR] --collection is required for --mode ingest, query, or naive")
            exit(1)
        run_query(args.collection)
