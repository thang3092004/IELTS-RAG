from dataclasses import dataclass, field
from typing import List, Any
from .evidence_types import EvidenceItem

@dataclass
class DebateConfig:
    model: str = "gpt-4o-mini"
    max_rounds: int = 2
    tool_top_k: int = 6

@dataclass
class DebateState:
    query: str
    evidence: List[EvidenceItem] = field(default_factory=list)
    transcript: List[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
