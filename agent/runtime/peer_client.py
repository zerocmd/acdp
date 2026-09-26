"""Call peer agents discovered through ACDP.

ACDP 1.1 peers are called over A2A (JSON-RPC ``message/send``) using the a2a-sdk
client. ACDP 1.0 peers, which only expose the REST ``/assist`` endpoint, are still
reachable so mixed-version networks keep working during migration.

The a2a-sdk client is used directly rather than ``strands.agent.a2a_agent.A2AAgent``
because every outbound message must carry the ACDP delegation trace in
``Message.metadata``; ``A2AAgent`` builds the message internally and does not expose it.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import AgentCard, Message, Part, Role, Task, TaskState, TextPart

from utils.endpoints import a2a_url, endpoint_url

from .a2a_card import card_acdp_params
from .delegation import ACDP_EXTENSION_URI, DelegationState

logger = logging.getLogger(__name__)

CARD_TTL_SECONDS = 300


class PeerCallError(Exception):
    """A peer could not be reached or returned an unusable response."""


@dataclass
class PeerReply:
    peer_id: str
    peer_name: str
    text: str
    transport: str  # "a2a" or "rest-assist"
    task_state: Optional[str] = None


def extract_text(event: Any) -> tuple[str, Optional[str]]:
    """Text and task state from the final A2A client event (Message or (Task, update))."""
    if isinstance(event, Message):
        return _parts_text(event.parts), None
    if isinstance(event, tuple) and event and isinstance(event[0], Task):
        task: Task = event[0]
        state = task.status.state.value if task.status and task.status.state else None
        chunks = [_parts_text(a.parts) for a in task.artifacts or []]
        text = "".join(chunks).strip()
        if not text and task.status and task.status.message:
            text = _parts_text(task.status.message.parts)
        return text, state
    return "", None


def _parts_text(parts: Any) -> str:
    out = []
    for part in parts or []:
        root = getattr(part, "root", part)
        if isinstance(root, TextPart):
            out.append(root.text)
    return "".join(out)


class PeerClient:
    """Sends questions to peers, preferring A2A and falling back to ACDP /assist."""

    def __init__(
        self,
        config: Dict[str, Any],
        http_client_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
    ):
        self.config = config
        self.self_id = config["id"]
        security = config.get("security") or {}
        self.token = security.get("a2a_token")
        self.verify_cards = security.get("verify_peer_cards", True)
        self.timeout = (config.get("collaboration") or {}).get("timeout", 120)
        self._http_client_factory = http_client_factory or self._default_http_client
        self._cards: Dict[str, tuple[float, AgentCard]] = {}

    def _default_http_client(self) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        return httpx.AsyncClient(timeout=self.timeout, headers=headers)

    async def get_card(self, peer_id: str, base_url: str, http: httpx.AsyncClient) -> AgentCard:
        cached = self._cards.get(peer_id)
        if cached and time.time() - cached[0] < CARD_TTL_SECONDS:
            return cached[1]
        card = await A2ACardResolver(httpx_client=http, base_url=base_url).get_agent_card()
        if self.verify_cards:
            claimed = card_acdp_params(card.model_dump(mode="json", exclude_none=True)).get("id")
            if claimed != peer_id:
                raise PeerCallError(
                    f"Agent Card at {base_url} claims ACDP id {claimed!r}, expected {peer_id!r}"
                )
        self._cards[peer_id] = (time.time(), card)
        return card

    async def ask(
        self,
        peer_id: str,
        peer_info: Dict[str, Any],
        question: str,
        delegation: DelegationState,
    ) -> PeerReply:
        peer_name = peer_info.get("name") or peer_id
        base = a2a_url(peer_info)
        if base:
            return await self._ask_a2a(peer_id, peer_name, base, question, delegation)
        return await self._ask_legacy(peer_id, peer_name, peer_info, question)

    async def _ask_a2a(
        self,
        peer_id: str,
        peer_name: str,
        base_url: str,
        question: str,
        delegation: DelegationState,
    ) -> PeerReply:
        message = Message(
            role=Role.user,
            message_id=str(uuid.uuid4()),
            parts=[Part(root=TextPart(text=question))],
            metadata={
                **delegation.next_hop(self.self_id),
                "acdp_requestor": {"id": self.self_id, "name": self.config.get("name")},
            },
            extensions=[ACDP_EXTENSION_URI],
        )
        async with self._http_client_factory() as http:
            try:
                card = await self.get_card(peer_id, base_url, http)
                client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)
                final = None
                async for event in client.send_message(message):
                    final = event
            except PeerCallError:
                raise
            except Exception as e:  # a2a-sdk raises several client error types
                raise PeerCallError(f"A2A call to {peer_id} failed: {e}") from e

        text, state = extract_text(final)
        if state in (TaskState.failed.value, TaskState.rejected.value, TaskState.canceled.value):
            raise PeerCallError(f"{peer_id} ended the task in state {state}: {text or 'no detail'}")
        if not text:
            raise PeerCallError(f"{peer_id} returned no text")
        return PeerReply(peer_id, card.name or peer_name, text, "a2a", state)

    async def _ask_legacy(
        self, peer_id: str, peer_name: str, peer_info: Dict[str, Any], question: str
    ) -> PeerReply:
        url = endpoint_url(peer_id, peer_info, "assist", "/assist")
        if not url:
            raise PeerCallError(f"cannot determine an endpoint for {peer_id}")
        payload = {
            "question": question,
            "requestor_id": self.self_id,
            "requestor_name": self.config.get("name"),
            "timestamp": time.time(),
        }
        async with self._http_client_factory() as http:
            try:
                response = await http.post(url, json=payload)
                response.raise_for_status()
                body = response.json()
            except Exception as e:
                raise PeerCallError(f"/assist call to {peer_id} failed: {e}") from e
        text = body.get("response")
        if body.get("status") == "error" or not text:
            raise PeerCallError(f"{peer_id} /assist error: {body.get('error', 'empty response')}")
        return PeerReply(peer_id, body.get("agent_name") or peer_name, text, "rest-assist")
