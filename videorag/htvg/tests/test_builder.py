"""
videorag/htvg/tests/test_builder.py
=====================================
Unit tests for the HTVG builder pipeline.

All tests use *synthetic* data and do NOT require a GPU, LLM API keys, or a
real VideoRAG working directory.  Embeddings are deterministic random arrays
seeded at test time.

Usage:
    python -m pytest videorag/htvg/tests/test_builder.py -v
"""

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import networkx as nx
import numpy as np
import pytest

from videorag.htvg.graph import HTVGraph, _l2_normalize
from videorag.htvg.aggregator import HierarchicalAggregator, TemporalTransformer
from videorag.htvg.builder import (
    build_htvg,
    _add_clip_tans,
    _add_temporal_edges,
    _add_cross_modal_edges,
    _add_scene_tans_and_edges,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

CLIP_DIM = 1024
SCENE_DIM = 768
SEM_DIM = 8   # tiny for tests


@pytest.fixture
def rng():
    return np.random.default_rng(seed=42)


@pytest.fixture
def tiny_htvg():
    return HTVGraph(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, semantic_dim=SEM_DIM)


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
        emb = rng.random(CLIP_DIM).astype(np.float32)
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


@pytest.fixture
def tiny_aggregator():
    model = TemporalTransformer(
        clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, nhead=4, num_layers=1, max_seq_len=8
    )
    return HierarchicalAggregator(
        model=model,
        scene_window=2,
        device="cpu",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — individual stages
# ─────────────────────────────────────────────────────────────────────────────

class TestHTVGraph:
    def test_add_clip_tan_is_idempotent(self, tiny_htvg, rng):
        emb = rng.random(CLIP_DIM).astype(np.float32)
        tiny_htvg.add_clip_tan("video_a_0", "video_a", "0", "0-30", "content", emb)
        assert tiny_htvg.num_nodes() == 1
        # Second call should not duplicate
        tiny_htvg.add_clip_tan("video_a_0", "video_a", "0", "0-30", "content", emb)
        assert tiny_htvg.num_nodes() == 1

    def test_temporal_edge_direction(self, tiny_htvg, rng):
        for i in range(3):
            emb = rng.random(CLIP_DIM).astype(np.float32)
            tiny_htvg.add_clip_tan(f"video_a_{i}", "video_a", str(i), f"{i*30}-{(i+1)*30}", "", emb)
        tiny_htvg.add_temporal_edge("video_a_0", "video_a_1")
        tiny_htvg.add_temporal_edge("video_a_1", "video_a_2")
        assert tiny_htvg._graph.has_edge("video_a_0", "video_a_1")
        assert not tiny_htvg._graph.has_edge("video_a_1", "video_a_0")

    def test_semantic_edge_is_bidirectional(self, tiny_htvg, rng):
        emb = rng.random(SEM_DIM).astype(np.float32)
        tiny_htvg.add_semantic_node("ENT_X", "CONCEPT", "desc", "src", emb)
        tiny_htvg.add_semantic_node("ENT_Y", "PERSON", "desc2", "src2", emb)
        tiny_htvg.add_semantic_edge("ENT_X", "ENT_Y", weight=1.0)
        assert tiny_htvg._graph.has_edge("ENT_X", "ENT_Y")
        assert tiny_htvg._graph.has_edge("ENT_Y", "ENT_X")

    def test_faiss_search_returns_correct_id(self, tiny_htvg, rng):
        embs = rng.random((5, CLIP_DIM)).astype(np.float32)
        for i, emb in enumerate(embs):
            tiny_htvg.add_clip_tan(f"v_{i}", "vid", str(i), f"{i*30}-{(i+1)*30}", "", emb)
        # Query with the exact embedding of v_2 — should rank first
        results = tiny_htvg.search_clip_index(embs[2], top_k=3)
        top_id, top_score = results[0]
        assert top_id == "v_2"
        assert top_score > 0.99

    def test_save_load_roundtrip(self, tiny_htvg, rng):
        emb = rng.random(CLIP_DIM).astype(np.float32)
        tiny_htvg.add_clip_tan("video_a_0", "video_a", "0", "0-30", "hello", emb)
        tiny_htvg.add_temporal_edge("video_a_0", "video_a_0")  # self-loop for edge test

        with tempfile.TemporaryDirectory() as tmpdir:
            tiny_htvg.save(tmpdir)
            loaded = HTVGraph.load(tmpdir)

        assert loaded.num_nodes() == 1
        assert loaded._clip_id_list == ["video_a_0"]
        node = loaded.get_node("video_a_0")
        assert node is not None
        assert node["video_name"] == "video_a"


class TestClipTANConstruction:
    def test_all_segments_added(self, fake_video_segments, fake_vdb, rng):
        htvg = HTVGraph(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, semantic_dim=SEM_DIM)
        _add_clip_tans(fake_video_segments, fake_vdb, htvg)
        # 2 videos × 3 segments = 6 clip TANs
        assert htvg.num_nodes() == 6

    def test_segment_id_format(self, fake_video_segments, fake_vdb):
        htvg = HTVGraph(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, semantic_dim=SEM_DIM)
        _add_clip_tans(fake_video_segments, fake_vdb, htvg)
        assert htvg._graph.has_node("video_a_0")
        assert htvg._graph.has_node("video_b_2")


class TestTemporalEdges:
    def test_edges_count(self, fake_video_segments, fake_vdb):
        htvg = HTVGraph(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, semantic_dim=SEM_DIM)
        video_clip_map = _add_clip_tans(fake_video_segments, fake_vdb, htvg)
        _add_temporal_edges(video_clip_map, fake_video_segments, htvg)
        # Each video: 3 segments → 2 temporal edges. 2 videos → 4
        edges = [
            (s, t)
            for s, t, d in htvg._graph.edges(data=True)
            if d.get("edge_type") == "temporal"
        ]
        assert len(edges) == 4


class TestCrossModalEdges:
    def test_cross_modal_edges_added(self, fake_video_segments, fake_vdb, fake_entity_graph, fake_text_chunks):
        htvg = HTVGraph(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, semantic_dim=SEM_DIM)
        video_clip_map = _add_clip_tans(fake_video_segments, fake_vdb, htvg)

        # Add dummy semantic nodes (without embeddings — just graph structure)
        for nid, data in fake_entity_graph.nodes(data=True):
            htvg._graph.add_node(nid, node_type="semantic", **data)

        _add_cross_modal_edges(fake_entity_graph, fake_text_chunks, htvg)
        cross_edges = [
            (s, t)
            for s, t, d in htvg._graph.edges(data=True)
            if d.get("edge_type") == "cross_modal"
        ]
        # ENTITY_A → video_a_0, video_a_1 (chunk-01) + video_a_2 (chunk-02)
        # ENTITY_B → video_a_0, video_a_1 (chunk-01)
        # ENTITY_C → video_b_0 (chunk-03)
        assert len(cross_edges) >= 4


class TestSceneAggregation:
    def test_scene_count(self, fake_video_segments, fake_vdb, tiny_aggregator):
        htvg = HTVGraph(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, semantic_dim=SEM_DIM)
        video_clip_map = _add_clip_tans(fake_video_segments, fake_vdb, htvg)
        _add_scene_tans_and_edges(video_clip_map, fake_video_segments, htvg, tiny_aggregator)

        scene_nodes = [
            n for n, d in htvg._graph.nodes(data=True)
            if d.get("tan_level") == "scene"
        ]
        # scene_window=2, 3 clips per video → ceil(3/2)=2 scenes × 2 videos = 4
        assert len(scene_nodes) == 4

    def test_hierarchical_edges_connect_clip_to_scene(self, fake_video_segments, fake_vdb, tiny_aggregator):
        htvg = HTVGraph(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, semantic_dim=SEM_DIM)
        video_clip_map = _add_clip_tans(fake_video_segments, fake_vdb, htvg)
        _add_scene_tans_and_edges(video_clip_map, fake_video_segments, htvg, tiny_aggregator)

        hier_edges = [
            (s, t)
            for s, t, d in htvg._graph.edges(data=True)
            if d.get("edge_type") == "hierarchical"
        ]
        assert len(hier_edges) >= 6  # 3 clips × 2 videos = 6 hierarchical edges


# ─────────────────────────────────────────────────────────────────────────────
# Integration test — full build_htvg pipeline
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildHTVGIntegration:
    @pytest.mark.asyncio
    async def test_full_pipeline(
        self,
        fake_video_segments,
        fake_entity_graph,
        fake_text_chunks,
        fake_vdb,
        fake_embedding_func,
        tiny_aggregator,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            htvg = HTVGraph(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, semantic_dim=SEM_DIM)
            result = await build_htvg(
                video_segments_data=fake_video_segments,
                existing_entity_graph=fake_entity_graph,
                text_chunks_data=fake_text_chunks,
                video_segment_feature_vdb=fake_vdb,
                text_embedding_func=fake_embedding_func,
                aggregator=tiny_aggregator,
                htvg=htvg,
                working_dir=tmpdir,
                semantic_dim=SEM_DIM,
            )

        assert result is htvg  # same object mutated in-place
        assert result.num_nodes() > 6  # clips + scenes + semantics
        assert result.build_meta is not None
        assert result.build_meta["num_clip_tans"] == 6
        assert result.build_meta["num_semantic_nodes"] == 3

    @pytest.mark.asyncio
    async def test_incremental_build_is_idempotent(
        self,
        fake_video_segments,
        fake_entity_graph,
        fake_text_chunks,
        fake_vdb,
        fake_embedding_func,
        tiny_aggregator,
    ):
        """Running build_htvg twice should not create duplicate nodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            htvg = HTVGraph(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, semantic_dim=SEM_DIM)
            await build_htvg(
                fake_video_segments, fake_entity_graph, fake_text_chunks,
                fake_vdb, fake_embedding_func, tiny_aggregator, htvg, tmpdir, SEM_DIM,
            )
            n_nodes_after_first = htvg.num_nodes()

            await build_htvg(
                fake_video_segments, fake_entity_graph, fake_text_chunks,
                fake_vdb, fake_embedding_func, tiny_aggregator, htvg, tmpdir, SEM_DIM,
            )
            n_nodes_after_second = htvg.num_nodes()

        assert n_nodes_after_first == n_nodes_after_second


class TestTemporalTransformer:
    def test_output_shape(self):
        model = TemporalTransformer(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, nhead=8, num_layers=2)
        import torch
        B, T = 4, 6
        x = torch.randn(B, T, CLIP_DIM)
        out = model(x)
        assert out.shape == (B, SCENE_DIM)

    def test_output_is_l2_normalized(self):
        model = TemporalTransformer(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM)
        import torch
        x = torch.randn(2, 4, CLIP_DIM)
        out = model(x)
        norms = out.norm(dim=-1)
        assert torch.allclose(norms, torch.ones(2), atol=1e-5)

    def test_checkpoint_save_load(self, tmp_path):
        model = TemporalTransformer(clip_dim=CLIP_DIM, scene_dim=SCENE_DIM, nhead=4, num_layers=1)
        agg = HierarchicalAggregator(model=model, device="cpu")
        ckpt_path = agg.save_checkpoint(str(tmp_path), epoch=1, loss=0.42)
        assert os.path.exists(ckpt_path)
        loaded_agg = HierarchicalAggregator.load_checkpoint(ckpt_path, device="cpu")
        assert loaded_agg.model.clip_dim == CLIP_DIM


class TestSceneDetection:
    def test_fixed_window(self):
        model = TemporalTransformer(clip_dim=8, scene_dim=4, nhead=2, num_layers=1)
        agg = HierarchicalAggregator(model=model, scene_window=3, device="cpu", use_cosine_detection=False)
        embs = np.random.rand(7, 8).astype(np.float32)
        groups = agg.detect_scene_boundaries(embs)
        assert len(groups) == 3  # [0,1,2], [3,4,5], [6]
        assert groups[0] == [0, 1, 2]

    def test_cosine_drop(self):
        model = TemporalTransformer(clip_dim=8, scene_dim=4, nhead=2, num_layers=1)
        agg = HierarchicalAggregator(
            model=model, similarity_threshold=0.99, device="cpu", use_cosine_detection=True
        )
        # Two very different clip vectors → should create 2 scenes
        embs = np.zeros((4, 8), dtype=np.float32)
        embs[:2, 0] = 1.0  # clips 0,1 point in +x direction
        embs[2:, 1] = 1.0  # clips 2,3 point in +y direction — very different
        groups = agg.detect_scene_boundaries(embs)
        assert len(groups) == 2
