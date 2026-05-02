"""
EBR-RAG Debate Manager — full rewrite.

Key improvements over previous version:
1. Generator outputs structured JSON hypotheses (deterministic parsing)
2. Defenders run CONCURRENTLY via asyncio.gather — each has isolated message history
3. Shared evidence pool is append-only (asyncio single-thread → no race conditions)
4. Tool-call loops use while-has_tool_calls pattern (not fixed depth)
5. Citation validation: judge citations are cross-checked against real evidence pool IDs
6. Observability: state.rounds_run and state.tool_calls_made are incremented
"""
import json
import asyncio
import logging
from typing import List, Callable, Any

from ..agents import agents_prompts
from ..agents.roles import ROLE_CONFIGS, RoleConfig
from ..debate.state import DebateConfig, DebateState
from ..debate.evidence_types import EvidenceItem
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import RateLimitError, APIConnectionError, BadRequestError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level LLM call
# ---------------------------------------------------------------------------

def clean_toxic_json_chars(obj: Any) -> Any:
    """Recursively clean strings within any object hierarchy to remove JSON-breaking characters and surrogates."""
    if isinstance(obj, str):
        import re, unicodedata
        # Remove control characters except \n, \r, \t
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", obj)
        # Fix surrogates and normalize
        text = text.encode("utf-8", "ignore").decode("utf-8")
        return unicodedata.normalize("NFC", text)
    elif isinstance(obj, list):
        return [clean_toxic_json_chars(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: clean_toxic_json_chars(v) for k, v in obj.items()}
    # Handle OpenAI types like ChatCompletionMessageToolCall by converting to dict if needed?
    # Actually, the most robust way is to use getattr if it's an object
    elif hasattr(obj, "__dict__") or hasattr(obj, "model_dump"):
        try:
            # Pydantic or NamedTuple / Simple Namespace
            d = obj.model_dump() if hasattr(obj, "model_dump") else vars(obj)
            return clean_toxic_json_chars(d)
        except:
            return obj
    return obj

@retry(
    stop=stop_after_attempt(12),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type((RateLimitError, APIConnectionError, BadRequestError)),
)
async def _chat(
    llm_client,
    model: str,
    messages: list[dict],
    tools=None,
    tool_choice: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
):
    # CRITICAL: Clean everything twice. Standardize to pure serializable dicts.
    safe_messages = clean_toxic_json_chars(messages)
    
    kwargs: dict[str, Any] = {"model": model, "messages": safe_messages}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    
    return await llm_client.chat.completions.create(**kwargs)


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------

def _format_evidence(evs: List[EvidenceItem], limit: int = 50) -> str:
    rows = []
    for ev in evs[:limit]:
        row = f"[{ev.id}] ({ev.type}) score={ev.score:.3f} src={ev.source}"
        if ev.video_name and ev.time_range:
            row += f" | video={ev.video_name} time={ev.time_range}"
        if ev.snippet:
            # Removed the destructive [:300] truncation to ensure fairness with Naive RAG
            row += f"\n  Snippet: {ev.snippet}"
        rows.append(row)
    return "\n\n".join(rows)


def _compact_transcript(transcript: list[dict], limit: int = 40, max_chars: int = 600) -> list[dict]:
    trimmed = transcript[-limit:]
    compact = []
    for msg in trimmed:
        content = msg.get("content") or ""
        if isinstance(content, str) and len(content) > max_chars:
            content = content[:max_chars] + "…"
        compact.append({k: v for k, v in msg.items() if k not in {"tool_calls"}} | {"content": content})
    return compact


def _validate_citations(citations: list[dict], evidence_pool: List[EvidenceItem]) -> list[dict]:
    """
    Cross-check judge citations against valid evidence IDs.
    Sets `validated=True` on matching EvidenceItems; flags invalid ones in returned list.
    """
    valid_ids = {ev.id for ev in evidence_pool}
    validated = []
    for cite in citations:
        eid = cite.get("evidence_id", "")
        is_valid = eid in valid_ids
        if is_valid:
            # Mark the evidence item as validated
            for ev in evidence_pool:
                if ev.id == eid:
                    ev.validated = True
                    break
        validated.append({**cite, "validated": is_valid})
    return validated


# ---------------------------------------------------------------------------
# Stage 2 — Generator
# ---------------------------------------------------------------------------

async def _generate_hypotheses(
    query: str,
    evidence: List[EvidenceItem],
    llm_client,
    cfg: DebateConfig,
    role_cfgs: dict = ROLE_CONFIGS,
) -> list[dict]:
    """Returns list of {id, claim, reasoning} dicts. Falls back gracefully on bad JSON."""
    r_cfg: RoleConfig = role_cfgs.get("generator", RoleConfig(model=cfg.model))
    ctx = _format_evidence(evidence)
    messages = [
        {"role": "system", "content": agents_prompts.GENERATOR_PROMPT_OPEN},
        {"role": "user", "content": f"Query: {query}\n\nEvidence Pool:\n{ctx}"},
    ]
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        resp = await _chat(
            llm_client, r_cfg.model, messages,
            temperature=r_cfg.temperature, max_tokens=r_cfg.max_tokens,
        )
        raw = (resp.choices[0].message.content or "").strip()
        
        # Robust JSON extraction — Generator returns an array [...], not an object {...}
        from .._utils import locate_json_array_from_string
        json_body = locate_json_array_from_string(raw)
        
        if json_body:
            try:
                hypotheses = json.loads(json_body)
                if isinstance(hypotheses, list) and hypotheses:
                    return hypotheses
            except json.JSONDecodeError:
                pass
        
        retry_count += 1
        logger.warning(f"[Generator] Could not parse JSON hypotheses (attempt {retry_count}/{max_retries}). Retrying...")

    # If all retries fail, then we raise an error because the user wants "perfection" and no fallbacks
    logger.error("[Generator] Failed to generate valid hypotheses after all retries.")
    raise ValueError("Generator failed to produce valid JSON hypotheses. Check LLM connectivity or prompt clarity.")


# ---------------------------------------------------------------------------
# Stage 3 — Single Defender coroutine (runs independently per hypothesis)
# ---------------------------------------------------------------------------

async def _defend_hypothesis(
    hypothesis: dict,
    query: str,
    state: DebateState,
    llm_client,
    tools: list[dict],
    dispatch_tool: Callable,
    cfg: DebateConfig,
    role_cfgs: dict = ROLE_CONFIGS,
    is_mcq: bool = False,
) -> str:
    """
    Defends one hypothesis in isolation. Has its own local message history.
    Appends new evidence to state.evidence (append-only → asyncio-safe).
    Returns a defence summary string to be added to the shared transcript.
    """
    r_cfg: RoleConfig = role_cfgs.get("defender", RoleConfig(model=cfg.model))
    prompt_tpl = agents_prompts.DEFENDER_PROMPT_MCQ if is_mcq else agents_prompts.DEFENDER_PROMPT_OPEN
    system_prompt = prompt_tpl.format(
        hypothesis_claim=hypothesis.get("claim", ""),
        hypothesis_reasoning=hypothesis.get("reasoning", ""),
        assigned_option=hypothesis.get("claim", ""),  # for MCQ
        query=query                                 # for MCQ
    )
    # Local message history (never shared with parallel defenders)
    local_msgs: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"Query: {query}\n"
            f"Your hypothesis {hypothesis.get('id')}: {hypothesis.get('claim')}\n"
            f"Current evidence:\n{_format_evidence(state.evidence)}"
        )},
    ]
    # Tool-call loop variables (must be declared before the early-return branch)
    max_calls = 3
    calls_made = 0

    # Ablation: Disable tool calling — make a single LLM call WITHOUT tools
    if getattr(cfg, "defender_disable_tools", False):
        resp = await _chat(
            llm_client, r_cfg.model, local_msgs,
            tools=None, tool_choice=None,
            temperature=r_cfg.temperature, max_tokens=r_cfg.max_tokens,
        )
        return resp.choices[0].message.content or ""

    while calls_made < max_calls and state.tool_calls_made < 25:  # Global limit 25
        resp = await _chat(
            llm_client, r_cfg.model, local_msgs,
            tools=tools, tool_choice="auto",
            temperature=r_cfg.temperature, max_tokens=r_cfg.max_tokens,
        )
        msg = resp.choices[0].message
        local_msgs.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [tc.model_dump() for tc in msg.tool_calls] if msg.tool_calls else None,
        })

        if not msg.tool_calls:
            # No more tool calls → defender is done
            return msg.content or ""

        # Dispatch tool calls
        for call in msg.tool_calls:
            state.tool_calls_made += 1
            calls_made += 1
            args = json.loads(call.function.arguments or "{}")
            result = await dispatch_tool(call.function.name, args, state.evidence)
            new_evs: list[EvidenceItem] = result.get("evidence", []) if isinstance(result, dict) else []
            state.evidence.extend(new_evs)
            local_msgs.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.function.name,
                "content": json.dumps(
                    {"evidence_added": len(new_evs), "ids": [e.id for e in new_evs]},
                    ensure_ascii=False
                ),
            })

    if state.tool_calls_made >= 25:
        logger.warning(f"[Defender] Reached global tool call limit (25) — finishing early")
    elif calls_made >= max_calls:
        logger.warning(f"[Defender] Reached max local tool calls ({max_calls}) — finishing early")

    # Get the last assistant message (not user message)
    for msg in reversed(local_msgs):
        if msg.get("role") == "assistant" and msg.get("content"):
            return msg["content"]
    return "No response generated."


# ---------------------------------------------------------------------------
# Stage 3 — Critique coroutine
# ---------------------------------------------------------------------------

async def _run_critique(
    query: str,
    hypotheses: list[dict],
    state: DebateState,
    defender_summaries: list[str],
    llm_client,
    tools: list[dict],
    dispatch_tool: Callable,
    cfg: DebateConfig,
    role_cfgs: dict = ROLE_CONFIGS,
    is_mcq: bool = False,
) -> str:
    r_cfg: RoleConfig = role_cfgs.get("critique", RoleConfig(model=cfg.model))
    hyp_summary = "\n".join(
        f"{h.get('id')}: {h.get('claim')} — Defence: {s[:200]}"
        for h, s in zip(hypotheses, defender_summaries)
    )
    prompt_base = agents_prompts.CRITIQUE_PROMPT_MCQ if is_mcq else agents_prompts.CRITIQUE_PROMPT_OPEN
    # Critique is intentionally blinded from tools/evidence; single-shot critique.
    # Ablation: Allow Critique to see the full evidence pool
    evidence_ctx = ""
    if getattr(cfg, "critique_see_evidence", False):
        evidence_ctx = f"\n\nFull Evidence Pool:\n{_format_evidence(state.evidence, limit=50)}"

    local_msgs: list[dict] = [
        {"role": "system", "content": prompt_base},
        {"role": "user", "content": (
            f"Query: {query}\n\n"
            f"Hypotheses & Defences:\n{hyp_summary}\n\n"
            f"{'Note: Challenge the options for this MCQ.' if is_mcq else ''}"
            f"{evidence_ctx}"
        )},
    ]
    resp = await _chat(
        llm_client, r_cfg.model, local_msgs,
        tools=None, tool_choice=None,
        temperature=r_cfg.temperature, max_tokens=r_cfg.max_tokens,
    )
    msg = resp.choices[0].message
    return msg.content or ""


# ---------------------------------------------------------------------------
# Stage 4 — Judge
# ---------------------------------------------------------------------------

async def _run_judge(
    query: str,
    state: DebateState,
    llm_client,
    cfg: DebateConfig,
    role_cfgs: dict = ROLE_CONFIGS,
    is_mcq: bool = False,
    wo_reference: bool = True,
) -> dict:
    r_cfg: RoleConfig = role_cfgs.get("judge", RoleConfig(model=cfg.model))
    compact_transcript = _compact_transcript(state.transcript, limit=50, max_chars=600)
    
    if is_mcq:
        prompt_base = agents_prompts.JUDGE_PROMPT_MCQ
    else:
        prompt_base = agents_prompts.JUDGE_PROMPT_OPEN
        if not wo_reference:
            # Inject citation instructions if references are requested
            prompt_base += "\n\n" + agents_prompts.JUDGE_CITATION_INSTRUCTIONS

    judge_msgs = [
        {"role": "system", "content": prompt_base},
        {"role": "user", "content": (
            f"Query: {query}\n\n"
            f"Debate Transcript:\n{json.dumps(compact_transcript, ensure_ascii=False)}\n\n"
            f"Full Evidence Pool:\n{_format_evidence(state.evidence, limit=50)}"
        )},
    ]
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        resp = await _chat(
            llm_client, r_cfg.model, judge_msgs,
            temperature=r_cfg.temperature, max_tokens=r_cfg.max_tokens,
        )
        raw = (resp.choices[0].message.content or "").strip()
        
        # Robust JSON extraction using baseline's regex logic
        from .._utils import locate_json_string_body_from_string
        json_body = locate_json_string_body_from_string(raw)
        
        if json_body:
            try:
                verdict = json.loads(json_body)
                # Normalize keys to match EBR-RAG internal expectations
                if is_mcq:
                    normalized = {
                        "Answer": verdict.get("Answer", verdict.get("answer", "")),
                        "Explanation": verdict.get("Explanation", verdict.get("rationale", "")),
                        "Confidence": verdict.get("Confidence", verdict.get("confidence", 1.0))
                    }
                    # Internal code uses lowercase answer/rationale/confidence, let's keep that but support capitalized from LLM
                    final_verdict = {
                        "answer": normalized["Answer"],
                        "rationale": normalized["Explanation"],
                        "confidence": normalized["Confidence"]
                    }
                    return final_verdict
                return verdict
            except json.JSONDecodeError:
                pass
        
        if not is_mcq:
            # For Open-ended, if JSON parsing fails, it's likely intentional Markdown output (baseline style)
            # We don't retry for Open-ended if it looks like a valid text response
            logger.info("[Judge] Open-ended response received as text (Baseline style)")
            return {"answer": raw, "rationale": "Synthesized from debate.", "confidence": 1.0, "citations": []}

        retry_count += 1
        logger.warning(f"[Judge] MCQ response not valid JSON (attempt {retry_count}/{max_retries}). Retrying...")

    # Final fallback if all retries fail
    if is_mcq:
        logger.error("[Judge] Failed to generate valid MCQ JSON after all retries.")
        raise ValueError("MCQ Judge failed to produce valid JSON. Aborting to prevent data corruption.")
        
    logger.warning("[Judge] All retries failed — wrapping raw response as answer")
    return {"answer": raw, "rationale": "Fallback after failed JSON parsing.", "confidence": 0.0, "citations": []}


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

async def run_debate(
    query: str,
    initial_evidence: List[EvidenceItem],
    llm_client,
    tools: list[dict],
    dispatch_tool: Callable[[str, dict, list[EvidenceItem]], Any],
    cfg: DebateConfig,
    role_cfgs: dict = ROLE_CONFIGS,
    is_mcq: bool = False,
    forced_hypotheses: list[dict] | None = None,
    wo_reference: bool = True,
) -> tuple[dict, DebateState]:
    """
    Run the full EBR-RAG debate pipeline.

    Returns:
        (final_answer_dict, state)
        final_answer_dict has keys: answer, rationale, confidence, citations (validated)
    """
    state = DebateState(query=query, evidence=list(initial_evidence))

    # --- Stage 2: Generate or use forced hypotheses ---
    if is_mcq and forced_hypotheses:
        hypotheses = forced_hypotheses
    else:
        hypotheses = await _generate_hypotheses(query, state.evidence, llm_client, cfg, role_cfgs)
        
        # Ablation: Single hypothesis mode
        if getattr(cfg, "single_hypothesis", False) and len(hypotheses) > 1:
            logger.info(f"[Debate] Ablation: Single hypothesis mode. Truncating {len(hypotheses)} -> 1")
            hypotheses = hypotheses[:1]
    
    state.transcript.append({
        "role": "system",
        "content": f"[Generator/MCQ] Using {len(hypotheses)} candidates:\n" +
                   "\n".join(f"  {h.get('id')}: {h.get('claim')}" for h in hypotheses),
    })

    # --- Stage 3: Debate rounds (defend concurrently → critique sequentially) ---
    for round_num in range(cfg.max_rounds):
        state.rounds_run += 1

        # Run all defenders CONCURRENTLY — each coroutine has its own local message history
        defender_summaries: list[str] = await asyncio.gather(*[
            _defend_hypothesis(h, query, state, llm_client, tools, dispatch_tool, cfg, role_cfgs, is_mcq)
            for h in hypotheses
        ])

        # Append defender summaries to shared transcript
        for h, summary in zip(hypotheses, defender_summaries):
            state.transcript.append({
                "role": "assistant",
                "content": f"[{'Advocate' if is_mcq else 'Defender'} {h.get('id')}] {summary}",
            })

        # Run critique
        critique_summary = await _run_critique(
            query, hypotheses, state, defender_summaries,
            llm_client, tools, dispatch_tool, cfg, role_cfgs, is_mcq
        )
        state.transcript.append({
            "role": "assistant",
            "content": f"[{'Prosecutor' if is_mcq else 'Critique'} Round {round_num + 1}] {critique_summary}",
        })

    # --- Stage 4: Judge ---
    verdict = await _run_judge(query, state, llm_client, cfg, role_cfgs, is_mcq, wo_reference)

    # --- Citation validation ---
    raw_citations = verdict.get("citations", [])
    verdict["citations"] = _validate_citations(raw_citations, state.evidence)

    invalid = [c for c in verdict["citations"] if not c.get("validated")]
    if invalid:
        logger.warning(f"[Judge] {len(invalid)} citation(s) not found in evidence pool: "
                       f"{[c.get('evidence_id') for c in invalid]}")

    return verdict, state
