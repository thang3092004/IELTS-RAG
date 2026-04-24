"""
Visual (multimodal) evidence retrieval tool for EBR-RAG.

Uses ImageBind cross-modal embeddings. Applies LLM query rewriting before searching,
matching the behaviour of videorag_query().
"""
from typing import Any, Optional

from .formatters import make_segment_evidence
from ..debate.evidence_types import EvidenceItem
from .._utils import logger
# Import _op.py internal — wrap, don't re-implement
from .._op import _refine_visual_retrieval_query


async def search_visual_segment(
    query: str,
    stores: dict[str, Any],
    top_k: int = 4,
    global_config: Optional[dict] = None,
    query_param=None,
) -> list[EvidenceItem]:
    """
    Retrieve video segments using ImageBind cross-modal embeddings.

    If `global_config` is provided, applies LLM query rewriting tailored for
    visual retrieval before hitting the ImageBind VDB.
    """
    video_segment_feature_vdb = stores.get("video_segment_feature_vdb")
    video_segments = stores.get("video_segments")

    if video_segment_feature_vdb is None:
        return []

    # --- Step 1: LLM visual query rewriting ---
    visual_query = query
    if global_config is not None and query_param is not None:
        try:
            visual_query = await _refine_visual_retrieval_query(query, query_param, global_config)
            logger.debug(f"[search_visual_segment] rewritten visual query: {visual_query!r}")
        except Exception as e:
            logger.warning(f"[search_visual_segment] visual query rewriting failed, using raw query: {e}")

    # --- Step 2: ImageBind vector search ---
    evidence: list[EvidenceItem] = []
    try:
        results = await video_segment_feature_vdb.query(visual_query, top_k=top_k)
        for res in results:
            seg_id = res.get("id") or res.get("__id__")
            if seg_id is None:
                continue
            video_name = "_".join(str(seg_id).split("_")[:-1])
            seg_idx = str(seg_id).split("_")[-1]

            segment_payload = None
            if video_segments is not None:
                video_data = getattr(video_segments, "_data", {}).get(video_name, {})
                segment_payload = video_data.get(seg_idx, {}) if isinstance(video_data, dict) else {}
                if isinstance(segment_payload, dict):
                    segment_payload = {
                        **segment_payload,
                        "video_name": video_name,
                        "segment_index": seg_idx,
                    }

            ev = make_segment_evidence({"id": seg_id, **res}, segment_payload)
            evidence.append(ev)
    except Exception as e:
        logger.warning(f"[search_visual_segment] visual retrieval failed: {e}")

    return evidence
