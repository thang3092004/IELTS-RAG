from dataclasses import dataclass

@dataclass
class RoleConfig:
    model: str
    temperature: float = 0.3
    max_tokens: int = 800

# Default role configs (override via caller if needed)
GENERATOR_CONFIG = RoleConfig(model="gpt-4o-mini", temperature=0.4, max_tokens=600)
DEFENDER_CONFIG = RoleConfig(model="gpt-4o-mini", temperature=0.5, max_tokens=700)
CRITIQUE_CONFIG = RoleConfig(model="gpt-4o-mini", temperature=0.6, max_tokens=700)
JUDGE_CONFIG = RoleConfig(model="gpt-4o-mini", temperature=0.2, max_tokens=600)
