"""
videorag/tvg/tests/test_builder.py
=====================================
Unit tests for the TVG builder pipeline.

All tests use *synthetic* data and do NOT require a GPU, LLM API keys, or a
real VideoRAG working directory.  Embeddings are deterministic random arrays
seeded at test time.

Usage:
    python -m pytest videorag/tvg/tests/test_builder.py -v
"""

import asyncio
import os
import tempfile

import networkx as nx
import numpy as np
import pytest
from unittest.mock import MagicMock

from videorag.tvg.graph import TVGraph, _l2_normalize
from videorag.tvg.builder import (
    build_tvg,
    _add_tans,
    _add_temporal_edges,
    _add_cross_modal_edges,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

TAN_DIM = 1024
SEM_DIM = 8   # tiny for tests


@pytest.fixture
def rng():
    return np.random.default_rng(seed=42)


@pytest.fixture
def tiny_tvg():
    return TVGraph(tan_dim=TAN_DIM, semantic_dim=SEM_DIM)


@pytest.fixture
def fake_video_segments():
    """Simulate video_segments._data for two videos with 3 segments each."""
    data = {}
    for vid in ["video_a", "video_b"]:
        data[vid] = {}
        for i in range(3):
            start = i * 30
            end = start + 30
            data[vid][str(i)] = {
                "content": f"Caption:\nScene {i} of {vid}\nTranscript:\nHello {i}",
                "time": f"{start}-{end}",
                "transcript": f"Hello {i}",
                "frame_times": [float(start), float(start + 10), float(start + 20)],
            }
    return data


@pytest.fixture
def fake_entity_graph(rng):
    """Minimal nx.Graph with 3 entity nodes and 2 edges."""
    g = nx.Graph()
    g.add_node(
        "ENTITY_A",
        entity_type="CONCEPT",
        description="Entity A description",
        source_id="chunk-01<SEP>chunk-02",
    )
    g.add_node(
        "ENTITY_B",
        entity_type="PERSON",
        description="Entity B description",
        source_id="chunk-01",
    )
    g.add_node(
        "ENTITY_C",
        entity_type="LOCATION",
        description="Entity C description",
        source_id="chunk-03",
    )
    g.add_edge("ENTITY_A", "ENTITY_B", weight=1.5, description="relates to", source_id="chunk-01")
    g.add_edge("ENTITY_B", "ENTITY_C", weight=1.0, description="near", source_id="chunk-01")
    return g


@pytest.fixture
def fake_text_chunks():
    """Minimal text_chunks._data mapping chunk IDs to segment IDs."""
    return {
        "chunk-01": {
            "content": "some content",
            "tokens": 50,
            "chunk_order_index": 0,
            "video_segment_id": ["video_a_0", "video_a_1"],
        },
        "chunk-02": {
            "content": "other content",
            "tokens": 30,
            "chunk_order_index": 1,
            "video_segment_id": ["video_a_2"],
        },
        "chunk-03": {
            "content": "third content",
            "tokens": 40,
            "chunk_order_index": 2,
            "video_segment_id": ["video_b_0"],
        },
    }


@pytest.fixture
def fake_vdb(rng):
    """Mock NanoVectorDBVideoSegmentStorage with .data entries."""
    def make_item(seg_id):
        emb = rng.random(TAN_DIM).astype(np.float32)
        emb /= np.linalg.norm(emb)
        return {"__id__": seg_id, "__vector__": emb.tolist()}

    mock_client = MagicMock()
    mock_client.data = []
    for vid in ["video_a", "video_b"]:
        for i in range(3):
            mock_client.data.append(make_item(f"{vid}_{i}"))

    vdb = MagicMock()
    vdb._client = mock_client
    return vdb


@pytest.fixture
def fake_embedding_func(rng):
    """Async callable returning tiny (SEM_DIM,) embeddings."""
    async def _emb(texts):
        n = len(texts)
        arr = rng.random((n, SEM_DIM)).astype(np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / norms
    return _emb


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — individual stages
# ─────────────────────────────────────────────────────────────────────────────

class TestTVGraph:
    def test_add_tan_is_idempotent(self, tiny_tvg, rng):
        emb = rng.random(TAN_DIM).astype(np.float32)
        tiny_tvg.add_tan("video_a_0", "video_a", "0", "0-30", "content", emb)
        assert tiny_tvg.num_nodes() == 1
        # Second call should not duplicate
        tiny_tvg.add_tan("video_a_0", "video_a", "0", "0-30", "content", emb)
        assert tiny_tvg.num_nodes() == 1

    def test_temporal_edge_direction(self, tiny_tvg, rng):
        for i in range(3):
            emb = rng.random(TAN_DIM).astype(np.float32)
            tiny_tvg.add_tan(f"video_a_{i}", "video_a", str(i), f"{i*30}-{(i+1)*30}", "", emb)
        tiny_tvg.add_temporal_edge("video_a_0", "video_a_1")
        tiny_tvg.add_temporal_edge("video_a_1", "video_a_2")
        assert tiny_tvg._graph.has_edge("video_a_0", "video_a_1")
        assert not tiny_tvg._graph.has_edge("video_a_1", "video_a_0")

    def test_semantic_edge_is_bidirectional(self, tiny_tvg, rng):
        emb = rng.random(SEM_DIM).astype(np.float32)
        tiny_tvg.add_semantic_node("ENT_X", "CONCEPT", "desc", "src", emb)
        tiny_tvg.add_semantic_node("ENT_Y", "PERSON", "desc2", "src2", emb)
        tiny_tvg.add_semantic_edge("ENT_X", "ENT_Y", weight=1.0)
        assert tiny_tvg._graph.has_edge("ENT_X", "ENT_Y")
        assert tiny_tvg._graph.has_edge("ENT_Y", "ENT_X")

    def test_faiss_search_returns_correct_id(self, tiny_tvg, rng):
        embs = rng.random((5, TAN_DIM)).astype(np.float32)
        for i, emb in enumerate(embs):
            tiny_tvg.add_tan(f"v_{i}", "vid", str(i), f"{i*30}-{(i+1)*30}", "", emb)
        # Query with the exact embedding of v_2 — should rank first
        results = tiny_tvg.search_tan_index(embs[2], top_k=3)
        top_id, top_score = results[0]
        assert top_id == "v_2"
        assert top_score > 0.99

    def test_save_load_roundtrip(self, tiny_tvg, rng):
        emb = rng.random(TAN_DIM).astype(np.float32)
        tiny_tvg.add_tan("video_a_0", "video_a", "0", "0-30", "hello", emb)
        tiny_tvg.add_temporal_edge("video_a_0", "video_a_0")  # self-loop for edge test

        with tempfile.TemporaryDirectory() as tmpdir:
            tiny_tvg.save(tmpdir)
            loaded = TVGraph.load(tmpdir)

        assert loaded.num_nodes() == 1
        assert loaded._tan_id_list == ["video_a_0"]
        node = loaded.get_node("video_a_0")
        assert node is not None
        assert node["video_name"] == "video_a"

    def test_no_scene_nodes(self, tiny_tvg, rng):
        """TVGraph should have no scene-related methods or attributes."""
        assert not hasattr(tiny_tvg, "_scene_index")
        assert not hasattr(tiny_tvg, "_scene_id_list")
        assert not hasattr(tiny_tvg, "scene_dim")
        assert not hasattr(tiny_tvg, "add_scene_tan")
        assert not hasattr(tiny_tvg, "add_hierarchical_edge")
        assert not hasattr(tiny_tvg, "search_scene_index")


class TestTANConstruction:
    def test_all_segments_added(self, fake_video_segments, fake_vdb, rng):
        tvg = TVGraph(tan_dim=TAN_DIM, semantic_dim=SEM_DIM)
        _add_tans(fake_video_segments, fake_vdb, tvg)
        # 2 videos × 3 segments = 6 TANs
        assert tvg.num_nodes() == 6

    def test_segment_id_format(self, fake_video_segments, fake_vdb):
        tvg = TVGraph(tan_dim=TAN_DIM, semantic_dim=SEM_DIM)
        _add_tans(fake_video_segments, fake_vdb, tvg)
        assert tvg._graph.has_node("video_a_0")
        assert tvg._graph.has_node("video_b_2")

    def test_node_type_is_tan(self, fake_video_segments, fake_vdb):
        tvg = TVGraph(tan_dim=TAN_DIM, semantic_dim=SEM_DIM)
        _add_tans(fake_video_segments, fake_vdb, tvg)
        node = tvg.get_node("video_a_0")
        assert node is not None
        assert node["node_type"] == "tan"


class TestTemporalEdges:
    def test_edges_count(self, fake_video_segments, fake_vdb):
        tvg = TVGraph(tan_dim=TAN_DIM, semantic_dim=SEM_DIM)
        video_tan_map = _add_tans(fake_video_segments, fake_vdb, tvg)
        _add_temporal_edges(video_tan_map, fake_video_segments, tvg)
        # Each video: 3 segments → 2 temporal edges. 2 videos → 4
        edges = [
            (s, t)
            for s, t, d in tvg._graph.edges(data=True)
            if d.get("edge_type") == "temporal"
        ]
        assert len(edges) == 4


class TestCrossModalEdges:
    def test_cross_modal_edges_added(self, fake_video_segments, fake_vdb, fake_entity_graph, fake_text_chunks):
        tvg = TVGraph(tan_dim=TAN_DIM, semantic_dim=SEM_DIM)
        video_tan_map = _add_tans(fake_video_segments, fake_vdb, tvg)

        # Add dummy semantic nodes (without embeddings — just graph structure)
        for nid, data in fake_entity_graph.nodes(data=True):
            tvg._graph.add_node(nid, node_type="semantic", **data)

        _add_cross_modal_edges(fake_entity_graph, fake_text_chunks, tvg)
        cross_edges = [
            (s, t)
            for s, t, d in tvg._graph.edges(data=True)
            if d.get("edge_type") == "cross_modal"
        ]
        # ENTITY_A → video_a_0, video_a_1 (chunk-01) + video_a_2 (chunk-02)
        # ENTITY_B → video_a_0, video_a_1 (chunk-01)
        # ENTITY_C → video_b_0 (chunk-03)
        assert len(cross_edges) >= 4


# ─────────────────────────────────────────────────────────────────────────────
# Integration test — full build_tvg pipeline
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildTVGIntegration:
    @pytest.mark.asyncio
    async def test_full_pipeline(
        self,
        fake_video_segments,
        fake_entity_graph,
        fake_text_chunks,
        fake_vdb,
        fake_embedding_func,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tvg = TVGraph(tan_dim=TAN_DIM, semantic_dim=SEM_DIM)
            result = await build_tvg(
                video_segments_data=fake_video_segments,
                existing_entity_graph=fake_entity_graph,
                text_chunks_data=fake_text_chunks,
                video_segment_feature_vdb=fake_vdb,
                text_embedding_func=fake_embedding_func,
                tvg=tvg,
                working_dir=tmpdir,
                semantic_dim=SEM_DIM,
            )

        assert result is tvg  # same object mutated in-place
        assert result.num_nodes() > 6  # TANs + semantics
        assert result.build_meta is not None
        assert result.build_meta["num_tans"] == 6
        assert result.build_meta["num_semantic_nodes"] == 3
        # No scene counts in meta
        assert "num_scene_tans" not in result.build_meta

    @pytest.mark.asyncio
    async def test_incremental_build_is_idempotent(
        self,
        fake_video_segments,
        fake_entity_graph,
        fake_text_chunks,
        fake_vdb,
        fake_embedding_func,
    ):
        """Running build_tvg twice should not create duplicate nodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tvg = TVGraph(tan_dim=TAN_DIM, semantic_dim=SEM_DIM)
            await build_tvg(
                fake_video_segments, fake_entity_graph, fake_text_chunks,
                fake_vdb, fake_embedding_func, tvg, tmpdir, SEM_DIM,
            )
            n_nodes_after_first = tvg.num_nodes()

            await build_tvg(
                fake_video_segments, fake_entity_graph, fake_text_chunks,
                fake_vdb, fake_embedding_func, tvg, tmpdir, SEM_DIM,
            )
            n_nodes_after_second = tvg.num_nodes()

        assert n_nodes_after_first == n_nodes_after_second
