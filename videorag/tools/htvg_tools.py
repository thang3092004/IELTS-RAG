"""
videorag/tools/htvg_tools.py
=============================
``search_htvg_evidence()`` — wraps :func:`videorag.htvg.retrieval.async_query_htvg`
and converts the rich ``HTVGSubgraph`` into typed ``EvidenceItem`` objects
consumable by the IELTS-RAG multi-agent debate loop.

Evidence types produced
-----------------------
* ``type="entity"`` — from ``HTVGSubgraph.semantic_nodes``
* ``type="segment"`` — from ``HTVGSubgraph.clip_tans``
  (richer than the baseline because they carry ``provenance_path``)
* ``type="segment"`` — from ``HTVGSubgraph.scene_tans``
  (scene-level with hierarchical context)

Graceful degradation
--------------------
If ``htvg_storage`` is absent from ``stores`` or the HTVG is empty, the
function returns an empty list without raising.  This preserves full backward
compatibility with the existing baseline retrieval paths.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from ..debate.evidence_types import EvidenceItem
from ..htvg.schemas import HTVGSubgraph
from .._utils import logger

logger = logging.getLogger("nano-graphrag")


async def search_htvg_evidence(
    query: str,
    stores: dict,
    top_k: int = 8,
    temporal_context_hops: int = 2,
    global_config: Optional[dict] = None,
    query_param=None,
) -> List[EvidenceItem]:
    """Retrieve evidence from the HTVG and convert to ``EvidenceItem`` list.

    Args:
        query: Natural-language query string.
        stores: Store handle dict — must contain ``"htvg_storage"`` and
            optionally ``"text_embedding_func"`` and ``"clip_embedding_func"``.
        top_k: Number of candidates per FAISS search step.
        temporal_context_hops: Number of temporal BFS hops to expand.
        global_config: VideoRAG global config (used to pull LLM functions).
        query_param: ``QueryParam`` instance (unused currently but kept for
            API symmetry with other tool functions).

    Returns:
        List of ``EvidenceItem`` objects, empty if HTVG is unavailable.
    """
    htvg_storage = stores.get("htvg_storage")
    if htvg_storage is None:
        return []

    # Retrieve or construct embedding callables
    text_embedding_func = stores.get("text_embedding_func")
    if text_embedding_func is None and global_config is not None:
        try:
            text_embedding_func = global_config.get("llm", {}).get(
                "embedding_func", None
            )
        except Exception:
            pass

    if text_embedding_func is None:
        logger.warning("[search_htvg_evidence] No text embedding func available. Skipping HTVG.")
        return []

    clip_embedding_func = stores.get("clip_embedding_func", None)

    try:
        subgraph: HTVGSubgraph = await htvg_storage.query(
            query=query,
            text_embedding_func=text_embedding_func,
            top_k=top_k,
            temporal_context_hops=temporal_context_hops,
            clip_embedding_func=clip_embedding_func,
        )
    except Exception as e:
        logger.warning(f"[search_htvg_evidence] HTVG query failed: {e}")
        return []

    evidence: List[EvidenceItem] = []

    # --- Semantic nodes → entity evidence ---
    for sem_node in subgraph.get("semantic_nodes", []):
        ev = EvidenceItem(
            id=f"htvg_sem_{sem_node.get('node_id', '')}",
            type="entity",
            score=0.8,  # semantic FAISS score not stored in node; use constant
            snippet=sem_node.get("description", ""),
            source="htvg_semantic",
            metadata={
                "entity_type": sem_node.get("entity_type", ""),
                "node_id": sem_node.get("node_id", ""),
                "source_id": sem_node.get("source_id", ""),
            },
        )
        evidence.append(ev)

    # --- Clip TANs → segment evidence ---
    provenance_paths = subgraph.get("provenance_paths", [])
    provenance_lookup = _build_provenance_lookup(provenance_paths)

    for clip_tan in subgraph.get("clip_tans", []):
        node_id = clip_tan.get("node_id", "")
        video_name = clip_tan.get("video_name", "")
        seg_idx = clip_tan.get("segment_index", "")
        time_range = clip_tan.get("time_range", "")
        content = clip_tan.get("content", "")

        ev = EvidenceItem(
            id=f"htvg_clip_{node_id}",
            type="segment",
            score=0.75,
            snippet=content,
            source="htvg_clip_tan",
            video_name=video_name,
            segment_index=seg_idx,
            time_range=time_range,
            provenance_path=provenance_lookup.get(node_id, ""),
            metadata={
                "node_id": node_id,
                "tan_level": "clip",
            },
        )
        evidence.append(ev)

    # --- Scene TANs → segment evidence (scene-level context) ---
    for scene_tan in subgraph.get("scene_tans", []):
        node_id = scene_tan.get("node_id", "")
        video_name = scene_tan.get("video_name", "")
        time_range = scene_tan.get("time_range", "")
        clip_ids_str = scene_tan.get("clip_ids", "")
        scene_idx = scene_tan.get("scene_index", "")

        ev = EvidenceItem(
            id=f"htvg_scene_{node_id}",
            type="segment",
            score=0.7,
            snippet=f"[Scene {scene_idx} of {video_name}] Covers clips: {clip_ids_str}",
            source="htvg_scene_tan",
            video_name=video_name,
            segment_index=scene_idx,
            time_range=time_range,
            provenance_path=f"[hierarchical] ← {node_id}",
            metadata={
                "node_id": node_id,
                "tan_level": "scene",
                "clip_ids": clip_ids_str,
            },
        )
        evidence.append(ev)

    logger.info(
        f"[search_htvg_evidence] Retrieved {len(evidence)} items "
        f"({len(subgraph.get('semantic_nodes', []))} semantic, "
        f"{len(subgraph.get('clip_tans', []))} clips, "
        f"{len(subgraph.get('scene_tans', []))} scenes) "
        f"for query: {query[:80]!r}"
    )
    return evidence


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_provenance_lookup(provenance_paths: list) -> dict:
    """Build a mapping from clip node_id to its provenance path string.

    Parses strings of the form:
    ``"ENTITY_NAME → [cross_modal] → video_5 → [hierarchical] → scene_video_0"``

    Args:
        provenance_paths: List of provenance path strings from ``HTVGSubgraph``.

    Returns:
        Dict mapping clip node_ids → shortest provenance path string.
    """
    lookup: dict = {}
    for path in provenance_paths:
        # Extract clip node id (the part after [cross_modal] → )
        parts = path.split("→")
        for i, part in enumerate(parts):
            if "[cross_modal]" in part and i + 1 < len(parts):
                clip_part = parts[i + 1].strip()
                # Clip part may continue with " → [hierarchical]..."
                clip_id = clip_part.split(" → ")[0].strip()
                if clip_id and clip_id not in lookup:
                    lookup[clip_id] = path
    return lookup
