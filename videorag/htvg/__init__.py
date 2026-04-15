"""
videorag/htvg/__init__.py
=========================
Public surface of the ``videorag.htvg`` package.

Everything that downstream components (storage, tools, pipeline) need is
re-exported here for a clean single-import experience.
"""

from .schemas import (
    SemanticNode,
    ClipTANNode,
    SceneTANNode,
    SemanticEdge,
    TemporalEdge,
    CrossModalEdge,
    HierarchicalEdge,
    HTVGSubgraph,
    HTVGBuildMeta,
)
from .graph import HTVGraph
from .aggregator import TemporalTransformer, HierarchicalAggregator
from .builder import build_htvg
from .retrieval import query_htvg, async_query_htvg

__all__ = [
    # Schemas
    "SemanticNode",
    "ClipTANNode",
    "SceneTANNode",
    "SemanticEdge",
    "TemporalEdge",
    "CrossModalEdge",
    "HierarchicalEdge",
    "HTVGSubgraph",
    "HTVGBuildMeta",
    # Core classes
    "HTVGraph",
    "TemporalTransformer",
    "HierarchicalAggregator",
    # Functions
    "build_htvg",
    "query_htvg",
    "async_query_htvg",
]
