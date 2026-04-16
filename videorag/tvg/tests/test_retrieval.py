"""
videorag/tvg/tests/test_retrieval.py
=======================================
Unit tests for the TVG retrieval API (``query_tvg`` and ``async_query_tvg``).

All tests use synthetic graph data and do NOT require GPU or network access.

Usage:
    python -m pytest videorag/tvg/tests/test_retrieval.py -v
"""

import asyncio
from typing import List, Tuple

import numpy as np
import pytest

from videorag.tvg.graph import TVGraph
from videorag.tvg.retrieval import (
    query_tvg,
    async_query_tvg,
    _expand_temporal_context,
    _sort_segment_ids,
    _collect_subgraph_edges,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers to build a small synthetic TVGraph
# ─────────────────────────────────────────────────────────────────────────────

TAN_DIM = 16
SEM_DIM = 8


def _rand_emb(dim: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v


def _build_synthetic_tvg() -> Tuple[TVGraph, np.ndarray, np.ndarray]:
    """
    Graph structure:
        Semantic: ENT_A, ENT_B
        TANs:     video_test_0 … video_test_4 (5 TANs)
        Edges:
          temporal:   0→1→2→3→4
          cross:      ENT_A → video_test_0, video_test_1
                      ENT_B → video_test_3
          semantic:   ENT_A ↔ ENT_B

    Returns:
        (tvg, ent_a_emb, ent_b_emb) so tests can pass matching query vectors.
    """
    tvg = TVGraph(tan_dim=TAN_DIM, semantic_dim=SEM_DIM)

    # TANs
    tan_embs = {f"video_test_{i}": _rand_emb(TAN_DIM, seed=i) for i in range(5)}
    for i in range(5):
        tid = f"video_test_{i}"
        tvg.add_tan(tid, "video_test", str(i), f"{i*30}-{(i+1)*30}", f"content_{i}", tan_embs[tid])

    # Temporal edges
    for i in range(4):
        tvg.add_temporal_edge(f"video_test_{i}", f"video_test_{i+1}")

    # Semantic nodes
    ent_a_emb = _rand_emb(SEM_DIM, seed=10)
    ent_b_emb = _rand_emb(SEM_DIM, seed=11)
    tvg.add_semantic_node("ENT_A", "CONCEPT", "concept A", "chunk-1", ent_a_emb)
    tvg.add_semantic_node("ENT_B", "PERSON", "person B", "chunk-2", ent_b_emb)

    # Semantic edge
    tvg.add_semantic_edge("ENT_A", "ENT_B", weight=1.0)

    # Cross-modal edges
    tvg.add_cross_modal_edge("ENT_A", "video_test_0")
    tvg.add_cross_modal_edge("ENT_A", "video_test_1")
    tvg.add_cross_modal_edge("ENT_B", "video_test_3")

    return tvg, ent_a_emb, ent_b_emb


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def synthetic_tvg_fixture():
    return _build_synthetic_tvg()


class TestQueryTVG:
    def test_returns_tvg_subgraph_keys(self, synthetic_tvg_fixture):
        tvg, ent_a_emb, _ = synthetic_tvg_fixture
        result = query_tvg(
            query_semantic_emb=ent_a_emb,
            query_tan_emb=None,
            tvg=tvg,
            top_k=2,
            temporal_context_hops=1,
            query="test",
        )
        for key in ["semantic_nodes", "tans", "edges", "segment_ids"]:
            assert key in result
        # Confirm no scene_tans key
        assert "scene_tans" not in result

    def test_semantic_hit_ent_a(self, synthetic_tvg_fixture):
        tvg, ent_a_emb, _ = synthetic_tvg_fixture
        result = query_tvg(
            query_semantic_emb=ent_a_emb,
            query_tan_emb=None,
            tvg=tvg,
            top_k=1,
            temporal_context_hops=0,
        )
        sem_ids = [n["node_id"] for n in result["semantic_nodes"]]
        assert "ENT_A" in sem_ids

    def test_cross_modal_tans_retrieved(self, synthetic_tvg_fixture):
        tvg, ent_a_emb, _ = synthetic_tvg_fixture
        result = query_tvg(
            query_semantic_emb=ent_a_emb,
            query_tan_emb=None,
            tvg=tvg,
            top_k=1,
            temporal_context_hops=0,
        )
        tan_ids = {c["node_id"] for c in result["tans"]}
        # ENT_A is cross-modal linked to video_test_0 and video_test_1
        assert "video_test_0" in tan_ids
        assert "video_test_1" in tan_ids

    def test_temporal_context_expansion(self, synthetic_tvg_fixture):
        tvg, ent_a_emb, _ = synthetic_tvg_fixture
        result = query_tvg(
            query_semantic_emb=ent_a_emb,
            query_tan_emb=None,
            tvg=tvg,
            top_k=1,
            temporal_context_hops=2,  # should pull in video_test_2 as neighbour
        )
        tan_ids = {c["node_id"] for c in result["tans"]}
        assert "video_test_2" in tan_ids

    def test_segment_ids_sorted(self, synthetic_tvg_fixture):
        tvg, ent_a_emb, _ = synthetic_tvg_fixture
        result = query_tvg(
            query_semantic_emb=ent_a_emb,
            query_tan_emb=None,
            tvg=tvg,
            top_k=2,
            temporal_context_hops=2,
        )
        seg_ids = result["segment_ids"]
        indices = [int(s.split("_")[-1]) for s in seg_ids]
        assert indices == sorted(indices)

    def test_edges_all_within_subgraph(self, synthetic_tvg_fixture):
        tvg, ent_a_emb, _ = synthetic_tvg_fixture
        result = query_tvg(
            query_semantic_emb=ent_a_emb,
            query_tan_emb=None,
            tvg=tvg,
            top_k=2,
            temporal_context_hops=1,
        )
        all_node_ids = (
            {n["node_id"] for n in result["semantic_nodes"]}
            | {c["node_id"] for c in result["tans"]}
        )
        for edge in result["edges"]:
            assert edge["src_id"] in all_node_ids or edge["tgt_id"] in all_node_ids

    def test_provenance_paths_non_empty(self, synthetic_tvg_fixture):
        tvg, ent_a_emb, _ = synthetic_tvg_fixture
        result = query_tvg(
            query_semantic_emb=ent_a_emb,
            query_tan_emb=None,
            tvg=tvg,
            top_k=1,
            temporal_context_hops=0,
        )
        assert len(result["provenance_paths"]) > 0
        assert any("cross_modal" in p for p in result["provenance_paths"])

    def test_visual_search_augments_tans(self, synthetic_tvg_fixture):
        tvg, ent_a_emb, _ = synthetic_tvg_fixture
        # Use TAN embedding of video_test_3 which ENT_A doesn't cross-link to
        tan_emb_of_3 = _rand_emb(TAN_DIM, seed=3)
        result_with_visual = query_tvg(
            query_semantic_emb=ent_a_emb,
            query_tan_emb=tan_emb_of_3,
            tvg=tvg,
            top_k=1,
            temporal_context_hops=0,
        )
        result_without_visual = query_tvg(
            query_semantic_emb=ent_a_emb,
            query_tan_emb=None,
            tvg=tvg,
            top_k=1,
            temporal_context_hops=0,
        )
        assert len(result_with_visual["tans"]) >= len(result_without_visual["tans"])

    def test_empty_graph_returns_empty_subgraph(self):
        empty_tvg = TVGraph(tan_dim=TAN_DIM, semantic_dim=SEM_DIM)
        result = query_tvg(
            query_semantic_emb=_rand_emb(SEM_DIM),
            query_tan_emb=None,
            tvg=empty_tvg,
            top_k=5,
        )
        assert result["semantic_nodes"] == []
        assert result["tans"] == []
        assert "scene_tans" not in result


class TestTemporalExpansion:
    def test_hop_zero_no_expansion(self, synthetic_tvg_fixture):
        tvg, _, _ = synthetic_tvg_fixture
        seeds = {"video_test_2"}
        expanded = _expand_temporal_context(seeds, tvg, hops=0)
        assert expanded == set()

    def test_hop_one_adds_neighbours(self, synthetic_tvg_fixture):
        tvg, _, _ = synthetic_tvg_fixture
        seeds = {"video_test_2"}
        expanded = _expand_temporal_context(seeds, tvg, hops=1)
        assert "video_test_1" in expanded
        assert "video_test_3" in expanded

    def test_hop_two_adds_further_neighbours(self, synthetic_tvg_fixture):
        tvg, _, _ = synthetic_tvg_fixture
        seeds = {"video_test_2"}
        expanded = _expand_temporal_context(seeds, tvg, hops=2)
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
    async def test_async_query_returns_subgraph(self, synthetic_tvg_fixture):
        tvg, ent_a_emb, _ = synthetic_tvg_fixture

        async def mock_embed(texts):
            return np.stack([ent_a_emb] * len(texts))

        result = await async_query_tvg(
            query="test query about concept A",
            tvg=tvg,
            text_embedding_func=mock_embed,
            tan_embedding_func=None,
            top_k=1,
            temporal_context_hops=0,
        )
        assert "semantic_nodes" in result
        assert "tans" in result
        sem_ids = [n["node_id"] for n in result["semantic_nodes"]]
        assert "ENT_A" in sem_ids
