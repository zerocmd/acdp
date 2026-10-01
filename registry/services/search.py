"""Search service for the registry."""

import time
from typing import Any, Dict, Iterable, List, Optional

# Agents that have not heartbeated for this long are reported as "stale".
STALE_AFTER_SECONDS = 120


def agent_status(agent: Dict[str, Any], now: Optional[float] = None) -> str:
    now = time.time() if now is None else now
    return "online" if now - agent.get("last_update", 0) < STALE_AFTER_SECONDS else "stale"


def skill_ids(agent: Dict[str, Any]) -> List[str]:
    """A2A skill ids and tags, from the stored Agent Card or the ACDP a2a block."""
    ids = list((agent.get("a2a") or {}).get("skills") or [])
    for skill in (agent.get("agent_card") or {}).get("skills") or []:
        ids.append(skill.get("id", ""))
        ids.extend(skill.get("tags") or [])
    return [i for i in ids if i]


def speaks(agent: Dict[str, Any], protocol: str) -> bool:
    """Protocol match; "a2a" matches versioned entries such as "a2a/0.3"."""
    return any(
        p == protocol or p.split("/", 1)[0] == protocol for p in agent.get("protocols") or []
    )


class SearchService:
    """Service for searching agents in the registry."""

    def __init__(self, agents_db):
        """Initialize with the agents database."""
        self.agents_db = agents_db

    def search_by_capability(self, capability, limit=None, offset=0):
        """Search agents by capability (ACDP capability or A2A skill id/tag)."""
        return self.search_by_criteria({"capabilities": [capability]}, limit, offset)

    def search_by_criteria(self, criteria, limit=None, offset=0):
        """Search agents by multiple criteria."""
        results: Iterable[Dict[str, Any]] = list(self.agents_db.values())

        # Filter by capabilities (AND logic - must have all capabilities)
        if criteria.get("capabilities"):
            capabilities = criteria["capabilities"]
            results = [
                agent
                for agent in results
                if all(
                    cap in agent.get("capabilities", []) or cap in skill_ids(agent)
                    for cap in capabilities
                )
            ]

        # Filter by A2A skill id or tag
        if criteria.get("skill"):
            skill = criteria["skill"]
            results = [agent for agent in results if skill in skill_ids(agent)]

        # Filter by name or description (fuzzy match)
        if criteria.get("query"):
            query = criteria["query"].lower()
            results = [
                agent
                for agent in results
                if query in agent.get("name", "").lower()
                or query in agent.get("description", "").lower()
            ]

        # Filter by protocol support
        if criteria.get("protocol"):
            results = [agent for agent in results if speaks(agent, criteria["protocol"])]

        # Filter by model provider
        if criteria.get("provider"):
            provider = criteria["provider"]
            results = [
                agent
                for agent in results
                if agent.get("model_info", {}).get("provider") == provider
            ]

        # Filter by liveness
        if criteria.get("status"):
            now = time.time()
            results = [agent for agent in results if agent_status(agent, now) == criteria["status"]]

        # Convert results to list if it's not already
        results = list(results)

        # Apply pagination if specified
        if limit is not None:
            results = results[offset : offset + limit]

        return results
