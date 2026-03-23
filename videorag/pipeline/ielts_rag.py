import asyncio
from typing import Any
from openai import AsyncOpenAI

from ..tools.text_tools import search_text_evidence
from ..tools.vision_tools import search_visual_segment
from ..tools.schemas import ALL_TOOLS
from ..debate.debate_manager import run_debate
from ..debate.state import DebateConfig
from ..debate.evidence_types import EvidenceItem
from ..agents.roles import ROLE_CONFIGS
from .._llm import get_openai_async_client_instance


def _dedup_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen = set()
    deduped = []
    for ev in items:
        if ev.id in seen:
            continue
        seen.add(ev.id)
        deduped.append(ev)
    return deduped


async def ielts_rag_answer(vrag, query: str, param) -> dict:
    """Iterative Evidence-Verification RAG tailored for IELTS-style Q&A."""

    stores: dict[str, Any] = {
        "chunks_vdb": getattr(vrag, "chunks_vdb", None),
        "text_chunks": getattr(vrag, "text_chunks", None),
        "entities_vdb": getattr(vrag, "entities_vdb", None),
        "knowledge_graph": getattr(vrag, "chunk_entity_relation_graph", None),
        "video_segment_feature_vdb": getattr(vrag, "video_segment_feature_vdb", None),
        "video_segments": getattr(vrag, "video_segments", None),
    }

    top_k = getattr(param, "top_k", 6) if param else 6

    init_ev: list[EvidenceItem] = []
    init_ev += await search_text_evidence(query, stores, top_k=top_k, entity_boost=True)
    init_ev += await search_visual_segment(query, stores, top_k=min(4, top_k))
    init_ev = _dedup_evidence(init_ev)

    model_name = getattr(getattr(vrag, "llm", None), "best_model_name", "gpt-4o-mini")
    debate_cfg = DebateConfig(model=model_name, max_rounds=2, tool_top_k=top_k)

    try:
        llm_client: AsyncOpenAI = get_openai_async_client_instance()
    except TypeError:
        llm_client = AsyncOpenAI()

    async def dispatch_tool(name: str, args: dict, evidence_pool: list[EvidenceItem]):
        if name == "search_text_evidence":
            evs = await search_text_evidence(args.get("query", ""), stores, args.get("top_k", top_k), args.get("entity_boost", True))
            return {"evidence": evs}
        if name == "search_visual_segment":
            evs = await search_visual_segment(args.get("query", ""), stores, args.get("top_k", min(4, top_k)))
            return {"evidence": evs}
        return {"error": f"unknown tool {name}"}

    final_answer, state = await run_debate(
        query=query,
        initial_evidence=init_ev,
        llm_client=llm_client,
        tools=ALL_TOOLS,
        dispatch_tool=dispatch_tool,
        cfg=debate_cfg,
        role_cfgs=ROLE_CONFIGS,
    )

    return {
        "answer": final_answer.get("answer") if isinstance(final_answer, dict) else str(final_answer),
        "rationale": final_answer.get("rationale") if isinstance(final_answer, dict) else "",
        "citations": final_answer.get("citations") if isinstance(final_answer, dict) else [],
        "transcript": state.transcript,
        "evidence": [ev.__dict__ for ev in state.evidence],
    }
