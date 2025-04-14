from flask import Flask, request, jsonify, render_template, send_from_directory
import time
import datetime
import traceback
import logging
import os

app = Flask(__name__, static_folder="static")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory store of registered agents
agents = {}

# In-memory store of shared memory between agents
shared_memory = {}

# In-memory store of agent chat messages
agent_chats = {}


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
    """Return all registered agents or filter by capability"""
    try:
        capability = request.args.get("capability")
        query = request.args.get("query")
        protocol = request.args.get("protocol")
        provider = request.args.get("provider")
        limit = request.args.get("limit", type=int)
        offset = request.args.get("offset", 0, type=int)

        # If only capability is provided, use the simple search
        if capability and not (query or protocol or provider):
            results = []
            for agent_id, agent in agents.items():
                if capability in agent.get("capabilities", []):
                    results.append(agent)

            # Apply pagination if specified
            if limit is not None:
                results = results[offset : offset + limit]

            return jsonify({"agents": results})

        # If multiple criteria are provided, use the advanced search
        if capability or query or protocol or provider:
            results = []
            for agent_id, agent in agents.items():
                # Check capability
                if capability and capability not in agent.get("capabilities", []):
                    continue

                # Check query in name or description
                if query:
                    query_lower = query.lower()
                    name = agent.get("name", "").lower()
                    description = agent.get("description", "").lower()
                    if query_lower not in name and query_lower not in description:
                        continue

                # Check protocol
                if protocol and protocol not in agent.get("protocols", []):
                    continue

                # Check provider
                if provider and agent.get("model_info", {}).get("provider") != provider:
                    continue

                # If we got here, the agent matches all criteria
                results.append(agent)

            # Apply pagination if specified
            if limit is not None:
                results = results[offset : offset + limit]

            return jsonify({"agents": results})

        # If no filters, return all agents (with pagination if specified)
        all_agents = list(agents.values())
        if limit is not None:
            all_agents = all_agents[offset : offset + limit]

        return jsonify({"agents": all_agents})
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
        return jsonify(agent)
    except Exception as e:
        logger.error(f"Error getting agent {agent_id}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/registerAgent", methods=["POST"])
def register_agent():
    """Register a new agent or update existing one"""
    try:
        data = request.json

        # Validate required fields
        required_fields = ["id", "name", "capabilities", "interfaces"]
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        # Update or create agent
        agent_id = data["id"]
        data["last_update"] = time.time()

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
        agent_info = agents[agent_id]
        host = agent_info.get("host")
        port = agent_info.get("port")

        if not host or not port:
            # Try to extract from interfaces
            rest_interface = agent_info.get("interfaces", {}).get("rest", "")
            if rest_interface:
                import urllib.parse

                parsed = urllib.parse.urlparse(rest_interface)
                if parsed.netloc:
                    host_port = parsed.netloc.split(":")
                    host = host_port[0]
                    if len(host_port) > 1:
                        port = int(host_port[1])

        # If we still don't have host/port, try to use the agent ID
        if not host and "." in agent_id:
            host = agent_id.split(".")[0]  # Use service name from domain
            port = 8000  # Default port

        if not host or not port:
            return jsonify({"error": "Could not determine agent endpoint"}), 400

        # Make the request
        import requests

        response = requests.get(f"http://{host}:{port}/peers", timeout=5)
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
        agent_info = agents[agent_id]
        host = agent_info.get("host")
        port = agent_info.get("port")

        if not host or not port:
            # Try to extract from interfaces
            rest_interface = agent_info.get("interfaces", {}).get("rest", "")
            if rest_interface:
                import urllib.parse

                parsed = urllib.parse.urlparse(rest_interface)
                if parsed.netloc:
                    host_port = parsed.netloc.split(":")
                    host = host_port[0]
                    if len(host_port) > 1:
                        port = int(host_port[1])

        # If we still don't have host/port, try to use the agent ID
        if not host and "." in agent_id:
            host = agent_id.split(".")[0]  # Use service name from domain
            port = 8000  # Default port

        if not host or not port:
            return jsonify({"error": "Could not determine agent endpoint"}), 400

        # Make the request
        import requests

        response = requests.post(
            f"http://{host}:{port}/chat", json={"text": data["text"]}, timeout=30
        )
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


# Add a simple health check endpoint
@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "ok", "agent_count": len(agents)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
