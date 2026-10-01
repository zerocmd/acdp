"""Conversation threads: ids, colors, participants, caps, and closing rules."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from arena.envelope import ArenaMessage, Intent

NEW_THREAD = "new"
COLOR_COUNT = 12


@dataclass
class Thread:
    id: str
    owner: str
    title: str
    color: int
    cap: int
    closer: Optional[str] = None
    participants: Set[str] = field(default_factory=set)
    messages: List[ArenaMessage] = field(default_factory=list)
    closed: bool = False
    close_reason: str = ""


class ThreadRegistry:
    """All threads of one arena run.

    Args:
        default_cap: Messages after which a thread closes.
    """

    def __init__(self, default_cap: int = 12) -> None:
        self.default_cap = default_cap
        self._threads: Dict[str, Thread] = {}

    def open(
        self,
        owner: str,
        title: str,
        closer: Optional[str] = None,
        cap: Optional[int] = None,
    ) -> Thread:
        number = len(self._threads) + 1
        thread = Thread(
            id=f"t{number}",
            owner=owner,
            title=title,
            color=(number - 1) % COLOR_COUNT,
            cap=cap or self.default_cap,
            closer=closer,
            participants={owner},
        )
        self._threads[thread.id] = thread
        return thread

    def get(self, thread_id: str) -> Optional[Thread]:
        return self._threads.get(thread_id)

    def check_send(self, thread_id: str) -> Optional[str]:
        """Reason a message cannot go to the thread, or None."""
        thread = self._threads.get(thread_id)
        if thread is None:
            return "unknown thread"
        if thread.closed:
            return "thread closed"
        return None

    def append(self, message: ArenaMessage) -> Optional[str]:
        """Record a sent message.

        Returns:
            The close reason when this message closes the thread, else None.
        """
        thread = self._threads[message.thread_id]
        thread.messages.append(message)
        thread.participants.update({message.from_id, message.to_id})
        reason = None
        if message.intent is Intent.CLOSE and message.from_id == thread.owner:
            reason = "closed by owner"
        elif message.intent is Intent.VERDICT and message.from_id == thread.closer:
            reason = "verdict"
        elif len(thread.messages) >= thread.cap:
            reason = "cap reached"
        if reason:
            thread.closed = True
            thread.close_reason = reason
        return reason

    def for_agent(self, agent_id: str) -> List[Thread]:
        return [t for t in self._threads.values() if agent_id in t.participants]

    def open_threads(self) -> List[Thread]:
        return [t for t in self._threads.values() if not t.closed]

    def open_count(self) -> int:
        return len(self.open_threads())
