TEXT_GRAPH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_text_evidence",
        "description": "Retrieve textual or graph-related evidence (chunks/entities/linked segments) relevant to a query or sub-question.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query or sub-question."},
                "top_k": {"type": "integer", "description": "Max items", "minimum": 1, "maximum": 20, "default": 6},
                "entity_boost": {"type": "boolean", "description": "Expand via entity/graph retrieval", "default": True},
            },
            "required": ["query"],
        },
    }
}

VISUAL_TOOL = {
    "type": "function",
    "function": {
        "name": "search_visual_segment",
        "description": "Retrieve video segments using cross-modal embeddings (ImageBind) from a visual/text hint.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Visual or textual description to match segments."},
                "top_k": {"type": "integer", "description": "Max segments", "minimum": 1, "maximum": 10, "default": 4},
            },
            "required": ["query"],
        },
    }
}

TVG_TOOL = {
    "type": "function",
    "function": {
        "name": "search_tvg_evidence",
        "description": "Retrieve deep evidence using the Temporal-Visual Graph (TVG). Captures cross-modal links and temporal contexts (before/after events).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query or event description."},
                "top_k": {"type": "integer", "description": "Max items", "minimum": 1, "maximum": 20, "default": 4},
                "temporal_hops": {"type": "integer", "description": "Number of temporal hops to expand context", "minimum": 0, "maximum": 5, "default": 2},
            },
            "required": ["query"],
        },
    }
}

ALL_TOOLS = [TEXT_GRAPH_TOOL, VISUAL_TOOL, TVG_TOOL]

