"""
PeerManager class for managing agent peer-to-peer relationships.
"""

import threading
import time
import random
import requests
import logging
from typing import Dict, List, Set, Any, Optional
import json

logger = logging.getLogger(__name__)


class PeerManager:
    """Manager for agent peer-to-peer relationships."""

    def __init__(self, agent_id, discovery_service=None, config=None):
        """
        Initialize the peer manager.

        Args:
            agent_id: ID of this agent
            discovery_service: Optional discovery service for resolving peers
            config: Configuration dictionary
        """
        self.agent_id = agent_id
        self.discovery_service = discovery_service
        self.config = config or {}

        # Internal state
        self._peers = {}  # Dictionary of peer_id -> peer_info
        self._peer_health = (
            {}
        )  # Dictionary of peer_id -> health_status ("healthy", "unhealthy", "unknown")
        self._peer_last_seen = {}  # Dictionary of peer_id -> timestamp
        self._peer_lock = threading.RLock()  # Lock for thread safety

        # Gossip state
        self._gossip_thread = None
        self._gossip_running = False
        self._gossip_interval = self.config.get("gossip_interval", 60)  # seconds
        self._max_peers_to_exchange = self.config.get("max_peers_to_exchange", 10)
        self._peer_ttl = self.config.get(
            "peer_ttl", 3600
        )  # Time-to-live for peers in seconds

        # Gossip metrics
        self.gossip_stats = {
            "rounds_initiated": 0,
            "rounds_completed": 0,
            "peers_sent": 0,
            "peers_received": 0,
            "new_peers_discovered": 0,
            "stale_peers_removed": 0,
            "last_gossip_time": 0,
            "errors": 0,
        }

    def add_peer(self, peer_id: str, peer_info: Dict[str, Any]) -> bool:
        """
        Add or update a peer.

        Args:
            peer_id: Peer ID (typically domain name)
            peer_info: Dictionary of peer information

        Returns:
            True if the peer was added/updated, False otherwise
        """
        # Skip self
        if peer_id == self.agent_id:
            return False

        with self._peer_lock:
            is_new = peer_id not in self._peers
            self._peers[peer_id] = peer_info
            self._peer_last_seen[peer_id] = time.time()

            # Initialize health as unknown for new peers
            if is_new:
                self._peer_health[peer_id] = "unknown"
                logger.debug(f"Added new peer: {peer_id}")
            else:
                logger.debug(f"Updated existing peer: {peer_id}")

            return True

    def remove_peer(self, peer_id: str) -> bool:
        """
        Remove a peer.

        Args:
            peer_id: Peer ID

        Returns:
            True if the peer was removed, False if not found
        """
        with self._peer_lock:
            if peer_id in self._peers:
                del self._peers[peer_id]
                if peer_id in self._peer_health:
                    del self._peer_health[peer_id]
                if peer_id in self._peer_last_seen:
                    del self._peer_last_seen[peer_id]
                logger.debug(f"Removed peer: {peer_id}")
                return True
            return False

    def get_peer(self, peer_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific peer.

        Args:
            peer_id: Peer ID

        Returns:
            Peer information or None if not found
        """
        with self._peer_lock:
            return self._peers.get(peer_id)

    def get_all_peers(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all peers.

        Returns:
            Dictionary of peer_id -> peer_info
        """
        with self._peer_lock:
            return self._peers.copy()

    def get_peer_ids(self) -> List[str]:
        """
        Get IDs of all known peers.

        Returns:
            List of peer IDs
        """
        with self._peer_lock:
            return list(self._peers.keys())

    def get_healthy_peers(self) -> Dict[str, Dict[str, Any]]:
        """
        Get peers that are considered healthy.

        Returns:
            Dictionary of peer_id -> peer_info for healthy peers
        """
        with self._peer_lock:
            # Consider peers with "healthy" status or "unknown" status that haven't been checked yet
            healthy_peers = {}
            current_time = time.time()

            for peer_id, peer_info in self._peers.items():
                # Consider a peer healthy if:
                # 1. It's marked healthy OR
                # 2. It's unknown but we've seen it recently OR
                # 3. We have no health info but have peer info (benefit of doubt)
                health_status = self._peer_health.get(peer_id, "unknown")
                last_seen = self._peer_last_seen.get(peer_id, 0)

                if (
                    health_status == "healthy"
                    or (health_status == "unknown" and current_time - last_seen < 300)
                    or peer_id not in self._peer_health
                ):
                    healthy_peers[peer_id] = peer_info

            # If we have no healthy peers but have some peers, use all peers
            # This ensures we don't unnecessarily skip collaboration
            if not healthy_peers and self._peers:
                logger.warning(
                    "No peers marked as healthy, using all peers as a fallback"
                )
                return self._peers.copy()

            return healthy_peers

    def check_peer_health(self, peer_id: str) -> str:
        """
        Check if a peer is healthy.

        Args:
            peer_id: Peer ID

        Returns:
            Status: "healthy", "unhealthy", or "unknown"
        """
        # If we don't have this peer, return unknown
        peer_info = self.get_peer(peer_id)
        if not peer_info:
            return "unknown"

        try:
            # Extract host/port from peer info
            host, port = self._extract_host_port(peer_id, peer_info)

            if not host:
                logger.warning(f"Cannot determine host for peer {peer_id}")
                with self._peer_lock:
                    self._peer_health[peer_id] = "unknown"
                return "unknown"

            # Check health endpoint
            health_url = f"http://{host}:{port}/health"
            response = requests.get(health_url, timeout=2)

            if response.status_code == 200:
                with self._peer_lock:
                    self._peer_health[peer_id] = "healthy"
                    self._peer_last_seen[peer_id] = time.time()
                return "healthy"
            else:
                with self._peer_lock:
                    self._peer_health[peer_id] = "unhealthy"
                return "unhealthy"
        except requests.exceptions.RequestException as e:
            logger.warning(f"Health check failed for peer {peer_id}: {e}")
            with self._peer_lock:
                self._peer_health[peer_id] = "unhealthy"
            return "unhealthy"
        except Exception as e:
            logger.error(f"Error checking health for peer {peer_id}: {e}")
            with self._peer_lock:
                self._peer_health[peer_id] = "unknown"
            return "unknown"

    def update_peer_health(self, peer_id: str, status: str) -> None:
        """
        Update a peer's health status.

        Args:
            peer_id: Peer ID
            status: Status ("healthy", "unhealthy", "unknown")
        """
        with self._peer_lock:
            self._peer_health[peer_id] = status
            self._peer_last_seen[peer_id] = time.time()

    def _clean_stale_peers(self) -> List[str]:
        """
        Remove peers that haven't been seen for too long.

        Returns:
            List of removed peer IDs
        """
        current_time = time.time()
        removed_peers = []

        with self._peer_lock:
            for peer_id, last_seen in list(self._peer_last_seen.items()):
                if current_time - last_seen > self._peer_ttl:
                    removed_peers.append(peer_id)
                    self.remove_peer(peer_id)

        if removed_peers:
            logger.info(f"Removed {len(removed_peers)} stale peers")

        return removed_peers

    def start_gossip_thread(self) -> bool:
        """
        Start the gossip protocol thread.

        Returns:
            True if started, False if already running
        """
        if self._gossip_running:
            return False

        self._gossip_running = True
        self._gossip_thread = threading.Thread(target=self._gossip_loop, daemon=True)
        self._gossip_thread.start()
        return True

    def stop_gossip_thread(self) -> bool:
        """
        Stop the gossip protocol thread.

        Returns:
            True if stopped, False if not running
        """
        if not self._gossip_running:
            return False

        self._gossip_running = False
        # The thread will exit on its next iteration
        if self._gossip_thread:
            self._gossip_thread.join(
                timeout=1
            )  # Wait up to 1 second for thread to exit
            self._gossip_thread = None
        return True

    def _gossip_loop(self) -> None:
        """Background thread loop for gossiping with peers."""
        logger.info("Starting gossip loop")

        while self._gossip_running:
            try:
                self._gossip_round()
            except Exception as e:
                logger.error(f"Error in gossip round: {e}")
                self.gossip_stats["errors"] += 1

            # Sleep between rounds
            sleep_time = self._gossip_interval
            if sleep_time < 1:
                sleep_time = 60  # Default to 60s if configured too low

            # Break sleep into smaller chunks to allow clean shutdown
            for _ in range(int(sleep_time)):
                if not self._gossip_running:
                    break
                time.sleep(1)

        logger.info("Gossip loop stopped")

    def _gossip_round(self) -> Dict[str, Any]:
        """
        Perform a single round of gossip protocol.

        Returns:
            Dictionary with gossip round results
        """
        start_time = time.time()
        self.gossip_stats["rounds_initiated"] += 1

        # Clean stale peers first
        removed_peers = self._clean_stale_peers()
        self.gossip_stats["stale_peers_removed"] += len(removed_peers)

        # Get a sample of peers to gossip with
        peers_to_gossip = self._select_gossip_peers()

        if not peers_to_gossip:
            logger.debug("No peers available for gossip")
            return {"status": "no_peers"}

        # Record of this round
        results = {}

        # Perform gossip exchange with each selected peer
        for peer_id in peers_to_gossip:
            try:
                result = self._gossip_with_peer(peer_id)
                results[peer_id] = result

                # If we successfully gossiped, mark the peer as healthy
                if result.get("status") == "success":
                    self.update_peer_health(peer_id, "healthy")

            except Exception as e:
                logger.error(f"Error gossiping with peer {peer_id}: {e}")
                results[peer_id] = {"status": "error", "error": str(e)}

        # Update stats
        self.gossip_stats["rounds_completed"] += 1
        self.gossip_stats["last_gossip_time"] = start_time

        # Log summary
        round_result = {
            "status": "completed",
            "gossip_peers": peers_to_gossip,
            "results": results,
            "stale_peers_removed": removed_peers,
        }
        logger.info(f"Gossip round completed: {round_result}")

        return round_result

    def _select_gossip_peers(self) -> List[str]:
        """
        Select a subset of peers for a gossip round.

        Returns:
            List of peer IDs
        """
        with self._peer_lock:
            peer_ids = list(self._peers.keys())

        if not peer_ids:
            return []

        # How many peers to gossip with
        fanout = self.config.get("fanout", 3)

        if fanout >= len(peer_ids):
            # If we have fewer peers than fanout, use all
            return peer_ids
        else:
            # Otherwise, select a random subset
            return random.sample(peer_ids, fanout)

    def _extract_host_port(self, peer_id: str, peer_info: Dict[str, Any]) -> tuple:
        """
        Extract host and port from peer information.

        Args:
            peer_id: Peer ID
            peer_info: Peer information

        Returns:
            Tuple of (host, port)
        """
        # First try to get explicit host and port
        host = peer_info.get("host")

        # Be more explicit about handling port - first check direct port field
        port = None
        if "port" in peer_info:
            try:
                port = int(peer_info["port"])
                logger.debug(f"Found explicit port {port} in peer info for {peer_id}")
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid port in peer info for {peer_id}: {peer_info.get('port')}"
                )

        # If no host, try to extract from interfaces
        if not host and "interfaces" in peer_info and "rest" in peer_info["interfaces"]:
            try:
                from urllib.parse import urlparse

                parsed = urlparse(peer_info["interfaces"]["rest"])
                if parsed.netloc:
                    host_parts = parsed.netloc.split(":")
                    host = host_parts[0]
                    if len(host_parts) > 1 and not port:
                        try:
                            port = int(host_parts[1])
                            logger.debug(
                                f"Extracted port {port} from REST interface for {peer_id}"
                            )
                        except (ValueError, TypeError):
                            logger.warning(
                                f"Invalid port in REST interface for {peer_id}"
                            )
            except Exception as e:
                logger.error(f"Error parsing REST interface for {peer_id}: {e}")

        # If still no host, try using the peer_id (domain)
        if not host and "." in peer_id:
            # For Docker, use the service name part
            host = peer_id.split(".")[0]
            logger.debug(f"Using service name {host} from peer_id {peer_id}")

        # Default port if needed - this is the most common issue
        if not port:
            # In Docker Compose, services typically expose their internal port
            # If we're in the same Docker network, we should use the container's internal port
            port = 8000
            logger.debug(f"Using default port {port} for {peer_id}")

        return host, port

    def _gossip_with_peer(self, peer_id: str) -> Dict[str, Any]:
        """
        Exchange peer information with a specific peer.

        Args:
            peer_id: Peer ID

        Returns:
            Dictionary with gossip results
        """
        # Get info for this peer
        peer_info = self.get_peer(peer_id)
        if not peer_info:
            return {"status": "error", "error": "Peer not found"}

        # Extract peer's host and port
        host, port = self._extract_host_port(peer_id, peer_info)

        # Ensure we have a host to contact
        if not host:
            return {"status": "error", "error": "Cannot determine peer host"}

        # Prepare the API URL
        peers_url = f"http://{host}:{port}/peers"
        logger.debug(f"Getting peers from {peer_id} at {peers_url}")

        # Step 1: Get the peer's peers
        try:
            get_response = requests.get(peers_url, timeout=5)
            get_response.raise_for_status()
            their_peers = get_response.json().get("peers", [])
            logger.debug(f"Received {len(their_peers)} peers from {peer_id}")
        except Exception as e:
            return {"status": "error", "error": f"Failed to get peers: {e}"}

        # Step 2: Send our peers to them
        try:
            with self._peer_lock:
                # Don't send them themself or us
                our_peers = [
                    p for p in self._peers.keys() if p != peer_id and p != self.agent_id
                ]

            # Limit number of peers to send
            if len(our_peers) > self._max_peers_to_exchange:
                our_peers = random.sample(our_peers, self._max_peers_to_exchange)

            payload = {"peers": our_peers}
            post_response = requests.post(peers_url, json=payload, timeout=5)
            post_response.raise_for_status()
            post_result = post_response.json()

            # Update stats
            self.gossip_stats["peers_sent"] += len(our_peers)
        except Exception as e:
            return {"status": "error", "error": f"Failed to send peers: {e}"}

        # Step 3: Process the peers we received
        new_peers = []
        for new_peer_id in their_peers:
            # Skip ourselves and the peer we're talking to
            if new_peer_id == self.agent_id or new_peer_id == peer_id:
                continue

            # If this is a new peer, try to get its details
            if new_peer_id not in self._peers and self.discovery_service:
                try:
                    new_peer_info = self.discovery_service.discover_agent(new_peer_id)
                    if new_peer_info and self.add_peer(new_peer_id, new_peer_info):
                        new_peers.append(new_peer_id)
                        self.gossip_stats["new_peers_discovered"] += 1
                except Exception as e:
                    logger.warning(f"Failed to discover new peer {new_peer_id}: {e}")

        # Step 4: Process their response to our peers
        added_by_them = post_result.get("added_peers", [])
        self.gossip_stats["peers_received"] += len(their_peers)

        return {
            "status": "success",
            "sent_peers": len(our_peers),
            "received_peers": len(their_peers),
            "new_peers": new_peers,
        }
