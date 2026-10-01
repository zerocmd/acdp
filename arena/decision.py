"""Structured output that an agent model returns on each tick."""

from typing import Literal

from pydantic import BaseModel, Field

from arena.envelope import MAX_BODY, Intent


class TurnDecision(BaseModel):
    """Decide to send one message or to wait.

    to: agent id of the recipient. thread_id: an existing thread id or "new".
    """

    action: Literal["send", "wait"]
    to: str = ""
    thread_id: str = ""
    intent: Intent = Intent.REQUEST
    body: str = Field(default="", max_length=MAX_BODY)
