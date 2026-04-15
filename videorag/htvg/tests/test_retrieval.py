"""
videorag/htvg/tests/test_retrieval.py
=======================================
Unit tests for the HTVG retrieval API (``query_htvg`` and ``async_query_htvg``).

All tests use synthetic graph data and do NOT require GPU or network access.

Usage:
    python -m pytest videorag/htvg/tests/test_retrieval.py -v
"""

import asyncio
from typing import List, Tuple

import numpy as np
import pytest

from videorag.htvg.graph import HTVGraph
from videorag.htvg.retrieval import (
    query_htvg,
    async_query_htvg,
    _expand_temporal_context,
    _sort_segment_ids,
    _collect_subgraph_edges,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers to build a small synthetic HTVG
# ─────────────────────────────────────────────────────────────────────────────

CLIP_DIM = 16
SCENE_DIM = 8
SEM_DIM = 8


def _rand_emb(dim: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v


def _build_synthetic_htvg() -> Tuple[HTVGraph, np.ndarray, np.ndarray]:
    """
    Graph structure:
        Semantic: ENT_A, ENT_B
        Clips:    video_test_0 … video_test_4 (5 clips)
        Scenes:   scene_video_test_0 (clips 0-2), scene_video_test_1 (clips 3-4)
        Edges:
          tempo:   0→1→2→3→4
          cross:   ENT_A → video_test_0, video_test_1
                   ENT_B → video_test_3
          hier:    0→scene_0, 1→scene_0, 2→scene_0
                   3→scene_1, 4→scene_1
          semantic: ENT_A ↔ ENT_B

    Returns:
        (htvg, ent_a_emb, ent_b_emb) so tests can pass matching query vectors.
    """
    htvg = HTVGraph(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, semantic_dim=SEM_DIM)

    # Clip TANs
    clip_embs = {f"video_test_{i}": _rand_emb(CLIP_DIM, seed=i) for i in range(5)}
    for i in range(5):
        cid = f"video_test_{i}"
        htvg.add_clip_tan(cid, "video_test", str(i), f"{i*30}-{(i+1)*30}", f"content_{i}", clip_embs[cid])

    # Temporal edges
    for i in range(4):
        htvg.add_temporal_edge(f"video_test_{i}", f"video_test_{i+1}")

    # Scene TANs
    scene0_emb = _rand_emb(SCENE_DIM, seed=99)
    htvg.add_scene_tan("scene_video_test_0", "video_test", "0", "0-90",
                        ["video_test_0", "video_test_1", "video_test_2"], scene0_emb)
    scene1_emb = _rand_emb(SCENE_DIM, seed=100)
    htvg.add_scene_tan("scene_video_test_1", "video_test", "1", "90-150",
                        ["video_test_3", "video_test_4"], scene1_emb)

    # Hierarchical edges
    for i in range(3):
        htvg.add_hierarchical_edge(f"video_test_{i}", "scene_video_test_0")
    for i in range(3, 5):
        htvg.add_hierarchical_edge(f"video_test_{i}", "scene_video_test_1")

    # Semantic nodes
    ent_a_emb = _rand_emb(SEM_DIM, seed=10)
    ent_b_emb = _rand_emb(SEM_DIM, seed=11)
    htvg.add_semantic_node("ENT_A", "CONCEPT", "concept A", "chunk-1", ent_a_emb)
    htvg.add_semantic_node("ENT_B", "PERSON", "person B", "chunk-2", ent_b_emb)

    # Semantic edge
    htvg.add_semantic_edge("ENT_A", "ENT_B", weight=1.0)

    # Cross-modal edges
    htvg.add_cross_modal_edge("ENT_A", "video_test_0")
    htvg.add_cross_modal_edge("ENT_A", "video_test_1")
    htvg.add_cross_modal_edge("ENT_B", "video_test_3")

    return htvg, ent_a_emb, ent_b_emb


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def synthetic_htvg_fixture():
    return _build_synthetic_htvg()


class TestQueryHTVG:
    def test_returns_htcg_subgraph_keys(self, synthetic_htvg_fixture):
        htvg, ent_a_emb, _ = synthetic_htvg_fixture
        result = query_htvg(
            query_semantic_emb=ent_a_emb,
            query_clip_emb=None,
            htvg=htvg,
            top_k=2,
            temporal_context_hops=1,
            query="test",
        )
        for key in ["semantic_nodes", "clip_tans", "scene_tans", "edges", "segment_ids"]:
            assert key in result

    def test_semantic_hit_ent_a(self, synthetic_htvg_fixture):
        htvg, ent_a_emb, _ = synthetic_htvg_fixture
        result = query_htvg(
            query_semantic_emb=ent_a_emb,
            query_clip_emb=None,
            htvg=htvg,
            top_k=1,
            temporal_context_hops=0,
        )
        sem_ids = [n["node_id"] for n in result["semantic_nodes"]]
        assert "ENT_A" in sem_ids

    def test_cross_modal_clips_retrieved(self, synthetic_htvg_fixture):
        htvg, ent_a_emb, _ = synthetic_htvg_fixture
        result = query_htvg(
            query_semantic_emb=ent_a_emb,
            query_clip_emb=None,
            htvg=htvg,
            top_k=1,
            temporal_context_hops=0,
        )
        clip_ids = {c["node_id"] for c in result["clip_tans"]}
        # ENT_A is cross-modal linked to video_test_0 and video_test_1
        assert "video_test_0" in clip_ids
        assert "video_test_1" in clip_ids

    def test_temporal_context_expansion(self, synthetic_htvg_fixture):
        htvg, ent_a_emb, _ = synthetic_htvg_fixture
        result = query_htvg(
            query_semantic_emb=ent_a_emb,
            query_clip_emb=None,
            htvg=htvg,
            top_k=1,
            temporal_context_hops=2,  # should pull in video_test_2 as neighbour
        )
        clip_ids = {c["node_id"] for c in result["clip_tans"]}
        assert "video_test_2" in clip_ids

    def test_scene_tans_populated(self, synthetic_htvg_fixture):
        htvg, ent_a_emb, _ = synthetic_htvg_fixture
        result = query_htvg(
            query_semantic_emb=ent_a_emb,
            query_clip_emb=None,
            htvg=htvg,
            top_k=1,
            temporal_context_hops=0,
        )
        scene_ids = {s["node_id"] for s in result["scene_tans"]}
        assert "scene_video_test_0" in scene_ids

    def test_segment_ids_sorted(self, synthetic_htvg_fixture):
        htvg, ent_a_emb, _ = synthetic_htvg_fixture
        result = query_htvg(
            query_semantic_emb=ent_a_emb,
            query_clip_emb=None,
            htvg=htvg,
            top_k=2,
            temporal_context_hops=2,
        )
        seg_ids = result["segment_ids"]
        # All should belong to video_test; should be sorted by index
        indices = [int(s.split("_")[-1]) for s in seg_ids]
        assert indices == sorted(indices)

    def test_edges_all_within_subgraph(self, synthetic_htvg_fixture):
        htvg, ent_a_emb, _ = synthetic_htvg_fixture
        result = query_htvg(
            query_semantic_emb=ent_a_emb,
            query_clip_emb=None,
            htvg=htvg,
            top_k=2,
            temporal_context_hops=1,
        )
        all_node_ids = (
            {n["node_id"] for n in result["semantic_nodes"]}
            | {c["node_id"] for c in result["clip_tans"]}
            | {s["node_id"] for s in result["scene_tans"]}
        )
        for edge in result["edges"]:
            assert edge["src_id"] in all_node_ids or edge["tgt_id"] in all_node_ids

    def test_provenance_paths_non_empty(self, synthetic_htvg_fixture):
        htvg, ent_a_emb, _ = synthetic_htvg_fixture
        result = query_htvg(
            query_semantic_emb=ent_a_emb,
            query_clip_emb=None,
            htvg=htvg,
            top_k=1,
            temporal_context_hops=0,
        )
        assert len(result["provenance_paths"]) > 0
        # Paths should contain cross_modal marker
        assert any("cross_modal" in p for p in result["provenance_paths"])

    def test_visual_search_augments_clips(self, synthetic_htvg_fixture):
        htvg, ent_a_emb, _ = synthetic_htvg_fixture
        # Use clip embedding of video_test_3 which ENT_A doesn't cross-link to
        clip_emb_of_3 = _rand_emb(CLIP_DIM, seed=3)
        result_with_visual = query_htvg(
            query_semantic_emb=ent_a_emb,
            query_clip_emb=clip_emb_of_3,
            htvg=htvg,
            top_k=1,
            temporal_context_hops=0,
        )
        result_without_visual = query_htvg(
            query_semantic_emb=ent_a_emb,
            query_clip_emb=None,
            htvg=htvg,
            top_k=1,
            temporal_context_hops=0,
        )
        # With visual search, more clips should be retrieved (or at least equal)
        assert len(result_with_visual["clip_tans"]) >= len(result_without_visual["clip_tans"])

    def test_empty_graph_returns_empty_subgraph(self):
        empty_htvg = HTVGraph(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, semantic_dim=SEM_DIM)
        result = query_htvg(
            query_semantic_emb=_rand_emb(SEM_DIM),
            query_clip_emb=None,
            htvg=empty_htvg,
            top_k=5,
        )
        assert result["semantic_nodes"] == []
        assert result["clip_tans"] == []
        assert result["scene_tans"] == []


class TestTemporalExpansion:
    def test_hop_zero_no_expansion(self, synthetic_htvg_fixture):
        htvg, _, _ = synthetic_htvg_fixture
        seeds = {"video_test_2"}
        expanded = _expand_temporal_context(seeds, htvg, hops=0)
        assert expanded == set()

    def test_hop_one_adds_neighbours(self, synthetic_htvg_fixture):
        htvg, _, _ = synthetic_htvg_fixture
        seeds = {"video_test_2"}
        expanded = _expand_temporal_context(seeds, htvg, hops=1)
        # video_test_1 (predecessor) and video_test_3 (successor)
        assert "video_test_1" in expanded
        assert "video_test_3" in expanded

    def test_hop_two_adds_further_neighbours(self, synthetic_htvg_fixture):
        htvg, _, _ = synthetic_htvg_fixture
        seeds = {"video_test_2"}
        expanded = _expand_temporal_context(seeds, htvg, hops=2)
        assert "video_test_0" in expanded
        assert "video_test_4" in expanded


class TestSortSegmentIds:
    def test_sorts_by_video_then_index(self):
        ids = ["video_b_2", "video_a_10", "video_a_2", "video_b_0"]
        result = _sort_segment_ids(ids)
        assert result == ["video_a_2", "video_a_10", "video_b_0", "video_b_2"]

    def test_deduplicates(self):
        ids = ["video_a_1", "video_a_1", "video_a_0"]
        result = _sort_segment_ids(ids)
        assert result == ["video_a_0", "video_a_1"]


class TestAsyncQueryWrapper:
    @pytest.mark.asyncio
    async def test_async_query_returns_subgraph(self, synthetic_htvg_fixture):
        htvg, ent_a_emb, _ = synthetic_htvg_fixture

        async def mock_embed(texts):
            return np.stack([ent_a_emb] * len(texts))

        result = await async_query_htvg(
            query="test query about concept A",
            htvg=htvg,
            text_embedding_func=mock_embed,
            clip_embedding_func=None,
            top_k=1,
            temporal_context_hops=0,
        )
        assert "semantic_nodes" in result
        assert "clip_tans" in result
        # Should have retrieved ENT_A since mock embedding matches ent_a_emb
        sem_ids = [n["node_id"] for n in result["semantic_nodes"]]
        assert "ENT_A" in sem_ids
