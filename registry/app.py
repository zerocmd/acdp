from flask import Flask, request, jsonify, render_template, send_from_directory
import time
import datetime
import traceback
import logging
import os
import re
import socket
import urllib.parse

import dns.exception
import dns.resolver
import requests

from services.search import SearchService, agent_status
from services.verification import OrgDirectory, normalize_org, verify_registration

app = Flask(__name__, static_folder="static")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory store of registered agents
agents = {}

# In-memory store of shared memory between agents
shared_memory = {}

# In-memory store of agent chat messages
agent_chats = {}

# All state above is per-process. Run a single worker process (threads are fine);
# multiple workers each hold a different registry. See registry/DockerFile.
search_service = SearchService(agents)
orgs = OrgDirectory()
DNS_SERVER = os.environ.get("DNS_SERVER", "bind")
CARD_PATH_SUFFIX = "/.well-known/agent-card.json"
# Hosts the registry may fetch cards from. Empty means any host (local development).
CARD_HOSTS = {
    h.strip().lower() for h in os.environ.get("REGISTRY_CARD_HOSTS", "").split(",") if h.strip()
}


def fetch_card(url):
    """Fetch an Agent Card for verification. Returns None on any fetch failure.

    The URL comes from the registrant, so the registry fetches only card paths,
    only from allowed hosts, and does not follow redirects.
    """
    if not isinstance(url, str):
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.path.endswith(CARD_PATH_SUFFIX):
        return None
    if CARD_HOSTS and (parsed.hostname or "").lower() not in CARD_HOSTS:
        return None
    try:
        response = requests.get(url, timeout=5, allow_redirects=False)
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError):
        return None
    return body if isinstance(body, dict) else None


def lookup_txt(agent_id):
    """TXT strings for _llm-agent._tcp.<agent_id> from the ACDP DNS server."""
    try:
        resolver = dns.resolver.Resolver(configure=False)
        resolver.nameservers = [socket.gethostbyname(DNS_SERVER)]
        answers = resolver.resolve(f"_llm-agent._tcp.{agent_id}", "TXT", lifetime=3)
    except (dns.exception.DNSException, OSError):
        return None
    return [s.decode("utf-8") for rdata in answers for s in rdata.strings]

# DNS-style agent ids, e.g. agent1.agents.local
AGENT_ID_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")


def _summary(agent):
    """Agent entry for list responses: everything except the full Agent Card."""
    entry = {k: v for k, v in agent.items() if k != "agent_card"}
    entry["status"] = agent_status(agent)
    return entry


def _agent_base_url(agent_id, agent_info):
    """Origin (scheme://host:port) of an agent's HTTP surface."""
    interfaces = agent_info.get("interfaces", {})
    for candidate in ((agent_info.get("a2a") or {}).get("url"), interfaces.get("a2a"), interfaces.get("rest")):
        if candidate:
            parsed = urllib.parse.urlparse(candidate)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
    host = agent_info.get("host") or (agent_id.split(".")[0] if "." in agent_id else None)
    port = agent_info.get("port") or 8000
    return f"http://{host}:{port}" if host else None


def _validate_card(card):
    """Minimal structural check of an A2A Agent Card (0.3 or 1.0 JSON)."""
    if not isinstance(card, dict):
        return "agent_card must be an object"
    if not card.get("name"):
        return "agent_card.name is required"
    has_url = card.get("url") or any(
        i.get("url") for i in card.get("supportedInterfaces") or [] if isinstance(i, dict)
    )
    if not has_url:
        return "agent_card must declare url (A2A 0.3) or supportedInterfaces (A2A 1.0)"
    return None


# Define custom Jinja2 filters
@app.template_filter("timestamp")
def timestamp_filter(timestamp):
    """Convert Unix timestamp to readable date"""
    try:
        dt = datetime.datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logger.error(f"Error formatting timestamp: {e}")
        return "Invalid timestamp"


@app.route("/static/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)


@app.route("/")
def index():
    """Simple dashboard to view registered agents"""
    try:
        return render_template("index.html", agents=agents, now=time.time())
    except Exception as e:
        logger.error(f"Error rendering index: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/agents", methods=["GET"])
def get_agents():
    """Return registered agents, optionally filtered.

    Filters: capability (ACDP capability or A2A skill), skill (A2A skill id/tag),
    query (name/description), protocol ("a2a" matches "a2a/0.3"), provider,
    status (online|stale), plus limit/offset pagination.
    """
    try:
        criteria = {
            "capabilities": [request.args["capability"]] if request.args.get("capability") else None,
            "skill": request.args.get("skill"),
            "query": request.args.get("query"),
            "protocol": request.args.get("protocol"),
            "provider": request.args.get("provider"),
            "status": request.args.get("status"),
        }
        results = search_service.search_by_criteria(
            criteria,
            limit=request.args.get("limit", type=int),
            offset=request.args.get("offset", 0, type=int),
        )
        return jsonify({"agents": [_summary(agent) for agent in results]})
    except Exception as e:
        logger.error(f"Error getting agents: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e), "agents": []}), 500


@app.route("/agents/<agent_id>", methods=["GET"])
def get_agent(agent_id):
    """Get a specific agent by ID"""
    try:
        agent = agents.get(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404
        return jsonify(dict(agent, status=agent_status(agent)))
    except Exception as e:
        logger.error(f"Error getting agent {agent_id}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/registerAgent", methods=["POST"])
def register_agent():
    """Register a new agent or update existing one"""
    try:
        data = request.json

        if not isinstance(data, dict):
            return jsonify({"error": "Expected a JSON object"}), 400

        # Validate required fields
        required_fields = ["id", "name", "capabilities", "interfaces"]
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        agent_id = data["id"]
        if not isinstance(agent_id, str) or not AGENT_ID_RE.fullmatch(agent_id):
            return jsonify({"error": "id must be a DNS-style name, e.g. agent1.agents.local"}), 400
        if not isinstance(data["capabilities"], list):
            return jsonify({"error": "capabilities must be a list"}), 400

        # ACDP 1.1 agents include their A2A Agent Card; ACDP 1.0 agents do not.
        if "agent_card" in data:
            problem = _validate_card(data["agent_card"])
            if problem:
                return jsonify({"error": problem}), 400
            data["verification"] = verify_registration(data, fetch_card, lookup_txt, orgs)

        # Update or create agent
        now = time.time()
        data["registered_at"] = agents.get(agent_id, {}).get("registered_at", now)
        data["last_update"] = now

        # If this is an update, log it
        if agent_id in agents:
            logger.info(f"Updating agent: {agent_id}")
        else:
            logger.info(f"Registering new agent: {agent_id}")

        agents[agent_id] = data

        # Return success with the agent data
        return jsonify(
            {
                "status": "success",
                "message": "Agent registered successfully",
                "agent": data,
            }
        )
    except Exception as e:
        logger.error(f"Error registering agent: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/agents/<agent_id>/card", methods=["GET"])
def get_agent_card(agent_id):
    """The A2A Agent Card an agent registered (ACDP 1.1+)."""
    agent = agents.get(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found"}), 404
    if not agent.get("agent_card"):
        return jsonify({"error": "Agent did not register an A2A Agent Card"}), 404
    return jsonify(agent["agent_card"])


@app.route("/.well-known/agent-registry", methods=["GET"])
def well_known_registry():
    """Registry descriptor (ACDP.md, "Well-Known URI Pattern")."""
    base = request.host_url.rstrip("/")
    return jsonify(
        {
            "registries": [
                {
                    "name": os.environ.get("REGISTRY_NAME", "ACDP PoC Registry"),
                    "endpoint": base,
                    "api_version": "1.1",
                    "capabilities": ["agent-discovery", "a2a-agent-cards"],
                    "endpoints": {
                        "agents": "/agents",
                        "agent": "/agents/{id}",
                        "agent_card": "/agents/{id}/card",
                        "register": "/registerAgent",
                        "heartbeat": "/agents/{id}/heartbeat",
                    },
                }
            ]
        }
    )


@app.route("/agents/<agent_id>/heartbeat", methods=["PUT"])
def heartbeat(agent_id):
    """Update agent's last seen timestamp"""
    try:
        if agent_id not in agents:
            return jsonify({"error": "Agent not found"}), 404

        agents[agent_id]["last_update"] = time.time()
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error updating heartbeat for {agent_id}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/agents/<agent_id>", methods=["DELETE"])
def unregister_agent(agent_id):
    """Remove an agent from the registry"""
    try:
        if agent_id not in agents:
            return jsonify({"error": "Agent not found"}), 404

        del agents[agent_id]
        logger.info(f"Unregistered agent: {agent_id}")
        return jsonify({"status": "success", "message": "Agent unregistered"})
    except Exception as e:
        logger.error(f"Error unregistering agent {agent_id}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/agents/<agent_id>/peers", methods=["GET"])
def get_agent_peers(agent_id):
    """Get an agent's peers"""
    try:
        if agent_id not in agents:
            return jsonify({"error": "Agent not found"}), 404

        # Make a request to the agent's peers endpoint
        base = _agent_base_url(agent_id, agents[agent_id])
        if not base:
            return jsonify({"error": "Could not determine agent endpoint"}), 400

        response = requests.get(f"{base}/peers", timeout=5)
        response.raise_for_status()

        return jsonify(response.json())
    except Exception as e:
        logger.error(f"Error getting peers for agent {agent_id}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/agents/<agent_id>/chat", methods=["POST"])
def chat_with_agent(agent_id):
    """Send a chat message to an agent"""
    try:
        if agent_id not in agents:
            return jsonify({"error": "Agent not found"}), 404

        data = request.json
        if not data or "text" not in data:
            return jsonify({"error": "Missing text parameter"}), 400

        # Make a request to the agent's chat endpoint
        base = _agent_base_url(agent_id, agents[agent_id])
        if not base:
            return jsonify({"error": "Could not determine agent endpoint"}), 400

        response = requests.post(f"{base}/chat", json={"text": data["text"]}, timeout=180)
        response.raise_for_status()

        # Store the chat message and response
        if agent_id not in agent_chats:
            agent_chats[agent_id] = []

        agent_chats[agent_id].append(
            {
                "user": data["text"],
                "agent": response.json().get("response", "No response"),
                "timestamp": time.time(),
            }
        )

        return jsonify(response.json())
    except Exception as e:
        logger.error(f"Error chatting with agent {agent_id}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/agents/<agent_id>/chat/history", methods=["GET"])
def get_chat_history(agent_id):
    """Get chat history with an agent"""
    try:
        if agent_id not in agent_chats:
            return jsonify({"messages": []})

        return jsonify({"messages": agent_chats[agent_id]})
    except Exception as e:
        logger.error(f"Error getting chat history for agent {agent_id}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/shared-memory", methods=["GET"])
def get_shared_memory():
    """Get all shared memory"""
    return jsonify({"memory": shared_memory})


@app.route("/shared-memory", methods=["POST"])
def update_shared_memory():
    """Update shared memory"""
    try:
        data = request.json
        if not data or "key" not in data or "value" not in data:
            return jsonify({"error": "Missing key or value parameter"}), 400

        shared_memory[data["key"]] = {
            "value": data["value"],
            "timestamp": time.time(),
            "owner": data.get("owner", "unknown"),
        }

        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error updating shared memory: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/orgs/<normalized>", methods=["GET"])
def get_org(normalized):
    """Canonical domain of an organization (first registrant wins)."""
    entry = orgs.get(normalize_org(normalized))
    if not entry:
        return jsonify({"error": "Organization not found"}), 404
    return jsonify(entry)


# Add a simple health check endpoint
@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "ok", "agent_count": len(agents)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
