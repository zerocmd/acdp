"""A2A send side: deliver a signed envelope to a peer's mounted endpoint."""

import uuid
from typing import Any, Callable, Dict, Optional

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, TextPart

from arena.envelope import ArenaMessage


class SendError(Exception):
    """The A2A call failed."""


def _reply_text(event: Any) -> str:
    if isinstance(event, Message):
        return "".join(
            p.root.text for p in event.parts if isinstance(p.root, TextPart)
        )
    return ""


class A2ASender:
    """Sends one A2A message per call.

    Args:
        http_factory: Returns a new httpx.AsyncClient.
    """

    def __init__(self, http_factory: Callable[[], httpx.AsyncClient]) -> None:
        self._http_factory = http_factory

    async def send(self, base_url: str, message: ArenaMessage) -> str:
        """Send the envelope in metadata["arena"] and the body as text."""
        return await self.send_raw(base_url, {"arena": message.payload()}, message.body)

    async def send_raw(
        self, base_url: str, metadata: Optional[Dict[str, Any]], text: str
    ) -> str:
        a2a_message = Message(
            role=Role.user,
            message_id=str(uuid.uuid4()),
            parts=[Part(root=TextPart(text=text))],
            metadata=metadata,
        )
        async with self._http_factory() as http:
            try:
                card = await A2ACardResolver(
                    httpx_client=http, base_url=base_url
                ).get_agent_card()
                client = ClientFactory(
                    ClientConfig(httpx_client=http, streaming=False)
                ).create(card)
                final = None
                async for event in client.send_message(a2a_message):
                    final = event
            except Exception as e:  # a2a-sdk raises several client error types
                raise SendError(f"A2A send to {base_url} failed: {e}") from e
        return _reply_text(final)
