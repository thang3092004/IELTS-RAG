"""
IELTS-RAG Pipeline Orchestrator — full rewrite.

ielts_rag_answer() is the top-level entry point called from VideoRAG.aquery()
when param.mode == "ielts_rag".

Improvements over previous version:
- threads global_config (LLM + retrieval functions) into retrieval tools
- reads max_rounds and ielts_top_k from QueryParam
- dispatch_tool passes global_config + query_param for LLM query rewriting
- returns richer output: confidence, rounds_run, tool_calls_made
- (NEW) incorporates HTVG evidence when htvg_storage is available on vrag
"""
import asyncio
import re
from dataclasses import asdict
from typing import Any, List

from openai import AsyncOpenAI

from ..tools.text_tools import search_text_evidence
from ..tools.vision_tools import search_visual_segment
from ..tools.htvg_tools import search_htvg_evidence
from ..tools.schemas import ALL_TOOLS
from ..debate.debate_manager import run_debate
from ..debate.state import DebateConfig, DebateState
from ..debate.evidence_types import EvidenceItem
from ..agents.roles import ROLE_CONFIGS
from .._llm import get_openai_async_client_instance
from .._utils import logger


def _extract_mcq_options(query: str) -> List[dict]:
    """Helper to extract options from queries like '(A) apple (B) banana'."""
    options = []
    # Matches patterns like (A) text or A) text
    pattern = r'(?:\(?([A-D])[\)\.])\s*([^\(\n]+)'
    matches = re.findall(pattern, query)
    for label, text in matches:
        options.append({
            "id": f"Option {label}",
            "claim": f"{label}) {text.strip()}",
            "reasoning": f"Official option {label} from the multiple-choice query."
        })
    return options


def _dedup_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[str] = set()
    deduped: list[EvidenceItem] = []
    for ev in items:
        if ev.id in seen:
            continue
        seen.add(ev.id)
        deduped.append(ev)
    return deduped


async def ielts_rag_answer(vrag, query: str, param) -> dict:
    """
    Iterative Evidence-Verification RAG (IELTS-RAG pipeline).

    Args:
        vrag:   VideoRAG instance (provides all storage handles + global_config)
        query:  User question
        param:  QueryParam — controls ielts_top_k, max_rounds

    Returns:
        {answer, rationale, confidence, citations, transcript,
         evidence, rounds_run, tool_calls_made}
    """
    # --- Build store handles & config ---
    stores: dict[str, Any] = {
        "chunks_vdb":               getattr(vrag, "chunks_vdb", None),
        "text_chunks":              getattr(vrag, "text_chunks", None),
        "entities_vdb":             getattr(vrag, "entities_vdb", None),
        "knowledge_graph":          getattr(vrag, "chunk_entity_relation_graph", None),
        "video_segment_feature_vdb": getattr(vrag, "video_segment_feature_vdb", None),
        "video_segments":           getattr(vrag, "video_segments", None),
        # HTVG stores (present only when HTVG ingest has been run)
        "htvg_storage":             getattr(vrag, "htvg_storage", None),
        # Embedding func exposed so htvg_tools can embed the query
        "text_embedding_func":      getattr(getattr(vrag, "embedding_func", None), "func", None)
                                    or getattr(vrag, "embedding_func", None),
    }

    # global_config is the full asdict(vrag) dict — contains LLM functions, retrieval params
    global_config: dict = asdict(vrag) if hasattr(vrag, "__dataclass_fields__") else {}

    top_k: int = getattr(param, "ielts_top_k", 2) # Ablation: Very small initial top_k
    max_rounds: int = getattr(param, "max_rounds", 3) # Ablation: Increase rounds to 3
    
    # Ablation: Explicitly limit graph entity expansion for IELTS-RAG down to top_k. 
    # (Because the baseline VideoRAG config now has this set to 15)
    global_config["retrieval_topk_chunks"] = top_k

    # --- Stage 1: Dual retrieval (skimming & scanning) ---
    logger.info(f"[ielts_rag] Stage 1 — dual retrieval top_k={top_k}")
    text_ev, visual_ev = await asyncio.gather(
        search_text_evidence(query, stores, top_k=top_k, entity_boost=True,
                             global_config=global_config, query_param=param),
        search_visual_segment(query, stores, top_k=min(4, top_k),
                              global_config=global_config, query_param=param),
    )
    init_evidence = _dedup_evidence(text_ev + visual_ev)
    logger.info(f"[ielts_rag] Initial evidence pool: {len(init_evidence)} items "
                f"({len(text_ev)} text, {len(visual_ev)} visual)")

    # --- Stage 1b: HTVG evidence (additive, skipped if htvg_storage is None) ---
    if stores.get("htvg_storage") is not None:
        logger.info(f"[ielts_rag] Stage 1b — HTVG evidence top_k={top_k}")
        try:
            htvg_ev = await search_htvg_evidence(
                query, stores, top_k=top_k,
                temporal_context_hops=2,
                global_config=global_config,
                query_param=param,
            )
            init_evidence = _dedup_evidence(init_evidence + htvg_ev)
            logger.info(
                f"[ielts_rag] After HTVG: evidence pool = {len(init_evidence)} items "
                f"(+{len(htvg_ev)} htvg)"
            )
        except Exception as _htvg_exc:
            logger.warning(f"[ielts_rag] HTVG evidence step failed (non-fatal): {_htvg_exc}")


    # --- Build LLM client ---
    model_name: str = getattr(getattr(vrag, "llm", None), "best_model_name", "gpt-4o-mini")
    try:
        llm_client: AsyncOpenAI = get_openai_async_client_instance()
    except TypeError:
        llm_client = AsyncOpenAI()

    debate_cfg = DebateConfig(model=model_name, max_rounds=max_rounds, tool_top_k=top_k)

    # --- Tool dispatcher (bridges debate loop → retrieval functions) ---
    async def dispatch_tool(name: str, args: dict, evidence_pool: list[EvidenceItem]) -> dict:
        q: str = args.get("query", query)
        tk: int = int(args.get("top_k", top_k))
        
        # Ablation: Hard limit per tool call
        tk = min(tk, 2)
        
        # Ablation: Ensure graph entity expansion in this tool call is also hard-limited
        call_config = dict(global_config)
        call_config["retrieval_topk_chunks"] = tk

        if name == "search_text_evidence":
            evs = await search_text_evidence(
                q, stores,
                top_k=tk,
                entity_boost=bool(args.get("entity_boost", True)),
                global_config=call_config,
                query_param=param,
            )
            return {"evidence": evs}

        if name == "search_visual_segment":
            evs = await search_visual_segment(
                q, stores,
                top_k=min(tk, 2), # Ablation limit to 2
                global_config=call_config,
                query_param=param,
            )
            return {"evidence": evs}

        if name == "search_htvg_evidence":
            evs = await search_htvg_evidence(
                q, stores,
                top_k=tk,
                temporal_context_hops=int(args.get("temporal_hops", 2)),
                global_config=call_config,
                query_param=param,
            )
            return {"evidence": evs}

        logger.warning(f"[ielts_rag] Unknown tool requested: {name!r}")
        return {"error": f"unknown tool: {name}"}

    # --- Detect MCQ ---
    mcq_options = _extract_mcq_options(query)
    is_mcq = len(mcq_options) > 0
    if is_mcq:
        logger.info(f"[ielts_rag] MCQ detected with {len(mcq_options)} options")

    # --- Stage 2-4: Multi-agent debate ---
    logger.info(f"[ielts_rag] Starting debate: max_rounds={max_rounds}, model={model_name}, mode={'MCQ' if is_mcq else 'Open'}")
    verdict, state = await run_debate(
        query=query,
        initial_evidence=init_evidence,
        llm_client=llm_client,
        tools=ALL_TOOLS,
        dispatch_tool=dispatch_tool,
        cfg=debate_cfg,
        role_cfgs=ROLE_CONFIGS,
        is_mcq=is_mcq,
        forced_hypotheses=mcq_options if is_mcq else None
    )
    logger.info(f"[ielts_rag] Debate complete — "
                f"rounds={state.rounds_run}, tool_calls={state.tool_calls_made}, "
                f"evidence_pool={len(state.evidence)}, "
                f"confidence={verdict.get('confidence', 'N/A')}")

    return {
        "answer":          verdict.get("answer", ""),
        "rationale":       verdict.get("rationale", ""),
        "confidence":      verdict.get("confidence", 0.0),
        "citations":       verdict.get("citations", []),    # validated citation list
        "transcript":      state.transcript,
        "evidence":        [ev.to_dict() for ev in state.evidence],
        "rounds_run":      state.rounds_run,
        "tool_calls_made": state.tool_calls_made,
    }
