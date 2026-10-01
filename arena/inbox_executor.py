"""A2A receive side: verify, queue, and acknowledge. No model call.

The Strands A2AServer calls the model for every inbound message. Arena agents
decide on their own timer, so the receive side only queues the message.
"""

from typing import Awaitable, Callable, Optional

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskStore, TaskUpdater
from a2a.types import AgentCard, Part, TaskState, TextPart, UnsupportedOperationError
from a2a.utils import new_agent_text_message, new_task
from a2a.utils.errors import ServerError
from fastapi import FastAPI
from pydantic import ValidationError

from arena.envelope import ArenaMessage, Intent
from arena.verify import Trust

Deliver = Callable[[ArenaMessage, Optional[str]], Awaitable[Trust]]


class InboxExecutor(AgentExecutor):
    """Executor that hands each envelope to the recipient agent's inbox.

    A `request` gets an A2A Task in state working. The arena finishes it later
    when the recipient answers. Other intents get a Message ack.

    Args:
        deliver: The recipient's receive coroutine (message, task_id) -> Trust.
    """

    def __init__(self, deliver: Deliver) -> None:
        self._deliver = deliver

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        metadata = (context.message.metadata or {}) if context.message else {}
        raw = metadata.get("arena")
        if raw is None:
            await self._reply(context, event_queue, "rejected: missing arena envelope")
            return
        try:
            message = ArenaMessage.model_validate(raw)
        except ValidationError:
            await self._reply(context, event_queue, "rejected: invalid envelope")
            return
        if message.intent is not Intent.REQUEST:
            trust = await self._deliver(message, None)
            await self._reply(context, event_queue, f"ack {message.id} {trust.status}")
            return
        task = context.current_task or new_task(context.message)
        await event_queue.enqueue_event(task)
        trust = await self._deliver(message, task.id)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.update_status(
            TaskState.working,
            message=updater.new_agent_message(
                [Part(root=TextPart(text=f"ack {message.id} {trust.status}"))]
            ),
        )

    async def _reply(self, context: RequestContext, event_queue: EventQueue, text: str) -> None:
        await event_queue.enqueue_event(
            new_agent_text_message(text, context_id=context.context_id)
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            raise ServerError(error=UnsupportedOperationError())
        await TaskUpdater(event_queue, task.id, task.context_id).cancel()


def build_a2a_app(
    card: AgentCard, executor: AgentExecutor, store: Optional[TaskStore] = None
) -> FastAPI:
    """A2A JSON-RPC app that serves the card at /.well-known/agent-card.json."""
    handler = DefaultRequestHandler(
        agent_executor=executor, task_store=store or InMemoryTaskStore()
    )
    return A2AFastAPIApplication(agent_card=card, http_handler=handler).build()
