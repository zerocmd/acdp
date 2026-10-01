"""Event bus: in-process publish/subscribe, JSONL run log, and replay.

The bus only observes. Agents never receive messages through it.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Replay never waits longer than this between two events.
MAX_REPLAY_GAP = 5.0


class EventBus:
    """Ordered events with a full in-memory history for late subscribers.

    Args:
        run_id: Identifier of the current run.
        log_path: JSONL file for persistent events. None disables the log.
        clock: Time source for event timestamps.
        max_queue: Queue size per subscriber. A full queue drops the subscriber.
    """

    def __init__(
        self,
        run_id: str,
        log_path: Optional[Path] = None,
        clock: Callable[[], float] = time.time,
        max_queue: int = 1000,
    ) -> None:
        self.run_id = run_id
        self.log_path = log_path
        self.clock = clock
        self.max_queue = max_queue
        self.history: List[Dict[str, Any]] = []
        self._seq = 0
        self._subscribers: Set[asyncio.Queue] = set()

    def publish(
        self, event_type: str, data: Dict[str, Any], persist: bool = True
    ) -> Dict[str, Any]:
        """Record an event and send it to every subscriber.

        Args:
            event_type: Dotted event name, for example "message.sent".
            data: JSON-serializable event data.
            persist: Write the event to the JSONL log when one is set.

        Returns:
            The event.
        """
        event = {
            "seq": self._seq,
            "ts": self.clock(),
            "run_id": self.run_id,
            "type": event_type,
            "data": data,
        }
        self._seq += 1
        self.history.append(event)
        if persist and self.log_path is not None:
            with self.log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(event) + "\n")
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Dropping a slow event subscriber")
                self._subscribers.discard(queue)
        return event

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def is_subscribed(self, queue: asyncio.Queue) -> bool:
        return queue in self._subscribers

    def reset(
        self,
        run_id: str,
        log_path: Optional[Path] = None,
        note: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Start a new history and tell subscribers to clear their state."""
        self.history = []
        self._seq = 0
        self.run_id = run_id
        self.log_path = log_path
        self.publish("bus.reset", {"run_id": run_id, **(note or {})}, persist=False)


def load_log(path: Path) -> List[Dict[str, Any]]:
    """Read a JSONL run log."""
    with path.open(encoding="utf-8") as log:
        return [json.loads(line) for line in log if line.strip()]


async def replay(
    events: List[Dict[str, Any]],
    bus: EventBus,
    speed: float,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> None:
    """Publish logged events again, with gaps divided by speed.

    Args:
        events: Events from load_log, in order.
        bus: The bus that receives the events (not persisted).
        speed: Playback factor, 1 to 10.
        sleep: Async sleep function (tests replace it).
    """
    previous_ts: Optional[float] = None
    for event in events:
        if previous_ts is not None:
            gap = max(0.0, event["ts"] - previous_ts) / speed
            await sleep(min(gap, MAX_REPLAY_GAP))
        previous_ts = event["ts"]
        bus.publish(event["type"], event["data"], persist=False)
