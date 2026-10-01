"""Structured output that an agent model returns on each tick."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
    looking_for: str = Field(default="", max_length=200)
    why_this_peer: str = Field(default="", max_length=200)

    @field_validator("looking_for", "why_this_peer", mode="before")
    @classmethod
    def _truncate(cls, value: object) -> object:
        """Display-only fields: cut long text instead of rejecting the decision."""
        return value[:200] if isinstance(value, str) else value
