"""Gossip protocol implementation for peer discovery."""

import logging
import time
import threading
import random
from typing import Dict, List, Set, Optional
import requests

logger = logging.getLogger(__name__)


class GossipProtocol:
    """
    Implementation of a gossip protocol for peer discovery.

    This protocol allows agents to spread knowledge about other agents
    through periodic exchanges of peer lists.
    """

    def __init__(self, agent_id: str, peer_manager=None, config=None):
        """
        Initialize the gossip protocol.

        Args:
            agent_id: This agent's ID
            peer_manager: Peer manager for tracking peers
            config: Configuration dictionary
        """
        self.agent_id = agent_id
        self.peer_manager = peer_manager
        self.config = config or {}

        # Gossip settings
        self.gossip_interval = self.config.get(
            "gossip_interval", 300
        )  # Seconds between gossip rounds
        self.fanout = self.config.get(
            "fanout", 3
        )  # Number of peers to gossip with in each round
        self.max_peers_per_message = self.config.get(
            "max_peers_per_message", 10
        )  # Max peers to send in each message

        # Tracking
        self.running = False
        self.gossip_thread = None
        self.last_gossip_time = 0
        self.gossip_stats = {
            "rounds": 0,
            "messages_sent": 0,
            "messages_received": 0,
            "peers_sent": 0,
            "peers_received": 0,
            "new_peers_discovered": 0,
        }

    def select_gossip_targets(self) -> List[str]:
        """
        Select peers to gossip with in this round.

        Returns:
            List of peer IDs to gossip with
        """
        if not self.peer_manager:
            return []

        # Get all healthy peers
        healthy_peers = list(self.peer_manager.get_healthy_peers().keys())

        # If we don't have enough healthy peers, include unknown health peers
        if len(healthy_peers) < self.fanout:
            all_peers = self.peer_manager.get_peer_ids()
            unknown_peers = [p for p in all_peers if p not in healthy_peers]
            healthy_peers.extend(unknown_peers)

        # Select random subset of peers
        num_targets = min(self.fanout, len(healthy_peers))
        if num_targets == 0:
            return []

        return random.sample(healthy_peers, num_targets)

    def select_peers_to_send(self, target_peer_id: str) -> List[str]:
        """
        Select which peers to tell the target about.

        Args:
            target_peer_id: The peer we're gossiping with

        Returns:
            List of peer IDs to send
        """
        if not self.peer_manager:
            return []

        # Get all peers except the target
        all_peers = [p for p in self.peer_manager.get_peer_ids() if p != target_peer_id]

        # Select random subset of peers
        num_peers = min(self.max_peers_per_message, len(all_peers))
        if num_peers == 0:
            return []

        return random.sample(all_peers, num_peers)

    def send_gossip_message(self, target_peer_id: str) -> Dict:
        """
        Send a gossip message to a peer.

        Args:
            target_peer_id: The peer to send the message to

        Returns:
            Dictionary with the result
        """
        if not self.peer_manager:
            return {"error": "No peer manager available"}

        target_peer = self.peer_manager.get_peer(target_peer_id)
        if not target_peer:
            return {"error": f"Peer {target_peer_id} not found"}

        # Get the peer's peers endpoint
        peers_endpoint = None
        if "endpoints" in target_peer and "peers" in target_peer["endpoints"]:
            peers_endpoint = target_peer["endpoints"]["peers"]
        else:
            # Try to construct a peers endpoint URL
            host = target_peer.get("host")
            port = target_peer.get("port")
            if host and port:
                peers_endpoint = f"http://{host}:{port}/peers"

        if not peers_endpoint:
            return {
                "error": f"Cannot gossip with {target_peer_id}: No peers endpoint found"
            }

        # Select peers to send
        peers_to_send = self.select_peers_to_send(target_peer_id)
        if not peers_to_send:
            return {"status": "no_peers_to_send"}

        # Send gossip message
        try:
            response = requests.post(
                peers_endpoint, json={"peers": peers_to_send}, timeout=10
            )

            if response.status_code != 200:
                return {
                    "error": f"Failed to send gossip to {target_peer_id}: {response.status_code}",
                    "response": response.text,
                }

            # Update stats
            self.gossip_stats["messages_sent"] += 1
            self.gossip_stats["peers_sent"] += len(peers_to_send)

            # Process response
            response_data = response.json()
            added_peers = response_data.get("added_peers", [])

            return {
                "status": "success",
                "peers_sent": len(peers_to_send),
                "peers_added_by_target": len(added_peers),
                "added_peers": added_peers,
            }

        except Exception as e:
            logger.error(f"Error sending gossip to {target_peer_id}: {e}")
            return {"error": str(e)}

    def receive_gossip_message(self, peer_ids: List[str], source_peer_id: str) -> Dict:
        """
        Process a received gossip message.

        Args:
            peer_ids: List of peer IDs received in the gossip
            source_peer_id: The peer that sent the gossip

        Returns:
            Dictionary with the result
        """
        if not self.peer_manager:
            return {"error": "No peer manager available"}

        # Track stats
        self.gossip_stats["messages_received"] += 1
        self.gossip_stats["peers_received"] += len(peer_ids)

        # Process each peer ID
        new_peers = []
        for peer_id in peer_ids:
            # Skip self and source peer
            if peer_id == self.agent_id or peer_id == source_peer_id:
                continue

            # Check if this is a new peer
            if not self.peer_manager.get_peer(peer_id):
                # Try to discover this peer
                discovered = False

                # If we have a discovery service on the peer manager, use it
                if (
                    hasattr(self.peer_manager, "discovery_service")
                    and self.peer_manager.discovery_service
                ):
                    try:
                        peer_info = self.peer_manager.discovery_service.discover_agent(
                            peer_id
                        )
                        if peer_info:
                            self.peer_manager.add_peer(peer_id, peer_info)
                            new_peers.append(peer_id)
                            discovered = True
                            self.gossip_stats["new_peers_discovered"] += 1
                    except Exception as e:
                        logger.warning(
                            f"Failed to discover peer {peer_id} from gossip: {e}"
                        )

                # If discovery failed or not available, add a placeholder
                if not discovered:
                    # Add minimal info so we know about this peer
                    self.peer_manager.add_peer(
                        peer_id,
                        {
                            "id": peer_id,
                            "source": "gossip",
                            "discovered_via": source_peer_id,
                            "needs_resolution": True,
                        },
                    )
                    new_peers.append(peer_id)

        return {
            "status": "success",
            "peers_received": len(peer_ids),
            "new_peers_added": len(new_peers),
            "new_peers": new_peers,
        }

    def run_gossip_round(self) -> Dict:
        """
        Run a single round of the gossip protocol.

        Returns:
            Dictionary with the results of this round
        """
        start_time = time.time()

        # Select peers to gossip with
        targets = self.select_gossip_targets()
        if not targets:
            logger.info("No gossip targets available")
            return {"status": "no_targets"}

        # Send gossip to each target
        results = {}
        for target_id in targets:
            results[target_id] = self.send_gossip_message(target_id)

        # Update stats
        self.gossip_stats["rounds"] += 1
        self.last_gossip_time = time.time()

        # Clean up stale peers if peer manager supports it
        stale_peers_removed = []
        if hasattr(self.peer_manager, "clean_stale_peers"):
            stale_peers_removed = self.peer_manager.clean_stale_peers()

        return {
            "status": "completed",
            "targets": targets,
            "results": results,
            "duration": time.time() - start_time,
            "stale_peers_removed": stale_peers_removed,
            "stats": self.gossip_stats.copy(),
        }

    def start(self) -> bool:
        """
        Start the gossip protocol in a background thread.

        Returns:
            True if started successfully, False otherwise
        """
        if self.running:
            logger.warning("Gossip protocol already running")
            return False

        self.running = True

        def gossip_loop():
            logger.info(
                f"Starting gossip protocol with interval {self.gossip_interval}s"
            )

            while self.running:
                try:
                    logger.debug("Running gossip round")
                    result = self.run_gossip_round()
                    logger.debug(f"Gossip round completed: {result}")
                except Exception as e:
                    logger.error(f"Error in gossip round: {e}")

                # Sleep until next round
                time.sleep(self.gossip_interval)

        self.gossip_thread = threading.Thread(target=gossip_loop, daemon=True)
        self.gossip_thread.start()

        return True

    def stop(self) -> bool:
        """
        Stop the gossip protocol.

        Returns:
            True if stopped successfully, False otherwise
        """
        if not self.running:
            logger.warning("Gossip protocol not running")
            return False

        logger.info("Stopping gossip protocol")
        self.running = False

        # Wait for thread to terminate (with timeout)
        if self.gossip_thread and self.gossip_thread.is_alive():
            self.gossip_thread.join(timeout=5.0)

        return True

    def get_stats(self) -> Dict:
        """
        Get current gossip statistics.

        Returns:
            Dictionary with gossip statistics
        """
        stats = self.gossip_stats.copy()
        stats["last_gossip_time"] = self.last_gossip_time
        stats["running"] = self.running
        return stats
