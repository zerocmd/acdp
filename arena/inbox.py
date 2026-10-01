"""Items that wait in an agent's inbox until its next tick."""

from dataclasses import dataclass
from typing import Optional

from arena.envelope import ArenaMessage
from arena.verify import Trust


@dataclass(frozen=True)
class InboxItem:
    """A received message with its trust result, or a system note (seed)."""

    message: Optional[ArenaMessage] = None
    trust: Optional[Trust] = None
    thread_id: str = ""
    text: str = ""
