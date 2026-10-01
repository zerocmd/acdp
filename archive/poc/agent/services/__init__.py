"""Service for collaborative answering with peer agents."""

import logging
import time
import json
import requests
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class CollaborativeService:
    """Service for collaborative answering with peers."""

    def __init__(self, discovery_service=None, peer_manager=None, config=None):
        """
        Initialize the collaborative service.

        Args:
            discovery_service: Service for discovering agents
            peer_manager: Service for managing peers
            config: Configuration
        """
        self.discovery_service = discovery_service
        self.peer_manager = peer_manager
        self.config = config or {}

    def get_assistance(
        self, question: str, capability: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get assistance from peer agents to answer a question.

        Args:
            question: The question to get assistance for
            capability: Optional specific capability to filter peers

        Returns:
            List of peer responses
        """
        # Get relevant peers based on capability
        peers = self._get_relevant_peers(capability)
        if not peers:
            logger.info(f"No peers found with capability: {capability}")
            return []

        logger.info(f"Found {len(peers)} potential peers for assistance")

        # Query peers in parallel
        peer_responses = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            # Start the query tasks
            future_to_peer = {
                executor.submit(self._query_peer, peer_id, peer_info, question): (
                    peer_id,
                    peer_info,
                )
                for peer_id, peer_info in peers.items()
            }

            # Process results as they come in
            for future in as_completed(future_to_peer):
                peer_id, peer_info = future_to_peer[future]
                try:
                    response = future.result()
                    if response:
                        peer_responses.append(
                            {
                                "peer_id": peer_id,
                                "peer_name": peer_info.get("name", peer_id),
                                "response": response,
                                "timestamp": time.time(),
                            }
                        )
                        logger.info(f"Received response from peer {peer_id}")
                    else:
                        logger.warning(f"No usable response from peer {peer_id}")
                except Exception as e:
                    logger.error(f"Error getting assistance from peer {peer_id}: {e}")

        return peer_responses

    def _get_relevant_peers(
        self, capability: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get peers that can help with a specific capability.

        Args:
            capability: The capability to filter by

        Returns:
            Dictionary of peer IDs to peer info
        """
        relevant_peers = {}

        # First, get peers from peer manager (these are already discovered)
        if self.peer_manager:
            all_peers = self.peer_manager.get_all_peers()

            # Filter by capability if specified
            for peer_id, peer_info in all_peers.items():
                peer_capabilities = peer_info.get("capabilities", [])
                if not capability or capability in peer_capabilities:
                    # Check if peer is healthy
                    health_status = self.peer_manager.check_peer_health(peer_id)
                    if health_status == "healthy":
                        relevant_peers[peer_id] = peer_info

        # Then, try discovery service to find more peers
        if self.discovery_service and capability:
            try:
                discovered_agents = (
                    self.discovery_service.discover_agents_by_capability(capability)
                )

                for agent in discovered_agents:
                    agent_id = agent.get("id")
                    if (
                        agent_id
                        and agent_id not in relevant_peers
                        and agent_id != self.config.get("id")
                    ):
                        # Add to peer manager for future use
                        if self.peer_manager:
                            self.peer_manager.add_peer(agent_id, agent)
                        relevant_peers[agent_id] = agent
            except Exception as e:
                logger.error(
                    f"Error discovering agents by capability {capability}: {e}"
                )

        return relevant_peers

    def _query_peer(
        self, peer_id: str, peer_info: Dict[str, Any], question: str
    ) -> Optional[str]:
        """
        Query a peer agent for assistance with a question.

        Args:
            peer_id: The peer's ID
            peer_info: The peer's info
            question: The question to ask

        Returns:
            The peer's response or None if failed
        """
        # Try to find the assistance endpoint
        assist_endpoint = None

        # Check if the peer has an assist endpoint defined
        if "endpoints" in peer_info and "assist" in peer_info["endpoints"]:
            assist_endpoint = peer_info["endpoints"]["assist"]

        # If no specific assist endpoint, try to use the task endpoint
        if (
            not assist_endpoint
            and "endpoints" in peer_info
            and "task" in peer_info["endpoints"]
        ):
            assist_endpoint = peer_info["endpoints"]["task"]

        # If still no endpoint, construct one using host/port
        if not assist_endpoint:
            # Extract host/port from peer info
            host = None
            port = None

            # Try to extract from interfaces.rest
            if "interfaces" in peer_info and "rest" in peer_info["interfaces"]:
                rest_interface = peer_info["interfaces"]["rest"]
                try:
                    parsed = urlparse(rest_interface)
                    if parsed.netloc:
                        host_port = parsed.netloc.split(":")
                        host = host_port[0]
                        if len(host_port) > 1:
                            port = int(host_port[1])
                except Exception as e:
                    logger.error(f"Error parsing REST interface: {e}")

            # If we still don't have host/port, try direct properties
            if not host:
                host = peer_info.get("host")
            if not port:
                port = peer_info.get("port")

            # Try the agent ID if all else fails (Docker service name)
            if not host and "." in peer_id:
                host = peer_id.split(".")[0]

            # Default port if needed
            if not port:
                port = 8000

            if host:
                assist_endpoint = f"http://{host}:{port}/assist"

        if not assist_endpoint:
            logger.error(f"Could not determine assist endpoint for peer {peer_id}")
            return None

        # Ensure the endpoint has a scheme
        if not assist_endpoint.startswith(("http://", "https://")):
            # Check if it's a path or full URL
            if assist_endpoint.startswith("/"):
                # It's a path, need to add host/port
                host = peer_info.get("host") or peer_id.split(".")[0]
                port = peer_info.get("port") or 8000
                assist_endpoint = f"http://{host}:{port}{assist_endpoint}"
            else:
                # Add default scheme
                assist_endpoint = f"http://{assist_endpoint}"

        try:
            # Send the assistance request
            logger.info(f"Querying peer {peer_id} for assistance at {assist_endpoint}")

            headers = {"Content-Type": "application/json"}
            data = {
                "question": question,
                "requestor_id": self.config.get("id", "unknown-agent"),
                "requestor_name": self.config.get("name", "Unknown Agent"),
                "timestamp": time.time(),
            }

            # Use a shorter timeout to avoid waiting too long
            response = requests.post(
                assist_endpoint,
                headers=headers,
                json=data,
                timeout=5,  # 5 second timeout
            )

            if response.status_code == 200:
                result = response.json()
                return result.get("response")
            else:
                logger.warning(
                    f"Peer {peer_id} returned status code {response.status_code}"
                )
                return None
        except Exception as e:
            logger.error(f"Error querying peer {peer_id}: {e}")
            return None
