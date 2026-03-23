"""
Shared formatting helpers that convert raw VDB/graph results into typed EvidenceItems.
`_score_from_result` is the single source of truth — do NOT duplicate in text_tools.py / vision_tools.py.
"""
from typing import Any
from ..debate.evidence_types import EvidenceItem


def _score_from_result(result: dict) -> float:
    """Normalise VDB result scores to [0, 1]."""
    if "similarity" in result:
        return float(result.get("similarity", 0.0))
    if "distance" in result:
        try:
            return max(0.0, 1.0 - float(result.get("distance", 1.0)))
        except Exception:
            return 0.0
    return 0.0


def make_text_evidence(result: dict, content: str) -> EvidenceItem:
    return EvidenceItem(
        id=str(result.get("id")),
        type="text",
        score=_score_from_result(result),
        snippet=content,
        source="text_chunk",
        metadata={k: v for k, v in result.items() if k not in {"id", "distance", "similarity"}},
    )


def make_entity_evidence(result: dict, node_data: dict[str, Any] | None) -> EvidenceItem:
    snippet = node_data.get("description", "") if node_data else ""
    return EvidenceItem(
        id=str(result.get("entity_name", result.get("id"))),
        type="entity",
        score=_score_from_result(result),
        snippet=snippet,
        source="entity",
        metadata={"entity_name": result.get("entity_name")},
    )


def make_segment_evidence(result: dict, segment_payload: dict[str, Any] | None) -> EvidenceItem:
    video_name = None
    segment_index = None
    time_range = None
    snippet = ""
    if segment_payload:
        video_name = segment_payload.get("video_name")
        segment_index = segment_payload.get("segment_index")
        time_range = segment_payload.get("time") or segment_payload.get("time_range")
        snippet = segment_payload.get("content", "")
    return EvidenceItem(
        id=str(result.get("id")),
        type="segment",
        score=_score_from_result(result),
        snippet=snippet,
        source="video_segment",
        video_name=video_name,
        segment_index=segment_index,
        time_range=time_range,
        metadata={k: v for k, v in result.items() if k not in {"id", "distance", "similarity"}},
    )
