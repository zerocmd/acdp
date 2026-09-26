import os
import socket

# Get hostname or use environment variable
hostname = os.environ.get("AGENT_HOSTNAME", socket.gethostname())
port = int(os.environ.get("AGENT_PORT", 8000))

# Use the full domain for the agent ID
agent_id = os.environ.get("AGENT_ID", f"{hostname}.agents.local")

# For Docker networking, extract the service name from the hostname or ID
service_name = hostname
if "." in hostname:
    service_name = hostname.split(".")[0]

# Try to resolve the DNS server to an IP address
dns_server = os.environ.get("DNS_SERVER", "bind")
try:
    dns_server_ip = socket.gethostbyname(dns_server)
except OSError:
    dns_server_ip = "127.0.0.1"  # Fallback to localhost

# Get capabilities from environment. See docker-compose.yml for agent examples.
capabilities_str = os.environ.get(
    "AGENT_CAPABILITIES", "chat,summarization,translation"
)
capabilities = [cap.strip() for cap in capabilities_str.split(",") if cap.strip()]

# Public base URL other agents use to reach this agent (A2A card URL, ACDP interfaces).
public_url = os.environ.get("AGENT_PUBLIC_URL", f"http://{service_name}:{port}").rstrip("/")

# ACDP protocol version advertised in DNS TXT "ver=" and in the A2A extension params.
# 1.1 = ACDP 1.0 discovery + A2A invocation profile (see ACDP.md "A2A Interoperability Profile").
ACDP_VERSION = "1.1"

# Model provider for the Strands agent. "anthropic" (default) or "bedrock".
model_provider = os.environ.get("MODEL_PROVIDER", "anthropic").lower()
model_id = os.environ.get(
    "MODEL_ID", "claude-sonnet-5" if model_provider == "anthropic" else ""
)

AGENT_CONFIG = {
    "id": agent_id,
    "name": os.environ.get("AGENT_NAME", f"Agent-{hostname}"),
    "description": os.environ.get(
        "AGENT_DESCRIPTION", "A general purpose AI agent built on Strands Agents"
    ),
    "capabilities": capabilities,  # Now populated from environment
    "interfaces": {
        "rest": public_url,  # ACDP REST surface (/metadata, /peers, /chat, ...)
        "a2a": f"{public_url}/",  # A2A JSON-RPC endpoint (Agent Card "url")
    },
    "model_info": {
        "type": model_id,
        "provider": "Anthropic" if model_provider == "anthropic" else model_provider,
        "runtime": "strands-agents",
    },
    "model": {
        "provider": model_provider,
        "model_id": model_id,
        "max_tokens": int(os.environ.get("MODEL_MAX_TOKENS", "16000")),
        "region": os.environ.get("AWS_REGION"),
    },
    "owner": os.environ.get("AGENT_OWNER", "Command Zero"),
    "owner_url": os.environ.get("AGENT_OWNER_URL", "https://github.com/zerocmd/acdp"),
    "endpoints": {
        "metadata": "/metadata",
        "peers": "/peers",
        "ping": "/health",
        "task": "/chat",
        "assist": "/assist",  # Legacy ACDP 1.0 peer assistance
        "a2a": "/",  # A2A JSON-RPC (message/send, message/stream, tasks/*)
        "agent_card": "/.well-known/agent-card.json",
    },
    "version": os.environ.get("AGENT_VERSION", "0.2.0"),
    "protocols": ["a2a/0.3", "rest-json"],
    "acdp_version": ACDP_VERSION,
    "registry_url": os.environ.get("REGISTRY_URL", "http://registry:5000"),
    "dns_server": dns_server_ip,  # Use resolved IP
    "dns_port": int(os.environ.get("DNS_PORT", "53")),
    "host": service_name,  # Use the Docker service name for networking
    "port": port,
    "public_url": public_url,
    "discovery": {
        "refresh_interval": 300,  # How often to refresh the agent cache in seconds
        "cache_ttl": 600,  # How long to keep agent info in cache
        "methods": ["registry", "dns", "peers"],  # Discovery methods to use
    },
    "security": {
        # Shared bearer token for agent-to-agent calls (A2A JSON-RPC and /assist).
        # Unset = open, matching the original PoC. The Agent Card advertises the scheme when set.
        "a2a_token": os.environ.get("ACDP_A2A_TOKEN") or None,
        # Reject peers whose Agent Card does not carry the ACDP extension with a matching id.
        "verify_peer_cards": os.environ.get("ACDP_VERIFY_PEER_CARDS", "true").lower()
        == "true",
    },
    "peers": {
        "max_peers_to_exchange": 10,
        "peer_ttl": 3600,  # Time-to-live for peers in seconds
        "gossip_interval": 60,  # Seconds between gossip exchanges
        "fanout": 3,  # Number of peers to gossip with in each round
    },
    "collaboration": {
        # auto: the model decides when to consult peers (tools available)
        # always: the system prompt requires consulting at least one relevant peer for questions
        # off: no peer tools; the agent answers alone
        "mode": os.environ.get("COLLABORATION_MODE", "auto").lower(),
        "timeout": int(os.environ.get("COLLABORATION_TIMEOUT", "120")),
        # Maximum ask_agent calls a single request may make (across all tool cycles).
        "max_peer_calls": int(os.environ.get("ACDP_MAX_PEER_CALLS", "4")),
        # Longest allowed delegation chain (user -> A -> B counts as 1 hop from A).
        "max_delegation_depth": int(os.environ.get("ACDP_MAX_DELEGATION_DEPTH", "2")),
    },
    "sessions": {
        "max_sessions": int(os.environ.get("MAX_SESSIONS", "100")),
    },
}
