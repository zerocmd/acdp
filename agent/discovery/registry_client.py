"""Client for interacting with the central registry."""

import requests
import logging
import json
import time
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class RegistryClient:
    """Client for interacting with the central registry"""

    def __init__(self, base_url):
        self.base_url = base_url
        logger.info(f"Initialized registry client with base URL: {base_url}")

    def register_agent(self, agent_data: Dict) -> Dict:
        """Register an agent with the registry"""
        logger.info(f"Registering agent {agent_data.get('id')} with registry")
        try:
            response = requests.post(
                f"{self.base_url}/registerAgent", json=agent_data, timeout=10
            )
            response.raise_for_status()
            logger.info(f"Successfully registered agent with registry")
            return response.json()
        except Exception as e:
            logger.error(f"Error registering with registry: {str(e)}")
            if hasattr(e, "response") and e.response:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response content: {e.response.text}")
            raise

    def get_agents(
        self,
        capability=None,
        query=None,
        protocol=None,
        provider=None,
        limit=None,
        offset=None,
    ) -> Dict:
        """
        Get agents from the registry with optional filtering.

        Args:
            capability: Filter by capability
            query: Search in name and description
            protocol: Filter by supported protocol
            provider: Filter by model provider
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            Dictionary with agents list
        """
        logger.info(f"Fetching agents from registry")
        url = f"{self.base_url}/agents"

        # Build query parameters
        params = {}
        if capability:
            params["capability"] = capability
        if query:
            params["query"] = query
        if protocol:
            params["protocol"] = protocol
        if provider:
            params["provider"] = provider
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching agents: {str(e)}")
            if hasattr(e, "response") and e.response:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response content: {e.response.text}")
            return {"agents": []}

    def get_agent(self, agent_id: str) -> Dict:
        """Get a specific agent by ID"""
        logger.info(f"Fetching agent {agent_id} from registry")
        try:
            response = requests.get(f"{self.base_url}/agents/{agent_id}", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching agent {agent_id}: {str(e)}")
            if hasattr(e, "response") and e.response:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response content: {e.response.text}")
            raise

    def heartbeat(self, agent_id: str) -> Dict:
        """Send a heartbeat for an agent"""
        logger.debug(f"Sending heartbeat for agent {agent_id}")
        try:
            response = requests.put(
                f"{self.base_url}/agents/{agent_id}/heartbeat", timeout=5
            )

            # If we get a 404, the agent might not be registered yet
            if response.status_code == 404:
                logger.warning(
                    f"Agent {agent_id} not found in registry. Attempting to re-register."
                )
                return {"status": "not_found", "message": "Agent not found in registry"}

            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending heartbeat for agent {agent_id}: {str(e)}")
            if hasattr(e, "response") and e.response:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response content: {e.response.text}")
            return {"status": "error", "message": str(e)}

    def unregister_agent(self, agent_id: str) -> Dict:
        """Unregister an agent from the registry"""
        logger.info(f"Unregistering agent {agent_id} from registry")
        try:
            response = requests.delete(f"{self.base_url}/agents/{agent_id}", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error unregistering agent {agent_id}: {str(e)}")
            if hasattr(e, "response") and e.response:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response content: {e.response.text}")
            raise

    def search_agents(self, criteria: Dict) -> Dict:
        """
        Search for agents using advanced criteria

        Args:
            criteria: Dictionary of search criteria
                - capabilities: List of required capabilities
                - query: Text to search in name/description
                - protocol: Required protocol support
                - provider: Model provider
                - limit: Maximum results
                - offset: Pagination offset

        Returns:
            Dictionary with agents list
        """
        logger.info(f"Searching agents with criteria: {criteria}")

        # Build query parameters from criteria
        params = {}
        if "capabilities" in criteria and criteria["capabilities"]:
            params["capability"] = criteria["capabilities"][
                0
            ]  # Use first capability for now
        if "query" in criteria:
            params["query"] = criteria["query"]
        if "protocol" in criteria:
            params["protocol"] = criteria["protocol"]
        if "provider" in criteria:
            params["provider"] = criteria["provider"]
        if "limit" in criteria:
            params["limit"] = criteria["limit"]
        if "offset" in criteria:
            params["offset"] = criteria["offset"]

        try:
            response = requests.get(
                f"{self.base_url}/agents", params=params, timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error searching agents: {str(e)}")
            if hasattr(e, "response") and e.response:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response content: {e.response.text}")
            return {"agents": []}

    # Local cache for shared memory since registry may not persist between requests
    _memory_cache = {"memory": {}}

    def get_shared_memory(self) -> Dict:
        """
        Get all shared memory entries from the registry.

        Note: Due to potential persistence issues with the registry,
        this method also maintains a local cache of memory entries.
        """
        logger.info(
            f"Fetching shared memory from registry: {self.base_url}/shared-memory"
        )
        try:
            response = requests.get(f"{self.base_url}/shared-memory", timeout=10)
            logger.info(f"Memory response status: {response.status_code}")
            response.raise_for_status()
            result = response.json()
            logger.info(
                f"Memory response keys: {list(result.keys() if isinstance(result, dict) else [])}"
            )

            # If registry returns empty memory but we have cached entries, use cache
            if not result.get("memory") and self._memory_cache.get("memory"):
                logger.warning("Registry returned empty memory, using cached entries")
                return self._memory_cache

            # Update our cache with any new entries from registry
            if result.get("memory"):
                self._memory_cache["memory"].update(result.get("memory", {}))

            return self._memory_cache
        except Exception as e:
            logger.error(f"Error fetching shared memory: {str(e)}")
            if hasattr(e, "response") and e.response:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response content: {e.response.text}")

            # Return cached memory on error
            logger.info(
                f"Returning cached memory with {len(self._memory_cache.get('memory', {}))} entries"
            )
            return self._memory_cache

    def update_shared_memory(self, key: str, value: Any, owner: str = None) -> Dict:
        """
        Update a shared memory entry

        Args:
            key: The memory key
            value: The value to store (must be JSON serializable)
            owner: Optional owner identifier

        Returns:
            Response from the registry
        """
        logger.info(f"Updating shared memory key: {key}")
        try:
            data = {"key": key, "value": value, "owner": owner}
            logger.info(f"Sending memory update to {self.base_url}/shared-memory")
            logger.debug(f"Memory update payload: {json.dumps(data)[:1000]}")

            # Update the local cache regardless of registry success
            self._memory_cache["memory"][key] = {
                "value": value,
                "timestamp": time.time(),
                "owner": owner or "unknown",
            }
            logger.info(f"Updated local memory cache for key: {key}")

            # Attempt to update the registry
            response = requests.post(
                f"{self.base_url}/shared-memory", json=data, timeout=10
            )
            logger.info(f"Memory update response status: {response.status_code}")
            response.raise_for_status()

            result = response.json()
            logger.info(f"Memory update result: {result}")
            return result
        except Exception as e:
            logger.error(f"Error updating shared memory in registry: {str(e)}")
            if hasattr(e, "response") and e.response:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response content: {e.response.text}")

            # Even if registry update fails, we've updated the local cache
            return {"status": "success", "message": "Updated in local cache only"}
