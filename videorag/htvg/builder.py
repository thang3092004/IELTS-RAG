"""
videorag/htvg/builder.py
========================
``build_htvg()`` — the master ingest function that populates an ``HTVGraph``
from an already-processed VideoRAG working directory.

Pipeline stages
---------------
1. **Semantic migration** — copy all entity nodes and semantic edges from the
   existing ``chunk_entity_relation_graph`` (``NetworkXStorage`` / ``nx.Graph``)
   into the HTVG, computing text embeddings in batches.
2. **Clip TAN construction** — for each video segment in ``video_segments._data``,
   add a ``tan_clip`` node using its stored ImageBind embedding (fetched from the
   existing ``NanoVectorDBVideoSegmentStorage``).
3. **Temporal edges** — connect adjacent clip TANs chronologically within each
   video.
4. **Cross-modal edges** — for each entity node, parse ``source_id`` → chunk IDs
   → ``video_segment_id`` → segment IDs → add ``semantic → tan_clip`` edges.
5. **Hierarchical aggregation** — group clip TANs into scenes using
   ``HierarchicalAggregator``, add scene TAN nodes and hierarchical edges.
6. **FAISS optimisation** — call ``htvg.maybe_promote_indices()`` for large corpora.
7. **Persist** — save HTVG to ``{working_dir}/htvg/``.

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
import torch

from .aggregator import HierarchicalAggregator, TemporalTransformer
from .graph import HTVGraph
from .schemas import HTVGBuildMeta

logger = logging.getLogger("nano-graphrag")

# Separator used in source_id fields (matches GRAPH_FIELD_SEP in prompt.py)
_FIELD_SEP = "<SEP>"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def build_htvg(
    video_segments_data: Dict[str, Dict[str, Dict]],
    existing_entity_graph: nx.Graph,
    text_chunks_data: Dict[str, Dict],
    video_segment_feature_vdb: Any,
    text_embedding_func: Any,
    aggregator: HierarchicalAggregator,
    htvg: HTVGraph,
    working_dir: str,
    semantic_dim: Optional[int] = None,
) -> HTVGraph:
    """Build or incrementally update the HTVG.

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
        aggregator: ``HierarchicalAggregator`` instance (may hold a randomly
            initialised model if fine-tuning has not yet been run).
        htvg: ``HTVGraph`` instance to populate (may already contain nodes from
            a previous incremental build).
        working_dir: Base working directory (used for saving the HTVG).
        semantic_dim: Text embedding dimensionality.  Inferred automatically
            from a probe call to ``text_embedding_func`` if ``None``.

    Returns:
        The populated ``HTVGraph`` (same object as input, mutated in place).
    """
    save_dir = os.path.join(working_dir, "htvg")

    # --- Stage 1: Infer semantic_dim if needed ---
    if semantic_dim is None:
        semantic_dim = await _probe_embedding_dim(text_embedding_func)
        logger.info(f"[build_htvg] Inferred semantic_dim={semantic_dim}")

    # Update htvg dims if needed
    if htvg.semantic_dim != semantic_dim:
        htvg.semantic_dim = semantic_dim
        from .graph import _build_flat_index
        htvg._semantic_index = _build_flat_index(semantic_dim)
        htvg._semantic_id_list = []

    # --- Stage 2: Migrate semantic nodes (entity graph → HTVG) ---
    logger.info("[build_htvg] Stage 1/6 — Migrating semantic nodes…")
    await _migrate_semantic_nodes(existing_entity_graph, htvg, text_embedding_func)

    # --- Stage 3: Add clip TANs ---
    logger.info("[build_htvg] Stage 2/6 — Adding clip TANs…")
    video_clip_map = _add_clip_tans(
        video_segments_data, video_segment_feature_vdb, htvg
    )

    # --- Stage 4: Add temporal edges ---
    logger.info("[build_htvg] Stage 3/6 — Adding temporal edges…")
    _add_temporal_edges(video_clip_map, video_segments_data, htvg)

    # --- Stage 5: Add cross-modal edges ---
    logger.info("[build_htvg] Stage 4/6 — Adding cross-modal edges…")
    _add_cross_modal_edges(existing_entity_graph, text_chunks_data, htvg)

    # --- Stage 6: Hierarchical aggregation (scene TANs) ---
    logger.info("[build_htvg] Stage 5/6 — Running HierarchicalAggregator…")
    _add_scene_tans_and_edges(video_clip_map, video_segments_data, htvg, aggregator)

    # --- Stage 7: FAISS optimisation ---
    logger.info("[build_htvg] Stage 6/6 — Optimising FAISS indices…")
    htvg.maybe_promote_indices()

    # --- Store build metadata ---
    videos_processed = list(video_segments_data.keys())
    htvg.build_meta = HTVGBuildMeta(
        built_at=datetime.now(timezone.utc).isoformat(),
        num_semantic_nodes=len(htvg._semantic_id_list),
        num_clip_tans=len(htvg._clip_id_list),
        num_scene_tans=len(htvg._scene_id_list),
        num_edges=htvg.num_edges(),
        clip_dim=htvg.clip_dim,
        scene_dim=htvg.scene_dim,
        semantic_dim=htvg.semantic_dim,
        aggregator_checkpoint="",
        videos_processed=",".join(videos_processed),
    )

    # --- Persist ---
    htvg.save(save_dir)
    logger.info(
        f"[build_htvg] Done. "
        f"Nodes: {htvg.num_nodes()} | Edges: {htvg.num_edges()} | "
        f"Clips: {len(htvg._clip_id_list)} | Scenes: {len(htvg._scene_id_list)} | "
        f"Semantics: {len(htvg._semantic_id_list)}"
    )
    return htvg


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
    htvg: HTVGraph,
    text_embedding_func: Any,
    embed_batch_size: int = 64,
) -> None:
    """Copy all entity nodes and edges from the existing KG into the HTVG.

    Only nodes not already present in ``htvg`` are embedded and inserted.

    Args:
        entity_graph: ``nx.Graph`` loaded from ``graph_chunk_entity_relation.graphml``.
        htvg: Target HTVG to populate.
        text_embedding_func: Async callable for text embeddings.
        embed_batch_size: Number of entity descriptions embedded per API call.
    """
    new_nodes = [
        (nid, data)
        for nid, data in entity_graph.nodes(data=True)
        if not htvg._graph.has_node(nid)
        and data.get("node_type", "semantic") != "tan_clip"
        and data.get("node_type", "semantic") != "tan_scene"
    ]

    if not new_nodes:
        logger.info("[build_htvg] No new semantic nodes to add.")
    else:
        # Embed in batches
        texts = [
            (nid + " " + data.get("description", ""))[:4096]
            for nid, data in new_nodes
        ]
        all_embs = await _batch_embed(texts, text_embedding_func, embed_batch_size)

        for (nid, data), emb in zip(new_nodes, all_embs):
            htvg.add_semantic_node(
                node_id=nid,
                entity_type=data.get("entity_type", "UNKNOWN"),
                description=data.get("description", ""),
                source_id=data.get("source_id", ""),
                text_emb=emb,
            )
        logger.info(f"[build_htvg]   Added {len(new_nodes)} semantic nodes.")

    # Migrate semantic edges (undirected in source, stored bi-directionally in HTVG)
    edge_count = 0
    for src, tgt, data in entity_graph.edges(data=True):
        if htvg._graph.has_edge(src, tgt):
            continue
        if not (htvg._graph.has_node(src) and htvg._graph.has_node(tgt)):
            continue
        htvg.add_semantic_edge(
            src_id=src,
            tgt_id=tgt,
            weight=float(data.get("weight", 1.0)),
            description=data.get("description", ""),
            source_id=data.get("source_id", ""),
        )
        edge_count += 1
    logger.info(f"[build_htvg]   Added {edge_count} semantic edges.")


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


def _add_clip_tans(
    video_segments_data: Dict[str, Dict[str, Dict]],
    video_segment_feature_vdb: Any,
    htvg: HTVGraph,
) -> Dict[str, List[str]]:
    """Add clip TAN nodes to HTVG, retrieving embeddings from the existing VDB.

    Args:
        video_segments_data: ``{video_name: {segment_index: segment_dict}}``.
        video_segment_feature_vdb: ``NanoVectorDBVideoSegmentStorage`` instance.
        htvg: Target HTVG.

    Returns:
        ``video_clip_map``: ``{video_name: [sorted clip_node_ids in chronological order]}``.
    """
    # Build a lookup: segment_id → embedding vector from NanoVectorDB
    vdb_emb_lookup: Dict[str, np.ndarray] = {}
    try:
        client = video_segment_feature_vdb._client
        # NanoVectorDB stores items in client.data (list of dicts with __id__ and __vector__)
        for item in client.data:
            seg_id = item.get("__id__")
            vec = item.get("__vector__")
            if seg_id is not None and vec is not None:
                vdb_emb_lookup[seg_id] = np.array(vec, dtype=np.float32)
    except AttributeError:
        logger.warning(
            "[build_htvg] Could not access NanoVectorDB internals for clip embeddings. "
            "Clip TANs will have zero embeddings."
        )

    video_clip_map: Dict[str, List[str]] = {}

    for video_name, segments in video_segments_data.items():
        # Sort segment indices numerically
        sorted_indices = sorted(segments.keys(), key=lambda x: int(x))
        clip_ids_for_video: List[str] = []

        for seg_idx in sorted_indices:
            seg_data = segments[seg_idx]
            node_id = f"{video_name}_{seg_idx}"
            clip_ids_for_video.append(node_id)

            if htvg._graph.has_node(node_id):
                continue  # incremental skip

            # Fetch embedding or fall back to zeros
            emb = vdb_emb_lookup.get(node_id, np.zeros(htvg.clip_dim, dtype=np.float32))

            htvg.add_clip_tan(
                node_id=node_id,
                video_name=video_name,
                segment_index=seg_idx,
                time_range=seg_data.get("time", "0-0"),
                content=seg_data.get("content", ""),
                visual_emb=emb,
            )

        video_clip_map[video_name] = clip_ids_for_video

    total_clips = sum(len(v) for v in video_clip_map.values())
    logger.info(f"[build_htvg]   Total clip TANs: {total_clips}")
    return video_clip_map


def _add_temporal_edges(
    video_clip_map: Dict[str, List[str]],
    video_segments_data: Dict[str, Dict[str, Dict]],
    htvg: HTVGraph,
) -> None:
    """Connect adjacent clip TANs with directed temporal edges.

    Args:
        video_clip_map: ``{video_name: [clip_node_ids in order]}``.
        video_segments_data: Raw segment data (used for computing delta_seconds).
        htvg: Target HTVG.
    """
    edge_count = 0
    for video_name, clip_ids in video_clip_map.items():
        segments = video_segments_data[video_name]
        for i in range(len(clip_ids) - 1):
            src_id = clip_ids[i]
            tgt_id = clip_ids[i + 1]
            if htvg._graph.has_edge(src_id, tgt_id):
                continue

            # Compute delta_seconds between end of clip_i and start of clip_{i+1}
            src_idx = src_id.split("_")[-1]
            tgt_idx = tgt_id.split("_")[-1]
            try:
                src_end = float(segments[src_idx]["time"].split("-")[-1])
                tgt_start = float(segments[tgt_idx]["time"].split("-")[0])
                delta = max(0.0, tgt_start - src_end)
            except (KeyError, ValueError, IndexError):
                delta = 0.0

            htvg.add_temporal_edge(src_id, tgt_id, delta_seconds=delta)
            edge_count += 1
    logger.info(f"[build_htvg]   Added {edge_count} temporal edges.")


def _add_cross_modal_edges(
    entity_graph: nx.Graph,
    text_chunks_data: Dict[str, Dict],
    htvg: HTVGraph,
) -> None:
    """Ground semantic nodes to clip TANs via cross-modal edges.

    For each semantic node:
    1. Parse ``source_id`` → chunk IDs.
    2. For each chunk, read ``video_segment_id`` (list of segment IDs).
    3. Add ``semantic → tan_clip`` edge for each segment.

    Args:
        entity_graph: Existing ``nx.Graph``.
        text_chunks_data: ``text_chunks._data`` (chunk_id → chunk dict).
        htvg: Target HTVG.
    """
    edge_count = 0
    for node_id, data in entity_graph.nodes(data=True):
        if not htvg._graph.has_node(node_id):
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
                if seg_id and htvg._graph.has_node(seg_id):
                    htvg.add_cross_modal_edge(node_id, seg_id, confidence=1.0)
                    edge_count += 1
    logger.info(f"[build_htvg]   Added {edge_count} cross-modal edges.")


def _add_scene_tans_and_edges(
    video_clip_map: Dict[str, List[str]],
    video_segments_data: Dict[str, Dict[str, Dict]],
    htvg: HTVGraph,
    aggregator: HierarchicalAggregator,
) -> None:
    """Create scene TANs via HierarchicalAggregator and wire hierarchical edges.

    Args:
        video_clip_map: ``{video_name: [clip_node_ids in order]}``.
        video_segments_data: Raw segment data (used for time_range extraction).
        htvg: Target HTVG.
        aggregator: Pre-initialised (possibly randomly weighted) aggregator.
    """
    scene_count = 0
    hierarchical_edge_count = 0

    for video_name, clip_ids in video_clip_map.items():
        if not clip_ids:
            continue

        # Check if all scene TANs already exist (incremental skip)
        first_scene_id = f"scene_{video_name}_0"
        if htvg._graph.has_node(first_scene_id):
            logger.info(
                f"[build_htvg]   Scene TANs for {video_name} already present, skipping."
            )
            continue

        # Gather embeddings in order from FAISS clip index
        clip_embs = _collect_clip_embs(clip_ids, htvg)
        segments = video_segments_data[video_name]
        sorted_indices = sorted(segments.keys(), key=lambda x: int(x))
        time_ranges = [
            segments[idx].get("time", "0-0") for idx in sorted_indices
        ]

        # Verify lengths match (defensive)
        if len(clip_embs) != len(time_ranges):
            min_len = min(len(clip_embs), len(time_ranges))
            clip_embs = clip_embs[:min_len]
            clip_ids_for_agg = clip_ids[:min_len]
            time_ranges = time_ranges[:min_len]
        else:
            clip_ids_for_agg = clip_ids

        scene_dicts = aggregator.aggregate(
            video_name=video_name,
            clip_embs=clip_embs,
            clip_ids=clip_ids_for_agg,
            time_ranges=time_ranges,
        )

        for scene_dict in scene_dicts:
            htvg.add_scene_tan(
                node_id=scene_dict["node_id"],
                video_name=scene_dict["video_name"],
                scene_index=scene_dict["scene_index"],
                time_range=scene_dict["time_range"],
                clip_ids=scene_dict["clip_ids"],
                scene_emb=scene_dict["scene_emb"],
            )
            scene_count += 1

            for clip_id in scene_dict["clip_ids"]:
                htvg.add_hierarchical_edge(clip_id, scene_dict["node_id"])
                hierarchical_edge_count += 1

    logger.info(
        f"[build_htvg]   Added {scene_count} scene TANs "
        f"and {hierarchical_edge_count} hierarchical edges."
    )


def _collect_clip_embs(
    clip_ids: List[str], htvg: HTVGraph
) -> np.ndarray:
    """Reconstruct clip embedding matrix from the FAISS flat index.

    Only works with ``IndexFlatIP`` (supports ``reconstruct``). Falls back to
    zero vectors if the index is an IVF type (which doesn't support reconstruct
    after training).

    Args:
        clip_ids: Ordered list of clip TAN node IDs.
        htvg: HTVGraph with ``_clip_index`` and ``_clip_id_list``.

    Returns:
        Float32 array of shape ``(N, clip_dim)``.
    """
    import faiss as faiss_module

    embs = np.zeros((len(clip_ids), htvg.clip_dim), dtype=np.float32)
    id_to_row = {nid: row for row, nid in enumerate(htvg._clip_id_list)}

    for i, clip_id in enumerate(clip_ids):
        row = id_to_row.get(clip_id, -1)
        if row < 0:
            continue
        try:
            vec = np.zeros(htvg.clip_dim, dtype=np.float32)
            htvg._clip_index.reconstruct(row, vec)
            embs[i] = vec
        except (RuntimeError, faiss_module.swigfaiss.FaissException):
            pass  # IVF doesn't support reconstruct; leave as zeros

    return embs
