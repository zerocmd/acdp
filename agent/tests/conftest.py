"""Test fixtures: scripted Strands model, in-memory registry/discovery, ASGI routing.

Nothing here touches the network or an LLM. Agents talk to each other over real A2A
JSON-RPC, routed in-process through httpx ASGI transports.
"""

import copy
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest
from strands.models import Model

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from node import AgentNode  # noqa: E402


# --------------------------------------------------------------------------- model


def last_user_blocks(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return messages[-1]["content"] if messages else []


def first_user_text(messages: List[Dict[str, Any]]) -> str:
    for message in messages:
        if message["role"] == "user":
            for block in message["content"]:
                if "text" in block:
                    return block["text"]
    return ""


def tool_results(messages: List[Dict[str, Any]]) -> List[str]:
    out = []
    for block in last_user_blocks(messages):
        result = block.get("toolResult")
        if result:
            out.append(" ".join(c.get("text", "") for c in result.get("content", [])))
    return out


class ScriptedModel(Model):
    """Strands Model whose turns are decided by a Python function.

    ``script(messages)`` returns either ``("text", str)`` or
    ``("tools", [(tool_name, input_dict), ...])``.
    """

    def __init__(self, script: Callable[[List[Dict[str, Any]]], tuple]):
        self.script = script
        self._n = 0

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> Dict[str, Any]:
        return {"model_id": "scripted"}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        action = self.script(messages)
        yield {"messageStart": {"role": "assistant"}}
        if action[0] == "tools":
            for name, tool_input in action[1]:
                self._n += 1
                yield {
                    "contentBlockStart": {
                        "start": {"toolUse": {"toolUseId": f"tooluse_{self._n}", "name": name}}
                    }
                }
                yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}}
                yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": action[1]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}


# --------------------------------------------------------------------------- ACDP fakes


class FakeRegistry:
    def __init__(self):
        self.memory: Dict[str, Any] = {}
        self.registered: List[Dict[str, Any]] = []

    def register_agent(self, data):
        self.registered.append(data)
        return {"status": "success"}

    def heartbeat(self, agent_id):
        return {"status": "success"}

    def get_agents(self, **kwargs):
        return {"agents": []}

    def get_shared_memory(self):
        return {"memory": copy.deepcopy(self.memory)}

    def update_shared_memory(self, key, value, owner=None):
        self.memory[key] = {"value": value, "owner": owner, "timestamp": 0}
        return {"status": "success"}


class FakeDiscovery:
    def __init__(self, agents: Optional[Dict[str, Dict[str, Any]]] = None):
        self.agents = agents or {}
        self.cache_ttl = 600

    def discover_agent(self, agent_id):
        return copy.deepcopy(self.agents.get(agent_id))

    def discover_agents_by_capability(self, capability):
        return [
            copy.deepcopy(a) for a in self.agents.values() if capability in a.get("capabilities", [])
        ]

    def discover_agents_by_criteria(self, criteria):
        return []


# --------------------------------------------------------------------------- routing


class RoutingTransport(httpx.AsyncBaseTransport):
    """Dispatch requests to in-process ASGI apps by URL host."""

    def __init__(self):
        self.apps: Dict[str, httpx.ASGITransport] = {}

    def add(self, host: str, app: Any) -> None:
        self.apps[host] = httpx.ASGITransport(app=app)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        transport = self.apps.get(request.url.host)
        if transport is None:
            raise httpx.ConnectError(f"no route to {request.url.host}", request=request)
        return await transport.handle_async_request(request)


def make_config(
    service: str,
    name: str,
    capabilities: List[str],
    token: Optional[str] = None,
    max_depth: int = 2,
    max_peer_calls: int = 4,
) -> Dict[str, Any]:
    public_url = f"http://{service}:8000"
    return {
        "id": f"{service}.agents.local",
        "name": name,
        "description": f"{name} test agent",
        "capabilities": capabilities,
        "interfaces": {"rest": public_url, "a2a": f"{public_url}/"},
        "model_info": {"type": "scripted", "provider": "test", "runtime": "strands-agents"},
        "model": {"provider": "test", "model_id": "scripted", "max_tokens": 1000},
        "owner": "Test Owner",
        "owner_url": "https://example.com",
        "endpoints": {
            "metadata": "/metadata",
            "peers": "/peers",
            "ping": "/health",
            "task": "/chat",
            "assist": "/assist",
            "a2a": "/",
            "agent_card": "/.well-known/agent-card.json",
        },
        "version": "0.2.0",
        "protocols": ["a2a/0.3", "rest-json"],
        "acdp_version": "1.1",
        "registry_url": "http://registry:5000",
        "dns_server": "127.0.0.1",
        "dns_port": 53,
        "host": service,
        "port": 8000,
        "public_url": public_url,
        "discovery": {"cache_ttl": 600},
        "security": {"a2a_token": token, "verify_peer_cards": True},
        "peers": {"max_peers_to_exchange": 10, "peer_ttl": 3600, "gossip_interval": 60},
        "collaboration": {
            "mode": "auto",
            "timeout": 30,
            "max_peer_calls": max_peer_calls,
            "max_delegation_depth": max_depth,
        },
        "sessions": {"max_sessions": 10},
    }


class Network:
    """A set of in-process agent nodes that can reach each other over A2A."""

    def __init__(self):
        self.transport = RoutingTransport()
        self.discovery = FakeDiscovery()
        self.nodes: Dict[str, AgentNode] = {}
        self.apps: Dict[str, Any] = {}

    def client_factory(self, token: Optional[str] = None) -> Callable[[], httpx.AsyncClient]:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        return lambda: httpx.AsyncClient(transport=self.transport, headers=headers, timeout=30)

    def add(self, config: Dict[str, Any], script, peer_token: Optional[str] = None) -> AgentNode:
        node = AgentNode(
            config,
            model_factory=lambda: ScriptedModel(script),
            peer_http_client_factory=self.client_factory(peer_token),
            registry=FakeRegistry(),
            discovery_service=self.discovery,
        )
        app = node.build_app(start_background=False)
        self.transport.add(config["host"], app)
        self.discovery.agents[node.id] = node.to_dict()
        self.nodes[config["host"]] = node
        self.apps[config["host"]] = app
        return node


@pytest.fixture
def network() -> Network:
    return Network()
