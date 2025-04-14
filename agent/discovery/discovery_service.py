"""Unified discovery service for finding agents through multiple methods."""

import logging
from typing import Dict, List, Optional, Any
import time
from .registry_client import RegistryClient
from .dns_resolver import DNSResolver

logger = logging.getLogger(__name__)


class DiscoveryService:
    """Service for discovering other agents through multiple methods."""

    def __init__(self, registry_url: str, dns_server: str = "bind", dns_port: int = 53):
        """
        Initialize the discovery service.

        Args:
            registry_url: URL of the central registry
            dns_server: DNS server hostname or IP
            dns_port: DNS server port
        """
        self.registry_client = RegistryClient(registry_url)
        self.dns_resolver = DNSResolver(dns_server, dns_port)
        self.agent_cache = {}  # Cache of discovered agents
        self.last_refresh = 0
        self.cache_ttl = 300  # Cache TTL in seconds

    def discover_agent(self, agent_id: str) -> Optional[Dict]:
        """
        Discover an agent by ID using multiple methods.

        Args:
            agent_id: The agent ID or domain name

        Returns:
            Agent information dictionary or None if not found
        """
        # Check cache first
        if agent_id in self.agent_cache:
            cached_agent = self.agent_cache[agent_id]
            # Return from cache if it's still valid
            if time.time() - cached_agent.get("_cache_time", 0) < self.cache_ttl:
                logger.debug(f"Using cached agent info for {agent_id}")
                return cached_agent

        logger.info(f"Discovering agent {agent_id}")

        # Try registry first
        try:
            agent_info = self.registry_client.get_agent(agent_id)
            if agent_info and not isinstance(agent_info, dict):
                agent_info = {"error": "Invalid response format"}

            if agent_info and "error" not in agent_info:
                logger.info(f"Found agent {agent_id} in registry")
                agent_info["_source"] = "registry"
                agent_info["_cache_time"] = time.time()
                self.agent_cache[agent_id] = agent_info
                return agent_info
        except Exception as e:
            logger.warning(f"Failed to discover agent {agent_id} via registry: {e}")

        # If registry fails, try DNS
        try:
            agent_info = self.dns_resolver.resolve_agent(agent_id)
            if agent_info:
                logger.info(f"Found agent {agent_id} via DNS")
                agent_info["_source"] = "dns"
                agent_info["_cache_time"] = time.time()
                self.agent_cache[agent_id] = agent_info
                return agent_info
        except Exception as e:
            logger.warning(f"Failed to discover agent {agent_id} via DNS: {e}")

        logger.error(f"Agent {agent_id} not found via any discovery method")
        return None

    def discover_agents_by_capability(self, capability: str) -> List[Dict]:
        """
        Discover agents with a specific capability.

        Args:
            capability: The capability to search for

        Returns:
            List of agent information dictionaries
        """
        logger.info(f"Discovering agents with capability: {capability}")

        # Try registry first as it's more efficient for capability-based search
        try:
            response = self.registry_client.get_agents(capability=capability)
            agents = response.get("agents", [])

            # Update cache with discovered agents
            for agent in agents:
                agent_id = agent.get("id")
                if agent_id:
                    agent["_source"] = "registry"
                    agent["_cache_time"] = time.time()
                    self.agent_cache[agent_id] = agent

            logger.info(
                f"Found {len(agents)} agents with capability {capability} in registry"
            )
            return agents
        except Exception as e:
            logger.warning(f"Failed to discover agents by capability via registry: {e}")
            return []

    def discover_agents_by_criteria(self, criteria: Dict) -> List[Dict]:
        """
        Discover agents matching multiple criteria.

        Args:
            criteria: Dictionary of search criteria
                - capabilities: List of required capabilities
                - query: Text to search in name/description
                - protocol: Required protocol support
                - provider: Model provider

        Returns:
            List of agent information dictionaries
        """
        logger.info(f"Discovering agents with criteria: {criteria}")

        try:
            response = self.registry_client.search_agents(criteria)
            agents = response.get("agents", [])

            # Update cache with discovered agents
            for agent in agents:
                agent_id = agent.get("id")
                if agent_id:
                    agent["_source"] = "registry"
                    agent["_cache_time"] = time.time()
                    self.agent_cache[agent_id] = agent

            logger.info(f"Found {len(agents)} agents matching criteria")
            return agents
        except Exception as e:
            logger.warning(f"Failed to discover agents by criteria: {e}")
            return []

    def refresh_cache(self):
        """Refresh the agent cache by re-fetching all known agents."""
        logger.info("Refreshing agent cache")

        # Remember agent IDs we currently know about
        known_agent_ids = list(self.agent_cache.keys())

        # Refresh each agent
        for agent_id in known_agent_ids:
            try:
                self.discover_agent(agent_id)
            except Exception as e:
                logger.warning(f"Failed to refresh agent {agent_id}: {e}")

        self.last_refresh = time.time()
        logger.info(f"Cache refresh complete, {len(self.agent_cache)} agents in cache")

    def clear_cache(self):
        """Clear the agent cache."""
        logger.info("Clearing agent cache")
        self.agent_cache = {}
