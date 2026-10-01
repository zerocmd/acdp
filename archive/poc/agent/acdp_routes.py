"""ACDP REST surface of an agent node.

Keeps every endpoint of the original Flask app so existing clients, the registry
dashboard and the scripts under scripts/ continue to work. /chat and /assist are now
backed by the Strands agent; peer collaboration happens through A2A tools instead of a
keyword heuristic.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict

from fastapi import APIRouter, Body, HTTPException, Query

from runtime.delegation import DelegationState

if TYPE_CHECKING:
    from node import AgentNode

logger = logging.getLogger(__name__)


def build_router(node: "AgentNode") -> APIRouter:
    router = APIRouter()
    max_depth = (node.config.get("collaboration") or {}).get("max_delegation_depth", 2)

    @router.get("/metadata")
    def get_metadata() -> Dict[str, Any]:
        return node.to_dict()

    @router.get("/health")
    def health_check() -> Dict[str, Any]:
        return {"status": "ok", "registered": node.registered}

    @router.get("/peers")
    def get_peers() -> Dict[str, Any]:
        return {"peers": node.peer_manager.get_peer_ids()}

    @router.post("/peers")
    def update_peers(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        peer_ids = payload.get("peers")
        if not isinstance(peer_ids, list):
            raise HTTPException(status_code=400, detail="Invalid peer data")
        known = node.peer_manager.get_all_peers()
        added = []
        # Gossip is a hint: resolve each new id through registry/DNS rather than
        # trusting data from the sender (ACDP.md, "Peer Communications and Data Integrity").
        for peer_id in peer_ids[:50]:
            if not isinstance(peer_id, str) or peer_id == node.id or peer_id in known:
                continue
            info = node.discovery_service.discover_agent(peer_id)
            if info:
                node.peer_manager.add_peer(peer_id, info)
                added.append(peer_id)
        return {
            "status": "success",
            "added_peers": added,
            "total_peers": len(node.peer_manager.get_all_peers()),
        }

    @router.post("/chat")
    async def chat(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        text = payload.get("text") or payload.get("message")
        if not text:
            raise HTTPException(status_code=400, detail="Missing text parameter")
        session_id = str(payload.get("session_id", "default"))

        agent, lock = node.runtime.session(session_id)
        consulted: list = []
        invocation_state = {
            "acdp_delegation": DelegationState(),
            "acdp_consulted": consulted,
        }
        async with lock:
            try:
                response = await node.runtime.invoke(agent, text, invocation_state)
            except Exception as e:
                logger.exception("Chat invocation failed")
                raise HTTPException(status_code=502, detail=f"Agent error: {e}") from e

        result: Dict[str, Any] = {"response": response, "session_id": session_id}
        if consulted:
            result["meta"] = {
                "collaborative": True,
                "peer_count": len(consulted),
                "peers": [c["name"] for c in consulted],
                "transports": sorted({c["transport"] for c in consulted}),
            }
        try:
            memory_result = await asyncio.to_thread(
                node.record_interaction_in_memory, text, response, session_id
            )
            result["memory_recorded"] = memory_result.get("status") == "success"
        except Exception as e:
            logger.error(f"Error recording chat in memory: {e}")
            result["memory_recorded"] = False
        return result

    @router.post("/assist")
    async def assist(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Legacy ACDP 1.0 peer-assistance endpoint.

        ACDP 1.1 agents call peers over A2A; this stays for 1.0 peers. Assist requests
        never delegate further, which preserves the original behaviour.
        """
        question = payload.get("question")
        if not question:
            return {"status": "error", "error": "Missing question in request"}
        requestor_id = payload.get("requestor_id", "unknown-agent")
        requestor_name = payload.get("requestor_name", "Unknown Agent")
        logger.info(f"Assistance request from {requestor_name} ({requestor_id})")

        prompt = (
            f"{requestor_name} asks for your help with this question. Answer concisely "
            f"(under 250 words) from the perspective of your capabilities; the answer will be "
            f"merged into {requestor_name}'s reply.\n\n{question}"
        )
        agent = node.runtime.new_agent(f"assist:{requestor_id}", peer_tools=False)
        state = DelegationState(hops=max_depth, trace=[requestor_id])
        try:
            response = await node.runtime.invoke(agent, prompt, {"acdp_delegation": state})
        except Exception as e:
            logger.exception("Assist invocation failed")
            return {"status": "error", "error": f"Error generating response: {e}"}
        return {
            "status": "success",
            "response": response,
            "agent_id": node.id,
            "agent_name": node.name,
        }

    @router.get("/discover")
    def discover_agents(capability: str = Query(...)) -> Dict[str, Any]:
        return {"agents": node.discovery_service.discover_agents_by_capability(capability)}

    @router.post("/search")
    def search_agents(criteria: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        return {"agents": node.discovery_service.discover_agents_by_criteria(criteria)}

    @router.get("/resolve/{agent_id}")
    def resolve_agent(agent_id: str) -> Dict[str, Any]:
        info = node.discovery_service.discover_agent(agent_id)
        if not info:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        return info

    @router.get("/gossip/stats")
    def gossip_stats() -> Dict[str, Any]:
        return node.peer_manager.gossip_stats

    @router.post("/gossip/start")
    def start_gossip() -> Dict[str, Any]:
        started = node.peer_manager.start_gossip_thread()
        return {"status": "started" if started else "already running"}

    @router.post("/gossip/stop")
    def stop_gossip() -> Dict[str, Any]:
        stopped = node.peer_manager.stop_gossip_thread()
        return {"status": "stopped" if stopped else "not running"}

    @router.get("/memory")
    def get_memory() -> Dict[str, Any]:
        return node.registry.get_shared_memory()

    @router.get("/memory/{key}")
    def get_memory_key(key: str) -> Dict[str, Any]:
        memory = node.registry.get_shared_memory().get("memory", {})
        if key not in memory:
            raise HTTPException(status_code=404, detail="Memory key not found")
        return {"memory": {key: memory[key]}}

    @router.post("/memory")
    def update_memory(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        if "key" not in payload or "value" not in payload:
            raise HTTPException(status_code=400, detail="Missing key or value")
        return node.store_in_shared_memory(payload["key"], payload["value"])

    return router
