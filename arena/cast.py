"""Cast definitions: who is in the arena and how each agent behaves."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

MODEL_IDS = {"sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-4-5-20251001"}
ROLES = ("investigation", "agenda", "impostor")
SECTORS = ("member", "provider", "assurance")
SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")
DEFAULT_CAST = Path(__file__).with_name("cast.yaml")


@dataclass(frozen=True)
class AgentSpec:
    slug: str
    name: str
    organization: str
    domain: str
    capability: str
    description: str
    needs: Tuple[str, ...]
    model: str
    role: str
    cadence: Tuple[float, float]
    system_prompt: str
    thread_cap: int = 12
    sector: str = "provider"

    @property
    def agent_id(self) -> str:
        return f"{self.slug}.{self.domain}"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentSpec":
        """Build and check a spec.

        Raises:
            ValueError: A field is missing or invalid.
        """
        try:
            cadence = tuple(float(v) for v in data["cadence"])
            spec = cls(
                slug=str(data["slug"]),
                name=str(data["name"]),
                organization=str(data["organization"]),
                domain=str(data["domain"]).lower(),
                capability=str(data["capability"]),
                description=str(data["description"]),
                needs=tuple(str(n) for n in data.get("needs") or ()),
                model=str(data["model"]),
                role=str(data["role"]),
                cadence=cadence,  # type: ignore[arg-type]
                system_prompt=str(data["system_prompt"]).strip(),
                thread_cap=int(data.get("thread_cap", 12)),
                sector=str(data.get("sector", "provider")),
            )
        except (KeyError, TypeError) as e:
            raise ValueError(f"invalid agent spec: {e}") from e
        if not SLUG_RE.fullmatch(spec.slug):
            raise ValueError(f"invalid slug: {spec.slug!r}")
        if spec.model not in MODEL_IDS:
            raise ValueError(f"model must be one of {sorted(MODEL_IDS)}")
        if spec.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if spec.sector not in SECTORS:
            raise ValueError(f"sector must be one of {SECTORS}")
        if len(spec.cadence) != 2 or not 0 < spec.cadence[0] <= spec.cadence[1]:
            raise ValueError("cadence must be [low, high] seconds")
        return spec


@dataclass(frozen=True)
class Seed:
    owner: str
    closer: str
    title: str
    brief: str


@dataclass
class Cast:
    seed: Seed
    agents: List[AgentSpec]

    def by_slug(self, slug: str) -> AgentSpec:
        for agent in self.agents:
            if agent.slug == slug:
                return agent
        raise KeyError(slug)


def load_cast(path: Path = DEFAULT_CAST) -> Cast:
    """Load the cast file. Agent order is registration order."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    seed = Seed(**{k: str(v).strip() for k, v in data["seed"].items()})
    return Cast(seed=seed, agents=[AgentSpec.from_dict(a) for a in data["agents"]])
