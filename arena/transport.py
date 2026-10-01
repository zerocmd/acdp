"""A2A send side: deliver a signed envelope to a peer's mounted endpoint."""

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, TaskIdParams, TaskQueryParams, TextPart

from arena.envelope import ArenaMessage
from arena.tasks import task_outcome


class SendError(Exception):
    """The A2A call failed."""


@dataclass(frozen=True)
class SendResult:
    text: str
    task_id: Optional[str] = None


def _reply_text(event: Any) -> str:
    if isinstance(event, Message):
        return "".join(
            p.root.text for p in event.parts if isinstance(p.root, TextPart)
        )
    return ""


class A2ASender:
    """Sends A2A messages and reads or cancels tasks on peers.

    Args:
        http_factory: Returns a new httpx.AsyncClient.
    """

    def __init__(self, http_factory: Callable[[], httpx.AsyncClient]) -> None:
        self._http_factory = http_factory

    async def _with_client(self, base_url: str, call):
        async with self._http_factory() as http:
            try:
                card = await A2ACardResolver(httpx_client=http, base_url=base_url).get_agent_card()
                client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)
                return await call(client)
            except Exception as e:  # a2a-sdk raises several client error types
                raise SendError(f"A2A call to {base_url} failed: {e}") from e

    async def send(self, base_url: str, message: ArenaMessage) -> SendResult:
        """Send the envelope in metadata["arena"] and the body as text."""
        return await self.send_raw(base_url, {"arena": message.payload()}, message.body)

    async def send_raw(
        self, base_url: str, metadata: Optional[Dict[str, Any]], text: str
    ) -> SendResult:
        a2a_message = Message(
            role=Role.user,
            message_id=str(uuid.uuid4()),
            parts=[Part(root=TextPart(text=text))],
            metadata=metadata,
        )

        async def call(client):
            final = None
            async for event in client.send_message(a2a_message):
                final = event
            return final

        final = await self._with_client(base_url, call)
        if isinstance(final, tuple):
            task = final[0]
            return SendResult(task_outcome(task)[1], task.id)
        return SendResult(_reply_text(final))

    async def get_task(self, base_url: str, task_id: str) -> Tuple[str, str, str]:
        task = await self._with_client(base_url, lambda c: c.get_task(TaskQueryParams(id=task_id)))
        return task_outcome(task)

    async def cancel_task(self, base_url: str, task_id: str) -> str:
        task = await self._with_client(base_url, lambda c: c.cancel_task(TaskIdParams(id=task_id)))
        return task.status.state.value
