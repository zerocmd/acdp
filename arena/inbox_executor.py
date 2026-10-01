"""A2A receive side: verify, queue, and acknowledge. No model call.

The Strands A2AServer calls the model for every inbound message. Arena agents
decide on their own timer, so the receive side only queues the message.
"""

from typing import Awaitable, Callable

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, UnsupportedOperationError
from a2a.utils import new_agent_text_message
from a2a.utils.errors import ServerError
from fastapi import FastAPI
from pydantic import ValidationError

from arena.envelope import ArenaMessage
from arena.verify import Trust

Deliver = Callable[[ArenaMessage], Awaitable[Trust]]


class InboxExecutor(AgentExecutor):
    """Executor that hands each envelope to the recipient agent's inbox.

    Args:
        deliver: The recipient's receive coroutine. It verifies and queues.
    """

    def __init__(self, deliver: Deliver) -> None:
        self._deliver = deliver

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        metadata = (context.message.metadata or {}) if context.message else {}
        raw = metadata.get("arena")
        if raw is None:
            text = "rejected: missing arena envelope"
        else:
            try:
                message = ArenaMessage.model_validate(raw)
            except ValidationError:
                text = "rejected: invalid envelope"
            else:
                trust = await self._deliver(message)
                text = f"ack {message.id} {trust.status}"
        await event_queue.enqueue_event(
            new_agent_text_message(text, context_id=context.context_id)
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise ServerError(error=UnsupportedOperationError())


def build_a2a_app(card: AgentCard, executor: AgentExecutor) -> FastAPI:
    """A2A JSON-RPC app that serves the card at /.well-known/agent-card.json."""
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore())
    return A2AFastAPIApplication(agent_card=card, http_handler=handler).build()
