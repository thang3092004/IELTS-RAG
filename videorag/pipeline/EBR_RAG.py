"""
EBR-RAG Pipeline Orchestrator — full rewrite.

EBR_RAG_answer() is the top-level entry point called from VideoRAG.aquery()
when param.mode == "EBR_RAG".

Improvements over previous version:
- threads global_config (LLM + retrieval functions) into retrieval tools
- reads max_rounds and ebr_top_k from QueryParam
- dispatch_tool passes global_config + query_param for LLM query rewriting
- returns richer output: confidence, rounds_run, tool_calls_made
- (NEW) incorporates TVG evidence when tvg_storage is available on vrag
"""
import asyncio
import os
import re
from dataclasses import asdict
from typing import Any, List

from openai import AsyncOpenAI

from ..tools.text_tools import search_text_evidence
from ..tools.vision_tools import search_visual_segment
from ..tools.tvg_tools import search_tvg_evidence
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


async def EBR_RAG_answer(vrag, query: str, param) -> dict:
    """
    Iterative Evidence-Verification RAG (EBR-RAG pipeline).

    Args:
        vrag:   VideoRAG instance (provides all storage handles + global_config)
        query:  User question
        param:  QueryParam — controls ebr_top_k, max_rounds

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
        # TVG stores (present only when TVG ingest has been run)
        "tvg_storage":              getattr(vrag, "tvg_storage", None),
        # Embedding func exposed so tvg_tools can embed the query
        "text_embedding_func":      getattr(getattr(vrag, "embedding_func", None), "func", None)
                                    or getattr(vrag, "embedding_func", None),
    }

    # Helper for lazy ImageBind instantiation for TVG direct visual search
    def _tan_embed(q: str):
        from .._videoutil import encode_string_query
        from imagebind.models import imagebind_model
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        embedder = imagebind_model.imagebind_huge(pretrained=True).to(device)
        embedder.eval()
        return encode_string_query(q, embedder)[0].numpy()
        
    stores["tan_embedding_func"] = _tan_embed

    # global_config is the full asdict(vrag) dict — contains LLM functions, retrieval params
    global_config: dict = asdict(vrag) if hasattr(vrag, "__dataclass_fields__") else {}

    # -------------------------------------------------------------------------
    # FAIRNESS ABLATION CONTROLLER (Evidence Budgeting)
    # -------------------------------------------------------------------------
    max_rounds: int = getattr(param, "max_rounds", 3)
    use_tvg_only = getattr(param, "ebr_use_tvg_only", False)
    use_text_only = getattr(param, "ebr_use_text_only", False)
    
    # 1. Base initial budget
    # Calculate a mathematically perfectly fair evidence budget.
    # A typical 3-round debate across 3 hypotheses generates roughly 36 items 
    # (3 agents * 2 calls/round * 2 items/call * 3 rounds).
    base_top_k: int = getattr(param, "ebr_top_k", 2)
    debate_bonus = 36 
    
    if max_rounds == 0:
        # No-Debate: we pull the "debate bonus" up front.
        total_init_budget = base_top_k + (debate_bonus // 2)
        logger.info(f"[EBR_RAG] No-Debate Ablation. Boosting initial budget to {total_init_budget} to match debate capacity.")
    else:
        # Debate: we pull base items up front, agents retrieve the rest.
        total_init_budget = base_top_k
        
    # 2. Module Allocation
    # Distribute the total_init_budget across active retrieval modules
    if use_tvg_only:
        text_k, tvg_k = 0, total_init_budget * 2  # Give TVG everything
    elif use_text_only:
        text_k, tvg_k = total_init_budget * 2, 0  # Give Text everything
    else:
        text_k, tvg_k = total_init_budget, total_init_budget

    global_config["retrieval_topk_chunks"] = text_k
    # -------------------------------------------------------------------------

    # --- Stage 1: Dual retrieval (skimming & scanning) ---
    init_evidence = []
    
    # Text evidence
    text_ev = []
    if text_k > 0:
        logger.info(f"[EBR_RAG] Stage 1a — Text retrieval top_k={text_k}")
        text_ev = await search_text_evidence(query, stores, top_k=text_k, entity_boost=True,
                                             global_config=global_config, query_param=param)
    
    # Visual evidence (Baseline)
    visual_ev = []
    if stores.get("tvg_storage") is None and not use_tvg_only and not use_text_only:
        v_k = min(4, text_k) if text_k > 0 else 4
        logger.info(f"[EBR_RAG] Stage 1b — Visual retrieval (Baseline) top_k={v_k}")
        visual_ev = await search_visual_segment(query, stores, top_k=v_k,
                                               global_config=global_config, query_param=param)
    else:
        logger.info("[EBR_RAG] Stage 1b — Skipping Baseline Visual (TVG active or ablated)")

    init_evidence = _dedup_evidence(text_ev + visual_ev)

    # TVG evidence
    if stores.get("tvg_storage") is not None and tvg_k > 0:
        logger.info(f"[EBR_RAG] Stage 1c — TVG evidence top_k={tvg_k}")
        try:
            tvg_ev = await search_tvg_evidence(
                query, stores, top_k=tvg_k,
                temporal_context_hops=getattr(param, "tvg_temporal_hops", 2),
                global_config=global_config,
                query_param=param,
            )
            init_evidence = _dedup_evidence(init_evidence + tvg_ev)
            logger.info(
                f"[EBR_RAG] After TVG: evidence pool = {len(init_evidence)} items "
                f"(+{len(tvg_ev)} tvg)"
            )
        except Exception as _tvg_exc:
            logger.warning(f"[EBR_RAG] TVG evidence step failed (non-fatal): {_tvg_exc}")

    # -------------------------------------------------------------------------
    # STRICT GLOBAL FAIRNESS CAP
    # -------------------------------------------------------------------------
    # Regardless of graph expansion or debate retrieval, limit the LLM context 
    # to the exact theoretical max capacity of a Debate run.
    universal_cap = (base_top_k * 2) + debate_bonus
    if len(init_evidence) > universal_cap:
        logger.info(f"[EBR_RAG] Fairness Universal Cap: Truncating {len(init_evidence)} -> {universal_cap}")
        init_evidence = init_evidence[:universal_cap]
    else:
        logger.info(f"[EBR_RAG] Final initial evidence pool: {len(init_evidence)} items (cap is {universal_cap})")

    # --- Build LLM client ---
    model_name: str = getattr(getattr(vrag, "llm", None), "best_model_name", "gpt-4o-mini")
    try:
        llm_client: AsyncOpenAI = get_openai_async_client_instance()
    except TypeError:
        llm_client = AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL")
        )

    debate_cfg = DebateConfig(
        model=model_name,
        max_rounds=max_rounds,
        tool_top_k=base_top_k,
        critique_see_evidence=getattr(param, "debate_critique_see_evidence", False),
        defender_disable_tools=getattr(param, "debate_defender_disable_tools", False),
        single_hypothesis=getattr(param, "debate_single_hypothesis", False),
    )

    # --- Tool dispatcher (bridges debate loop → retrieval functions) ---
    async def dispatch_tool(name: str, args: dict, evidence_pool: list[EvidenceItem]) -> dict:
        q: str = args.get("query", query)
        tk: int = int(args.get("top_k", base_top_k))
        
        # Ablation: Hard limit per tool call
        tk = min(tk, 2)
        
        # Ablation: Ensure graph entity expansion in this tool call is also hard-limited
        call_config = dict(global_config)
        call_config["retrieval_topk_chunks"] = tk

        use_tvg_only = getattr(param, "ebr_use_tvg_only", False)

        if name == "search_text_evidence":
            # Enabled in both modes as requested (1 text, 2 tvg)
            evs = await search_text_evidence(
                q, stores,
                top_k=tk,
                entity_boost=bool(args.get("entity_boost", True)),
                global_config=call_config,
                query_param=param,
            )
            return {"evidence": evs}

        if name == "search_visual_segment":
            if stores.get("tvg_storage") is not None or use_tvg_only:
                return {"error": "Baseline visual search is disabled when TVG is active. Use search_tvg_evidence instead."}
            evs = await search_visual_segment(
                q, stores,
                top_k=min(tk, 2), # Ablation limit to 2
                global_config=call_config,
                query_param=param,
            )
            return {"evidence": evs}

        if name == "search_tvg_evidence":
            evs = await search_tvg_evidence(
                q, stores,
                top_k=tk,
                temporal_context_hops=int(args.get("temporal_hops", getattr(param, "tvg_temporal_hops", 2))),
                global_config=call_config,
                query_param=param,
            )
            return {"evidence": evs}

        logger.warning(f"[EBR_RAG] Unknown tool requested: {name!r}")
        return {"error": f"unknown tool: {name}"}

    # --- Detect MCQ ---
    mcq_options = _extract_mcq_options(query)
    is_mcq = len(mcq_options) > 0
    if is_mcq:
        logger.info(f"[EBR_RAG] MCQ detected with {len(mcq_options)} options")

    # --- Stage 2-4: Multi-agent debate ---
    logger.info(f"[EBR_RAG] Starting debate: max_rounds={max_rounds}, model={model_name}, mode={'MCQ' if is_mcq else 'Open'}")
    verdict, state = await run_debate(
        query=query,
        initial_evidence=init_evidence,
        llm_client=llm_client,
        tools=ALL_TOOLS,
        dispatch_tool=dispatch_tool,
        cfg=debate_cfg,
        role_cfgs=ROLE_CONFIGS,
        is_mcq=is_mcq,
        forced_hypotheses=mcq_options if is_mcq else None,
        wo_reference=param.wo_reference
    )
    # Ensure verdict is a dict (LLM might return a raw string for open-ended questions - baseline style)
    if isinstance(verdict, str):
        logger.info(f"[EBR_RAG] Verdict is a raw text string (baseline open-ended style). Wrapping.")
        verdict = {"answer": verdict, "rationale": "Synthesized from debate.", "confidence": 1.0}

    logger.info(f"[EBR_RAG] Debate complete — "
                f"rounds={state.rounds_run}, tool_calls={state.tool_calls_made}, "
                f"evidence_pool={len(state.evidence)}, "
                f"confidence={verdict.get('confidence', 'N/A')}")

    return {
        "answer":          verdict.get("answer", ""),
        "rationale":       verdict.get("rationale", ""),
        "confidence":      verdict.get("confidence", 0.0),
        "citations":       verdict.get("citations", []),
        "transcript":      state.transcript,
        "evidence":        [ev.to_dict() for ev in state.evidence],
        "rounds_run":      state.rounds_run,
        "tool_calls_made": state.tool_calls_made,
    }
