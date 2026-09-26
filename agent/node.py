"""An ACDP node: discovery and peer awareness around a Strands agent served over A2A.

Replaces the monolithic ``Agent`` class that used to live in agent.py. Responsibilities:

* ACDP: DNS registration, registry registration + heartbeat, peer refresh, gossip.
* Runtime: a Strands agent factory (runtime/strands_agent.py) with ACDP-aware tools.
* Surfaces: the A2A endpoint + Agent Card (Strands A2AServer) and the ACDP REST API
  (acdp_routes.py) on one FastAPI app.
"""

import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Optional

import httpx
from fastapi import FastAPI

from discovery.discovery_service import DiscoveryService
from discovery.registry_client import RegistryClient
from peers.peer_manager import PeerManager
from runtime.a2a_card import acdp_a2a_block, build_agent_card
from runtime.a2a_server import ACDPA2AServer, BearerTokenMiddleware
from runtime.peer_client import PeerClient
from runtime.strands_agent import AgentRuntime, ModelFactory
from utils.dns_utils import register_dns

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 60
PEER_REFRESH_INTERVAL = 300
MAX_A2A_CONTEXTS = 100


class AgentNode:
    def __init__(
        self,
        config: Dict[str, Any],
        model_factory: Optional[ModelFactory] = None,
        peer_http_client_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
        registry: Optional[RegistryClient] = None,
        discovery_service: Optional[DiscoveryService] = None,
    ):
        self.config = config
        self.id = config["id"]
        self.name = config["name"]
        self.registered = False
        self.last_update = time.time()

        self.registry = registry or RegistryClient(config["registry_url"])
        self.discovery_service = discovery_service or DiscoveryService(
            config["registry_url"], config["dns_server"], config.get("dns_port", 53)
        )
        self.discovery_service.cache_ttl = config.get("discovery", {}).get("cache_ttl", 600)
        self.peer_manager = PeerManager(
            agent_id=self.id,
            discovery_service=self.discovery_service,
            config=dict(config.get("peers", {}), capabilities=config["capabilities"]),
        )
        self.peer_client = PeerClient(config, http_client_factory=peer_http_client_factory)
        self.runtime = AgentRuntime(self, model_factory=model_factory)
        self.agent_card = build_agent_card(config)
        self._stop = threading.Event()

    # ------------------------------------------------------------------ metadata

    def to_dict(self) -> Dict[str, Any]:
        """ACDP metadata (served at /metadata and sent to the registry)."""
        c = self.config
        return {
            "id": self.id,
            "name": self.name,
            "description": c["description"],
            "capabilities": c["capabilities"],
            "interfaces": c["interfaces"],
            "model_info": c["model_info"],
            "owner": c["owner"],
            "endpoints": c["endpoints"],
            "version": c["version"],
            "protocols": c["protocols"],
            "acdp_version": c.get("acdp_version", "1.1"),
            "a2a": acdp_a2a_block(c, self.agent_card),
            "host": c["host"],
            "port": c["port"],
            "last_update": self.last_update,
        }

    def registration_payload(self) -> Dict[str, Any]:
        payload = self.to_dict()
        payload["agent_card"] = self.agent_card.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        return payload

    # ------------------------------------------------------------------ registry / DNS

    def register(self) -> bool:
        try:
            response = self.registry.register_agent(self.registration_payload())
            logger.info(f"Registered with registry: {response.get('status')}")
            self.registered = True
            return True
        except Exception as e:
            logger.error(f"Failed to register with registry: {e}")
            return False

    def register_dns(self) -> bool:
        return register_dns(
            domain=self.id,
            host=self.config["host"],
            port=self.config["port"],
            capabilities=",".join(self.config["capabilities"]),
            description=self.config["description"][:200],
            a2a_card_path=self.config["endpoints"]["agent_card"],
            protocols=",".join(self.config["protocols"]),
            version=self.config.get("acdp_version", "1.1"),
        )

    def fetch_peers(self) -> None:
        agents = self.registry.get_agents(status="online").get("agents", [])
        for info in agents:
            if info.get("id") and info["id"] != self.id:
                self.peer_manager.add_peer(info["id"], info)

    def refresh_peer_discovery(self) -> None:
        known = set(self.peer_manager.get_peer_ids())
        for capability in self.config["capabilities"]:
            for info in self.discovery_service.discover_agents_by_capability(capability):
                if info.get("id") and info["id"] != self.id:
                    self.peer_manager.add_peer(info["id"], info)
        new = set(self.peer_manager.get_peer_ids()) - known
        if new:
            logger.info(f"Discovered {len(new)} new peers: {sorted(new)}")

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.registered:
                    self.register()
                if self.registered:
                    response = self.registry.heartbeat(self.id)
                    if response.get("status") == "not_found":
                        logger.warning("Agent not found in registry, re-registering")
                        self.registered = False
                        self.register()
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
            self._stop.wait(HEARTBEAT_INTERVAL)

    def _peer_refresh_loop(self) -> None:
        # Let the other agents come up before the first discovery round.
        self._stop.wait(10)
        gossip_started = False
        while not self._stop.is_set():
            try:
                self.fetch_peers()
                self.refresh_peer_discovery()
                logger.info(f"Tracking {len(self.peer_manager.get_all_peers())} peers")
                if not gossip_started:
                    self.peer_manager.start_gossip_thread()
                    gossip_started = True
            except Exception as e:
                logger.error(f"Peer refresh failed: {e}")
            self._stop.wait(PEER_REFRESH_INTERVAL)

    def _startup(self) -> None:
        self.register_dns()
        if not self.register():
            logger.warning("Initial registration failed, the heartbeat loop will retry")

    def start_background_tasks(self) -> None:
        for target in (self._startup, self._heartbeat_loop, self._peer_refresh_loop):
            threading.Thread(target=target, daemon=True, name=target.__name__).start()

    def stop_background_tasks(self) -> None:
        self._stop.set()
        self.peer_manager.stop_gossip_thread()

    # ------------------------------------------------------------------ shared memory

    def store_in_shared_memory(self, key: str, value: Any) -> Dict[str, Any]:
        try:
            json.dumps(value)
        except TypeError:
            value = {"error": "Original value not serializable", "str_value": str(value)}
        return self.registry.update_shared_memory(key, value, owner=self.id)

    def record_interaction_in_memory(
        self, user_message: str, response: str, session_id: str = "default"
    ) -> Dict[str, Any]:
        memory_key = f"agent_memory_{self.id}"
        try:
            entry = self.registry.get_shared_memory().get("memory", {}).get(memory_key) or {}
            agent_memory = entry.get("value") if isinstance(entry.get("value"), dict) else {}
        except Exception as e:
            logger.warning(f"Could not read memory, starting fresh: {e}")
            agent_memory = {}
        interactions = list(agent_memory.get("interactions", []))
        interactions.append(
            {
                "user_message": user_message,
                "agent_response": response,
                "timestamp": time.time(),
                "session_id": session_id,
            }
        )
        agent_memory.update(
            interactions=interactions[-10:],
            last_updated=time.time(),
            agent_name=self.name,
            agent_id=self.id,
        )
        return self.store_in_shared_memory(memory_key, agent_memory)

    # ------------------------------------------------------------------ app

    def build_app(self, start_background: bool = True) -> FastAPI:
        from acdp_routes import build_router

        node = self

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            if start_background:
                node.start_background_tasks()
            yield
            node.stop_background_tasks()

        server = ACDPA2AServer(
            card=self.agent_card,
            agent_factory=self.runtime.new_agent,
            max_contexts=MAX_A2A_CONTEXTS,
            http_url=self.config["interfaces"]["a2a"],
            version=self.config["version"],
            skills=self.agent_card.skills,
            enable_a2a_compliant_streaming=True,
        )
        app = server.to_fastapi_app(
            app_kwargs={"title": f"ACDP agent {self.id}", "lifespan": lifespan}
        )
        app.include_router(build_router(self))
        app.add_middleware(
            BearerTokenMiddleware, token=(self.config.get("security") or {}).get("a2a_token")
        )
        return app
