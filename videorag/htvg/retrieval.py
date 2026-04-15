"""
videorag/htvg/retrieval.py
==========================
``query_htvg()`` — the unified retrieval API for the Hierarchical
Temporal-Visual Graph.

Retrieval strategy
------------------
1. **Semantic search** (text → semantic FAISS → entity nodes)
2. **Cross-modal traversal** (entity nodes → cross-modal edges → clip TANs)
3. **Direct visual search** (text → clip FAISS via ImageBind text embedding)
4. **Temporal context expansion** (clip TANs → temporal edges ± hops)
5. **Hierarchical context** (clip TANs → hierarchical edges → scene TANs)
6. **Subgraph assembly** into an ``HTVGSubgraph`` TypedDict

Memory layout
-------------
All intermediate sets use ``str`` node IDs (no tensor allocations during
traversal). Embedding lookups only happen for FAISS search steps. The function
is fully synchronous to avoid event-loop friction; callers in the async IELTS-RAG
pipeline should wrap with ``asyncio.get_event_loop().run_in_executor`` or call
the ``async`` wrapper :func:`async_query_htvg`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from .graph import HTVGraph, _l2_normalize
from .schemas import (
    ClipTANNode,
    HTVGSubgraph,
    SceneTANNode,
    SemanticNode,
)

logger = logging.getLogger("nano-graphrag")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query_htvg(
    query_semantic_emb: np.ndarray,
    query_clip_emb: Optional[np.ndarray],
    htvg: HTVGraph,
    top_k: int = 8,
    temporal_context_hops: int = 2,
    query: str = "",
) -> HTVGSubgraph:
    """Retrieve a rich, temporally-coherent subgraph from the HTVG.

    Args:
        query_semantic_emb: Text embedding of the query (for semantic FAISS
            search), shape ``(semantic_dim,)``.
        query_clip_emb: Optional ImageBind text embedding for direct visual
            search, shape ``(clip_dim,)``.  Pass ``None`` to skip visual search.
        htvg: Populated ``HTVGraph`` instance.
        top_k: Number of semantic nodes and clip TANs to retrieve in each
            FAISS search step.
        temporal_context_hops: Number of temporal hops to expand around each
            retrieved clip (e.g., 2 → retrieves clip ± 2 neighbours).
        query: Original query string (stored in the returned subgraph for
            debugging/logging).

    Returns:
        An ``HTVGSubgraph`` TypedDict containing semantic nodes, clip TANs,
        scene TANs, edges, segment IDs, and provenance traces.
    """
    # --- Step 1: Semantic FAISS search ---
    semantic_hits: List[Tuple[str, float]] = htvg.search_semantic_index(
        query_semantic_emb, top_k=top_k
    )
    semantic_node_ids: Set[str] = {nid for nid, _ in semantic_hits}

    # --- Step 2: Cross-modal traversal (semantic → clip TANs) ---
    clip_ids_from_semantic: Set[str] = set()
    provenance_map: Dict[str, str] = {}  # clip_id → provenance path string

    for sem_id, sem_score in semantic_hits:
        reachable_clips = htvg.get_successors_by_edge_type(sem_id, "cross_modal")
        for clip_id in reachable_clips:
            clip_ids_from_semantic.add(clip_id)
            provenance_map[clip_id] = (
                f"{sem_id} [cross_modal] → {clip_id}"
            )

    # --- Step 3: Direct visual search (skip if no clip embedding or empty index) ---
    clip_ids_from_visual: Set[str] = set()
    if query_clip_emb is not None and htvg._clip_index.ntotal > 0:
        visual_hits = htvg.search_clip_index(query_clip_emb, top_k=top_k)
        for clip_id, score in visual_hits:
            clip_ids_from_visual.add(clip_id)
            if clip_id not in provenance_map:
                provenance_map[clip_id] = f"[visual_search] → {clip_id}"

    # --- Step 4: Temporal context expansion ---
    all_clip_ids: Set[str] = clip_ids_from_semantic | clip_ids_from_visual
    expanded_clips = _expand_temporal_context(
        all_clip_ids, htvg, hops=temporal_context_hops
    )
    all_clip_ids |= expanded_clips

    # Annotate newly added clips in provenance map
    for clip_id in expanded_clips:
        if clip_id not in provenance_map:
            provenance_map[clip_id] = f"[temporal_context] → {clip_id}"

    # --- Step 5: Hierarchical context (clip → scene TANs) ---
    scene_ids: Set[str] = set()
    for clip_id in all_clip_ids:
        for scene_id in htvg.get_successors_by_edge_type(clip_id, "hierarchical"):
            scene_ids.add(scene_id)

    # --- Step 6: Collect edges within the subgraph ---
    subgraph_nodes = semantic_node_ids | all_clip_ids | scene_ids
    collected_edges = _collect_subgraph_edges(subgraph_nodes, htvg)

    # --- Step 7: Assemble output dicts ---
    semantic_nodes_out = _collect_semantic_nodes(semantic_node_ids, semantic_hits, htvg)
    clip_tans_out = _collect_clip_tans(all_clip_ids, htvg)
    scene_tans_out = _collect_scene_tans(scene_ids, htvg)

    # Chronologically-sorted segment IDs (for downstream captioning)
    segment_ids = _sort_segment_ids(list(all_clip_ids))

    # Provenance path strings (one per semantic node, tracing to clips and scenes)
    provenance_paths = _build_provenance_paths(
        semantic_hits, htvg, provenance_map, scene_ids
    )

    return HTVGSubgraph(
        semantic_nodes=semantic_nodes_out,
        clip_tans=clip_tans_out,
        scene_tans=scene_tans_out,
        edges=collected_edges,
        segment_ids=segment_ids,
        provenance_paths=provenance_paths,
        query=query,
        top_k=top_k,
    )


async def async_query_htvg(
    query: str,
    htvg: HTVGraph,
    text_embedding_func: Any,
    clip_embedding_func: Optional[Any],
    top_k: int = 8,
    temporal_context_hops: int = 2,
) -> HTVGSubgraph:
    """Async wrapper around :func:`query_htvg` for use in the IELTS-RAG pipeline.

    Computes both text and (optionally) visual query embeddings asynchronously,
    then delegates to the synchronous ``query_htvg`` for graph traversal.

    Args:
        query: Natural-language query string.
        htvg: Populated ``HTVGraph``.
        text_embedding_func: Async callable ``(list[str]) → np.ndarray (n, d)``.
        clip_embedding_func: Optional async callable for ImageBind text embeddings.
            Pass ``None`` to skip visual FAISS search.
        top_k: Number of candidates per FAISS search step.
        temporal_context_hops: Temporal context expansion hops.

    Returns:
        ``HTVGSubgraph`` with retrieved evidence.
    """
    # Embed query text
    sem_emb_batch = await text_embedding_func([query])
    sem_emb = np.array(sem_emb_batch, dtype=np.float32).reshape(-1)

    # Embed query for visual retrieval (ImageBind text encoder)
    clip_emb: Optional[np.ndarray] = None
    if clip_embedding_func is not None:
        try:
            clip_emb_batch = await asyncio.get_event_loop().run_in_executor(
                None, lambda: clip_embedding_func(query)
            )
            clip_emb = np.array(clip_emb_batch, dtype=np.float32).reshape(-1)
        except Exception as e:
            logger.warning(f"[async_query_htvg] clip embedding failed: {e}")

    # Run synchronous graph traversal in executor to avoid blocking the loop
    loop = asyncio.get_event_loop()
    subgraph = await loop.run_in_executor(
        None,
        lambda: query_htvg(
            query_semantic_emb=sem_emb,
            query_clip_emb=clip_emb,
            htvg=htvg,
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
    seed_clip_ids: Set[str],
    htvg: HTVGraph,
    hops: int,
) -> Set[str]:
    """BFS-expand seed clips along temporal edges for ±hops neighbours.

    Args:
        seed_clip_ids: Starting set of clip TAN node IDs.
        htvg: HTVG instance for edge traversal.
        hops: Number of temporal steps to expand in each direction.

    Returns:
        Set of additional clip TAN IDs (neighbours not in seed_clip_ids).
    """
    expanded: Set[str] = set()
    frontier: Set[str] = set(seed_clip_ids)

    for _ in range(hops):
        next_frontier: Set[str] = set()
        for clip_id in frontier:
            # Expand forward (temporal successors)
            for nxt in htvg.get_successors_by_edge_type(clip_id, "temporal"):
                if nxt not in seed_clip_ids and nxt not in expanded:
                    next_frontier.add(nxt)
                    expanded.add(nxt)
            # Expand backward (temporal predecessors)
            for prv in htvg.get_predecessors_by_edge_type(clip_id, "temporal"):
                if prv not in seed_clip_ids and prv not in expanded:
                    next_frontier.add(prv)
                    expanded.add(prv)
        frontier = next_frontier
        if not frontier:
            break

    return expanded


def _collect_subgraph_edges(
    node_set: Set[str], htvg: HTVGraph
) -> List[Dict]:
    """Collect all directed edges whose both endpoints are in node_set.

    Args:
        node_set: Set of node IDs defining the subgraph.
        htvg: HTVG instance.

    Returns:
        List of edge dicts with keys ``src_id``, ``tgt_id``, ``edge_type``
        (plus any extra attributes from the graph).
    """
    edges: List[Dict] = []
    seen: Set[Tuple[str, str]] = set()
    for src_id in node_set:
        if not htvg._graph.has_node(src_id):
            continue
        for _, tgt_id, data in htvg._graph.out_edges(src_id, data=True):
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
    htvg: HTVGraph,
) -> List[SemanticNode]:
    """Build SemanticNode dicts for returned hits.

    Args:
        node_ids: Set of retrieved semantic node IDs.
        hits: ``(node_id, score)`` list from FAISS search.
        htvg: HTVG for attribute lookup.

    Returns:
        List of ``SemanticNode`` TypedDicts.
    """
    score_map = {nid: score for nid, score in hits}
    nodes: List[SemanticNode] = []
    for nid in node_ids:
        attrs = htvg.get_node(nid)
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


def _collect_clip_tans(
    node_ids: Set[str], htvg: HTVGraph
) -> List[ClipTANNode]:
    """Build ClipTANNode dicts for all clip TAN IDs.

    Args:
        node_ids: Set of clip TAN node IDs.
        htvg: HTVG for attribute lookup.

    Returns:
        List of ``ClipTANNode`` TypedDicts.
    """
    tans: List[ClipTANNode] = []
    for nid in node_ids:
        attrs = htvg.get_node(nid)
        if attrs is None or attrs.get("tan_level") != "clip":
            continue
        tans.append(
            ClipTANNode(
                node_id=nid,
                node_type="tan_clip",
                tan_level="clip",
                video_name=attrs.get("video_name", ""),
                segment_index=attrs.get("segment_index", ""),
                time_range=attrs.get("time_range", ""),
                content=attrs.get("content", ""),
                faiss_row_id=int(attrs.get("faiss_row_id", -1)),
            )
        )
    return tans


def _collect_scene_tans(
    node_ids: Set[str], htvg: HTVGraph
) -> List[SceneTANNode]:
    """Build SceneTANNode dicts for all scene TAN IDs.

    Args:
        node_ids: Set of scene TAN node IDs.
        htvg: HTVG for attribute lookup.

    Returns:
        List of ``SceneTANNode`` TypedDicts.
    """
    tans: List[SceneTANNode] = []
    for nid in node_ids:
        attrs = htvg.get_node(nid)
        if attrs is None or attrs.get("tan_level") != "scene":
            continue
        clip_ids_str = attrs.get("clip_ids", "")
        clip_ids_list = [c for c in clip_ids_str.split(",") if c]
        tans.append(
            SceneTANNode(
                node_id=nid,
                node_type="tan_scene",
                tan_level="scene",
                video_name=attrs.get("video_name", ""),
                scene_index=attrs.get("scene_index", ""),
                time_range=attrs.get("time_range", ""),
                clip_ids=clip_ids_str,
                faiss_row_id=int(attrs.get("faiss_row_id", -1)),
            )
        )
    return tans


def _sort_segment_ids(clip_ids: List[str]) -> List[str]:
    """Sort segment IDs chronologically: by video name then numeric segment index.

    Args:
        clip_ids: List of ``"{video_name}_{segment_index}"`` strings.

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

    return sorted(set(clip_ids), key=_key)


def _build_provenance_paths(
    semantic_hits: List[Tuple[str, float]],
    htvg: HTVGraph,
    provenance_map: Dict[str, str],
    scene_ids: Set[str],
) -> List[str]:
    """Build human-readable provenance path strings.

    Each string traces the full path: semantic → cross_modal → clip → hierarchical → scene.

    Args:
        semantic_hits: List of ``(node_id, score)`` from semantic FAISS.
        htvg: HTVG for traversal.
        provenance_map: clip_id → partial provenance string.
        scene_ids: Set of retrieved scene TAN IDs.

    Returns:
        List of path strings, one per (semantic node, clip, scene) combination.
    """
    paths: List[str] = []
    for sem_id, _ in semantic_hits:
        clips = htvg.get_successors_by_edge_type(sem_id, "cross_modal")
        if not clips:
            paths.append(f"{sem_id} [no direct clips]")
            continue
        for clip_id in clips:
            scenes_of_clip = htvg.get_successors_by_edge_type(clip_id, "hierarchical")
            scene_part = (
                " → [hierarchical] → " + ", ".join(scenes_of_clip)
                if scenes_of_clip
                else ""
            )
            paths.append(f"{sem_id} → [cross_modal] → {clip_id}{scene_part}")
    return paths
