import os
import time
import uuid
import requests
import json
import logging
from flask import Flask, jsonify, request
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from utils.dns_utils import register_dns
from discovery.discovery_service import DiscoveryService
from discovery.registry_client import RegistryClient
from peers.peer_manager import PeerManager
from anthropic import Anthropic

# Configure logging with more detail
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG for more detailed logs
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# Set specific loggers to INFO to reduce noise
logging.getLogger("werkzeug").setLevel(logging.INFO)
logging.getLogger("urllib3").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Load configuration
from config import AGENT_CONFIG

# Initialize Anthropic client with version-compatible approach
try:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY environment variable not set")
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    client = Anthropic(api_key=api_key)
    logger.info("Successfully initialized Anthropic client")
except Exception as e:
    logger.error(f"Failed to initialize Anthropic client: {e}")

# Initialize registry client
registry = RegistryClient(AGENT_CONFIG["registry_url"])


class Agent:
    def __init__(self, config):
        self.id = config["id"]
        self.name = config["name"]
        self.description = config["description"]
        self.capabilities = config["capabilities"]
        self.interfaces = config["interfaces"]
        self.model_info = config["model_info"]
        self.owner = config["owner"]
        self.endpoints = config["endpoints"]
        self.version = config["version"]
        self.protocols = config["protocols"]
        self.last_update = time.time()
        self.registered = False
        self.config = config

        # Initialize chat history (simple in-memory storage)
        self.chat_history = {}

        # Initialize discovery service
        self.discovery_service = DiscoveryService(
            config["registry_url"], config["dns_server"], config.get("dns_port", 53)
        )

        # Set cache TTL from config
        self.discovery_service.cache_ttl = config.get("discovery", {}).get(
            "cache_ttl", 600
        )

        # Initialize peer manager
        self.peer_manager = PeerManager(
            agent_id=self.id,
            discovery_service=self.discovery_service,
            config=config.get("peers", {}),
        )

        # For backward compatibility
        self.peers = {}

        # Collaboration settings
        self.collaboration_enabled = config.get("collaboration", {}).get(
            "enabled", True
        )
        self.collaboration_timeout = config.get("collaboration", {}).get("timeout", 5)
        self.max_peers_to_query = config.get("collaboration", {}).get("max_peers", 3)

    def to_dict(self):
        """Convert agent to dictionary for serialization"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "interfaces": self.interfaces,
            "model_info": self.model_info,
            "owner": self.owner,
            "endpoints": self.endpoints,
            "version": self.version,
            "protocols": self.protocols,
            "last_update": self.last_update,
        }

    def register(self):
        """Register with the central registry"""
        try:
            response = registry.register_agent(self.to_dict())
            logger.info(f"Registered with registry: {response}")
            self.registered = True
            return True
        except Exception as e:
            logger.error(f"Failed to register with registry: {e}")
            return False

    def register_dns(self):
        """Register SRV and TXT records in DNS"""
        try:
            register_dns(
                domain=self.id,
                host=AGENT_CONFIG["host"],
                port=AGENT_CONFIG["port"],
                capabilities=",".join(self.capabilities),
                description=self.description[:255],  # DNS TXT record length limit
            )
            logger.info(f"Registered DNS records for {self.id}")
            return True
        except Exception as e:
            logger.error(f"Failed to register DNS records: {e}")
            return False

    def fetch_peers(self):
        """Fetch peers from registry"""
        try:
            agents_data = registry.get_agents()
            for agent in agents_data["agents"]:
                if agent["id"] != self.id:  # Don't add self as peer
                    # Add to peer manager
                    self.peer_manager.add_peer(agent["id"], agent)
                    # For backward compatibility
                    self.peers[agent["id"]] = agent
                    logger.info(f"Added peer: {agent['id']}")
            return self.peers
        except Exception as e:
            logger.error(f"Failed to fetch peers: {e}")
            return {}

    def heartbeat(self):
        """Send periodic heartbeats to registry"""
        retry_count = 0
        max_retries = 5
        last_register_time = 0
        register_cooldown = 10  # seconds between registration attempts

        while True:
            try:
                current_time = time.time()

                # If not registered, or if we need to re-register, try to register
                if not self.registered:
                    # Only attempt registration if we're past the cooldown period
                    if current_time - last_register_time > register_cooldown:
                        if retry_count < max_retries:
                            logger.info(
                                f"Not registered yet, attempting to register (attempt {retry_count+1}/{max_retries})"
                            )
                            if self.register():
                                retry_count = 0
                                # Wait a bit after successful registration before sending heartbeat
                                time.sleep(2)
                            else:
                                retry_count += 1

                            last_register_time = current_time
                        else:
                            logger.error(
                                f"Failed to register after {max_retries} attempts. Will retry later."
                            )
                            retry_count = 0
                            time.sleep(60)
                            continue

                # Only send heartbeat if registered
                if self.registered:
                    # Send heartbeat
                    response = registry.heartbeat(self.id)

                    # If we get a not_found status, try to re-register after a cooldown
                    if response.get("status") == "not_found":
                        logger.warning(
                            "Agent not found in registry, will re-register soon"
                        )
                        self.registered = False
                    else:
                        logger.debug(f"Sent heartbeat for {self.id}")
                        retry_count = 0

            except Exception as e:
                logger.error(f"Failed to send heartbeat: {e}")
                # If we've had too many consecutive errors, try to re-register
                retry_count += 1
                if retry_count >= max_retries:
                    logger.warning(
                        "Too many heartbeat failures, will try to re-register"
                    )
                    self.registered = False
                    retry_count = 0

            # Sleep between heartbeats
            time.sleep(60)  # Heartbeat every minute

    def ask_llm(self, prompt, system_prompt=None):
        try:
            if not system_prompt:
                system_prompt = "You are a helpful AI assistant."

            response = client.messages.create(
                model=AGENT_CONFIG["model"],
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

        except Exception as e:
            logger.error(f"Error querying LLM: {e}")
            return f"Error processing your request: {str(e)}"

    def discover_agent(self, agent_id):
        """Discover an agent by ID using the discovery service"""
        return self.discovery_service.discover_agent(agent_id)

    def discover_agents_by_capability(self, capability):
        """Discover agents with a specific capability"""
        return self.discovery_service.discover_agents_by_capability(capability)

    def discover_agents_by_criteria(self, criteria):
        """Discover agents matching multiple criteria"""
        return self.discovery_service.discover_agents_by_criteria(criteria)

    def find_agents_for_task(self, capability):
        """Find suitable agents for a specific task/capability"""
        agents = self.discover_agents_by_capability(capability)
        # Sort by last_update to prefer recently active agents
        return sorted(agents, key=lambda a: a.get("last_update", 0), reverse=True)

    def refresh_peer_discovery(self):
        """Refresh peer information through discovery"""
        try:
            # Get all known agent IDs
            known_peer_ids = set(self.peer_manager.get_peer_ids())

            # Discover agents with any capability
            for capability in self.capabilities:
                discovered_agents = self.discover_agents_by_capability(capability)

                for agent in discovered_agents:
                    agent_id = agent.get("id")
                    if agent_id and agent_id != self.id:  # Don't add self as peer
                        self.peer_manager.add_peer(agent_id, agent)
                        # For backward compatibility
                        self.peers[agent_id] = agent
                        logger.info(f"Discovered peer: {agent_id}")

            # Log new discoveries
            new_peers = set(self.peer_manager.get_peer_ids()) - known_peer_ids
            if new_peers:
                logger.info(f"Discovered {len(new_peers)} new peers: {new_peers}")

            return self.peer_manager.get_all_peers()
        except Exception as e:
            logger.error(f"Error refreshing peer discovery: {e}")
            return self.peer_manager.get_all_peers()

    def start_gossip(self):
        """Start the gossip protocol for peer-to-peer discovery"""
        # Make sure we have some initial peers before starting gossip
        if len(self.peer_manager.get_all_peers()) < 2:
            logger.info("Discovering initial peers before starting gossip")
            self.refresh_peer_discovery()

        # Pass capabilities to the peer manager for gossip
        self.peer_manager.config["capabilities"] = self.capabilities

        # Start the gossip thread in the peer manager
        logger.info("Starting gossip protocol")
        self.peer_manager.start_gossip_thread()
        logger.info("Gossip protocol started")
        return True

    # NEW COLLABORATION METHODS

    def get_assistance_from_peers(self, question):
        """
        Get assistance from peers to answer a question.

        Args:
            question: The question to ask peers

        Returns:
            List of peer responses
        """
        if not self.collaboration_enabled:
            logger.info("Collaboration is disabled")
            return []

        # Get healthy peers with any capability
        all_peers = self.peer_manager.get_healthy_peers()
        if not all_peers:
            logger.info("No healthy peers available for collaboration")
            return []

        # Prioritize peers based on capabilities
        # This is a simple heuristic - we could develop more sophisticated matching
        def peer_relevance_score(peer_info):
            # Count number of capabilities that overlap with ours
            peer_caps = peer_info.get("capabilities", [])
            overlap = len(set(peer_caps) & set(self.capabilities))
            # Peers with different capabilities might be more useful for diverse knowledge
            unique_caps = len(set(peer_caps) - set(self.capabilities))
            # Combine overlap and uniqueness, with more weight on uniqueness
            return unique_caps * 2 + overlap

        # Sort peers by relevance score
        sorted_peers = sorted(
            all_peers.items(), key=lambda x: peer_relevance_score(x[1]), reverse=True
        )

        # Select a subset of the most relevant peers
        selected_peers = sorted_peers[: self.max_peers_to_query]
        logger.info(f"Selected {len(selected_peers)} peers for collaboration")

        # Query peers in parallel
        peer_responses = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            # Start the query tasks
            future_to_peer = {
                executor.submit(
                    self._query_peer_for_assistance, peer_id, peer_info, question
                ): (peer_id, peer_info)
                for peer_id, peer_info in selected_peers
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

    def _query_peer_for_assistance(self, peer_id, peer_info, question):
        """
        Query a peer agent for assistance with a question.

        Args:
            peer_id: Peer's ID
            peer_info: Peer's information
            question: Question to ask

        Returns:
            Peer's response or None if failed
        """
        # First, try to extract host and port properly
        host = peer_info.get("host")
        port = None

        # Be more explicit about port extraction
        if "port" in peer_info:
            try:
                port = int(peer_info["port"])
                logger.debug(f"Found explicit port {port} in peer info for {peer_id}")
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid port in peer info for {peer_id}: {peer_info.get('port')}"
                )

        # Try to extract from interfaces.rest
        if "interfaces" in peer_info and "rest" in peer_info["interfaces"]:
            rest_interface = peer_info["interfaces"]["rest"]
            try:
                from urllib.parse import urlparse

                parsed = urlparse(rest_interface)
                if parsed.netloc:
                    host_port = parsed.netloc.split(":")
                    if not host:
                        host = host_port[0]
                    if len(host_port) > 1 and not port:
                        try:
                            port = int(host_port[1])
                            logger.debug(
                                f"Extracted port {port} from REST interface for {peer_id}"
                            )
                        except (ValueError, TypeError):
                            logger.warning(
                                f"Invalid port in REST interface for {peer_id}"
                            )
            except Exception as e:
                logger.error(f"Error parsing REST interface: {e}")

        # If we still don't have host, try the peer ID (Docker service name)
        if not host and "." in peer_id:
            host = peer_id.split(".")[0]
            logger.debug(f"Using service name {host} from peer_id {peer_id}")

        # Default port if needed (for Docker Compose internal networking)
        if not port:
            port = 8000
            logger.debug(f"Using default port {port} for {peer_id} in Docker network")

        logger.info(f"Will query peer {peer_id} at host={host}, port={port}")

        # Now construct the assist endpoint
        assist_endpoint = None

        # Check if the peer has an assist endpoint defined
        if "endpoints" in peer_info and "assist" in peer_info["endpoints"]:
            assist_path = peer_info["endpoints"]["assist"]
            # Is it a full URL or just a path?
            if assist_path.startswith(("http://", "https://")):
                assist_endpoint = assist_path
            else:
                # It's a path, add host and port
                assist_endpoint = f"http://{host}:{port}{assist_path}"
                if not assist_path.startswith("/"):
                    assist_endpoint = f"http://{host}:{port}/{assist_path}"

        # If no assist endpoint found, construct a default one
        if not assist_endpoint:
            assist_endpoint = f"http://{host}:{port}/assist"

        logger.info(f"Querying peer {peer_id} for assistance at {assist_endpoint}")

        try:
            # Send the assistance request
            request_data = {
                "question": question,
                "requestor_id": self.id,
                "requestor_name": self.name,
                "timestamp": time.time(),
            }

            logger.debug(f"Sending assist request to {peer_id}: {request_data}")

            # CHANGED: Increase timeout from 5 to 30 seconds to allow for LLM processing time
            response = requests.post(
                assist_endpoint,
                headers={"Content-Type": "application/json"},
                json=request_data,
                timeout=30,  # Increased timeout to 30 seconds
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Received successful response from {peer_id}")
                logger.debug(f"Response from {peer_id}: {result}")
                return result.get("response")
            else:
                logger.warning(
                    f"Peer {peer_id} returned status code {response.status_code}: {response.text}"
                )
                return None
        except Exception as e:
            logger.error(f"Error querying peer {peer_id}: {e}")
            return None

    def handle_assist_request(self, request_data):
        """
        Handle an assistance request from another agent.

        Args:
            request_data: Request data containing question and requestor info

        Returns:
            Response with assistance
        """
        question = request_data.get("question")
        requestor_id = request_data.get("requestor_id", "unknown-agent")
        requestor_name = request_data.get("requestor_name", "Unknown Agent")

        if not question:
            logger.error("Missing question in assist request")
            return {"status": "error", "error": "Missing question in request"}

        logger.info(
            f"Received assistance request from {requestor_name} ({requestor_id}): {question}"
        )

        try:
            # Create a special prompt for assistance requests
            system_prompt = f"""You are {self.name}, helping another agent named {requestor_name}.

{requestor_name} has asked for your assistance with the following question:

"{question}"

Provide a helpful, concise response based on your knowledge and capabilities. 
Your response will be incorporated into the final answer by {requestor_name}.
Focus on providing information related to your specific capabilities: {', '.join(self.capabilities)}.
Keep your response under 250 words for better integration.
"""

            # Call the LLM for a response
            logger.info(f"Generating assistance response for {requestor_name}")
            response = self.ask_llm(question, system_prompt=system_prompt)
            logger.info(
                f"Successfully generated assistance response ({len(response)} chars)"
            )

            # Create a proper JSON response
            result = {
                "status": "success",
                "response": response,
                "agent_id": self.id,
                "agent_name": self.name,
            }
            logger.debug(f"Returning assist response: {result}")
            return result
        except Exception as e:
            logger.error(f"Error handling assist request: {e}")
            return {"status": "error", "error": f"Error generating response: {str(e)}"}

    def get_shared_memory(self):
        """Get all shared memory entries"""
        return registry.get_shared_memory()

    def store_in_shared_memory(self, key, value):
        """
        Store a value in shared memory

        Args:
            key: Memory key
            value: Value to store (must be JSON serializable)

        Returns:
            Response from registry
        """
        try:
            # Validate that value is JSON serializable
            json_str = json.dumps(value)
            logger.debug(f"Serialized memory value for {key} (length: {len(json_str)})")

            logger.info(f"Storing memory with key: {key}, owner: {self.id}")
            result = registry.update_shared_memory(key, value, owner=self.id)

            # Verify memory was stored
            if result.get("status") == "success":
                logger.info(f"Successfully stored memory with key: {key}")
            else:
                logger.warning(f"Possible issue storing memory: {result}")

            return result
        except TypeError as e:
            logger.error(f"Memory value is not JSON serializable: {e}")
            # Try to store a simplified version
            try:
                simplified_value = {
                    "error": "Original value not serializable",
                    "str_value": str(value),
                }
                return registry.update_shared_memory(
                    key, simplified_value, owner=self.id
                )
            except Exception as e2:
                logger.error(f"Failed to store simplified memory value: {e2}")
                return {
                    "status": "error",
                    "message": f"Value not serializable: {str(e)}",
                }
        except Exception as e:
            logger.error(f"Unexpected error storing memory: {e}")
            return {"status": "error", "message": str(e)}

    def record_interaction_in_memory(
        self, user_message, response, session_id="default"
    ):
        """
        Record an interaction summary in shared memory

        Args:
            user_message: Message from the user
            response: Agent's response
            session_id: Chat session ID
        """
        # Create a memory key specific to this agent
        memory_key = f"agent_memory_{self.id}"

        # Get existing memory or create new
        try:
            memory_result = self.get_shared_memory()
            memory = memory_result.get("memory", {})
            agent_memory = memory.get(memory_key, {"interactions": []})

            # Extract just the value part if it's in the expected format
            if "value" in agent_memory and isinstance(agent_memory["value"], dict):
                agent_memory = agent_memory["value"]

            # Ensure interactions list exists
            if "interactions" not in agent_memory:
                agent_memory["interactions"] = []

        except Exception as e:
            logger.warning(f"Error retrieving memory, creating new: {e}")
            agent_memory = {"interactions": []}

        # Add the new interaction
        agent_memory["interactions"].append(
            {
                "user_message": user_message,
                "agent_response": response,
                "timestamp": time.time(),
                "session_id": session_id,
            }
        )

        # Keep only the last 10 interactions to prevent excessive growth
        if len(agent_memory["interactions"]) > 10:
            agent_memory["interactions"] = agent_memory["interactions"][-10:]

        # Store additional metadata
        agent_memory["last_updated"] = time.time()
        agent_memory["agent_name"] = self.name
        agent_memory["agent_id"] = self.id

        # Save the updated memory
        try:
            return self.store_in_shared_memory(memory_key, agent_memory)
        except Exception as e:
            logger.error(f"Failed to store interaction in memory: {e}")
            return {"status": "error", "message": str(e)}

    def handle_chat(self, message, session_id="default"):
        """
        Handle a chat message, potentially collaborating with peers.

        Args:
            message: User's message
            session_id: Chat session ID

        Returns:
            LLM response, potentially incorporating peer assistance
        """
        logger.info(f"Handling chat message: {message[:50]}... (session: {session_id})")

        # Initialize chat history for this session if needed
        if session_id not in self.chat_history:
            self.chat_history[session_id] = []

        # Add user message to history
        self.chat_history[session_id].append(
            {"role": "user", "content": message, "timestamp": time.time()}
        )

        # Determine if the message is a question that might benefit from collaboration
        # Helps encourage collaboration and discovery
        question_indicators = [
            "?",
            "who",
            "what",
            "when",
            "where",
            "why",
            "how",
            "can you",
            "could you",
        ]
        is_question = any(
            indicator in message.lower() for indicator in question_indicators
        )

        peer_responses = []
        if is_question and self.collaboration_enabled:
            # Get assistance from peers
            logger.info("Question detected, getting assistance from peers")
            # Log current peer info for debugging
            all_peers = self.peer_manager.get_all_peers()
            healthy_peers = self.peer_manager.get_healthy_peers()
            logger.info(
                f"Total peers: {len(all_peers)}, Healthy peers: {len(healthy_peers)}"
            )

            # If we have peers but none are healthy, log a warning and try to fix
            if all_peers and not healthy_peers:
                logger.warning(
                    "Have peers but none marked healthy, checking health now"
                )
                for peer_id in list(all_peers.keys())[:3]:  # Check first 3 peers
                    health = self.peer_manager.check_peer_health(peer_id)
                    logger.info(f"Health check for {peer_id}: {health}")
                # Get healthy peers again after checks
                healthy_peers = self.peer_manager.get_healthy_peers()
                logger.info(
                    f"After health checks - Healthy peers: {len(healthy_peers)}"
                )

            peer_responses = self.get_assistance_from_peers(message)
            logger.info(f"Received {len(peer_responses)} peer responses")

        # Create system prompt
        system_prompt = f"""You are {self.name}, an AI agent with the following capabilities: {', '.join(self.capabilities)}.

You help users by providing informative, helpful, and accurate responses. Your responses should be friendly, engaging, and tailored to the user's needs.
"""

        # Add peer response information if available
        if peer_responses:
            system_prompt += "\n\nYou have received assistance from peer agents. Include relevant information from these peers in your response, citing them appropriately."

            for i, peer_response in enumerate(peer_responses):
                system_prompt += f"\n\nPeer {i+1} ({peer_response['peer_name']}): {peer_response['response']}"

        # Get LLM response
        response = self.ask_llm(message, system_prompt=system_prompt)

        # Add assistant response to history
        self.chat_history[session_id].append(
            {"role": "assistant", "content": response, "timestamp": time.time()}
        )

        # Limit history length (keep last 10 messages)
        if len(self.chat_history[session_id]) > 10:
            self.chat_history[session_id] = self.chat_history[session_id][-10:]

        result = {"response": response, "session_id": session_id}

        # Include metadata about peer assistance if available
        if peer_responses:
            result["meta"] = {
                "collaborative": True,
                "peer_count": len(peer_responses),
                "peers": [pr["peer_name"] for pr in peer_responses],
            }

        return result


# Initialize agent
agent = Agent(AGENT_CONFIG)


# API endpoints
@app.route("/metadata", methods=["GET"])
def get_metadata():
    """Return agent metadata"""
    return jsonify(agent.to_dict())


@app.route("/peers", methods=["GET"])
def get_peers():
    """Return known peers"""
    return jsonify({"peers": agent.peer_manager.get_peer_ids()})


@app.route("/peers", methods=["POST"])
def update_peers():
    """Receive peer updates from other agents"""
    peers_data = request.json
    if not peers_data or "peers" not in peers_data:
        return jsonify({"error": "Invalid peer data"}), 400

    new_peers = []
    for peer_id in peers_data["peers"]:
        if peer_id != agent.id and peer_id not in agent.peer_manager.get_all_peers():
            # Get peer details through discovery service
            try:
                peer_data = agent.discover_agent(peer_id)
                if peer_data:
                    agent.peer_manager.add_peer(peer_id, peer_data)
                    # For backward compatibility
                    agent.peers[peer_id] = peer_data
                    new_peers.append(peer_id)
                else:
                    logger.warning(f"Could not discover peer {peer_id}")
            except Exception as e:
                logger.warning(f"Error discovering peer {peer_id}: {e}")

    return jsonify(
        {
            "status": "success",
            "added_peers": new_peers,
            "total_peers": len(agent.peer_manager.get_all_peers()),
        }
    )


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "ok"})


@app.route("/chat", methods=["POST"])
def chat():
    """Chat endpoint for basic interaction with collaborative capabilities"""
    data = request.json
    if not data or "text" not in data:
        return jsonify({"error": "Missing text parameter"}), 400

    session_id = data.get("session_id", "default")
    user_message = data["text"]

    # Handle the chat message
    result = agent.handle_chat(user_message, session_id)

    # Explicitly record interaction in memory
    try:
        response = result.get("response", "")
        memory_result = agent.record_interaction_in_memory(
            user_message, response, session_id
        )
        logger.info(f"Recorded chat interaction in memory: {memory_result}")

        # For debugging, add memory status to response
        if memory_result and memory_result.get("status") == "success":
            result["memory_recorded"] = True
        else:
            result["memory_recorded"] = False
            logger.warning(f"Memory recording may have failed: {memory_result}")
    except Exception as e:
        logger.error(f"Error recording chat in memory: {str(e)}")
        result["memory_recorded"] = False

    return jsonify(result)


@app.route("/assist", methods=["POST"])
def assist():
    """Assistance endpoint for peer agents"""
    data = request.json
    if not data:
        return jsonify({"error": "Missing request data"}), 400

    result = agent.handle_assist_request(data)
    return jsonify(result)


@app.route("/discover", methods=["GET"])
def discover_agents():
    """Discover agents by capability"""
    capability = request.args.get("capability")
    if not capability:
        return jsonify({"error": "Missing capability parameter"}), 400

    agents = agent.discover_agents_by_capability(capability)
    return jsonify({"agents": agents})


@app.route("/search", methods=["POST"])
def search_agents():
    """Search for agents by criteria"""
    criteria = request.json
    if not criteria:
        return jsonify({"error": "Missing search criteria"}), 400

    agents = agent.discover_agents_by_criteria(criteria)
    return jsonify({"agents": agents})


@app.route("/resolve/<agent_id>", methods=["GET"])
def resolve_agent(agent_id):
    """Resolve agent information by ID"""
    agent_info = agent.discover_agent(agent_id)
    if not agent_info:
        return jsonify({"error": f"Agent {agent_id} not found"}), 404

    return jsonify(agent_info)


@app.route("/gossip/stats", methods=["GET"])
def gossip_stats():
    """Get gossip protocol statistics"""
    return jsonify(agent.peer_manager.gossip_stats)


@app.route("/gossip/start", methods=["POST"])
def start_gossip():
    """Start the gossip protocol"""
    success = agent.start_gossip()
    return jsonify({"status": "started" if success else "failed"})


@app.route("/gossip/stop", methods=["POST"])
def stop_gossip():
    """Stop the gossip protocol"""
    success = agent.peer_manager.stop_gossip_thread()
    return jsonify({"status": "stopped" if success else "not running"})


@app.route("/memory", methods=["GET"])
def get_memory():
    """Get all shared memory"""
    result = agent.get_shared_memory()
    return jsonify(result)


@app.route("/memory/<key>", methods=["GET"])
def get_memory_key(key):
    """Get specific memory entry"""
    result = agent.get_shared_memory()
    memory = result.get("memory", {})
    if key in memory:
        return jsonify({"memory": {key: memory[key]}})
    else:
        return jsonify({"error": "Memory key not found"}), 404


@app.route("/memory", methods=["POST"])
def update_memory():
    """Update shared memory"""
    data = request.json
    if not data or "key" not in data or "value" not in data:
        return jsonify({"error": "Missing key or value"}), 400

    result = agent.store_in_shared_memory(data["key"], data["value"])
    return jsonify(result)


def start_background_tasks():
    """Start background tasks like heartbeat"""
    # Register with DNS
    agent.register_dns()

    # Register with registry
    if agent.register():
        logger.info("Successfully registered with registry")
    else:
        logger.warning("Initial registration failed, will retry in heartbeat thread")

    # Fetch initial peers
    agent.fetch_peers()

    # Start heartbeat thread
    heartbeat_thread = threading.Thread(target=agent.heartbeat, daemon=True)
    heartbeat_thread.start()

    # Start peer refresh thread with enhanced discovery
    def refresh_peers():
        while True:
            try:
                # Use both traditional fetch and discovery-based refresh
                agent.fetch_peers()
                agent.refresh_peer_discovery()
                logger.info(
                    f"Refreshed peers, now tracking {len(agent.peer_manager.get_all_peers())} peers"
                )
            except Exception as e:
                logger.error(f"Error in peer refresh: {e}")

            time.sleep(300)  # Refresh peers every 5 minutes

    peer_thread = threading.Thread(target=refresh_peers, daemon=True)
    peer_thread.start()

    # Wait a bit for initial peer discovery before starting gossip
    time.sleep(10)

    # Start the gossip protocol
    try:
        agent.start_gossip()
    except Exception as e:
        logger.error(f"Failed to start gossip protocol: {e}")


if __name__ == "__main__":
    # Start background tasks
    start_background_tasks()

    # Start Flask server
    app.run(host="0.0.0.0", port=AGENT_CONFIG["port"])
