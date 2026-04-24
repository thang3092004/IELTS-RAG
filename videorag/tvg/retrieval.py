"""
videorag/tvg/retrieval.py
==========================
``query_tvg()`` — the unified retrieval API for the Temporal-Visual Graph.

Retrieval strategy
------------------
1. **Semantic search** (text → semantic FAISS → entity nodes)
2. **Cross-modal traversal** (entity nodes → cross-modal edges → TANs)
3. **Direct visual search** (text → TAN FAISS via ImageBind text embedding)
4. **Temporal context expansion** (TANs → temporal edges ± hops)
5. **Subgraph assembly** into a ``TVGSubgraph`` TypedDict

Memory layout
-------------
All intermediate sets use ``str`` node IDs (no tensor allocations during
traversal). Embedding lookups only happen for FAISS search steps. The function
is fully synchronous to avoid event-loop friction; callers in the async EBR-RAG
pipeline should wrap with ``asyncio.get_event_loop().run_in_executor`` or call
the ``async`` wrapper :func:`async_query_tvg`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from .graph import TVGraph, _l2_normalize
from .schemas import (
    TANNode,
    TVGSubgraph,
    SemanticNode,
)

logger = logging.getLogger("nano-graphrag")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query_tvg(
    query_semantic_emb: np.ndarray,
    query_tan_emb: Optional[np.ndarray],
    tvg: TVGraph,
    top_k: int = 8,
    temporal_context_hops: int = 2,
    query: str = "",
) -> TVGSubgraph:
    """Retrieve a rich, temporally-coherent subgraph from the TVG.

    Args:
        query_semantic_emb: Text embedding of the query (for semantic FAISS
            search), shape ``(semantic_dim,)``.
        query_tan_emb: Optional ImageBind text embedding for direct visual
            search, shape ``(tan_dim,)``.  Pass ``None`` to skip visual search.
        tvg: Populated ``TVGraph`` instance.
        top_k: Number of semantic nodes and TANs to retrieve in each
            FAISS search step.
        temporal_context_hops: Number of temporal hops to expand around each
            retrieved TAN (e.g., 2 → retrieves TAN ± 2 neighbours).
        query: Original query string (stored in the returned subgraph for
            debugging/logging).

    Returns:
        A ``TVGSubgraph`` TypedDict containing semantic nodes, TANs,
        edges, segment IDs, and provenance traces.
    """
    # --- Step 1: Semantic FAISS search ---
    semantic_hits: List[Tuple[str, float]] = tvg.search_semantic_index(
        query_semantic_emb, top_k=top_k
    )
    semantic_node_ids: Set[str] = {nid for nid, _ in semantic_hits}

    # --- Step 2: Cross-modal traversal (semantic → TANs) ---
    tan_ids_from_semantic: Set[str] = set()
    provenance_map: Dict[str, str] = {}  # tan_id → provenance path string

    for sem_id, sem_score in semantic_hits:
        reachable_tans = tvg.get_successors_by_edge_type(sem_id, "cross_modal")
        for tan_id in reachable_tans:
            tan_ids_from_semantic.add(tan_id)
            provenance_map[tan_id] = (
                f"{sem_id} [cross_modal] → {tan_id}"
            )

    # --- Step 3: Direct visual search (skip if no TAN embedding or empty index) ---
    tan_ids_from_visual: Set[str] = set()
    if query_tan_emb is not None and tvg._tan_index.ntotal > 0:
        visual_hits = tvg.search_tan_index(query_tan_emb, top_k=top_k)
        for tan_id, score in visual_hits:
            tan_ids_from_visual.add(tan_id)
            if tan_id not in provenance_map:
                provenance_map[tan_id] = f"[visual_search] → {tan_id}"

    # --- Step 4: Temporal context expansion ---
    all_tan_ids: Set[str] = tan_ids_from_semantic | tan_ids_from_visual
    expanded_tans = _expand_temporal_context(
        all_tan_ids, tvg, hops=temporal_context_hops
    )
    all_tan_ids |= expanded_tans

    for tan_id in expanded_tans:
        if tan_id not in provenance_map:
            provenance_map[tan_id] = f"[temporal_context] → {tan_id}"

    # --- Step 5: Collect edges within the subgraph ---
    subgraph_nodes = semantic_node_ids | all_tan_ids
    collected_edges = _collect_subgraph_edges(subgraph_nodes, tvg)

    # --- Step 6: Assemble output dicts ---
    semantic_nodes_out = _collect_semantic_nodes(semantic_node_ids, semantic_hits, tvg)
    tans_out = _collect_tans(all_tan_ids, tvg)

    # Chronologically-sorted segment IDs (for downstream captioning)
    segment_ids = _sort_segment_ids(list(all_tan_ids))

    # Provenance path strings
    provenance_paths = _build_provenance_paths(
        semantic_hits, tvg, provenance_map
    )

    return TVGSubgraph(
        semantic_nodes=semantic_nodes_out,
        tans=tans_out,
        edges=collected_edges,
        segment_ids=segment_ids,
        provenance_paths=provenance_paths,
        query=query,
        top_k=top_k,
    )


async def async_query_tvg(
    query: str,
    tvg: TVGraph,
    text_embedding_func: Any,
    tan_embedding_func: Optional[Any],
    top_k: int = 8,
    temporal_context_hops: int = 2,
) -> TVGSubgraph:
    """Async wrapper around :func:`query_tvg` for use in the EBR-RAG pipeline.

    Computes both text and (optionally) visual query embeddings asynchronously,
    then delegates to the synchronous ``query_tvg`` for graph traversal.

    Args:
        query: Natural-language query string.
        tvg: Populated ``TVGraph``.
        text_embedding_func: Async callable ``(list[str]) → np.ndarray (n, d)``.
        tan_embedding_func: Optional async callable for ImageBind text embeddings.
            Pass ``None`` to skip visual FAISS search.
        top_k: Number of candidates per FAISS search step.
        temporal_context_hops: Temporal context expansion hops.

    Returns:
        ``TVGSubgraph`` with retrieved evidence.
    """
    # Embed query text
    sem_emb_batch = await text_embedding_func([query])
    sem_emb = np.array(sem_emb_batch, dtype=np.float32).reshape(-1)

    # Embed query for visual retrieval (ImageBind text encoder)
    tan_emb: Optional[np.ndarray] = None
    if tan_embedding_func is not None:
        try:
            tan_emb_batch = await asyncio.get_event_loop().run_in_executor(
                None, lambda: tan_embedding_func(query)
            )
            tan_emb = np.array(tan_emb_batch, dtype=np.float32).reshape(-1)
        except Exception as e:
            logger.warning(f"[async_query_tvg] TAN embedding failed: {e}")

    # Run synchronous graph traversal in executor to avoid blocking the loop
    loop = asyncio.get_event_loop()
    subgraph = await loop.run_in_executor(
        None,
        lambda: query_tvg(
            query_semantic_emb=sem_emb,
            query_tan_emb=tan_emb,
            tvg=tvg,
            top_k=top_k,
            temporal_context_hops=temporal_context_hops,
            query=query,
        ),
    )
    return subgraph


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _expand_temporal_context(
    seed_tan_ids: Set[str],
    tvg: TVGraph,
    hops: int,
) -> Set[str]:
    """BFS-expand seed TANs along temporal edges for ±hops neighbours.

    Args:
        seed_tan_ids: Starting set of TAN node IDs.
        tvg: TVGraph instance for edge traversal.
        hops: Number of temporal steps to expand in each direction.

    Returns:
        Set of additional TAN IDs (neighbours not in seed_tan_ids).
    """
    expanded: Set[str] = set()
    frontier: Set[str] = set(seed_tan_ids)

    for _ in range(hops):
        next_frontier: Set[str] = set()
        for tan_id in frontier:
            for nxt in tvg.get_successors_by_edge_type(tan_id, "temporal"):
                if nxt not in seed_tan_ids and nxt not in expanded:
                    next_frontier.add(nxt)
                    expanded.add(nxt)
            for prv in tvg.get_predecessors_by_edge_type(tan_id, "temporal"):
                if prv not in seed_tan_ids and prv not in expanded:
                    next_frontier.add(prv)
                    expanded.add(prv)
        frontier = next_frontier
        if not frontier:
            break

    return expanded


def _collect_subgraph_edges(
    node_set: Set[str], tvg: TVGraph
) -> List[Dict]:
    """Collect all directed edges whose both endpoints are in node_set.

    Args:
        node_set: Set of node IDs defining the subgraph.
        tvg: TVGraph instance.

    Returns:
        List of edge dicts with keys ``src_id``, ``tgt_id``, ``edge_type``
        (plus any extra attributes from the graph).
    """
    edges: List[Dict] = []
    seen: Set[Tuple[str, str]] = set()
    for src_id in node_set:
        if not tvg._graph.has_node(src_id):
            continue
        for _, tgt_id, data in tvg._graph.out_edges(src_id, data=True):
            if tgt_id not in node_set:
                continue
            key = (src_id, tgt_id)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "src_id": src_id,
                    "tgt_id": tgt_id,
                    "edge_type": data.get("edge_type", "unknown"),
                    **{k: v for k, v in data.items() if k != "edge_type"},
                }
            )
    return edges


def _collect_semantic_nodes(
    node_ids: Set[str],
    hits: List[Tuple[str, float]],
    tvg: TVGraph,
) -> List[SemanticNode]:
    """Build SemanticNode dicts for returned hits.

    Args:
        node_ids: Set of retrieved semantic node IDs.
        hits: ``(node_id, score)`` list from FAISS search.
        tvg: TVGraph for attribute lookup.

    Returns:
        List of ``SemanticNode`` TypedDicts.
    """
    nodes: List[SemanticNode] = []
    for nid in node_ids:
        attrs = tvg.get_node(nid)
        if attrs is None:
            continue
        nodes.append(
            SemanticNode(
                node_id=nid,
                node_type=attrs.get("node_type", "semantic"),
                entity_type=attrs.get("entity_type", ""),
                description=attrs.get("description", ""),
                source_id=attrs.get("source_id", ""),
                faiss_row_id=int(attrs.get("faiss_row_id", -1)),
            )
        )
    return nodes


def _collect_tans(
    node_ids: Set[str], tvg: TVGraph
) -> List[TANNode]:
    """Build TANNode dicts for all TAN IDs.

    Args:
        node_ids: Set of TAN node IDs.
        tvg: TVGraph for attribute lookup.

    Returns:
        List of ``TANNode`` TypedDicts.
    """
    tans: List[TANNode] = []\

    for nid in node_ids:
        attrs = tvg.get_node(nid)
        if attrs is None or attrs.get("node_type") != "tan":
            continue
        tans.append(
            TANNode(
                node_id=nid,
                node_type="tan",
                video_name=attrs.get("video_name", ""),
                segment_index=attrs.get("segment_index", ""),
                time_range=attrs.get("time_range", ""),
                content=attrs.get("content", ""),
                faiss_row_id=int(attrs.get("faiss_row_id", -1)),
            )
        )
    return tans


def _sort_segment_ids(tan_ids: List[str]) -> List[str]:
    """Sort segment IDs chronologically: by video name then numeric segment index.

    Args:
        tan_ids: List of ``"{video_name}_{segment_index}"`` strings.

    Returns:
        Sorted list.
    """

    def _key(seg_id: str):
        parts = seg_id.rsplit("_", 1)
        video = parts[0]
        try:
            idx = int(parts[1])
        except (IndexError, ValueError):
            idx = 0
        return (video, idx)

    return sorted(set(tan_ids), key=_key)


def _build_provenance_paths(
    semantic_hits: List[Tuple[str, float]],
    tvg: TVGraph,
    provenance_map: Dict[str, str],
) -> List[str]:
    """Build human-readable provenance path strings.

    Each string traces: semantic → cross_modal → TAN → temporal neighbours.

    Args:
        semantic_hits: List of ``(node_id, score)`` from semantic FAISS.
        tvg: TVGraph for traversal.
        provenance_map: tan_id → partial provenance string.

    Returns:
        List of path strings, one per (semantic node, TAN) combination.
    """
    paths: List[str] = []
    for sem_id, _ in semantic_hits:
        tans = tvg.get_successors_by_edge_type(sem_id, "cross_modal")
        if not tans:
            paths.append(f"{sem_id} [no direct TANs]")
            continue
        for tan_id in tans:
            paths.append(f"{sem_id} → [cross_modal] → {tan_id}")
    return paths
