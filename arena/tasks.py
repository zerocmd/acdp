"""A2A task helpers: finish a task in a local store, read a task's outcome."""

import uuid
from typing import Tuple

from a2a.server.tasks import TaskStore
from a2a.types import Artifact, Part, Task, TaskState, TaskStatus, TextPart
from a2a.utils import new_agent_text_message

FINAL = {"completed", "rejected", "canceled", "failed"}


async def finish_task(
    store: TaskStore, task_id: str, state: str, text: str, reply_id: str = ""
) -> bool:
    """Move a task to a final state.

    Args:
        store: The recipient's task store.
        task_id: The task to finish.
        state: "completed" or "rejected".
        text: The reply body (artifact for completed, status message for rejected).
        reply_id: Id of the arena message that answered the request.

    Returns:
        False when the task does not exist or is already final.
    """
    task = await store.get(task_id)
    if task is None or task.status.state.value in FINAL:
        return False
    task.status = TaskStatus(
        state=TaskState(state),
        message=new_agent_text_message(text, context_id=task.context_id, task_id=task.id),
    )
    if state == "completed":
        task.artifacts = [Artifact(
            artifact_id=uuid.uuid4().hex, name="reply",
            parts=[Part(root=TextPart(text=text))], metadata={"reply_id": reply_id},
        )]
    else:
        task.metadata = {**(task.metadata or {}), "reply_id": reply_id}
    await store.save(task)
    return True


def task_outcome(task: Task) -> Tuple[str, str, str]:
    """(state, text, reply_id) of a task read over A2A."""
    state = task.status.state.value
    if task.artifacts:
        artifact = task.artifacts[-1]
        text = "".join(p.root.text for p in artifact.parts if isinstance(p.root, TextPart))
        return state, text, (artifact.metadata or {}).get("reply_id", "")
    message = task.status.message
    text = "".join(p.root.text for p in message.parts if isinstance(p.root, TextPart)) if message else ""
    return state, text, (task.metadata or {}).get("reply_id", "")
