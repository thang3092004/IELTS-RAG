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
        subgraph: TVGSubgraph = await tvg_storage.query(
            query=query,
            text_embedding_func=text_embedding_func,
            top_k=top_k,
            temporal_context_hops=temporal_context_hops,
            tan_embedding_func=tan_embedding_func,
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
