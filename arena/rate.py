"""Arena-wide message rate and the run guard that caps cost."""

import time
from typing import Callable, Optional


class TokenBucket:
    """Allows rate_per_min sends per minute, with bursts up to that number."""

    def __init__(
        self, rate_per_min: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.capacity = float(rate_per_min)
        self.per_second = rate_per_min / 60.0
        self.clock = clock
        self.tokens = self.capacity
        self.updated = clock()

    def _refill(self) -> None:
        now = self.clock()
        self.tokens = min(
            self.capacity, self.tokens + (now - self.updated) * self.per_second
        )
        self.updated = now

    def available(self) -> bool:
        """True when a send can go now. Takes no token."""
        self._refill()
        return self.tokens >= 1

    def try_take(self) -> bool:
        self._refill()
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


class RunGuard:
    """Stops a run after a time limit or a model-call limit."""

    def __init__(
        self,
        max_minutes: float,
        max_calls: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_seconds = max_minutes * 60
        self.max_calls = max_calls
        self.clock = clock
        self.started = clock()
        self.calls = 0

    def note_call(self) -> None:
        self.calls += 1

    def exceeded(self) -> Optional[str]:
        if self.calls >= self.max_calls:
            return "model call limit reached"
        if self.clock() - self.started >= self.max_seconds:
            return "time limit reached"
        return None
