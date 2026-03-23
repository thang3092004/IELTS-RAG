from dataclasses import dataclass, field
from typing import Optional, Literal

EvidenceType = Literal["text", "entity", "segment"]

@dataclass
class EvidenceItem:
    id: str
    type: EvidenceType
    score: float
    snippet: str
    source: str
    video_name: Optional[str] = None
    segment_index: Optional[str] = None
    time_range: Optional[str] = None
    provenance_path: Optional[str] = None
    metadata: dict = field(default_factory=dict)
