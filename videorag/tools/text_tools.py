"""
Text and graph evidence retrieval tool for IELTS-RAG.

This module wraps existing _op.py retrieval functions instead of re-implementing them.
The key difference from the previous version: query rewriting via LLM is applied
BEFORE hitting the vector DB, matching what videorag_query() does.
"""
import asyncio
from typing import Any, Optional

from .formatters import make_text_evidence, make_entity_evidence, make_segment_evidence, _score_from_result
from ..debate.evidence_types import EvidenceItem
from ..prompt import GRAPH_FIELD_SEP
from .._utils import logger
# Import _op.py internals directly — we wrap, not re-implement
from .._op import (
    _refine_entity_retrieval_query,
    _find_most_related_segments_from_entities,
)


async def _fetch_text_chunks(text_chunks_db, ids: list[str]) -> list:
    if not ids:
        return []
    return await text_chunks_db.get_by_ids(ids)


def _get_segment_payload(video_segments, seg_id: str) -> dict | None:
    if video_segments is None:
        return None
    video_name = "_".join(seg_id.split("_")[:-1])
    seg_idx = seg_id.split("_")[-1]
    video_data = getattr(video_segments, "_data", {}) if hasattr(video_segments, "_data") else {}
    if not isinstance(video_data, dict):
        return None
    seg_payload = video_data.get(video_name, {}).get(seg_idx, {}) if isinstance(video_data.get(video_name, {}), dict) else {}
    if not isinstance(seg_payload, dict):
        return None
    return {**seg_payload, "video_name": video_name, "segment_index": seg_idx}


async def search_text_evidence(
    query: str,
    stores: dict[str, Any],
    top_k: int = 6,
    entity_boost: bool = True,
    global_config: Optional[dict] = None,
    query_param=None,
) -> list[EvidenceItem]:
    """
    Retrieve textual evidence: dense chunks + entity/graph expansion.

    If `global_config` is provided, applies LLM query rewriting before retrieval
    (matches the behaviour of videorag_query). Falls back to raw query otherwise.
    """
    chunks_vdb = stores.get("chunks_vdb")
    text_chunks_db = stores.get("text_chunks")
    entities_vdb = stores.get("entities_vdb")
    knowledge_graph = stores.get("knowledge_graph")
    video_segments = stores.get("video_segments")

    evidence: list[EvidenceItem] = []

    # --- Step 1: LLM query rewriting ---
    entity_query = query
    if global_config is not None and query_param is not None:
        try:
            entity_query = await _refine_entity_retrieval_query(query, query_param, global_config)
            logger.debug(f"[search_text_evidence] rewritten query: {entity_query!r}")
        except Exception as e:
            logger.warning(f"[search_text_evidence] query rewriting failed, using raw query: {e}")

    # --- Step 2: Dense chunk retrieval ---
    if chunks_vdb is not None and text_chunks_db is not None:
        logger.debug(f"[search_text_evidence] dense retrieval top_k={top_k}")
        try:
            dense_results = await chunks_vdb.query(entity_query, top_k=top_k)
            dense_ids = [r.get("id") for r in dense_results]
            dense_payloads = await _fetch_text_chunks(text_chunks_db, dense_ids)
            for res, payload in zip(dense_results, dense_payloads):
                if payload is None:
                    continue
                evidence.append(make_text_evidence(res, payload.get("content", "")))
        except Exception as e:
            logger.warning(f"[search_text_evidence] dense retrieval failed: {e}")

    # --- Step 3: Entity + knowledge graph expansion ---
    if entity_boost and entities_vdb is not None and knowledge_graph is not None:
        logger.debug(f"[search_text_evidence] entity/graph retrieval top_k={top_k}")
        try:
            entity_results = await entities_vdb.query(entity_query, top_k=top_k)
            node_datas = await asyncio.gather(
                *[knowledge_graph.get_node(r.get("entity_name", r.get("id"))) for r in entity_results]
            )
            node_degrees = await asyncio.gather(
                *[knowledge_graph.node_degree(r.get("entity_name", r.get("id"))) for r in entity_results]
            )

            # Build entity evidence items
            for res, node_data in zip(entity_results, node_datas):
                if node_data is None:
                    continue
                evidence.append(make_entity_evidence(res, node_data))

            # Use _find_most_related_segments_from_entities for proper graph traversal
            # (this walks the graph edges to find topk text chunks, not just direct sources)
            if global_config is not None and text_chunks_db is not None:
                node_datas_filtered = [
                    {**n, "entity_name": k.get("entity_name", k.get("id")), "rank": d}
                    for k, n, d in zip(entity_results, node_datas, node_degrees)
                    if n is not None
                ]
                if node_datas_filtered:
                    topk_chunks = global_config.get("retrieval_topk_chunks", 2)
                    segment_ids = await _find_most_related_segments_from_entities(
                        topk_chunks, node_datas_filtered, text_chunks_db, knowledge_graph
                    )
                    for seg_id in segment_ids:
                        payload = _get_segment_payload(video_segments, seg_id)
                        seg_res = {"id": seg_id, "similarity": 0.5}  # graph-derived, no direct score
                        evidence.append(make_segment_evidence(seg_res, payload))
            else:
                # Fallback: derive linked segments from node source_ids directly
                for res, node_data in zip(entity_results, node_datas):
                    if node_data is None:
                        continue
                    src_ids = node_data.get("source_id", "")
                    for seg in src_ids.split(GRAPH_FIELD_SEP):
                        seg = seg.strip()
                        if not seg:
                            continue
                        payload = _get_segment_payload(video_segments, seg)
                        seg_res = {"id": seg, "similarity": _score_from_result(res)}
                        evidence.append(make_segment_evidence(seg_res, payload))

        except Exception as e:
            logger.warning(f"[search_text_evidence] entity/graph retrieval failed: {e}")

    return evidence
