"""The signed message that every arena A2A call carries in metadata["arena"]."""

from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field

from arena.identity import Identity

MAX_BODY = 1200


class Intent(str, Enum):
    REQUEST = "request"
    REPLY = "reply"
    SHARE = "share"
    DECLINE = "decline"
    CHALLENGE = "challenge"
    VERDICT = "verdict"
    CLOSE = "close"


class ArenaMessage(BaseModel):
    """One message between two arena agents."""

    model_config = ConfigDict(extra="forbid")

    id: str
    thread_id: str
    from_id: str
    to_id: str
    from_did: str
    to_did: str
    ts: float
    intent: Intent
    body: str = Field(max_length=MAX_BODY)
    card_url: str
    sig: str = ""

    def payload(self) -> Dict[str, Any]:
        """JSON-mode dict, the form that is signed and sent."""
        return self.model_dump(mode="json")

    def signed(self, identity: Identity) -> "ArenaMessage":
        """Copy of this message with sig set by the sender's key."""
        return self.model_copy(update={"sig": identity.sign(self.payload())})
