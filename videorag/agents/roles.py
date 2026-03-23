from dataclasses import dataclass


@dataclass
class RoleConfig:
    model: str
    temperature: float = 0.3
    max_tokens: int = 800


# Generator: creative but not too long
GENERATOR_CONFIG = RoleConfig(model="gpt-4o-mini", temperature=0.5, max_tokens=600)

# Defenders: each defends one hypothesis; needs room for arguments + tool results
DEFENDER_CONFIG = RoleConfig(model="gpt-4o-mini", temperature=0.4, max_tokens=1000)

# Critique: adversarial; slightly higher temperature for finding unexpected angles
CRITIQUE_CONFIG = RoleConfig(model="gpt-4o-mini", temperature=0.6, max_tokens=1200)

# Judge: deterministic — should be reproducible given same evidence
JUDGE_CONFIG = RoleConfig(model="gpt-4o-mini", temperature=0.1, max_tokens=800)


ROLE_CONFIGS: dict[str, RoleConfig] = {
    "generator": GENERATOR_CONFIG,
    "defender": DEFENDER_CONFIG,
    "critique": CRITIQUE_CONFIG,
    "judge": JUDGE_CONFIG,
}
