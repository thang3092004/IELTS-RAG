"""
videorag/_storage/tvg_storage.py
==================================
``TVGStorage`` — a ``StorageNameSpace`` subclass that manages the lifecycle
of the Temporal-Visual Graph on disk.

Responsibilities
----------------
* Initialise (or load) the ``TVGraph`` from ``{working_dir}/tvg/``.
* Expose ``build_tvg()`` as an async coroutine wired to the VideoRAG ``ainsert``
  pipeline.
* Save all TVG artefacts on ``index_done_callback()``.
* Provide a ``query()`` convenience method that delegates to ``async_query_tvg``.

The storage class is intentionally thin — all complex logic lives in the
``videorag.tvg`` package modules.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import networkx as nx

from ..base import StorageNameSpace
from ..tvg import (
    TVGraph,
    TVGSubgraph,
    async_query_tvg,
    build_tvg,
)

logger = logging.getLogger("nano-graphrag")

# Default TVGraph hyper-parameters (can be overridden via global_config)
_DEFAULT_TAN_DIM: int = 1024


@dataclass
class TVGStorage(StorageNameSpace):
    """Persistent storage wrapper for the Temporal-Visual Graph.

    Args:
        namespace: Storage namespace (default: ``"tvg"``).
        global_config: VideoRAG global configuration dict (from ``asdict(vrag)``).
    """

    def __post_init__(self) -> None:
        self._save_dir = os.path.join(
            self.global_config["working_dir"], "tvg"
        )

        tan_dim: int = self.global_config.get("video_embedding_dim", _DEFAULT_TAN_DIM)
        semantic_dim: int = self.global_config.get(
            "llm", {}
        ).get("embedding_dim", 1536)  # default matches text-embedding-3-small

        # --- Load or initialise TVGraph ---
        if os.path.isfile(os.path.join(self._save_dir, "tvg_id_maps.json")):
            logger.info(f"[TVGStorage] Loading TVG from {self._save_dir}")
            self._tvg = TVGraph.load(self._save_dir)
        else:
            logger.info("[TVGStorage] Initialising new TVGraph")
            self._tvg = TVGraph(
                tan_dim=tan_dim,
                semantic_dim=semantic_dim,
            )

    # ------------------------------------------------------------------
    # StorageNameSpace callbacks
    # ------------------------------------------------------------------

    async def index_done_callback(self) -> None:
        """Persist the TVG to disk after indexing completes."""
        if self._tvg is not None:
            self._tvg.save(self._save_dir)
            logger.info(f"[TVGStorage] Saved TVG to {self._save_dir}")

    # ------------------------------------------------------------------
    # Build interface (called from VideoRAG.ainsert)
    # ------------------------------------------------------------------

    async def build(
        self,
        video_segments_data: Dict[str, Dict[str, Dict]],
        existing_entity_graph: nx.Graph,
        text_chunks_data: Dict[str, Dict],
        video_segment_feature_vdb: Any,
        text_embedding_func: Any,
    ) -> None:
        """Trigger TVG construction / incremental update.

        Args:
            video_segments_data: ``video_segments._data``.
            existing_entity_graph: ``chunk_entity_relation_graph._graph``.
            text_chunks_data: ``text_chunks._data``.
            video_segment_feature_vdb: ``NanoVectorDBVideoSegmentStorage`` instance.
            text_embedding_func: Async embedding callable.
        """
        semantic_dim: int = self.global_config.get(
            "llm", {}
        ).get("embedding_dim", self._tvg.semantic_dim)

        self._tvg = await build_tvg(
            video_segments_data=video_segments_data,
            existing_entity_graph=existing_entity_graph,
            text_chunks_data=text_chunks_data,
            video_segment_feature_vdb=video_segment_feature_vdb,
            text_embedding_func=text_embedding_func,
            tvg=self._tvg,
            working_dir=self.global_config["working_dir"],
            semantic_dim=semantic_dim,
        )

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    async def query(
        self,
        query: str,
        text_embedding_func: Any,
        top_k: int = 8,
        temporal_context_hops: int = 2,
        tan_embedding_func: Optional[Any] = None,
        visual_query: Optional[str] = None,
    ) -> TVGSubgraph:
        """Query the TVG and return a rich subgraph.

        Args:
            query: Natural-language query string.
            text_embedding_func: Async callable for text embeddings.
            top_k: Number of candidates per FAISS search step.
            temporal_context_hops: Temporal BFS expansion hops.
            tan_embedding_func: Optional callable for ImageBind text embeddings.

        Returns:
            ``TVGSubgraph`` with retrieved evidence.
        """
        return await async_query_tvg(
            query=query,
            tvg=self._tvg,
            text_embedding_func=text_embedding_func,
            tan_embedding_func=tan_embedding_func,
            top_k=top_k,
            temporal_context_hops=temporal_context_hops,
            visual_query=visual_query,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def tvg(self) -> TVGraph:
        """The underlying ``TVGraph`` instance."""
        return self._tvg

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cuda_available() -> bool:
        """Check whether a CUDA device is available.

        Returns:
            ``True`` if at least one CUDA device is available.
        """
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
