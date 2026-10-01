"""One arena agent: inbox, discovery, model decision, checks, and send."""

import asyncio
import logging
import random
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

from pydantic import ValidationError
from strands import Agent
from strands.models import Model
from strands.types.exceptions import StructuredOutputException

from arena.bus import EventBus
from arena.card import WELL_KNOWN
from arena.cast import AgentSpec
from arena.decision import TurnDecision
from arena.envelope import ArenaMessage
from arena.identity import Identity
from arena.inbox import InboxItem
from arena.prompts import system_prompt, turn_prompt
from arena.rate import RunGuard, TokenBucket
from arena.threads import NEW_THREAD, ThreadRegistry
from arena.transport import SendError
from arena.verify import Trust

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Target:
    base_url: str
    did: str


@dataclass
class ArenaContext:
    """Services that every agent in one arena shares."""

    bus: EventBus
    threads: ThreadRegistry
    bucket: TokenBucket
    guard: RunGuard
    acdp: Any
    verifier: Any
    sender: Any
    running: asyncio.Event = field(default_factory=asyncio.Event)
    stopped: asyncio.Event = field(default_factory=asyncio.Event)
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], Any] = asyncio.sleep
    model_timeout: float = 60.0
    retry_delay: float = 2.0


def _base_from_card_url(card_url: str) -> str:
    if card_url.endswith(WELL_KNOWN):
        return card_url[: -len(WELL_KNOWN)] + "/"
    return card_url


class ArenaAgent:
    """An agent that decides on its own timer and talks over A2A.

    Args:
        spec: Cast entry.
        identity: Key and identifiers.
        base_url: This agent's A2A base URL (ends with "/").
        model: Strands model for decisions.
        ctx: Shared arena services.
    """

    def __init__(
        self,
        spec: AgentSpec,
        identity: Identity,
        base_url: str,
        model: Model,
        ctx: ArenaContext,
    ) -> None:
        self.spec = spec
        self.identity = identity
        self.base_url = base_url
        self.card_url = base_url.rstrip("/") + WELL_KNOWN
        self.model = model
        self.ctx = ctx
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.trust: Dict[str, Trust] = {}
        # Senders seen in the inbox stay reachable for replies on later ticks.
        self.known: Dict[str, Target] = {}
        self.last_prompt = ""
        self.last_decision: Optional[Dict[str, Any]] = None
        self.decisions: Deque[Dict[str, Any]] = deque(maxlen=20)
        self.counters = {"sent": 0, "received": 0, "rejected": 0, "errors": 0}
        self.queries: Deque[Dict[str, Any]] = deque(maxlen=20)
        self.seen: Dict[str, Set[str]] = {}
        self.dns: Dict[str, Any] = {}
        self.verification: Dict[str, Any] = {"status": "pending", "reasons": []}

    @property
    def agent_id(self) -> str:
        return self.identity.agent_id

    def seed(self, thread_id: str, text: str) -> None:
        """Put a system note (the incident brief) in the inbox."""
        self.inbox.put_nowait(InboxItem(thread_id=thread_id, text=text))

    def state(self) -> str:
        """stopped, paused, or running."""
        if self.ctx.stopped.is_set():
            return "stopped"
        return "running" if self.ctx.running.is_set() else "paused"

    def _record(
        self, prompt: str, decision: Optional[TurnDecision], outcome: str
    ) -> None:
        record = {
            "agent": self.agent_id,
            "prompt": prompt,
            "decision": decision.model_dump(mode="json") if decision else None,
            "outcome": outcome,
        }
        self.last_prompt = prompt
        self.last_decision = record["decision"]
        self.decisions.append(record)
        if outcome.startswith("rejected: "):
            self.counters["rejected"] += 1
        self.ctx.bus.publish("decision.made", record)

    async def receive(self, message: ArenaMessage) -> Trust:
        """Verify an inbound message and queue it. No model call."""
        if message.to_id != self.agent_id:
            trust = Trust("failed", "wrong recipient")
        else:
            trust = await self.ctx.verifier.check(message)
        previous = self.trust.get(message.from_id)
        # A failed check never replaces a verified result: from_id is unproven
        # when the check fails, so a forger must not taint a real peer.
        if trust.status == "verified" or previous is None or previous.status != "verified":
            self.trust[message.from_id] = trust
        self.ctx.bus.publish("verification.peer_check", {
            "agent": self.agent_id,
            "sender": message.from_id,
            "message_id": message.id,
            "status": trust.status,
            "reason": trust.reason,
        })
        self.counters["received"] += 1
        self.inbox.put_nowait(InboxItem(message=message, trust=trust))
        return trust

    def _drain(self) -> List[InboxItem]:
        items = []
        while not self.inbox.empty():
            items.append(self.inbox.get_nowait())
        return items

    def _requeue(self, items: List[InboxItem]) -> None:
        """Return unused items so the next tick sees them again."""
        for item in items:
            self.inbox.put_nowait(item)

    async def _discover(
        self, items: List[InboxItem]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Target]]:
        peers: List[Dict[str, Any]] = []
        targets: Dict[str, Target] = {}
        for capability in self.spec.needs:
            seen_before = self.seen.get(capability, set())
            results = []
            for entry in await self.ctx.acdp.find(capability):
                url = (entry.get("a2a") or {}).get("url")
                if entry["id"] == self.agent_id or not url or entry["id"] in targets:
                    continue
                targets[entry["id"]] = Target(url, entry.get("did", ""))
                peers.append(entry)
                results.append({
                    "id": entry["id"],
                    "name": entry.get("name", ""),
                    "organization": entry.get("organization", ""),
                    "domain": entry.get("domain", ""),
                    "status": (entry.get("verification") or {}).get("status", "unknown"),
                    "new": entry["id"] not in seen_before,
                })
            self.seen[capability] = {r["id"] for r in results}
            self.queries.append(
                {"ts": time.time(), "capability": capability, "results": results}
            )
            self.ctx.bus.publish("discovery.query", {
                "agent": self.agent_id, "capability": capability, "results": results,
            })
        for item in items:
            if item.message is not None:
                self.known.setdefault(item.message.from_id, Target(
                    _base_from_card_url(item.message.card_url), item.message.from_did
                ))
        for agent_id, target in self.known.items():
            targets.setdefault(agent_id, target)
        return peers, targets

    def _reject(self, reason: str) -> None:
        self.ctx.bus.publish("decision.rejected", {"agent": self.agent_id, "reason": reason})

    async def _decide(self, prompt: str) -> Optional[TurnDecision]:
        agent = Agent(
            model=self.model,
            system_prompt=system_prompt(self.spec),
            callback_handler=None,
        )
        self.ctx.guard.note_call()
        try:
            result = await asyncio.wait_for(
                agent.invoke_async(prompt, structured_output_model=TurnDecision),
                self.ctx.model_timeout,
            )
        except (StructuredOutputException, ValidationError):
            self._reject("invalid model output")
            return None
        return result.structured_output

    def _check(self, decision: TurnDecision, targets: Dict[str, Target]) -> Optional[str]:
        if decision.to == self.agent_id:
            return "cannot send to self"
        if decision.to not in targets:
            return "unknown target"
        if decision.thread_id != NEW_THREAD:
            reason = self.ctx.threads.check_send(decision.thread_id)
            if reason:
                return reason
        if not self.ctx.bucket.try_take():
            return "arena rate limit"
        return None

    async def _send(self, target: Target, message: ArenaMessage) -> Optional[str]:
        """Send with one retry. Returns None on success, else the error text."""
        for attempt in range(2):
            try:
                await self.ctx.sender.send(target.base_url, message)
                return None
            except SendError as e:
                if attempt == 0:
                    await self.ctx.sleep(self.ctx.retry_delay)
                    continue
                self.ctx.bus.publish("message.failed", {
                    "id": message.id, "from_id": message.from_id,
                    "to_id": message.to_id, "error": str(e),
                })
                return str(e)
        return "send failed"

    async def tick(self) -> Optional[ArenaMessage]:
        """Run one decision cycle. Returns the sent message, or None."""
        if not self.ctx.bucket.available():
            # Skip the paid model call. The inbox waits for the next tick.
            self._reject("arena rate limit")
            return None
        items = self._drain()
        try:
            peers, targets = await self._discover(items)
            threads = self.ctx.threads.for_agent(self.agent_id)
            prompt = turn_prompt(
                items, threads, self.ctx.threads.open_threads(), peers, self.trust
            )
            decision = await self._decide(prompt)
        except BaseException:
            # Errors, timeouts, and cancellation must not lose the inbox.
            self._requeue(items)
            raise
        if decision is None:
            self._record(prompt, None, "rejected: invalid model output")
            self._requeue(items)
            return None
        if decision.action == "wait":
            self._record(prompt, decision, "wait")
            return None
        if not self.ctx.running.is_set():
            # Pause drops the decision, not the inbox.
            self._reject("paused")
            self._record(prompt, decision, "rejected: paused")
            self._requeue(items)
            return None
        reason = self._check(decision, targets)
        if reason:
            self._reject(reason)
            self._record(prompt, decision, f"rejected: {reason}")
            return None

        thread_id = decision.thread_id
        if thread_id == NEW_THREAD:
            thread = self.ctx.threads.open(
                self.agent_id, decision.body[:60], cap=self.spec.thread_cap
            )
            thread_id = thread.id
            self.ctx.bus.publish("thread.opened", {
                "id": thread.id, "owner": thread.owner,
                "title": thread.title, "color": thread.color,
            })
        target = targets[decision.to]
        message = ArenaMessage(
            id=uuid.uuid4().hex[:12],
            thread_id=thread_id,
            from_id=self.agent_id,
            to_id=decision.to,
            from_did=self.identity.did,
            to_did=target.did,
            ts=time.time(),
            intent=decision.intent,
            body=decision.body,
            card_url=self.card_url,
        ).signed(self.identity)
        error = await self._send(target, message)
        if error is not None:
            self._record(prompt, decision, f"failed: {error}")
            return None

        closed = self.ctx.threads.append(message)
        data = {k: v for k, v in message.payload().items() if k != "sig"}
        data["color"] = self.ctx.threads.get(thread_id).color
        data["looking_for"] = decision.looking_for
        data["why_this_peer"] = decision.why_this_peer
        self.counters["sent"] += 1
        self._record(prompt, decision, "sent")
        self.ctx.bus.publish("message.sent", data)
        if closed:
            self.ctx.bus.publish("thread.closed", {"id": thread_id, "reason": closed})
        return message

    async def run(self) -> None:
        """Tick on the agent's cadence until the arena stops."""
        backoff = 0.0
        while not self.ctx.stopped.is_set():
            await self.ctx.running.wait()
            await self.ctx.sleep(self.ctx.rng.uniform(*self.spec.cadence) + backoff)
            if self.ctx.stopped.is_set() or not self.ctx.running.is_set():
                continue
            try:
                await self.tick()
                backoff = 0.0
            except Exception as e:  # one failing agent must not stop the arena
                self.counters["errors"] += 1
                logger.exception(f"{self.agent_id} tick failed")
                self.ctx.bus.publish(
                    "agent.error", {"id": self.agent_id, "error": str(e) or type(e).__name__}
                )
                backoff = min(120.0, max(5.0, backoff * 2))
