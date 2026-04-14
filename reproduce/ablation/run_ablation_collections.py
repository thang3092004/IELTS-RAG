import os
import json
import logging
import warnings
import multiprocessing
import argparse
from typing import Any

warnings.filterwarnings("ignore")
logging.getLogger("httpx").setLevel(logging.WARNING)

parser = argparse.ArgumentParser(description="Run 3 ablation scenarios per collection")
parser.add_argument('--collection', type=str, required=True, help="Collection subfolder e.g. '4-rag-lecture'")
parser.add_argument('--cuda', type=str, default='0')
parser.add_argument('--top-k', type=int, default=8, help="Top-K evidence items per retrieval")
args = parser.parse_args()

os.environ["CUDA_VISIBLE_DEVICES"] = args.cuda

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import videorag._op as op
from videorag._llm import LLMConfig, openai_embedding, gpt_4o_mini_complete
from videorag.videorag import VideoRAG, QueryParam


# Same LLM config as the original paper
longervideos_llm_config = LLMConfig(
    embedding_func_raw=openai_embedding,
    embedding_model_name="text-embedding-3-small",
    embedding_dim=1536,
    embedding_max_token_size=8192,
    embedding_batch_num=32,
    embedding_func_max_async=16,
    query_better_than_threshold=0.2,
    best_model_func_raw=gpt_4o_mini_complete,
    best_model_name="gpt-4o-mini",
    best_model_max_token_size=32768,
    best_model_max_async=16,
    cheap_model_func_raw=gpt_4o_mini_complete,
    cheap_model_name="gpt-4o-mini",
    cheap_model_max_token_size=32768,
    cheap_model_max_async=16,
)

WORKDIR_BASE = "./longervideos/ielts-rag-workdir"


class DummyRetriever:
    def __init__(self, results: list[dict[str, Any]] | None = None):
        self._results = results or []

    async def query(self, query: str, top_k: int = 5):
        return self._results


class DummyGraph:
    async def get_node(self, node_id: str):
        return None

    async def node_degree(self, node_id: str):
        return 0

    async def get_node_edges(self, source_node_id: str):
        return []


def _normalize_response(resp: Any) -> str:
    if isinstance(resp, dict):
        for key in ("answer", "response", "content", "text"):
            if key in resp:
                return str(resp[key]).strip()
    return str(resp).strip()


def _patch_caption_to_use_stored_segments() -> None:
    def _stored_caption_only(
        caption_model,
        caption_tokenizer,
        refine_knowledge,
        retrieved_segments,
        video_path_db,
        video_segments,
        num_sampled_frames,
    ):
        out = {}
        for seg_id in retrieved_segments:
            video_name = "_".join(seg_id.split("_")[:-1])
            index = seg_id.split("_")[-1]
            try:
                seg = video_segments._data[video_name][index]
                out[seg_id] = seg.get("content", "")
            except Exception:
                out[seg_id] = ""
        return out

    op.retrieved_segment_caption = _stored_caption_only


def _run_scenario(vrag: VideoRAG, scenario: str, query: str, top_k: int) -> str:
    # Keep references to restore after each run.
    original_chunks_vdb = vrag.chunks_vdb
    original_visual_vdb = vrag.video_segment_feature_vdb
    original_entities_vdb = vrag.entities_vdb
    original_graph = vrag.chunk_entity_relation_graph

    try:
        if scenario == "no_visual":
            vrag.video_segment_feature_vdb = DummyRetriever([])

        elif scenario == "no_chunks":
            dummy_id = "ablation-dummy-chunk"
            if dummy_id not in vrag.text_chunks._data:
                vrag.text_chunks._data[dummy_id] = {
                    "tokens": 0,
                    "content": "",
                    "chunk_order_index": 0,
                    "video_segment_id": [],
                }
            vrag.chunks_vdb = DummyRetriever([{"id": dummy_id, "distance": 0.0}])

        elif scenario == "no_graph":
            vrag.entities_vdb = DummyRetriever([])
            vrag.chunk_entity_relation_graph = DummyGraph()

        else:
            raise ValueError(f"Unsupported scenario: {scenario}")

        # IMPORTANT: Run the same IELTS-RAG mode, just with the backend data disabled
        param = QueryParam(
            mode="ielts_rag",
            ielts_top_k=top_k,
            max_rounds=2,       # Same as ielts_rag_longervideos
            return_detailed=False,
        )
        response = vrag.query(query, param=param)
        return _normalize_response(response)
    finally:
        vrag.chunks_vdb = original_chunks_vdb
        vrag.video_segment_feature_vdb = original_visual_vdb
        vrag.entities_vdb = original_entities_vdb
        vrag.chunk_entity_relation_graph = original_graph


def run_query_ablations(collection: str):
    print(f"\n{'='*60}")
    print(f"[ABLATION] Collection: {collection}")
    print(f"{'='*60}")

    with open('./longervideos/dataset.json', 'r') as f:
        longervideos = json.load(f)

    collection_id = collection.split('-')[0]
    if collection_id not in longervideos:
        print(f"[ERROR] Collection ID '{collection_id}' not found in dataset.json")
        return

    description = longervideos[collection_id][0]['description']
    
    # Check what queries to run
    queries = longervideos[collection_id][0]['questions']
    print(f"[ABLATION] {len(queries)} question(s) to answer")

    # Load VideoRAG
    workdir = os.path.join(WORKDIR_BASE, collection)
    if not os.path.exists(workdir):
         print(f"[ERROR] Working dir not found. Run ingest first: {workdir}")
         return
    
    _patch_caption_to_use_stored_segments()

    videorag = VideoRAG(llm=longervideos_llm_config, working_dir=workdir)
    videorag.load_caption_model(debug=True)

    scenarios = ["no_graph", "no_chunks", "no_visual"]

    for scenario in scenarios:
        scenario_answer_folder = os.path.join(
            './reproduce/all_answers',
            f'{collection_id}-{description}',
            f'answers-{scenario}'
        )
        os.makedirs(scenario_answer_folder, exist_ok=True)
        print(f"\n=== Scenario: {scenario} ===")

        for i, q in enumerate(queries):
            query_id = q['id']
            query = q['question']
            out_path = os.path.join(scenario_answer_folder, f'answer_{query_id}.md')

            if os.path.exists(out_path):
                print(f"[SKIP] {scenario} Q{query_id} already exists: {out_path}")
                continue

            print(f"[Q{query_id}/{len(queries)-1}] {query[:80]}...")
            try:
                answer = _run_scenario(videorag, scenario, query, args.top_k)
            except Exception as e:
                print(f"  [ERROR] {e}")
                answer = str(e)
            
            print(f"  -> {str(answer)[:120]}...")

            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(answer)

if __name__ == '__main__':
    multiprocessing.set_start_method('spawn')
    run_query_ablations(args.collection)
