"""
videorag/tools/graph_tools.py
=============================
Author's original graph retrieval logic wrapped for EBR-RAG.
"""
from typing import Any, List, Optional
from ..debate.evidence_types import EvidenceItem
from .formatters import make_segment_evidence, make_entity_evidence
from .._op import _refine_entity_retrieval_query, _find_most_related_segments_from_entities
from .._utils import logger
import asyncio

async def search_graph_evidence(
    query: str,
    stores: dict,
    top_k: int = 8,
    global_config: Optional[dict] = None,
    query_param=None,
) -> List[EvidenceItem]:
    """Retrieve evidence from the Original/TM Graph using author's logic."""
    entities_vdb = stores.get("entities_vdb")
    kg = stores.get("knowledge_graph")
    text_chunks_db = stores.get("text_chunks")
    video_segments = stores.get("video_segments")

    if entities_vdb is None or kg is None:
        return []

    # 1. Refine query for entities
    entity_query = query
    if global_config and query_param:
        try:
            entity_query = await _refine_entity_retrieval_query(query, query_param, global_config)
        except Exception:
            pass

    # 2. Search entities in VDB
    entity_results = await entities_vdb.query(entity_query, top_k=top_k)
    if not entity_results:
        return []

    # 3. Get node data and find related segments (Author's logic)
    raw_nodes = await asyncio.gather(
        *[kg.get_node(r.get("entity_name", r.get("id"))) for r in entity_results]
    )
    
    node_datas = []
    for res, node in zip(entity_results, raw_nodes):
        if node:
            # Ensure entity_name is present in the dict for _find_most_related_segments_from_entities
            node_copy = dict(node)
            node_copy["entity_name"] = res.get("entity_name", res.get("id"))
            node_datas.append(node_copy)
    
    # We'll return both entities and segments as evidence
    evidence: List[EvidenceItem] = []
    
    # Add entities
    for node in node_datas:
        # For the formatter, we need a 'result' dict that has the score/id
        # We find the original result match
        res_match = next((r for r in entity_results if r.get("entity_name", r.get("id")) == node["entity_name"]), {})
        evidence.append(make_entity_evidence(res_match, node))

    # Add segments (using _find_most_related_segments_from_entities)
    # This matches the 'skimming' behaviour in NaiveRAG
    try:
        related_seg_ids = await _find_most_related_segments_from_entities(
            top_k, 
            node_datas, 
            text_chunks_db, 
            kg
        )
        
        for seg_id in related_seg_ids:
            video_name = "_".join(str(seg_id).split("_")[:-1])
            seg_idx = str(seg_id).split("_")[-1]
            
            segment_payload = {}
            if video_segments:
                video_data = getattr(video_segments, "_data", {}).get(video_name, {})
                segment_payload = video_data.get(seg_idx, {}) if isinstance(video_data, dict) else {}
                if isinstance(segment_payload, dict):
                    segment_payload = {**segment_payload, "video_name": video_name, "segment_index": seg_idx}
            
            # We use a dummy result dict for the formatter
            evidence.append(make_segment_evidence({"id": seg_id, "similarity": 0.75}, segment_payload))
    except Exception as e:
        logger.warning(f"[search_graph_evidence] segment extraction failed: {e}")

    return evidence
