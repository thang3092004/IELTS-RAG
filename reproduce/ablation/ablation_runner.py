import argparse
import json
from pathlib import Path
from typing import Any

import videorag._op as op
from videorag.base import QueryParam
from videorag.videorag import VideoRAG


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


def _load_queries(path: Path, max_queries: int) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"queries file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    queries: list[str] = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                queries.append(item)
            elif isinstance(item, dict) and item.get("question"):
                queries.append(str(item["question"]))
    elif isinstance(data, dict):
        # Support longervideos/dataset.json style
        for _, entry in data.items():
            if not entry:
                continue
            payload = entry[0] if isinstance(entry, list) and entry else entry
            for q in payload.get("questions", []):
                question = q.get("question")
                if question:
                    queries.append(str(question))

    if not queries:
        raise ValueError("No queries found in input file")
    return queries[:max_queries]


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
            seg = video_segments._data[video_name][index]
            out[seg_id] = seg.get("content", "")
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
            # videorag_query early-exits if chunks_vdb returns empty.
            # Inject one empty chunk so the rest of pipeline still runs.
            dummy_id = "ablation-dummy-chunk"
            vrag.text_chunks._data[dummy_id] = {
                "tokens": 0,
                "content": "",
                "chunk_order_index": 0,
                "video_segment_id": [],
            }
            vrag.chunks_vdb = DummyRetriever([{"id": dummy_id, "distance": 0.0}])

        elif scenario == "no_graph":
            # Disable graph contribution by nulling entity retrieval and graph ops.
            vrag.entities_vdb = DummyRetriever([])
            vrag.chunk_entity_relation_graph = DummyGraph()

        else:
            raise ValueError(f"Unsupported scenario: {scenario}")

        param = QueryParam(mode="videorag", top_k=top_k)
        response = vrag.query(query, param=param)
        return _normalize_response(response)
    finally:
        vrag.chunks_vdb = original_chunks_vdb
        vrag.video_segment_feature_vdb = original_visual_vdb
        vrag.entities_vdb = original_entities_vdb
        vrag.chunk_entity_relation_graph = original_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 3 ablation scenarios: no_graph, no_chunks, no_visual")
    parser.add_argument("--working-dir", type=Path, required=True, help="Existing VideoRAG working_dir with ingested data")
    parser.add_argument("--queries", type=Path, default=Path("longervideos/dataset.json"), help="JSON file containing questions")
    parser.add_argument("--max-queries", type=int, default=10, help="Maximum number of queries to run")
    parser.add_argument("--top-k", type=int, default=20, help="top_k for retrieval")
    parser.add_argument("--out", type=Path, default=Path("reproduce/ablation/results/ablation_results.json"), help="Output JSON path")
    args = parser.parse_args()

    if not args.working_dir.exists():
        raise FileNotFoundError(f"working_dir not found: {args.working_dir}")

    queries = _load_queries(args.queries, args.max_queries)

    # Avoid re-captioning with heavy VLM during ablation; use stored segment content.
    _patch_caption_to_use_stored_segments()

    vrag = VideoRAG(working_dir=str(args.working_dir), always_create_working_dir=False)

    scenarios = ["no_graph", "no_chunks", "no_visual"]
    results: dict[str, dict[str, str]] = {s: {} for s in scenarios}

    for scenario in scenarios:
        print(f"=== Running {scenario} ===")
        for i, query in enumerate(queries, start=1):
            print(f"[{scenario}] {i}/{len(queries)}")
            try:
                answer = _run_scenario(vrag, scenario, query, args.top_k)
            except Exception as e:
                answer = f"ERROR: {e}"
            results[scenario][query] = answer

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved results to: {args.out}")


if __name__ == "__main__":
    main()
