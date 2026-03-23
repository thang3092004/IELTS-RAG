import asyncio
from typing import Any
from .formatters import make_text_evidence, make_entity_evidence, make_segment_evidence
from ..debate.evidence_types import EvidenceItem
from ..prompt import GRAPH_FIELD_SEP
from .._utils import logger


async def _fetch_text_chunks(text_chunks_db, ids: list[str]):
    if not ids:
        return []
    return await text_chunks_db.get_by_ids(ids)


def _score_from_result(result: dict) -> float:
    if "similarity" in result:
        return float(result.get("similarity", 0.0))
    if "distance" in result:
        try:
            return max(0.0, 1.0 - float(result.get("distance", 1.0)))
        except Exception:
            return 0.0
    return 0.0


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


async def search_text_evidence(query: str, stores: dict[str, Any], top_k: int = 6, entity_boost: bool = True) -> list[EvidenceItem]:
    chunks_vdb = stores.get("chunks_vdb")
    text_chunks_db = stores.get("text_chunks")
    entities_vdb = stores.get("entities_vdb")
    knowledge_graph = stores.get("knowledge_graph")
    video_segments = stores.get("video_segments")

    evidence: list[EvidenceItem] = []

    # Dense text chunks
    if chunks_vdb is not None and text_chunks_db is not None:
        logger.debug(f"[search_text_evidence] dense query top_k={top_k}")
        dense_results = await chunks_vdb.query(query, top_k=top_k)
        dense_ids = [r.get("id") for r in dense_results]
        dense_payloads = await _fetch_text_chunks(text_chunks_db, dense_ids)
        for res, payload in zip(dense_results, dense_payloads):
            if payload is None:
                continue
            evidence.append(make_text_evidence(res, payload.get("content", "")))

    # Entity / graph expansion
    if entity_boost and entities_vdb is not None and knowledge_graph is not None:
        logger.debug(f"[search_text_evidence] entity/graph query top_k={top_k}")
        entity_results = await entities_vdb.query(query, top_k=top_k)
        node_datas = await asyncio.gather(
            *[knowledge_graph.get_node(r.get("entity_name", r.get("id"))) for r in entity_results]
        )
        for res, node_data in zip(entity_results, node_datas):
            if node_data is None:
                continue
            evidence.append(make_entity_evidence(res, node_data))
            # derive linked segments from node source ids
            src_ids = node_data.get("source_id", "")
            for seg in src_ids.split(GRAPH_FIELD_SEP):
                seg = seg.strip()
                if not seg:
                    continue
                payload = _get_segment_payload(video_segments, seg)
                seg_res = {"id": seg, "similarity": _score_from_result(res)}
                evidence.append(
                    make_segment_evidence(seg_res, payload)
                )

    return evidence
