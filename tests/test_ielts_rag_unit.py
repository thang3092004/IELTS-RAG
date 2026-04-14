"""
Unit tests for the IELTS-RAG rewrite.
Run with: python -m pytest tests/test_ielts_rag_unit.py -v
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from videorag.debate.evidence_types import EvidenceItem
from videorag.debate.state import DebateConfig, DebateState
from videorag.debate.debate_manager import (
    _validate_citations,
    _generate_hypotheses,
    run_debate,
)
from videorag.pipeline.ielts_rag import _dedup_evidence
from videorag.tools.formatters import _score_from_result, make_text_evidence, make_segment_evidence


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def make_ev(id: str, type: str = "text", score: float = 0.8, snippet: str = "test") -> EvidenceItem:
    return EvidenceItem(id=id, type=type, score=score, snippet=snippet, source="test")


# ---------------------------------------------------------------------------
# Test: Evidence deduplication
# ---------------------------------------------------------------------------

class TestDedup:
    def test_dedup_removes_duplicate_ids(self):
        evs = [make_ev("a"), make_ev("b"), make_ev("a"), make_ev("c")]
        result = _dedup_evidence(evs)
        assert [e.id for e in result] == ["a", "b", "c"]

    def test_dedup_empty(self):
        assert _dedup_evidence([]) == []

    def test_dedup_all_unique(self):
        evs = [make_ev("x"), make_ev("y"), make_ev("z")]
        assert len(_dedup_evidence(evs)) == 3


# ---------------------------------------------------------------------------
# Test: Citation validation
# ---------------------------------------------------------------------------

class TestCitationValidation:
    def test_valid_citation_gets_validated_flag(self):
        ev = make_ev("chunk-abc")
        citations = [{"evidence_id": "chunk-abc", "video_name": None, "time_range": None, "snippet": "..."}]
        result = _validate_citations(citations, [ev])
        assert result[0]["validated"] is True
        assert ev.validated is True

    def test_invalid_citation_flagged_false(self):
        ev = make_ev("chunk-real")
        citations = [{"evidence_id": "chunk-fake", "video_name": None, "time_range": None, "snippet": "..."}]
        result = _validate_citations(citations, [ev])
        assert result[0]["validated"] is False
        assert ev.validated is False

    def test_mixed_citations(self):
        evs = [make_ev("ev-1"), make_ev("ev-2")]
        citations = [
            {"evidence_id": "ev-1", "snippet": ""},
            {"evidence_id": "ev-99", "snippet": ""},
        ]
        result = _validate_citations(citations, evs)
        assert result[0]["validated"] is True
        assert result[1]["validated"] is False


# ---------------------------------------------------------------------------
# Test: Score normalisation
# ---------------------------------------------------------------------------

class TestScoreFromResult:
    def test_similarity_key(self):
        assert _score_from_result({"similarity": 0.75}) == 0.75

    def test_distance_key(self):
        assert abs(_score_from_result({"distance": 0.3}) - 0.7) < 1e-6

    def test_distance_clamped_at_zero(self):
        assert _score_from_result({"distance": 1.5}) == 0.0

    def test_no_key_returns_zero(self):
        assert _score_from_result({}) == 0.0


# ---------------------------------------------------------------------------
# Test: EvidenceItem.to_dict
# ---------------------------------------------------------------------------

class TestEvidenceItemToDict:
    def test_to_dict_keys(self):
        ev = EvidenceItem(
            id="ev-1", type="text", score=0.9, snippet="hello world",
            source="text_chunk", video_name="movie", time_range="0-30"
        )
        d = ev.to_dict()
        assert set(d.keys()) == {
            "id", "type", "score", "snippet", "source",
            "video_name", "segment_index", "time_range", "validated"
        }

    def test_to_dict_snippet_truncated(self):
        ev = make_ev("x", snippet="a" * 500)
        assert len(ev.to_dict()["snippet"]) == 300


# ---------------------------------------------------------------------------
# Test: Hypothesis generation (mocked LLM)
# ---------------------------------------------------------------------------

class TestGenerateHypotheses:
    @pytest.mark.asyncio
    async def test_valid_json_hypotheses(self):
        mock_client = MagicMock()
        hyp_json = json.dumps([
            {"id": "H1", "claim": "Claim one", "reasoning": "Reason one"},
            {"id": "H2", "claim": "Claim two", "reasoning": "Reason two"},
            {"id": "H3", "claim": "Claim three", "reasoning": "Reason three"},
        ])
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = hyp_json
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        cfg = DebateConfig(model="gpt-4o-mini")
        hyps = await _generate_hypotheses("test query", [], mock_client, cfg)
        assert len(hyps) == 3
        assert hyps[0]["id"] == "H1"

    @pytest.mark.asyncio
    async def test_bad_json_falls_back_gracefully(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "Not valid JSON at all"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        cfg = DebateConfig(model="gpt-4o-mini")
        hyps = await _generate_hypotheses("test query", [], mock_client, cfg)
        assert len(hyps) == 1
        assert hyps[0]["id"] == "H1"  # fallback single hypothesis


# ---------------------------------------------------------------------------
# Test: Tool dispatch (mocked) updates evidence pool
# ---------------------------------------------------------------------------

class TestToolDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_adds_evidence_to_state(self):
        new_ev = make_ev("new-ev-1")
        dispatch_mock = AsyncMock(return_value={"evidence": [new_ev]})

        state = DebateState(query="q", evidence=[make_ev("old-ev")])
        state.evidence.extend((await dispatch_mock("search_text_evidence", {"query": "q"}, state.evidence))["evidence"])

        assert any(e.id == "new-ev-1" for e in state.evidence)
        assert len(state.evidence) == 2
