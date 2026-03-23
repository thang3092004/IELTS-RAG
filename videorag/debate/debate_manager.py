"""
IELTS-RAG Debate Manager — full rewrite.

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

from ..agents.agents_prompts import (
    GENERATOR_PROMPT,
    DEFENDER_PROMPT,
    CRITIQUE_PROMPT,
    JUDGE_PROMPT,
)
from ..agents.roles import ROLE_CONFIGS, RoleConfig
from ..debate.state import DebateConfig, DebateState
from ..debate.evidence_types import EvidenceItem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level LLM call
# ---------------------------------------------------------------------------

async def _chat(
    llm_client,
    model: str,
    messages: list[dict],
    tools=None,
    tool_choice: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
):
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
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

def _format_evidence(evs: List[EvidenceItem], limit: int = 15) -> str:
    rows = []
    for ev in evs[:limit]:
        row = f"[{ev.id}] ({ev.type}) score={ev.score:.3f} src={ev.source}"
        if ev.video_name and ev.time_range:
            row += f" | video={ev.video_name} time={ev.time_range}"
        if ev.snippet:
            row += f"\n  Snippet: {ev.snippet[:300]}"
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
        {"role": "system", "content": GENERATOR_PROMPT},
        {"role": "user", "content": f"Query: {query}\n\nEvidence Pool:\n{ctx}"},
    ]
    resp = await _chat(
        llm_client, r_cfg.model, messages,
        temperature=r_cfg.temperature, max_tokens=r_cfg.max_tokens,
    )
    raw = (resp.choices[0].message.content or "").strip()

    # Robust JSON parsing
    try:
        hypotheses = json.loads(raw)
        if isinstance(hypotheses, list) and hypotheses:
            return hypotheses
    except json.JSONDecodeError:
        pass

    # Fallback: wrap the whole response as a single hypothesis
    logger.warning("[Generator] Could not parse JSON hypotheses — falling back to single hypothesis")
    return [{"id": "H1", "claim": raw[:200], "reasoning": "Generated as fallback (JSON parse error)"}]


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
) -> str:
    """
    Defends one hypothesis in isolation. Has its own local message history.
    Appends new evidence to state.evidence (append-only → asyncio-safe).
    Returns a defence summary string to be added to the shared transcript.
    """
    r_cfg: RoleConfig = role_cfgs.get("defender", RoleConfig(model=cfg.model))
    system_prompt = DEFENDER_PROMPT.format(
        hypothesis_claim=hypothesis.get("claim", ""),
        hypothesis_reasoning=hypothesis.get("reasoning", ""),
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

    # Tool-call loop
    max_calls = 5
    calls_made = 0
    while calls_made < max_calls:
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
    
    logger.warning(f"[Defender] Reached max tool calls ({max_calls}) — finishing early")
    return local_msgs[-1].get("content") or "Reached tool call limit."


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
) -> str:
    r_cfg: RoleConfig = role_cfgs.get("critique", RoleConfig(model=cfg.model))
    hyp_summary = "\n".join(
        f"{h.get('id')}: {h.get('claim')} — Defence: {s[:200]}"
        for h, s in zip(hypotheses, defender_summaries)
    )
    local_msgs: list[dict] = [
        {"role": "system", "content": CRITIQUE_PROMPT},
        {"role": "user", "content": (
            f"Query: {query}\n\n"
            f"Hypotheses & Defences:\n{hyp_summary}\n\n"
            f"Current evidence pool:\n{_format_evidence(state.evidence, limit=20)}"
        )},
    ]

    max_calls = 5
    calls_made = 0
    while calls_made < max_calls:
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
            return msg.content or ""

        for call in msg.tool_calls:
            state.tool_calls_made += 1
            calls_made += 1
            args = json.loads(call.function.arguments or "{}")
            result = await dispatch_tool(call.function.name, args, state.evidence)
            new_evs = result.get("evidence", []) if isinstance(result, dict) else []
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
    
    logger.warning(f"[Critique] Reached max tool calls ({max_calls}) — finishing early")
    return local_msgs[-1].get("content") or "Reached tool call limit."


# ---------------------------------------------------------------------------
# Stage 4 — Judge
# ---------------------------------------------------------------------------

async def _run_judge(
    query: str,
    state: DebateState,
    llm_client,
    cfg: DebateConfig,
    role_cfgs: dict = ROLE_CONFIGS,
) -> dict:
    r_cfg: RoleConfig = role_cfgs.get("judge", RoleConfig(model=cfg.model))
    compact_transcript = _compact_transcript(state.transcript, limit=50, max_chars=600)
    judge_msgs = [
        {"role": "system", "content": JUDGE_PROMPT},
        {"role": "user", "content": (
            f"Query: {query}\n\n"
            f"Debate Transcript:\n{json.dumps(compact_transcript, ensure_ascii=False)}\n\n"
            f"Full Evidence Pool:\n{_format_evidence(state.evidence, limit=30)}"
        )},
    ]
    resp = await _chat(
        llm_client, r_cfg.model, judge_msgs,
        temperature=r_cfg.temperature, max_tokens=r_cfg.max_tokens,
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[Judge] Could not parse JSON verdict — wrapping raw response")
        return {"answer": raw, "rationale": raw, "confidence": 0.0, "citations": []}


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
) -> tuple[dict, DebateState]:
    """
    Run the full IELTS-RAG debate pipeline.

    Returns:
        (final_answer_dict, state)
        final_answer_dict has keys: answer, rationale, confidence, citations (validated)
    """
    state = DebateState(query=query, evidence=list(initial_evidence))

    # --- Stage 2: Generate hypotheses ---
    hypotheses = await _generate_hypotheses(query, state.evidence, llm_client, cfg, role_cfgs)
    state.transcript.append({
        "role": "system",
        "content": f"[Generator] Proposed {len(hypotheses)} hypotheses:\n" +
                   "\n".join(f"  {h.get('id')}: {h.get('claim')}" for h in hypotheses),
    })

    # --- Stage 3: Debate rounds (defend concurrently → critique sequentially) ---
    for round_num in range(cfg.max_rounds):
        state.rounds_run += 1

        # Run all defenders CONCURRENTLY — each coroutine has its own local message history
        defender_summaries: list[str] = await asyncio.gather(*[
            _defend_hypothesis(h, query, state, llm_client, tools, dispatch_tool, cfg, role_cfgs)
            for h in hypotheses
        ])

        # Append defender summaries to shared transcript
        for h, summary in zip(hypotheses, defender_summaries):
            state.transcript.append({
                "role": "assistant",
                "content": f"[Defender {h.get('id')}] {summary}",
            })

        # Run critique
        critique_summary = await _run_critique(
            query, hypotheses, state, defender_summaries,
            llm_client, tools, dispatch_tool, cfg, role_cfgs
        )
        state.transcript.append({
            "role": "assistant",
            "content": f"[Critique Round {round_num + 1}] {critique_summary}",
        })

    # --- Stage 4: Judge ---
    verdict = await _run_judge(query, state, llm_client, cfg, role_cfgs)

    # --- Citation validation ---
    raw_citations = verdict.get("citations", [])
    verdict["citations"] = _validate_citations(raw_citations, state.evidence)

    invalid = [c for c in verdict["citations"] if not c.get("validated")]
    if invalid:
        logger.warning(f"[Judge] {len(invalid)} citation(s) not found in evidence pool: "
                       f"{[c.get('evidence_id') for c in invalid]}")

    return verdict, state
