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
except:
    dns_server_ip = "127.0.0.1"  # Fallback to localhost

# Get capabilities from environment. See docker-compose.yml for agent examples.
capabilities_str = os.environ.get(
    "AGENT_CAPABILITIES", "chat,summarization,translation"
)
capabilities = [cap.strip() for cap in capabilities_str.split(",")]

AGENT_CONFIG = {
    "id": agent_id,
    "name": os.environ.get("AGENT_NAME", f"Agent-{hostname}"),
    "description": os.environ.get(
        "AGENT_DESCRIPTION", "A general purpose AI agent powered by Anthropic Sonnet"
    ),
    "capabilities": capabilities,  # Now populated from environment
    "interfaces": {
        "rest": f"http://{service_name}:{port}/v1"  # Use Docker service name for networking
    },
    "model_info": {"type": "Claude-37-Sonnet", "provider": "Anthropic"},
    "model": "claude-3-7-sonnet-latest",  # Specify the model to use
    "owner": "Command Zero",
    "endpoints": {
        "metadata": "/metadata",
        "peers": "/peers",
        "ping": "/health",
        "task": "/chat",
        "assist": "/assist",  # Add assist endpoint
    },
    "version": "0.1.0",
    "protocols": ["rest-json"],
    "registry_url": os.environ.get("REGISTRY_URL", "http://registry:5000"),
    "dns_server": dns_server_ip,  # Use resolved IP
    "dns_port": int(os.environ.get("DNS_PORT", "53")),
    "host": service_name,  # Use the Docker service name for networking
    "port": port,
    "discovery": {
        "refresh_interval": 300,  # How often to refresh the agent cache in seconds
        "cache_ttl": 600,  # How long to keep agent info in cache
        "methods": ["registry", "dns", "peers"],  # Discovery methods to use
    },
    "security": {
        "require_auth": False,  # Whether to require authentication for API access
        "allowed_peers": [],  # List of peer IDs allowed to access this agent
    },
    "gossip": {
        "gossip_interval": 60,  # Seconds between gossip rounds
        "fanout": 3,  # Number of peers to gossip with in each round
        "max_peers_per_message": 10,  # Max peers to send in each message
    },
    "peers": {
        "max_peers_to_exchange": 10,
        "peer_ttl": 3600,  # Time-to-live for peers in seconds
        "gossip_interval": 60,  # Seconds between gossip exchanges
    },
    "collaboration": {
        "enabled": True,
        "timeout": 30,  # Increased timeout from 5 to 30 seconds
        "max_peers": 3,  # Maximum number of peers to query for each question
    },
}
