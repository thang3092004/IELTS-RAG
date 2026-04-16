"""
videorag/tvg/__init__.py
=========================
Public surface of the ``videorag.tvg`` package.

Everything that downstream components (storage, tools, pipeline) need is
re-exported here for a clean single-import experience.
"""

from .schemas import (
    SemanticNode,
    TANNode,
    SemanticEdge,
    TemporalEdge,
    CrossModalEdge,
    TVGSubgraph,
    TVGBuildMeta,
)
from .graph import TVGraph
from .builder import build_tvg
from .retrieval import query_tvg, async_query_tvg

__all__ = [
    # Schemas
    "SemanticNode",
    "TANNode",
    "SemanticEdge",
    "TemporalEdge",
    "CrossModalEdge",
    "TVGSubgraph",
    "TVGBuildMeta",
    # Core class
    "TVGraph",
    # Functions
    "build_tvg",
    "query_tvg",
    "async_query_tvg",
]
