import json
import asyncio
from typing import List, Callable, Any
from ..agents.agents_prompts import (
    GENERATOR_PROMPT,
    DEFENDER_PROMPT,
    CRITIQUE_PROMPT,
    JUDGE_PROMPT,
)
from ..agents.roles import ROLE_CONFIGS
from ..debate.state import DebateConfig, DebateState
from ..debate.evidence_types import EvidenceItem


async def _chat(llm_client, model: str, messages: list[dict], tools=None, tool_choice: str | None = None, temperature: float | None = None, max_tokens: int | None = None):
    kwargs = {"model": model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return await llm_client.chat.completions.create(**kwargs)


def _format_evidence(evs: List[EvidenceItem], limit: int = 12) -> str:
    rows = []
    for ev in evs[:limit]:
        row = f"[{ev.id}] ({ev.type}) score={ev.score:.3f} src={ev.source}"
        if ev.video_name and ev.time_range:
            row += f" video={ev.video_name} time={ev.time_range}"
        if ev.snippet:
            row += f"\nSnippet: {ev.snippet[:240]}"
        rows.append(row)
    return "\n\n".join(rows)


def _compact_transcript(transcript: list[dict], limit: int = 40, max_chars: int = 480) -> list[dict]:
    """Trim transcript to the last N messages and truncate content for judge step."""
    trimmed = transcript[-limit:]
    compact = []
    for msg in trimmed:
        content = msg.get("content", "")
        if isinstance(content, str) and len(content) > max_chars:
            content = content[: max_chars] + "..."
        compact.append({k: v for k, v in msg.items() if k != "tool_calls"} | {"content": content})
    return compact


async def generator_make_hypotheses(query: str, evidence: List[EvidenceItem], llm_client, cfg: DebateConfig, role_cfgs=ROLE_CONFIGS):
    ctx = _format_evidence(evidence)
    messages = [
        {"role": "system", "content": GENERATOR_PROMPT},
        {"role": "user", "content": f"Query: {query}\nEvidence:\n{ctx}"},
    ]
    gen_cfg = role_cfgs.get("generator", None)
    resp = await _chat(
        llm_client,
        gen_cfg.model if gen_cfg else cfg.model,
        messages,
        temperature=getattr(gen_cfg, "temperature", None),
        max_tokens=getattr(gen_cfg, "max_tokens", None),
    )
    content = resp.choices[0].message.content or ""
    # naive split; expects H1/H2/H3 labeling
    hyps = []
    for line in content.splitlines():
        if line.strip().startswith("H"):
            hyps.append(line.strip())
    return hyps[:3] if hyps else [content]


async def run_debate(
    query: str,
    initial_evidence: List[EvidenceItem],
    llm_client,
    tools: list[dict],
    dispatch_tool: Callable[[str, dict, list[EvidenceItem]], Any],
    cfg: DebateConfig,
    role_cfgs=ROLE_CONFIGS,
):
    state = DebateState(query=query, evidence=list(initial_evidence))

    hypotheses = await generator_make_hypotheses(query, state.evidence, llm_client, cfg, role_cfgs=role_cfgs)

    # shared context
    state.transcript.append({"role": "system", "content": _format_evidence(state.evidence)})

    async def step(user_msg: dict, role_key: str):
        r_cfg = role_cfgs.get(role_key, None)
        resp = await _chat(
            llm_client,
            r_cfg.model if r_cfg else cfg.model,
            state.transcript + [user_msg],
            tools=tools,
            tool_choice="auto",
            temperature=getattr(r_cfg, "temperature", None),
            max_tokens=getattr(r_cfg, "max_tokens", None),
        )
        msg = resp.choices[0].message
        state.transcript.append({"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls})
        if msg.tool_calls:
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                result = await dispatch_tool(call.function.name, args, state.evidence)
                # assume result is dict with evidence list
                new_evs = result.get("evidence", []) if isinstance(result, dict) else []
                state.evidence.extend(new_evs)
                state.transcript.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.function.name,
                    "content": json.dumps(result, ensure_ascii=False),
                })
            return True
        return False

    defender_prompts = [DEFENDER_PROMPT + f"\nDefend: {h}" for h in hypotheses]

    for _ in range(cfg.max_rounds):
        for prompt in defender_prompts:
            more = True
            while more:
                more = await step({"role": "user", "content": prompt}, role_key="defender")
        more = True
        while more:
                more = await step({"role": "user", "content": CRITIQUE_PROMPT}, role_key="critique")

    judge_ctx = _format_evidence(state.evidence, limit=24)
    compact_transcript = _compact_transcript(state.transcript, limit=40, max_chars=480)
    judge_messages = [
        {"role": "system", "content": JUDGE_PROMPT},
        {"role": "user", "content": f"Query: {query}\nTranscript: {compact_transcript}\nEvidence:\n{judge_ctx}"},
    ]
    judge_cfg = role_cfgs.get("judge", None)
    judge_resp = await _chat(
        llm_client,
        judge_cfg.model if judge_cfg else cfg.model,
        judge_messages,
        temperature=getattr(judge_cfg, "temperature", None),
        max_tokens=getattr(judge_cfg, "max_tokens", None),
    )
    raw_answer = judge_resp.choices[0].message.content or ""
    try:
        parsed = json.loads(raw_answer)
    except Exception:
        parsed = {"answer": raw_answer, "rationale": raw_answer, "citations": []}
    return parsed, state
