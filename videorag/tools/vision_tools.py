from typing import Any
from .formatters import make_segment_evidence
from ..debate.evidence_types import EvidenceItem


async def search_visual_segment(query: str, stores: dict[str, Any], top_k: int = 4) -> list[EvidenceItem]:
    video_segment_feature_vdb = stores.get("video_segment_feature_vdb")
    video_segments = stores.get("video_segments")
    if video_segment_feature_vdb is None:
        return []

    results = await video_segment_feature_vdb.query(query, top_k=top_k)
    evidence: list[EvidenceItem] = []
    for res in results:
        seg_id = res.get("id") or res.get("__id__")
        if seg_id is None:
            continue
        video_name = "_".join(str(seg_id).split("_")[:-1])
        seg_idx = str(seg_id).split("_")[-1]
        segment_payload = None
        if video_segments is not None:
            video_data = video_segments._data.get(video_name, {})  # type: ignore
            segment_payload = video_data.get(seg_idx, {}) if isinstance(video_data, dict) else {}
            if isinstance(segment_payload, dict):
                segment_payload = {
                    **segment_payload,
                    "video_name": video_name,
                    "segment_index": seg_idx,
                }
        ev = make_segment_evidence({"id": seg_id, **res}, segment_payload)
        evidence.append(ev)
    return evidence
