"""
videorag/tvg/schemas.py
========================
TypedDicts that define the data contracts for every node, edge, and subgraph
object in the Temporal-Visual Graph (TVG).

The TVG contains exactly two node types:
* **TANNode** — a Temporal Anchor Node, one per ~30-second video segment.
* **SemanticNode** — a text-derived entity/concept node.

And three edge types:
* **TemporalEdge** — ordered chain between consecutive TANs.
* **CrossModalEdge** — semantic entity → TAN (text-grounded to a clip).
* **SemanticEdge** — undirected relation between two SemanticNodes.

All names serialise cleanly to GraphML (flat string/int/float values).
Vector fields are stored externally in FAISS and referenced by ``faiss_row_id``.

Google-style docstrings are used throughout.
"""

from typing import List, Optional
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Node schemas
# ---------------------------------------------------------------------------

class SemanticNode(TypedDict, total=False):
    """A text-derived concept node (entity) in the TVG semantic layer.

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


class TANNode(TypedDict, total=False):
    """A Temporal Anchor Node — one per video segment (~30 s window).

    Attributes:
        node_id: ``"{video_name}_{segment_index}"``, e.g. ``"lecture_3"``.
        node_type: Always ``"tan"``.
        video_name: Base name of the source video file (no extension).
        segment_index: String integer index of the segment within the video.
        time_range: ``"start-end"`` in seconds, e.g. ``"90-120"``.
        content: Raw ``"Caption:\\n...\\nTranscript:\\n..."`` text stored in
            ``video_segments._data``.
        faiss_row_id: Integer row index into the TAN FAISS index (-1 if unindexed).
    """

    node_id: str
    node_type: str          # "tan"
    video_name: str
    segment_index: str
    time_range: str
    content: str
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
    """Directed edge ``TAN_i → TAN_{i+1}`` encoding chronological flow.

    Attributes:
        src_id: TAN node ID at time *t*.
        tgt_id: TAN node ID at time *t+1*.
        edge_type: Always ``"temporal"``.
        delta_seconds: Duration gap between the two segments (usually 0 for
            contiguous segments, >0 for jumps).
    """

    src_id: str
    tgt_id: str
    edge_type: str          # "temporal"
    delta_seconds: float


class CrossModalEdge(TypedDict, total=False):
    """Directed edge ``SemanticNode → TAN`` grounding text semantics temporally.

    Attributes:
        src_id: ``SemanticNode.node_id``.
        tgt_id: ``TANNode.node_id``.
        edge_type: Always ``"cross_modal"``.
        confidence: Estimated grounding confidence (0..1; derived from chunk
            proximity or explicit alignment score).
    """

    src_id: str
    tgt_id: str
    edge_type: str          # "cross_modal"
    confidence: float


# ---------------------------------------------------------------------------
# Subgraph schema — returned by query_tvg()
# ---------------------------------------------------------------------------

class TVGSubgraph(TypedDict, total=False):
    """Rich subgraph returned by :func:`videorag.tvg.retrieval.query_tvg`.

    This is the primary interface between TVG retrieval and the EBR-RAG
    multi-agent debate loop.  All lists are ordered for interpretability.

    Attributes:
        semantic_nodes: Matched entity/concept nodes from semantic FAISS search.
        tans: TANs reachable via cross-modal or direct visual search,
            plus temporal-context neighbours.
        edges: All edges in the subgraph as plain dicts (``src_id``, ``tgt_id``,
            ``edge_type``).
        segment_ids: Deduplicated, chronologically-sorted list of segment IDs
            (``"{video_name}_{index}"``) for use by downstream captioning /
            LLM grounding steps.
        provenance_paths: Human-readable trace strings, one per semantic node,
            e.g. ``"CLIMATE CHANGE → [cross_modal] → lecture_3 → [temporal] → lecture_4"``.
        query: The original query string (for logging/debugging).
        top_k: The ``top_k`` used during retrieval.
    """

    semantic_nodes: List[SemanticNode]
    tans: List[TANNode]
    edges: List[dict]
    segment_ids: List[str]
    provenance_paths: List[str]
    query: str
    top_k: int


# ---------------------------------------------------------------------------
# Build metadata — stored alongside the TVG for provenance
# ---------------------------------------------------------------------------

class TVGBuildMeta(TypedDict, total=False):
    """Metadata recorded at TVG build time.

    Attributes:
        built_at: ISO-8601 timestamp of the build.
        num_semantic_nodes: Count of semantic nodes.
        num_tans: Count of TAN nodes.
        num_edges: Total edge count.
        tan_dim: Dimensionality of TAN visual embeddings (ImageBind).
        semantic_dim: Dimensionality of entity text embeddings.
        videos_processed: Comma-separated list of video names ingested.
    """

    built_at: str
    num_semantic_nodes: int
    num_tans: int
    num_edges: int
    tan_dim: int
    semantic_dim: int
    videos_processed: str
