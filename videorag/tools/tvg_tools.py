"""
videorag/tools/tvg_tools.py
=============================
``search_tvg_evidence()`` — wraps :func:`videorag.tvg.retrieval.async_query_tvg`
and converts the rich ``TVGSubgraph`` into typed ``EvidenceItem`` objects
consumable by the EBR-RAG multi-agent debate loop.

Evidence types produced
-----------------------
* ``type="entity"`` — from ``TVGSubgraph.semantic_nodes``
* ``type="segment"`` — from ``TVGSubgraph.tans``
  (carry temporal provenance path)

Graceful degradation
--------------------
If ``tvg_storage`` is absent from ``stores`` or the TVG is empty, the
function returns an empty list without raising.  This preserves full backward
compatibility with the existing baseline retrieval paths.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from ..debate.evidence_types import EvidenceItem
from ..tvg.schemas import TVGSubgraph
from .._utils import logger

logger = logging.getLogger("nano-graphrag")


async def search_tvg_evidence(
    query: str,
    stores: dict,
    top_k: int = 8,
    temporal_context_hops: int = 2,
    global_config: Optional[dict] = None,
    query_param=None,
) -> List[EvidenceItem]:
    """Retrieve evidence from the TVG and convert to ``EvidenceItem`` list.

    Args:
        query: Natural-language query string.
        stores: Store handle dict — must contain ``"tvg_storage"`` and
            optionally ``"text_embedding_func"`` and ``"tan_embedding_func"``.
        top_k: Number of candidates per FAISS search step.
        temporal_context_hops: Number of temporal BFS hops to expand.
        global_config: VideoRAG global config (used to pull LLM functions).
        query_param: ``QueryParam`` instance (unused currently but kept for
            API symmetry with other tool functions).

    Returns:
        List of ``EvidenceItem`` objects, empty if TVG is unavailable.
    """
    tvg_storage = stores.get("tvg_storage")
    if tvg_storage is None:
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
        logger.warning("[search_tvg_evidence] No text embedding func available. Skipping TVG.")
        return []

    tan_embedding_func = stores.get("tan_embedding_func", None)

    try:
        from .._op import _refine_visual_retrieval_query
        visual_query = query
        if global_config is not None and query_param is not None:
            try:
                visual_query = await _refine_visual_retrieval_query(query, query_param, global_config)
                logger.debug(f"[search_tvg_evidence] rewritten visual query: {visual_query!r}")
            except Exception as e:
                logger.warning(f"[search_tvg_evidence] query rewriting failed: {e}")

        subgraph: TVGSubgraph = await tvg_storage.query(
            query=query,
            text_embedding_func=text_embedding_func,
            top_k=top_k,
            temporal_context_hops=temporal_context_hops,
            tan_embedding_func=tan_embedding_func,
            visual_query=visual_query,
            semantic_context_hops=getattr(query_param, "tvg_semantic_hops", 1),
            # Ablation flags
            disable_semantic=getattr(query_param, "tvg_disable_semantic", False),
            disable_tan=getattr(query_param, "tvg_disable_tan", False),
            disable_cross_modal=getattr(query_param, "tvg_disable_cross_modal", False),
            disable_semantic_edges=getattr(query_param, "tvg_disable_semantic_edges", False),
            disable_temporal=getattr(query_param, "tvg_disable_temporal", False),
        )
    except Exception as e:
        logger.warning(f"[search_tvg_evidence] TVG query failed: {e}")
        return []

    evidence: List[EvidenceItem] = []

    # --- Semantic nodes → entity evidence ---
    for sem_node in subgraph.get("semantic_nodes", []):
        ev = EvidenceItem(
            id=f"tvg_sem_{sem_node.get('node_id', '')}",
            type="entity",
            score=0.8,
            snippet=sem_node.get("description", ""),
            source="tvg_semantic",
            metadata={
                "entity_type": sem_node.get("entity_type", ""),
                "node_id": sem_node.get("node_id", ""),
                "source_id": sem_node.get("source_id", ""),
            },
        )
        evidence.append(ev)

    # --- TANs → segment evidence ---
    provenance_paths = subgraph.get("provenance_paths", [])
    provenance_lookup = _build_provenance_lookup(provenance_paths)

    for tan in subgraph.get("tans", []):
        node_id = tan.get("node_id", "")
        video_name = tan.get("video_name", "")
        seg_idx = tan.get("segment_index", "")
        time_range = tan.get("time_range", "")
        content = tan.get("content", "")

        ev = EvidenceItem(
            id=f"tvg_tan_{node_id}",
            type="segment",
            score=0.75,
            snippet=content,
            source="tvg_tan",
            video_name=video_name,
            segment_index=seg_idx,
            time_range=time_range,
            provenance_path=provenance_lookup.get(node_id, ""),
            metadata={
                "node_id": node_id,
            },
        )
        evidence.append(ev)

    # --- Fairness Truncation ---
    # Hard cap the evidence list to prevent Graph explosion from artificially
    # beating baselines just by feeding more tokens to the LLM.
    # We allow TVG to return slightly more items to account for temporal context,
    # but strictly cap it at min(50, top_k * 3). The Global Fairness Cap in EBR_RAG
    # will handle the absolute limit.
    MAX_CAPACITY = min(50, top_k * 3)
    if len(evidence) > MAX_CAPACITY:
        logger.info(f"[search_tvg_evidence] Local Truncation: {len(evidence)} items -> {MAX_CAPACITY}")
        # Keep semantic nodes (which are usually first) and top TAN nodes
        evidence = evidence[:MAX_CAPACITY]

    logger.info(
        f"[search_tvg_evidence] Retrieved {len(evidence)} items "
        f"({len(subgraph.get('semantic_nodes', []))} semantic, "
        f"{len(subgraph.get('tans', []))} TANs) "
        f"for query: {query[:80]!r}"
    )
    return evidence


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_provenance_lookup(provenance_paths: list) -> dict:
    """Build a mapping from TAN node_id to its provenance path string.

    Parses strings of the form:
    ``"ENTITY_NAME → [cross_modal] → video_5"``

    Args:
        provenance_paths: List of provenance path strings from ``TVGSubgraph``.

    Returns:
        Dict mapping TAN node_ids → shortest provenance path string.
    """
    lookup: dict = {}
    for path in provenance_paths:
        parts = path.split("→")
        for i, part in enumerate(parts):
            if "[cross_modal]" in part and i + 1 < len(parts):
                tan_part = parts[i + 1].strip()
                tan_id = tan_part.split(" → ")[0].strip()
                if tan_id and tan_id not in lookup:
                    lookup[tan_id] = path
    return lookup
