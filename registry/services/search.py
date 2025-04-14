"""Search service for the registry."""


class SearchService:
    """Service for searching agents in the registry."""

    def __init__(self, agents_db):
        """Initialize with the agents database."""
        self.agents_db = agents_db

    def search_by_capability(self, capability, limit=None, offset=0):
        """Search agents by capability."""
        results = []

        for agent_id, agent in self.agents_db.items():
            if capability in agent.get("capabilities", []):
                results.append(agent)

        # Apply pagination if specified
        if limit is not None:
            results = results[offset : offset + limit]

        return results

    def search_by_criteria(self, criteria, limit=None, offset=0):
        """Search agents by multiple criteria."""
        results = self.agents_db.values()

        # Filter by capabilities (AND logic - must have all capabilities)
        if "capabilities" in criteria:
            capabilities = criteria["capabilities"]
            results = [
                agent
                for agent in results
                if all(cap in agent.get("capabilities", []) for cap in capabilities)
            ]

        # Filter by name or description (fuzzy match)
        if "query" in criteria:
            query = criteria["query"].lower()
            results = [
                agent
                for agent in results
                if query in agent.get("name", "").lower()
                or query in agent.get("description", "").lower()
            ]

        # Filter by protocol support
        if "protocol" in criteria:
            protocol = criteria["protocol"]
            results = [
                agent for agent in results if protocol in agent.get("protocols", [])
            ]

        # Filter by model provider
        if "provider" in criteria:
            provider = criteria["provider"]
            results = [
                agent
                for agent in results
                if agent.get("model_info", {}).get("provider") == provider
            ]

        # Convert results to list if it's not already
        results = list(results)

        # Apply pagination if specified
        if limit is not None:
            results = results[offset : offset + limit]

        return results
