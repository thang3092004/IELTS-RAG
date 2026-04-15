"""
videorag/htvg/graph.py
======================
HTVGraph — the unified Hierarchical Temporal-Visual Graph.

Wraps a ``networkx.DiGraph`` (the structural backbone) and three parallel
``faiss.IndexFlatIP`` indices (fast ANN retrieval for clip-TANs, scene-TANs,
and semantic nodes). Embeddings are stored **only in FAISS**, keeping the
GraphML file lean. Each graph node stores a ``faiss_row_id`` integer attribute
as the bridge.

Design notes
------------
* ``IndexFlatIP`` uses inner-product similarity on **L2-normalised** vectors,
  which is numerically equivalent to cosine similarity.
* When the total segment count exceeds AUTO_SWITCH_THRESHOLD (10 000), the
  index is automatically promoted to ``IndexIVFFlat`` with a sensible nprobe.
* All public methods are **synchronous**; async callers should wrap with
  ``asyncio.get_event_loop().run_in_executor(None, ...)`` if needed.
"""

from __future__ import annotations

import json
import os
import pickle
from typing import Dict, List, Optional, Tuple

import faiss
import networkx as nx
import numpy as np

from .schemas import (
    ClipTANNode,
    HTVGBuildMeta,
    SceneTANNode,
    SemanticNode,
)

# Number of segments above which we switch from exact to approximate search.
AUTO_SWITCH_THRESHOLD: int = 10_000
# IVF number of centroids — rule of thumb: sqrt(n).
_IVF_NLIST_FACTOR: float = 1.0
# Number of IVF probes at query time.
_IVF_NPROBE: int = 64


def _build_flat_index(dim: int) -> faiss.IndexFlatIP:
    """Build an exact inner-product FAISS index.

    Args:
        dim: Embedding dimensionality.

    Returns:
        A ``faiss.IndexFlatIP`` index ready for ``add()`` calls.
    """
    index = faiss.IndexFlatIP(dim)
    return index


def _promote_to_ivf(flat_index: faiss.IndexFlatIP, dim: int) -> faiss.IndexIVFFlat:
    """Promote a flat index to IVF for faster approximate search.

    Args:
        flat_index: Already-populated flat index (used as training data).
        dim: Embedding dimensionality.

    Returns:
        A trained ``faiss.IndexIVFFlat`` with all vectors from flat_index.
    """
    n = flat_index.ntotal
    nlist = max(1, int((_IVF_NLIST_FACTOR * n) ** 0.5))
    quantizer = faiss.IndexFlatIP(dim)
    ivf = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)
    # Reconstruct training vectors from flat index
    vectors = np.zeros((n, dim), dtype=np.float32)
    flat_index.reconstruct_n(0, n, vectors)
    ivf.train(vectors)
    ivf.add(vectors)
    ivf.nprobe = _IVF_NPROBE
    return ivf


class HTVGraph:
    """Unified Hierarchical Temporal-Visual Graph.

    Maintains four parallel data structures:
    1. ``_graph``: a ``networkx.DiGraph`` for structural traversal.
    2. ``_clip_index``: FAISS index for clip-level TAN embeddings (d=clip_dim).
    3. ``_scene_index``: FAISS index for scene-level TAN embeddings (d=scene_dim).
    4. ``_semantic_index``: FAISS index for entity text embeddings (d=semantic_dim).

    Each index has a paired ``_*_id_list`` mapping FAISS row → node ID string.

    Args:
        clip_dim: Dimensionality of clip visual embeddings (default ImageBind 1024).
        scene_dim: Dimensionality of aggregated scene embeddings (default 768).
        semantic_dim: Dimensionality of text/entity embeddings.
    """

    def __init__(
        self,
        clip_dim: int = 1024,
        scene_dim: int = 768,
        semantic_dim: int = 1536,
    ) -> None:
        self.clip_dim = clip_dim
        self.scene_dim = scene_dim
        self.semantic_dim = semantic_dim

        self._graph: nx.DiGraph = nx.DiGraph()

        # FAISS indices (start flat, auto-promoted on large corpora)
        self._clip_index: faiss.Index = _build_flat_index(clip_dim)
        self._scene_index: faiss.Index = _build_flat_index(scene_dim)
        self._semantic_index: faiss.Index = _build_flat_index(semantic_dim)

        # Row-ID bookkeeping (list index == FAISS row ID)
        self._clip_id_list: List[str] = []
        self._scene_id_list: List[str] = []
        self._semantic_id_list: List[str] = []

        # Build metadata (populated by HTVGStorage after a full build)
        self.build_meta: Optional[HTVGBuildMeta] = None

    # ------------------------------------------------------------------
    # Node insertion helpers
    # ------------------------------------------------------------------

    def add_clip_tan(
        self,
        node_id: str,
        video_name: str,
        segment_index: str,
        time_range: str,
        content: str,
        visual_emb: np.ndarray,
    ) -> None:
        """Add or update a clip-level Temporal Anchor Node.

        If the node already exists, its FAISS entry is **not** duplicated;
        only the graph attributes are refreshed.

        Args:
            node_id: Segment identifier ``"{video_name}_{segment_index}"``.
            video_name: Base name of the source video.
            segment_index: String integer index of the segment.
            time_range: ``"start-end"`` in seconds.
            content: Raw caption+transcript content string.
            visual_emb: 1-D float32 numpy array of shape ``(clip_dim,)``.
        """
        if self._graph.has_node(node_id):
            return  # incremental build — skip already-indexed nodes

        emb = _l2_normalize(visual_emb.astype(np.float32).reshape(1, -1))
        faiss_row_id = self._clip_index.ntotal
        self._clip_index.add(emb)
        self._clip_id_list.append(node_id)

        self._graph.add_node(
            node_id,
            node_type="tan_clip",
            tan_level="clip",
            video_name=video_name,
            segment_index=segment_index,
            time_range=time_range,
            content=content,
            faiss_row_id=faiss_row_id,
        )

    def add_scene_tan(
        self,
        node_id: str,
        video_name: str,
        scene_index: str,
        time_range: str,
        clip_ids: List[str],
        scene_emb: np.ndarray,
    ) -> None:
        """Add or update a scene-level Temporal Anchor Node.

        Args:
            node_id: Scene identifier ``"scene_{video_name}_{scene_index}"``.
            video_name: Base name of the source video.
            scene_index: Sequential scene index within the video.
            time_range: ``"start-end"`` covering all constituent clips.
            clip_ids: List of constituent clip TAN node IDs.
            scene_emb: 1-D float32 numpy array of shape ``(scene_dim,)``.
        """
        if self._graph.has_node(node_id):
            return

        emb = _l2_normalize(scene_emb.astype(np.float32).reshape(1, -1))
        faiss_row_id = self._scene_index.ntotal
        self._scene_index.add(emb)
        self._scene_id_list.append(node_id)

        self._graph.add_node(
            node_id,
            node_type="tan_scene",
            tan_level="scene",
            video_name=video_name,
            scene_index=scene_index,
            time_range=time_range,
            clip_ids=",".join(clip_ids),
            faiss_row_id=faiss_row_id,
        )

    def add_semantic_node(
        self,
        node_id: str,
        entity_type: str,
        description: str,
        source_id: str,
        text_emb: np.ndarray,
    ) -> None:
        """Add or update a semantic (entity) node.

        Args:
            node_id: Upper-cased entity name, e.g. ``"CLIMATE CHANGE"``.
            entity_type: LLM-assigned category, e.g. ``"CONCEPT"``.
            description: Merged entity description.
            source_id: ``<GRAPH_FIELD_SEP>``-joined chunk IDs.
            text_emb: 1-D float32 numpy array of shape ``(semantic_dim,)``.
        """
        if self._graph.has_node(node_id):
            # Allow attribute refresh (description can grow)
            self._graph.nodes[node_id]["description"] = description
            self._graph.nodes[node_id]["source_id"] = source_id
            return

        emb = _l2_normalize(text_emb.astype(np.float32).reshape(1, -1))
        faiss_row_id = self._semantic_index.ntotal
        self._semantic_index.add(emb)
        self._semantic_id_list.append(node_id)

        self._graph.add_node(
            node_id,
            node_type="semantic",
            entity_type=entity_type,
            description=description,
            source_id=source_id,
            faiss_row_id=faiss_row_id,
        )

    # ------------------------------------------------------------------
    # Edge insertion helpers
    # ------------------------------------------------------------------

    def add_temporal_edge(
        self, src_id: str, tgt_id: str, delta_seconds: float = 0.0
    ) -> None:
        """Add a directed temporal edge between two clip TANs.

        Args:
            src_id: Source clip TAN node ID (at time *t*).
            tgt_id: Target clip TAN node ID (at time *t+1*).
            delta_seconds: Time gap between clips in seconds.
        """
        self._graph.add_edge(
            src_id, tgt_id, edge_type="temporal", delta_seconds=delta_seconds
        )

    def add_cross_modal_edge(
        self, semantic_id: str, clip_id: str, confidence: float = 1.0
    ) -> None:
        """Add a directed cross-modal edge from a semantic node to a clip TAN.

        Args:
            semantic_id: Source ``SemanticNode.node_id``.
            clip_id: Target ``ClipTANNode.node_id``.
            confidence: Grounding confidence score (0..1).
        """
        # Avoid duplicate edges
        if self._graph.has_edge(semantic_id, clip_id):
            return
        self._graph.add_edge(
            semantic_id, clip_id, edge_type="cross_modal", confidence=confidence
        )

    def add_semantic_edge(
        self,
        src_id: str,
        tgt_id: str,
        weight: float = 1.0,
        description: str = "",
        source_id: str = "",
    ) -> None:
        """Add an undirected semantic edge (stored as two directed edges).

        Args:
            src_id: First entity node ID.
            tgt_id: Second entity node ID.
            weight: Relation weight from LLM extraction.
            description: Natural-language description of the relationship.
            source_id: Chunk IDs supporting this relation.
        """
        data = dict(
            edge_type="semantic",
            weight=weight,
            description=description,
            source_id=source_id,
        )
        self._graph.add_edge(src_id, tgt_id, **data)
        self._graph.add_edge(tgt_id, src_id, **data)

    def add_hierarchical_edge(self, clip_id: str, scene_id: str) -> None:
        """Add a directed hierarchical edge from a clip TAN to its scene TAN.

        Args:
            clip_id: Source ``ClipTANNode.node_id``.
            scene_id: Target ``SceneTANNode.node_id``.
        """
        if self._graph.has_edge(clip_id, scene_id):
            return
        self._graph.add_edge(clip_id, scene_id, edge_type="hierarchical")

    # ------------------------------------------------------------------
    # FAISS query helpers
    # ------------------------------------------------------------------

    def search_clip_index(
        self, query_emb: np.ndarray, top_k: int
    ) -> List[Tuple[str, float]]:
        """Search clip TAN FAISS index with a query embedding.

        Args:
            query_emb: Query vector of shape ``(clip_dim,)`` or ``(1, clip_dim)``.
            top_k: Max number of results.

        Returns:
            List of ``(node_id, score)`` tuples sorted by descending similarity.
        """
        return self._search_index(
            self._clip_index, self._clip_id_list, query_emb, top_k
        )

    def search_scene_index(
        self, query_emb: np.ndarray, top_k: int
    ) -> List[Tuple[str, float]]:
        """Search scene TAN FAISS index.

        Args:
            query_emb: Query vector of shape ``(scene_dim,)`` or ``(1, scene_dim)``.
            top_k: Max number of results.

        Returns:
            List of ``(node_id, score)`` tuples sorted by descending similarity.
        """
        return self._search_index(
            self._scene_index, self._scene_id_list, query_emb, top_k
        )

    def search_semantic_index(
        self, query_emb: np.ndarray, top_k: int
    ) -> List[Tuple[str, float]]:
        """Search semantic (entity) FAISS index.

        Args:
            query_emb: Query vector of shape ``(semantic_dim,)`` or ``(1, semantic_dim)``.
            top_k: Max number of results.

        Returns:
            List of ``(node_id, score)`` tuples sorted by descending similarity.
        """
        return self._search_index(
            self._semantic_index, self._semantic_id_list, query_emb, top_k
        )

    @staticmethod
    def _search_index(
        index: faiss.Index,
        id_list: List[str],
        query_emb: np.ndarray,
        top_k: int,
    ) -> List[Tuple[str, float]]:
        """Internal search helper.

        Args:
            index: FAISS index to query.
            id_list: ID list mapping row → node ID.
            query_emb: Query embedding array.
            top_k: Max number of results.

        Returns:
            List of ``(node_id, score)`` pairs.
        """
        if index.ntotal == 0:
            return []
        q = _l2_normalize(query_emb.astype(np.float32).reshape(1, -1))
        actual_k = min(top_k, index.ntotal)
        scores, indices = index.search(q, actual_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(id_list):
                continue
            results.append((id_list[idx], float(score)))
        return results

    # ------------------------------------------------------------------
    # Auto-promote indices when scale demands it
    # ------------------------------------------------------------------

    def maybe_promote_indices(self) -> None:
        """Promote flat FAISS indices to IVF when corpus exceeds threshold.

        This is called automatically at the end of :func:`build_htvg`. It is
        idempotent: already-promoted indices are left unchanged.
        """
        if (
            self._clip_index.ntotal > AUTO_SWITCH_THRESHOLD
            and isinstance(self._clip_index, faiss.IndexFlatIP)
        ):
            self._clip_index = _promote_to_ivf(self._clip_index, self.clip_dim)

        if (
            self._scene_index.ntotal > AUTO_SWITCH_THRESHOLD
            and isinstance(self._scene_index, faiss.IndexFlatIP)
        ):
            self._scene_index = _promote_to_ivf(self._scene_index, self.scene_dim)

        if (
            self._semantic_index.ntotal > AUTO_SWITCH_THRESHOLD
            and isinstance(self._semantic_index, faiss.IndexFlatIP)
        ):
            self._semantic_index = _promote_to_ivf(
                self._semantic_index, self.semantic_dim
            )

    # ------------------------------------------------------------------
    # Property accessors
    # ------------------------------------------------------------------

    def num_nodes(self) -> int:
        """Return total node count across all types."""
        return self._graph.number_of_nodes()

    def num_edges(self) -> int:
        """Return total directed edge count."""
        return self._graph.number_of_edges()

    def get_node(self, node_id: str) -> Optional[Dict]:
        """Return node attribute dict or None.

        Args:
            node_id: Node identifier string.

        Returns:
            Attribute dict if node exists, else ``None``.
        """
        if self._graph.has_node(node_id):
            return dict(self._graph.nodes[node_id])
        return None

    def get_successors_by_edge_type(
        self, node_id: str, edge_type: str
    ) -> List[str]:
        """Return neighbour IDs reachable via edges of a given type.

        Args:
            node_id: Source node ID.
            edge_type: One of ``"temporal"``, ``"cross_modal"``, ``"hierarchical"``,
                ``"semantic"``.

        Returns:
            List of reachable node IDs.
        """
        result = []
        for _, tgt, data in self._graph.out_edges(node_id, data=True):
            if data.get("edge_type") == edge_type:
                result.append(tgt)
        return result

    def get_predecessors_by_edge_type(
        self, node_id: str, edge_type: str
    ) -> List[str]:
        """Return node IDs that have an edge of the given type pointing *to* node_id.

        Args:
            node_id: Target node ID.
            edge_type: Edge type filter.

        Returns:
            List of predecessor node IDs.
        """
        result = []
        for src, _, data in self._graph.in_edges(node_id, data=True):
            if data.get("edge_type") == edge_type:
                result.append(src)
        return result

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, save_dir: str) -> None:
        """Persist the HTVG to ``save_dir``.

        Files written:
        - ``graph_htvg.graphml``: NetworkX DiGraph (no embedding vectors).
        - ``htvg_clip.index``: FAISS clip index.
        - ``htvg_scene.index``: FAISS scene index.
        - ``htvg_semantic.index``: FAISS semantic index.
        - ``htvg_id_maps.json``: Mapping FAISS rows → node IDs + dimensions.
        - ``htvg_meta.json``: Build metadata (if available).

        Args:
            save_dir: Directory path (created if not exists).
        """
        os.makedirs(save_dir, exist_ok=True)

        nx.write_graphml(self._graph, os.path.join(save_dir, "graph_htvg.graphml"))
        faiss.write_index(
            self._clip_index, os.path.join(save_dir, "htvg_clip.index")
        )
        faiss.write_index(
            self._scene_index, os.path.join(save_dir, "htvg_scene.index")
        )
        faiss.write_index(
            self._semantic_index, os.path.join(save_dir, "htvg_semantic.index")
        )

        id_maps = {
            "clip_id_list": self._clip_id_list,
            "scene_id_list": self._scene_id_list,
            "semantic_id_list": self._semantic_id_list,
            "clip_dim": self.clip_dim,
            "scene_dim": self.scene_dim,
            "semantic_dim": self.semantic_dim,
        }
        with open(os.path.join(save_dir, "htvg_id_maps.json"), "w") as f:
            json.dump(id_maps, f, indent=2)

        if self.build_meta is not None:
            with open(os.path.join(save_dir, "htvg_meta.json"), "w") as f:
                json.dump(dict(self.build_meta), f, indent=2)

    @classmethod
    def load(cls, save_dir: str) -> "HTVGraph":
        """Load an HTVG from a previously saved directory.

        Args:
            save_dir: Directory containing HTVG files (as written by ``save()``).

        Returns:
            Populated ``HTVGraph`` instance.

        Raises:
            FileNotFoundError: If required files are missing.
        """
        id_map_path = os.path.join(save_dir, "htvg_id_maps.json")
        if not os.path.exists(id_map_path):
            raise FileNotFoundError(
                f"htvg_id_maps.json not found in {save_dir}. "
                "Run build_htvg() first."
            )
        with open(id_map_path) as f:
            id_maps = json.load(f)

        obj = cls(
            clip_dim=id_maps["clip_dim"],
            scene_dim=id_maps["scene_dim"],
            semantic_dim=id_maps["semantic_dim"],
        )
        obj._clip_id_list = id_maps["clip_id_list"]
        obj._scene_id_list = id_maps["scene_id_list"]
        obj._semantic_id_list = id_maps["semantic_id_list"]

        graph_path = os.path.join(save_dir, "graph_htvg.graphml")
        if os.path.exists(graph_path):
            obj._graph = nx.read_graphml(graph_path)

        for attr, fname in [
            ("_clip_index", "htvg_clip.index"),
            ("_scene_index", "htvg_scene.index"),
            ("_semantic_index", "htvg_semantic.index"),
        ]:
            fpath = os.path.join(save_dir, fname)
            if os.path.exists(fpath):
                setattr(obj, attr, faiss.read_index(fpath))

        meta_path = os.path.join(save_dir, "htvg_meta.json")
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                obj.build_meta = json.load(f)

        return obj


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def _l2_normalize(x: np.ndarray) -> np.ndarray:
    """L2-normalise a 2-D float32 array row-wise.

    Args:
        x: Array of shape ``(n, d)``.

    Returns:
        Row-wise L2-normalised array of the same shape.
    """
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)  # avoid divide-by-zero
    return (x / norms).astype(np.float32)
