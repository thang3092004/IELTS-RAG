"""
videorag/_storage/htvg_storage.py
==================================
``HTVGStorage`` — a ``StorageNameSpace`` subclass that manages the lifecycle
of the Hierarchical Temporal-Visual Graph on disk.

Responsibilities
----------------
* Initialise (or load) the ``HTVGraph`` and ``HierarchicalAggregator`` from
  ``{working_dir}/htvg/``.
* Expose ``build_htvg()`` as an async coroutine wired to the VideoRAG ``ainsert``
  pipeline.
* Save all HTVG artefacts on ``index_done_callback()``.
* Provide a ``query()`` convenience method that delegates to ``async_query_htvg``.

The storage class is intentionally thin — all complex logic lives in the
``videorag.htvg`` package modules.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import networkx as nx
import numpy as np

from ..base import StorageNameSpace
from ..htvg import (
    HTVGraph,
    HTVGSubgraph,
    HierarchicalAggregator,
    TemporalTransformer,
    async_query_htvg,
    build_htvg,
)

logger = logging.getLogger("nano-graphrag")

# Default TemporalTransformer hyper-parameters (can be overridden via global_config)
_DEFAULT_CLIP_DIM: int = 1024
_DEFAULT_SCENE_DIM: int = 768
_DEFAULT_SCENE_WINDOW: int = 5


@dataclass
class HTVGStorage(StorageNameSpace):
    """Persistent storage wrapper for the Hierarchical Temporal-Visual Graph.

    Args:
        namespace: Storage namespace (default: ``"htvg"``).
        global_config: VideoRAG global configuration dict (from ``asdict(vrag)``).
    """

    def __post_init__(self) -> None:
        self._save_dir = os.path.join(
            self.global_config["working_dir"], "htvg"
        )

        clip_dim: int = self.global_config.get("video_embedding_dim", _DEFAULT_CLIP_DIM)
        scene_dim: int = _DEFAULT_SCENE_DIM
        semantic_dim: int = self.global_config.get(
            "llm", {}
        ).get("embedding_dim", 1536)  # default matches text-embedding-3-small

        # --- Load or initialise HTVGraph ---
        if os.path.isfile(os.path.join(self._save_dir, "htvg_id_maps.json")):
            logger.info(f"[HTVGStorage] Loading HTVG from {self._save_dir}")
            self._htvg = HTVGraph.load(self._save_dir)
        else:
            logger.info("[HTVGStorage] Initialising new HTVGraph")
            self._htvg = HTVGraph(
                clip_dim=clip_dim,
                scene_dim=scene_dim,
                semantic_dim=semantic_dim,
            )

        # --- Load or initialise HierarchicalAggregator ---
        device = "cuda" if self._cuda_available() else "cpu"
        self._aggregator = self._load_or_init_aggregator(
            clip_dim=clip_dim,
            scene_dim=scene_dim,
            device=device,
        )

    # ------------------------------------------------------------------
    # StorageNameSpace callbacks
    # ------------------------------------------------------------------

    async def index_done_callback(self) -> None:
        """Persist the HTVG to disk after indexing completes."""
        if self._htvg is not None:
            self._htvg.save(self._save_dir)
            logger.info(f"[HTVGStorage] Saved HTVG to {self._save_dir}")

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
        """Trigger HTVG construction / incremental update.

        Args:
            video_segments_data: ``video_segments._data``.
            existing_entity_graph: ``chunk_entity_relation_graph._graph``.
            text_chunks_data: ``text_chunks._data``.
            video_segment_feature_vdb: ``NanoVectorDBVideoSegmentStorage`` instance.
            text_embedding_func: Async embedding callable.
        """
        semantic_dim: int = self.global_config.get(
            "llm", {}
        ).get("embedding_dim", self._htvg.semantic_dim)

        self._htvg = await build_htvg(
            video_segments_data=video_segments_data,
            existing_entity_graph=existing_entity_graph,
            text_chunks_data=text_chunks_data,
            video_segment_feature_vdb=video_segment_feature_vdb,
            text_embedding_func=text_embedding_func,
            aggregator=self._aggregator,
            htvg=self._htvg,
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
        clip_embedding_func: Optional[Any] = None,
    ) -> HTVGSubgraph:
        """Query the HTVG and return a rich subgraph.

        Args:
            query: Natural-language query string.
            text_embedding_func: Async callable for text embeddings.
            top_k: Number of candidates per FAISS search step.
            temporal_context_hops: Temporal BFS expansion hops.
            clip_embedding_func: Optional callable for ImageBind text embeddings.

        Returns:
            ``HTVGSubgraph`` with retrieved evidence.
        """
        return await async_query_htvg(
            query=query,
            htvg=self._htvg,
            text_embedding_func=text_embedding_func,
            clip_embedding_func=clip_embedding_func,
            top_k=top_k,
            temporal_context_hops=temporal_context_hops,
        )

    # ------------------------------------------------------------------
    # Aggregator checkpoint helpers (for fine-tuning workflow)
    # ------------------------------------------------------------------

    def save_aggregator_checkpoint(
        self,
        epoch: int,
        optimizer=None,
        loss: Optional[float] = None,
    ) -> str:
        """Save a fine-tuning checkpoint for the TemporalTransformer.

        Args:
            epoch: Current epoch index.
            optimizer: Optional torch optimizer (state dict saved if provided).
            loss: Optional scalar loss value.

        Returns:
            Path to saved ``.pt`` checkpoint file.
        """
        ckpt_dir = os.path.join(self._save_dir, "checkpoints")
        return self._aggregator.save_checkpoint(ckpt_dir, epoch, optimizer, loss)

    def load_aggregator_checkpoint(self, checkpoint_path: Optional[str] = None) -> None:
        """Load the latest (or specified) fine-tuning checkpoint.

        Args:
            checkpoint_path: Explicit path to a ``.pt`` file.  If ``None``,
                loads the highest-epoch checkpoint from the default directory.
        """
        ckpt_dir = os.path.join(self._save_dir, "checkpoints")
        if checkpoint_path is None:
            checkpoint_path = self._aggregator.get_latest_checkpoint(ckpt_dir)
        if checkpoint_path and os.path.isfile(checkpoint_path):
            device = "cuda" if self._cuda_available() else "cpu"
            self._aggregator = HierarchicalAggregator.load_checkpoint(
                checkpoint_path, device=device
            )
            # Update HTVG's stored checkpoint path in meta
            if self._htvg.build_meta is not None:
                self._htvg.build_meta["aggregator_checkpoint"] = checkpoint_path
            logger.info(f"[HTVGStorage] Loaded aggregator checkpoint: {checkpoint_path}")
        else:
            logger.warning("[HTVGStorage] No checkpoint found to load.")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def htvg(self) -> HTVGraph:
        """The underlying ``HTVGraph`` instance."""
        return self._htvg

    @property
    def aggregator(self) -> HierarchicalAggregator:
        """The underlying ``HierarchicalAggregator`` instance."""
        return self._aggregator

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_or_init_aggregator(
        self, clip_dim: int, scene_dim: int, device: str
    ) -> HierarchicalAggregator:
        """Load the aggregator from checkpoint if available, else init fresh.

        Args:
            clip_dim: Input embedding dimensionality for TemporalTransformer.
            scene_dim: Output embedding dimensionality.
            device: Torch device string.

        Returns:
            Initialised ``HierarchicalAggregator``.
        """
        ckpt_dir = os.path.join(self._save_dir, "checkpoints")
        # Create a temporary aggregator just to call get_latest_checkpoint
        tmp_model = TemporalTransformer(clip_dim=clip_dim, scene_dim=scene_dim)
        tmp_agg = HierarchicalAggregator(model=tmp_model, device=device)
        latest = tmp_agg.get_latest_checkpoint(ckpt_dir)

        if latest:
            logger.info(f"[HTVGStorage] Loading aggregator checkpoint: {latest}")
            return HierarchicalAggregator.load_checkpoint(latest, device=device)

        # No checkpoint — fresh model
        model = TemporalTransformer(clip_dim=clip_dim, scene_dim=scene_dim)
        scene_window: int = self.global_config.get("htvg_scene_window", _DEFAULT_SCENE_WINDOW)
        return HierarchicalAggregator(model=model, device=device, scene_window=scene_window)

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
