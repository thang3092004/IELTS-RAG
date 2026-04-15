"""
videorag/htvg/aggregator.py
============================
TemporalTransformer and HierarchicalAggregator — the core novelty of the HTVG
architecture.

TemporalTransformer
-------------------
A learnable Transformer encoder with a prepended CLS token that aggregates a
variable-length sequence of clip-level ImageBind embeddings (d=1024) into a
single scene-level vector (d=768).  Architecture:

    Input  : (B, T, clip_dim=1024)   — padded clip embeddings
    + CLS  : (B, T+1, clip_dim)
    + PosEnc: sinusoidal, max_seq_len=64
    Encoder: 2-layer nn.TransformerEncoder, nhead=8, dim_ff=2048, dropout=0.1
    CLS out: (B, clip_dim)
    Proj   : Linear(clip_dim, scene_dim=768) + LayerNorm
    Output : (B, scene_dim=768)

HierarchicalAggregator
-----------------------
Groups consecutive clip TANs into scenes using one of two strategies:

1. *Fixed window* (default): every ``scene_window`` clips form a scene.
2. *Cosine-drop*: a new scene begins when the cosine similarity between
   adjacent clip embeddings falls below ``similarity_threshold``.

After boundary detection, it calls ``TemporalTransformer`` in batched mode
to produce scene-level embeddings.

Includes checkpoint save/load for 50-epoch fine-tuning support (Task spec).

Memory note
-----------
Sequences of up to 64 clips per scene are supported.  For very long scenes the
sequence is truncated to ``max_seq_len`` from both ends (kept first + last
``max_seq_len//2`` clips) to preserve boundary context.
"""

from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# Positional encoding
# ---------------------------------------------------------------------------

class _SinusoidalPositionalEncoding(nn.Module):
    """Fixed sinusoidal positional encoding.

    Args:
        d_model: Embedding dimensionality.
        max_seq_len: Maximum supported sequence length (including CLS).
        dropout: Dropout probability applied after adding position encoding.
    """

    def __init__(
        self, d_model: int, max_seq_len: int = 65, dropout: float = 0.1
    ) -> None:
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)

        pe = torch.zeros(max_seq_len, d_model)
        position = torch.arange(0, max_seq_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)  # (1, max_seq_len, d_model)
        self.register_buffer("pe", pe)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Add positional encoding to input.

        Args:
            x: Input tensor of shape ``(B, T, d_model)``.

        Returns:
            Tensor of the same shape with positional encoding added.
        """
        x = x + self.pe[:, : x.size(1)]
        return self.dropout(x)


# ---------------------------------------------------------------------------
# TemporalTransformer
# ---------------------------------------------------------------------------

class TemporalTransformer(nn.Module):
    """Aggregates clip-level visual embeddings into a scene-level representation.

    Args:
        clip_dim: Dimensionality of input clip embeddings (default: 1024).
        scene_dim: Dimensionality of the output scene embedding (default: 768).
        nhead: Number of attention heads.  Must divide ``clip_dim``.
        num_layers: Number of Transformer encoder layers.
        dim_feedforward: Hidden dimensionality of the feed-forward network.
        dropout: Dropout rate used in the Transformer and positional encoding.
        max_seq_len: Maximum number of clips per scene (excluding CLS token).
    """

    def __init__(
        self,
        clip_dim: int = 1024,
        scene_dim: int = 768,
        nhead: int = 8,
        num_layers: int = 2,
        dim_feedforward: int = 2048,
        dropout: float = 0.1,
        max_seq_len: int = 64,
    ) -> None:
        super().__init__()
        self.clip_dim = clip_dim
        self.scene_dim = scene_dim
        self.max_seq_len = max_seq_len

        # CLS token (learnable)
        self.cls_token = nn.Parameter(torch.randn(1, 1, clip_dim) * 0.02)

        self.pos_enc = _SinusoidalPositionalEncoding(
            d_model=clip_dim, max_seq_len=max_seq_len + 1, dropout=dropout
        )

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=clip_dim,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True,
            norm_first=True,  # pre-norm for stability
        )
        self.transformer = nn.TransformerEncoder(
            encoder_layer, num_layers=num_layers, enable_nested_tensor=False
        )

        self.projection = nn.Sequential(
            nn.Linear(clip_dim, scene_dim),
            nn.LayerNorm(scene_dim),
        )

    def forward(
        self,
        clip_embs: torch.Tensor,
        src_key_padding_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Forward pass: clips → scene embedding.

        Args:
            clip_embs: Padded clip embeddings of shape ``(B, T, clip_dim)``.
            src_key_padding_mask: Boolean mask of shape ``(B, T+1)`` where
                ``True`` means *ignore this position*.  The CLS position (index 0)
                is always ``False`` (unmasked).  Pass ``None`` if all clips in a
                batch are real (no padding).

        Returns:
            Scene embeddings of shape ``(B, scene_dim)``, L2-normalised.
        """
        B = clip_embs.size(0)

        # Prepend CLS token: (B, 1, clip_dim)
        cls_tokens = self.cls_token.expand(B, -1, -1)
        x = torch.cat([cls_tokens, clip_embs], dim=1)  # (B, T+1, clip_dim)

        # Positional encoding
        x = self.pos_enc(x)

        # Transformer encoder (key_padding_mask covers T+1 positions)
        x = self.transformer(x, src_key_padding_mask=src_key_padding_mask)

        # Extract CLS output
        cls_out = x[:, 0, :]  # (B, clip_dim)

        # Project to scene_dim and L2-normalise
        scene_emb = self.projection(cls_out)  # (B, scene_dim)
        scene_emb = F.normalize(scene_emb, dim=-1)
        return scene_emb


# ---------------------------------------------------------------------------
# HierarchicalAggregator
# ---------------------------------------------------------------------------

class HierarchicalAggregator:
    """Groups clips into scenes and aggregates them with TemporalTransformer.

    Args:
        model: Pretrained or randomly initialised ``TemporalTransformer``.
        scene_window: Fixed number of clips per scene (used when
            ``use_cosine_detection=False``).
        similarity_threshold: Cosine similarity below which a new scene
            boundary is declared (used when ``use_cosine_detection=True``).
        use_cosine_detection: If ``True``, use cosine-drop scene detection
            instead of fixed windows.
        device: PyTorch device string (``"cuda"`` or ``"cpu"``).
        batch_size: Aggregation batch size (number of scenes processed together).
    """

    def __init__(
        self,
        model: TemporalTransformer,
        scene_window: int = 5,
        similarity_threshold: float = 0.73,
        use_cosine_detection: bool = False,
        device: str = "cuda",
        batch_size: int = 16,
    ) -> None:
        self.model = model.to(device)
        self.model.eval()
        self.scene_window = scene_window
        self.similarity_threshold = similarity_threshold
        self.use_cosine_detection = use_cosine_detection
        self.device = device
        self.batch_size = batch_size

    # ------------------------------------------------------------------
    # Scene boundary detection
    # ------------------------------------------------------------------

    def detect_scene_boundaries(
        self, clip_embs: np.ndarray
    ) -> List[List[int]]:
        """Partition clip indices into scene groups.

        Args:
            clip_embs: Array of shape ``(N, clip_dim)`` containing
                L2-normalised clip embeddings in chronological order.

        Returns:
            List of lists where each inner list contains the 0-based clip
            indices that belong to one scene.
        """
        N = len(clip_embs)
        if N == 0:
            return []

        if not self.use_cosine_detection:
            # Fixed window strategy
            scenes = []
            for start in range(0, N, self.scene_window):
                scenes.append(list(range(start, min(start + self.scene_window, N))))
            return scenes

        # Cosine-drop strategy
        scenes: List[List[int]] = [[0]]
        for i in range(1, N):
            # cos similarity between consecutive clips (already L2-normalised)
            cos_sim = float(np.dot(clip_embs[i - 1], clip_embs[i]))
            if cos_sim < self.similarity_threshold:
                scenes.append([])
            scenes[-1].append(i)
        return scenes

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def aggregate(
        self,
        video_name: str,
        clip_embs: np.ndarray,
        clip_ids: List[str],
        time_ranges: List[str],
    ) -> List[Dict]:
        """Aggregate clips into scenes and return scene-level dicts.

        Args:
            video_name: Base name of the source video.
            clip_embs: Array of shape ``(N, clip_dim)`` in chronological order.
            clip_ids: List of clip TAN node IDs in the same order as ``clip_embs``.
            time_ranges: List of ``"start-end"`` strings for each clip.

        Returns:
            List of dicts, each with keys:
            ``node_id``, ``video_name``, ``scene_index``, ``time_range``,
            ``clip_ids``, ``scene_emb`` (numpy array of shape ``(scene_dim,)``).
        """
        if len(clip_embs) == 0:
            return []

        # Detect scene boundaries
        scene_groups = self.detect_scene_boundaries(clip_embs)

        scene_dicts = []
        # Batch scene sequences for efficient GPU inference
        for batch_start in range(0, len(scene_groups), self.batch_size):
            batch_groups = scene_groups[batch_start : batch_start + self.batch_size]
            scene_embs = self._batch_aggregate(clip_embs, batch_groups)

            for local_idx, (grp, scene_emb) in enumerate(
                zip(batch_groups, scene_embs)
            ):
                scene_idx = batch_start + local_idx
                scene_id = f"scene_{video_name}_{scene_idx}"
                this_clip_ids = [clip_ids[i] for i in grp]
                # Compute encompassing time range
                start_sec = _parse_time_range(time_ranges[grp[0]])[0]
                end_sec = _parse_time_range(time_ranges[grp[-1]])[1]
                tr = f"{start_sec}-{end_sec}"

                scene_dicts.append(
                    {
                        "node_id": scene_id,
                        "video_name": video_name,
                        "scene_index": str(scene_idx),
                        "time_range": tr,
                        "clip_ids": this_clip_ids,
                        "scene_emb": scene_emb,
                    }
                )
        return scene_dicts

    def _batch_aggregate(
        self, clip_embs: np.ndarray, scene_groups: List[List[int]]
    ) -> List[np.ndarray]:
        """Run TemporalTransformer on a batch of scene clip sequences.

        Args:
            clip_embs: All clip embeddings for the video (N, clip_dim).
            scene_groups: List of index lists, one per scene in the batch.

        Returns:
            List of scene embedding numpy arrays (each shape ``(scene_dim,)``).
        """
        max_T = min(
            self.model.max_seq_len,
            max(len(g) for g in scene_groups),
        )
        B = len(scene_groups)
        clip_dim = clip_embs.shape[1]

        padded = np.zeros((B, max_T, clip_dim), dtype=np.float32)
        # True = masked (padding), False = real clip
        mask = np.ones((B, max_T + 1), dtype=bool)
        mask[:, 0] = False  # CLS is always unmasked

        for b_idx, grp in enumerate(scene_groups):
            # Truncate long scenes symmetrically
            if len(grp) > max_T:
                half = max_T // 2
                grp = grp[:half] + grp[-(max_T - half):]
            embs = clip_embs[grp]  # (T_real, clip_dim)
            T_real = len(embs)
            padded[b_idx, :T_real] = embs
            mask[b_idx, 1 : T_real + 1] = False  # unmasked real clips

        t_padded = torch.from_numpy(padded).to(self.device)
        t_mask = torch.from_numpy(mask).to(self.device)

        with torch.no_grad():
            scene_embs = self.model(t_padded, src_key_padding_mask=t_mask)

        scene_embs = scene_embs.cpu().numpy()  # (B, scene_dim)
        return [scene_embs[i] for i in range(B)]

    # ------------------------------------------------------------------
    # Checkpoint management (for 50-epoch fine-tuning)
    # ------------------------------------------------------------------

    def save_checkpoint(
        self,
        checkpoint_dir: str,
        epoch: int,
        optimizer: Optional[torch.optim.Optimizer] = None,
        loss: Optional[float] = None,
    ) -> str:
        """Save a training checkpoint.

        Args:
            checkpoint_dir: Directory in which to save the checkpoint file.
            epoch: Current training epoch (0-indexed).
            optimizer: If provided, saves its state dict for resum ability.
            loss: Optional scalar training loss to record.

        Returns:
            Path to the saved checkpoint file.
        """
        os.makedirs(checkpoint_dir, exist_ok=True)
        ckpt_path = os.path.join(checkpoint_dir, f"epoch_{epoch:04d}.pt")
        state: Dict = {
            "epoch": epoch,
            "model_state_dict": self.model.state_dict(),
            "model_hparams": {
                "clip_dim": self.model.clip_dim,
                "scene_dim": self.model.scene_dim,
                "max_seq_len": self.model.max_seq_len,
            },
            "aggregator_config": {
                "scene_window": self.scene_window,
                "similarity_threshold": self.similarity_threshold,
                "use_cosine_detection": self.use_cosine_detection,
            },
        }
        if optimizer is not None:
            state["optimizer_state_dict"] = optimizer.state_dict()
        if loss is not None:
            state["loss"] = loss
        torch.save(state, ckpt_path)
        return ckpt_path

    @classmethod
    def load_checkpoint(
        cls,
        checkpoint_path: str,
        device: str = "cuda",
        **aggregator_kwargs,
    ) -> "HierarchicalAggregator":
        """Load an aggregator from a saved checkpoint.

        Args:
            checkpoint_path: Path to ``*.pt`` checkpoint file.
            device: Device to load the model onto.
            **aggregator_kwargs: Additional kwargs forwarded to ``__init__``
                (override stored config values if provided).

        Returns:
            Restored ``HierarchicalAggregator`` instance.
        """
        state = torch.load(checkpoint_path, map_location=device)
        hparams = state.get("model_hparams", {})
        model = TemporalTransformer(
            clip_dim=hparams.get("clip_dim", 1024),
            scene_dim=hparams.get("scene_dim", 768),
            max_seq_len=hparams.get("max_seq_len", 64),
        )
        model.load_state_dict(state["model_state_dict"])

        agg_cfg = state.get("aggregator_config", {})
        merged_cfg = {**agg_cfg, **aggregator_kwargs}
        return cls(model=model, device=device, **merged_cfg)

    def get_latest_checkpoint(self, checkpoint_dir: str) -> Optional[str]:
        """Return path to the highest-epoch checkpoint in a directory.

        Args:
            checkpoint_dir: Directory to search.

        Returns:
            Absolute path to the latest ``epoch_*.pt`` file, or ``None``.
        """
        if not os.path.isdir(checkpoint_dir):
            return None
        pts = sorted(
            [f for f in os.listdir(checkpoint_dir) if f.startswith("epoch_") and f.endswith(".pt")]
        )
        if pts:
            return os.path.join(checkpoint_dir, pts[-1])
        return None


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def _parse_time_range(time_range: str) -> Tuple[float, float]:
    """Parse ``"start-end"`` into a (start, end) float tuple.

    Args:
        time_range: String like ``"90-120"`` or ``"90.0-120.5"``.

    Returns:
        ``(start_seconds, end_seconds)`` floats.
    """
    parts = time_range.split("-")
    try:
        return float(parts[0]), float(parts[-1])
    except (IndexError, ValueError):
        return 0.0, 0.0
