"""
videorag/tvg/builder.py
========================
``build_tvg()`` — the master ingest function that populates a ``TVGraph``
from an already-processed VideoRAG working directory.

Pipeline stages
---------------
1. **Semantic migration** — copy all entity nodes and semantic edges from the
   existing ``chunk_entity_relation_graph`` (``NetworkXStorage`` / ``nx.Graph``)
   into the TVG, computing text embeddings in batches.
2. **TAN construction** — for each video segment in ``video_segments._data``,
   add a ``tan`` node using its stored ImageBind embedding (fetched from the
   existing ``NanoVectorDBVideoSegmentStorage``).
3. **Temporal edges** — connect adjacent TANs chronologically within each video.
4. **Cross-modal edges** — for each entity node, parse ``source_id`` → chunk IDs
   → ``video_segment_id`` → segment IDs → add ``semantic → tan`` edges.
5. **FAISS optimisation** — call ``tvg.maybe_promote_indices()`` for large corpora.
6. **Persist** — save TVG to ``{working_dir}/tvg/``.

Incremental builds are fully supported: nodes that already exist in the graph
are skipped without re-computing embeddings.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import networkx as nx
import numpy as np

from .graph import TVGraph
from .schemas import TVGBuildMeta

logger = logging.getLogger("nano-graphrag")

# Separator used in source_id fields (matches GRAPH_FIELD_SEP in prompt.py)
_FIELD_SEP = "<SEP>"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def build_tvg(
    video_segments_data: Dict[str, Dict[str, Dict]],
    existing_entity_graph: nx.Graph,
    text_chunks_data: Dict[str, Dict],
    video_segment_feature_vdb: Any,
    text_embedding_func: Any,
    tvg: TVGraph,
    working_dir: str,
    semantic_dim: Optional[int] = None,
) -> TVGraph:
    """Build or incrementally update the TVG.

    Args:
        video_segments_data: ``video_segments._data`` dict with structure
            ``{video_name: {segment_index: {"content": ..., "time": ..., ...}}}``.
        existing_entity_graph: The ``NetworkXStorage._graph`` (``nx.Graph``) built
            during the standard entity-extraction pipeline.
        text_chunks_data: ``text_chunks._data`` dict mapping chunk ID → chunk dict
            (used to resolve ``source_id`` → ``video_segment_id``).
        video_segment_feature_vdb: ``NanoVectorDBVideoSegmentStorage`` instance;
            its internal NanoVectorDB client holds the ImageBind clip embeddings.
        text_embedding_func: Async callable that accepts a list of strings and
            returns a 2-D numpy array (n, embedding_dim).
        tvg: ``TVGraph`` instance to populate (may already contain nodes from
            a previous incremental build).
        working_dir: Base working directory (used for saving the TVG).
        semantic_dim: Text embedding dimensionality.  Inferred automatically
            from a probe call to ``text_embedding_func`` if ``None``.

    Returns:
        The populated ``TVGraph`` (same object as input, mutated in place).
    """
    save_dir = os.path.join(working_dir, "tvg")

    # --- Stage 1: Infer semantic_dim if needed ---
    if semantic_dim is None:
        semantic_dim = await _probe_embedding_dim(text_embedding_func)
        logger.info(f"[build_tvg] Inferred semantic_dim={semantic_dim}")

    # Update tvg dims if needed
    if tvg.semantic_dim != semantic_dim:
        tvg.semantic_dim = semantic_dim
        from .graph import _build_flat_index
        tvg._semantic_index = _build_flat_index(semantic_dim)
        tvg._semantic_id_list = []

    # --- Stage 2: Migrate semantic nodes (entity graph → TVG) ---
    logger.info("[build_tvg] Stage 1/5 — Migrating semantic nodes…")
    await _migrate_semantic_nodes(existing_entity_graph, tvg, text_embedding_func)

    # --- Stage 3: Add TANs ---
    logger.info("[build_tvg] Stage 2/5 — Adding TANs…")
    video_tan_map = _add_tans(
        video_segments_data, video_segment_feature_vdb, tvg
    )

    # --- Stage 4: Add temporal edges ---
    logger.info("[build_tvg] Stage 3/5 — Adding temporal edges…")
    _add_temporal_edges(video_tan_map, video_segments_data, tvg)

    # --- Stage 5: Add cross-modal edges ---
    logger.info("[build_tvg] Stage 4/5 — Adding cross-modal edges…")
    _add_cross_modal_edges(existing_entity_graph, text_chunks_data, tvg)

    # --- Stage 6: FAISS optimisation ---
    logger.info("[build_tvg] Stage 5/5 — Optimising FAISS indices…")
    tvg.maybe_promote_indices()

    # --- Store build metadata ---
    videos_processed = list(video_segments_data.keys())
    tvg.build_meta = TVGBuildMeta(
        built_at=datetime.now(timezone.utc).isoformat(),
        num_semantic_nodes=len(tvg._semantic_id_list),
        num_tans=len(tvg._tan_id_list),
        num_edges=tvg.num_edges(),
        tan_dim=tvg.tan_dim,
        semantic_dim=tvg.semantic_dim,
        videos_processed=",".join(videos_processed),
    )

    # --- Persist ---
    tvg.save(save_dir)
    logger.info(
        f"[build_tvg] Done. "
        f"Nodes: {tvg.num_nodes()} | Edges: {tvg.num_edges()} | "
        f"TANs: {len(tvg._tan_id_list)} | "
        f"Semantics: {len(tvg._semantic_id_list)}"
    )
    return tvg


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------

async def _probe_embedding_dim(embedding_func: Any) -> int:
    """Probe the text embedding function to determine its output dimensionality.

    Args:
        embedding_func: Async callable accepting list of strings.

    Returns:
        Integer embedding dimensionality.
    """
    result = await embedding_func(["probe"])
    arr = np.array(result)
    if arr.ndim == 1:
        return int(arr.shape[0])
    return int(arr.shape[-1])


async def _migrate_semantic_nodes(
    entity_graph: nx.Graph,
    tvg: TVGraph,
    text_embedding_func: Any,
    embed_batch_size: int = 64,
) -> None:
    """Copy all entity nodes and edges from the existing KG into the TVG.

    Only nodes not already present in ``tvg`` are embedded and inserted.

    Args:
        entity_graph: ``nx.Graph`` loaded from ``graph_chunk_entity_relation.graphml``.
        tvg: Target TVG to populate.
        text_embedding_func: Async callable for text embeddings.
        embed_batch_size: Number of entity descriptions embedded per API call.
    """
    new_nodes = [
        (nid, data)
        for nid, data in entity_graph.nodes(data=True)
        if not tvg._graph.has_node(nid)
        and data.get("node_type", "semantic") != "tan"
    ]

    if not new_nodes:
        logger.info("[build_tvg] No new semantic nodes to add.")
    else:
        texts = [
            (nid + " " + data.get("description", ""))[:4096]
            for nid, data in new_nodes
        ]
        all_embs = await _batch_embed(texts, text_embedding_func, embed_batch_size)

        for (nid, data), emb in zip(new_nodes, all_embs):
            tvg.add_semantic_node(
                node_id=nid,
                entity_type=data.get("entity_type", "UNKNOWN"),
                description=data.get("description", ""),
                source_id=data.get("source_id", ""),
                text_emb=emb,
            )
        logger.info(f"[build_tvg]   Added {len(new_nodes)} semantic nodes.")

    # Migrate semantic edges (undirected in source, stored bi-directionally in TVG)
    edge_count = 0
    for src, tgt, data in entity_graph.edges(data=True):
        if tvg._graph.has_edge(src, tgt):
            continue
        if not (tvg._graph.has_node(src) and tvg._graph.has_node(tgt)):
            continue
        tvg.add_semantic_edge(
            src_id=src,
            tgt_id=tgt,
            weight=float(data.get("weight", 1.0)),
            description=data.get("description", ""),
            source_id=data.get("source_id", ""),
        )
        edge_count += 1
    logger.info(f"[build_tvg]   Added {edge_count} semantic edges.")


async def _batch_embed(
    texts: List[str], embedding_func: Any, batch_size: int
) -> List[np.ndarray]:
    """Embed ``texts`` in batch-size chunks, returning a flat list of 1-D arrays.

    Args:
        texts: List of text strings to embed.
        embedding_func: Async callable accepting list[str] → np.ndarray (n, d).
        batch_size: Number of texts per API call.

    Returns:
        List of 1-D float32 numpy arrays, one per input text.
    """
    all_embs: List[np.ndarray] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        result = await embedding_func(batch)
        arr = np.array(result, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        for i in range(arr.shape[0]):
            all_embs.append(arr[i])
    return all_embs


def _add_tans(
    video_segments_data: Dict[str, Dict[str, Dict]],
    video_segment_feature_vdb: Any,
    tvg: TVGraph,
) -> Dict[str, List[str]]:
    """Add TAN nodes to TVG, retrieving embeddings from the existing VDB.

    Args:
        video_segments_data: ``{video_name: {segment_index: segment_dict}}``.
        video_segment_feature_vdb: ``NanoVectorDBVideoSegmentStorage`` instance.
        tvg: Target TVG.

    Returns:
        ``video_tan_map``: ``{video_name: [sorted tan_node_ids in chronological order]}``.
    """
    # Build a lookup: segment_id → embedding vector from NanoVectorDB
    vdb_emb_lookup: Dict[str, np.ndarray] = {}
    try:
        client = video_segment_feature_vdb._client
        for item in client.data:
            seg_id = item.get("__id__")
            vec = item.get("__vector__")
            if seg_id is not None and vec is not None:
                vdb_emb_lookup[seg_id] = np.array(vec, dtype=np.float32)
    except AttributeError:
        logger.warning(
            "[build_tvg] Could not access NanoVectorDB internals for TAN embeddings. "
            "TANs will have zero embeddings."
        )

    video_tan_map: Dict[str, List[str]] = {}

    for video_name, segments in video_segments_data.items():
        sorted_indices = sorted(segments.keys(), key=lambda x: int(x))
        tan_ids_for_video: List[str] = []

        for seg_idx in sorted_indices:
            seg_data = segments[seg_idx]
            node_id = f"{video_name}_{seg_idx}"
            tan_ids_for_video.append(node_id)

            if tvg._graph.has_node(node_id):
                continue  # incremental skip

            emb = vdb_emb_lookup.get(node_id, np.zeros(tvg.tan_dim, dtype=np.float32))

            tvg.add_tan(
                node_id=node_id,
                video_name=video_name,
                segment_index=seg_idx,
                time_range=seg_data.get("time", "0-0"),
                content=seg_data.get("content", ""),
                visual_emb=emb,
            )

        video_tan_map[video_name] = tan_ids_for_video

    total_tans = sum(len(v) for v in video_tan_map.values())
    logger.info(f"[build_tvg]   Total TANs: {total_tans}")
    return video_tan_map


def _add_temporal_edges(
    video_tan_map: Dict[str, List[str]],
    video_segments_data: Dict[str, Dict[str, Dict]],
    tvg: TVGraph,
) -> None:
    """Connect adjacent TANs with directed temporal edges.

    Args:
        video_tan_map: ``{video_name: [tan_node_ids in order]}``.
        video_segments_data: Raw segment data (used for computing delta_seconds).
        tvg: Target TVG.
    """
    edge_count = 0
    for video_name, tan_ids in video_tan_map.items():
        segments = video_segments_data[video_name]
        for i in range(len(tan_ids) - 1):
            src_id = tan_ids[i]
            tgt_id = tan_ids[i + 1]
            if tvg._graph.has_edge(src_id, tgt_id):
                continue

            src_idx = src_id.split("_")[-1]
            tgt_idx = tgt_id.split("_")[-1]
            try:
                src_end = float(segments[src_idx]["time"].split("-")[-1])
                tgt_start = float(segments[tgt_idx]["time"].split("-")[0])
                delta = max(0.0, tgt_start - src_end)
            except (KeyError, ValueError, IndexError):
                delta = 0.0

            tvg.add_temporal_edge(src_id, tgt_id, delta_seconds=delta)
            edge_count += 1
    logger.info(f"[build_tvg]   Added {edge_count} temporal edges.")


def _add_cross_modal_edges(
    entity_graph: nx.Graph,
    text_chunks_data: Dict[str, Dict],
    tvg: TVGraph,
) -> None:
    """Ground semantic nodes to TANs via cross-modal edges.

    For each semantic node:
    1. Parse ``source_id`` → chunk IDs.
    2. For each chunk, read ``video_segment_id`` (list of segment IDs).
    3. Add ``semantic → tan`` edge for each segment.

    Args:
        entity_graph: Existing ``nx.Graph``.
        text_chunks_data: ``text_chunks._data`` (chunk_id → chunk dict).
        tvg: Target TVG.
    """
    edge_count = 0
    for node_id, data in entity_graph.nodes(data=True):
        if not tvg._graph.has_node(node_id):
            continue
        raw_source_id = data.get("source_id", "")
        chunk_ids = [
            c.strip()
            for c in raw_source_id.split(_FIELD_SEP)
            if c.strip()
        ]
        for chunk_id in chunk_ids:
            chunk_data = text_chunks_data.get(chunk_id, {})
            if not chunk_data:
                continue
            video_segment_ids = chunk_data.get("video_segment_id", [])
            if isinstance(video_segment_ids, str):
                video_segment_ids = [video_segment_ids]
            for seg_id in video_segment_ids:
                if seg_id and tvg._graph.has_node(seg_id):
                    tvg.add_cross_modal_edge(node_id, seg_id, confidence=1.0)
                    edge_count += 1
    logger.info(f"[build_tvg]   Added {edge_count} cross-modal edges.")
