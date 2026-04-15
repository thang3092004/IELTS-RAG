"""
videorag/htvg/schemas.py
========================
TypedDicts that define the data contracts for every node, edge, and subgraph
object in the Hierarchical Temporal-Visual Graph (HTVG).

All names are intentionally terse so they serialise cleanly to GraphML
attributes (which only support flat string/int/float values when written to
disk — any vector field is stored externally in FAISS).

Google-style docstrings are used throughout the module where prose is needed.
"""

from typing import List, Optional
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Node schemas
# ---------------------------------------------------------------------------

class SemanticNode(TypedDict, total=False):
    """A text-derived concept node (entity) in the HTVG semantic layer.

    Attributes:
        node_id: Unique identifier — upper-cased entity name, e.g. "CLIMATE CHANGE".
        node_type: Always ``"semantic"``.
        entity_type: LLM-assigned category, e.g. ``"CONCEPT"``, ``"PERSON"``.
        description: Accumulated description from all mentions (may be LLM-summarised).
        source_id: ``<GRAPH_FIELD_SEP>``-joined chunk IDs that mention this entity.
        faiss_row_id: Integer row index into the semantic FAISS index (-1 if unindexed).
    """

    node_id: str
    node_type: str          # "semantic"
    entity_type: str
    description: str
    source_id: str
    faiss_row_id: int


class ClipTANNode(TypedDict, total=False):
    """A Temporal Anchor Node at the *clip* level (one per video segment).

    Attributes:
        node_id: ``{video_name}_{segment_index}``, e.g. ``"lecture_3"``.
        node_type: Always ``"tan_clip"``.
        tan_level: Always ``"clip"``.
        video_name: Base name of the source video file (no extension).
        segment_index: String integer index of the segment within the video.
        time_range: ``"start-end"`` in seconds, e.g. ``"90-120"``.
        content: Raw ``"Caption:\\n...\\nTranscript:\\n..."`` text stored in
            ``video_segments._data``.
        faiss_row_id: Integer row index into the clip FAISS index (-1 if unindexed).
    """

    node_id: str
    node_type: str          # "tan_clip"
    tan_level: str          # "clip"
    video_name: str
    segment_index: str
    time_range: str
    content: str
    faiss_row_id: int


class SceneTANNode(TypedDict, total=False):
    """A Temporal Anchor Node at the *scene* level (aggregated from clip TANs).

    Attributes:
        node_id: ``"scene_{video_name}_{scene_index}"``.
        node_type: Always ``"tan_scene"``.
        tan_level: Always ``"scene"``.
        video_name: Base name of the source video file (no extension).
        scene_index: Sequential scene index within the video (int as str).
        time_range: ``"start-end"`` covering all constituent clips.
        clip_ids: Comma-separated list of constituent ``ClipTAN.node_id`` values.
        faiss_row_id: Integer row index into the scene FAISS index (-1 if unindexed).
    """

    node_id: str
    node_type: str          # "tan_scene"
    tan_level: str          # "scene"
    video_name: str
    scene_index: str
    time_range: str
    clip_ids: str           # comma-separated clip node_id list
    faiss_row_id: int


# ---------------------------------------------------------------------------
# Edge schemas
# ---------------------------------------------------------------------------

class SemanticEdge(TypedDict, total=False):
    """Undirected edge between two SemanticNodes.

    Attributes:
        src_id: Source ``SemanticNode.node_id``.
        tgt_id: Target ``SemanticNode.node_id``.
        edge_type: Always ``"semantic"``.
        weight: Co-occurrence / relation weight from LLM extraction.
        description: Natural-language description of the relationship.
        source_id: Chunk IDs that support this relation.
    """

    src_id: str
    tgt_id: str
    edge_type: str          # "semantic"
    weight: float
    description: str
    source_id: str


class TemporalEdge(TypedDict, total=False):
    """Directed edge ``ClipTAN_i → ClipTAN_{i+1}`` encoding chronological flow.

    Attributes:
        src_id: Clip TAN node ID at time *t*.
        tgt_id: Clip TAN node ID at time *t+1*.
        edge_type: Always ``"temporal"``.
        delta_seconds: Duration gap between the two clips (usually 0 for
            contiguous segments, >0 for jumps).
    """

    src_id: str
    tgt_id: str
    edge_type: str          # "temporal"
    delta_seconds: float


class CrossModalEdge(TypedDict, total=False):
    """Directed edge ``SemanticNode → ClipTAN`` grounding text semantics temporally.

    Attributes:
        src_id: ``SemanticNode.node_id``.
        tgt_id: ``ClipTANNode.node_id``.
        edge_type: Always ``"cross_modal"``.
        confidence: Estimated grounding confidence (0..1; derived from chunk
            proximity or explicit alignment score).
    """

    src_id: str
    tgt_id: str
    edge_type: str          # "cross_modal"
    confidence: float


class HierarchicalEdge(TypedDict, total=False):
    """Directed edge ``ClipTAN → SceneTAN`` encoding the clip-to-scene hierarchy.

    Attributes:
        src_id: ``ClipTANNode.node_id``.
        tgt_id: ``SceneTANNode.node_id``.
        edge_type: Always ``"hierarchical"``.
    """

    src_id: str
    tgt_id: str
    edge_type: str          # "hierarchical"


# ---------------------------------------------------------------------------
# Subgraph schema — returned by query_htvg()
# ---------------------------------------------------------------------------

class HTVGSubgraph(TypedDict, total=False):
    """Rich subgraph returned by :func:`videorag.htvg.retrieval.query_htvg`.

    This is the primary interface between HTVG retrieval and the IELTS-RAG
    multi-agent debate loop.  All lists are ordered for interpretability.

    Attributes:
        semantic_nodes: Matched entity/concept nodes from semantic FAISS search.
        clip_tans: Clip-level TANs reachable via cross-modal or direct visual
            search, plus temporal-context neighbours.
        scene_tans: Scene-level TANs that aggregate the retrieved clips.
        edges: All edges in the subgraph as plain dicts (``src_id``, ``tgt_id``,
            ``edge_type``).
        segment_ids: Deduplicated, chronologically-sorted list of segment IDs
            (``"{video_name}_{index}"``) for use by downstream captioning /
            LLM grounding steps.
        provenance_paths: Human-readable trace strings, one per semantic node,
            e.g. ``"CLIMATE CHANGE → [cross_modal] → lecture_3 → [temporal]
            → lecture_4 → [hierarchical] → scene_lecture_0"``.
        query: The original query string (for logging/debugging).
        top_k: The ``top_k`` used during retrieval.
    """

    semantic_nodes: List[SemanticNode]
    clip_tans: List[ClipTANNode]
    scene_tans: List[SceneTANNode]
    edges: List[dict]
    segment_ids: List[str]
    provenance_paths: List[str]
    query: str
    top_k: int


# ---------------------------------------------------------------------------
# Build metadata — stored alongside the HTVG for provenance
# ---------------------------------------------------------------------------

class HTVGBuildMeta(TypedDict, total=False):
    """Metadata recorded at HTVG build time.

    Attributes:
        built_at: ISO-8601 timestamp of the build.
        num_semantic_nodes: Count of semantic nodes.
        num_clip_tans: Count of clip TAN nodes.
        num_scene_tans: Count of scene TAN nodes.
        num_edges: Total edge count.
        clip_dim: Dimensionality of clip-level visual embeddings.
        scene_dim: Dimensionality of scene-level aggregated embeddings.
        semantic_dim: Dimensionality of entity text embeddings.
        aggregator_checkpoint: Path to the TemporalTransformer checkpoint used.
        videos_processed: Comma-separated list of video names ingested.
    """

    built_at: str
    num_semantic_nodes: int
    num_clip_tans: int
    num_scene_tans: int
    num_edges: int
    clip_dim: int
    scene_dim: int
    semantic_dim: int
    aggregator_checkpoint: str
    videos_processed: str
