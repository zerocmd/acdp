"""The arena process: one FastAPI app, one asyncio task per agent."""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Set

import httpx
from a2a.server.tasks import InMemoryTaskStore
from fastapi import FastAPI
from strands import Agent
from strands.models import Model

from arena.acdp import AcdpError, dns_txt
from arena.agent import ArenaAgent, ArenaContext
from arena.bus import EventBus
from arena.card import agent_base_url, build_card, card_path, registration_payload
from arena.cast import SLUG_RE, AgentSpec, Cast
from arena.identity import Identity
from arena.inbox_executor import InboxExecutor, build_a2a_app
from arena.prompts import generate_request, system_prompt
from arena.rate import RunGuard, TokenBucket
from arena.threads import ThreadRegistry
from arena.transport import A2ASender
from arena.verify import Verifier

logger = logging.getLogger(__name__)

MISCONFIGURE = ("none", "no_txt", "wrong_key")
DOMAIN_RE = re.compile(
    r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"
)


class InjectionError(Exception):
    """An agent cannot join. The arena state did not change."""


@dataclass
class Settings:
    base_url: str = "http://arena:8080"
    host: str = "arena"
    port: int = 8080
    max_minutes: float = 20.0
    max_calls: int = 600
    rate_per_min: float = 10.0
    thread_cap: int = 12
    runs_dir: Path = field(default_factory=lambda: Path("runs"))
    guard_interval: float = 5.0

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        return cls(
            base_url=env.get("ARENA_PUBLIC_URL", "http://arena:8080"),
            host=env.get("ARENA_HOST", "arena"),
            port=int(env.get("ARENA_PORT", "8080")),
            max_minutes=float(env.get("ARENA_MAX_MINUTES", "20")),
            max_calls=int(env.get("ARENA_MAX_MODEL_CALLS", "600")),
            rate_per_min=float(env.get("ARENA_RATE_PER_MIN", "10")),
            runs_dir=Path(env.get("ARENA_RUNS_DIR", "runs")),
        )


class Arena:
    """Hosts every agent, registers it with ACDP, and runs its loop.

    Args:
        cast: Launch cast and seed incident.
        acdp: AcdpClient or a test double with the same async methods.
        http_factory: Returns a new httpx.AsyncClient.
        model_factory: (tier, slug) to a Strands model.
        settings: Runtime settings.
        bus: Event bus.
    """

    def __init__(
        self,
        cast: Cast,
        *,
        acdp: Any,
        http_factory: Callable[[], httpx.AsyncClient],
        model_factory: Callable[[str, str], Model],
        settings: Settings,
        bus: EventBus,
    ) -> None:
        self.cast = cast
        self.settings = settings
        self.http_factory = http_factory
        self.model_factory = model_factory
        self.app = FastAPI(title="ACDP Agent Arena")
        self.agents: Dict[str, ArenaAgent] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        # Slugs reserved by an add_agent call that has not finished yet.
        self._pending: Set[str] = set()
        self.live = False
        self._guard_task: Optional[asyncio.Task] = None
        self.replay_task: Optional[asyncio.Task] = None
        self.ctx = ArenaContext(
            bus=bus,
            threads=ThreadRegistry(settings.thread_cap),
            bucket=TokenBucket(settings.rate_per_min),
            guard=RunGuard(settings.max_minutes, settings.max_calls),
            acdp=acdp,
            verifier=Verifier(self._fetch_card, acdp.dns_agent, acdp.org),
            sender=A2ASender(http_factory),
        )

    @property
    def bus(self) -> EventBus:
        return self.ctx.bus

    async def _fetch_card(self, url: str) -> Optional[Dict[str, Any]]:
        async with self.http_factory() as http:
            try:
                response = await http.get(url)
            except httpx.HTTPError:
                return None
        if response.status_code != 200:
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    async def add_agent(self, spec: AgentSpec, misconfigure: str = "none") -> ArenaAgent:
        """Mount, publish DNS, and register one agent.

        Raises:
            InjectionError: Bad slug, bad domain, or the zone is refused. No state change.
        """
        if misconfigure not in MISCONFIGURE:
            raise InjectionError(f"misconfigure must be one of {MISCONFIGURE}")
        taken = spec.slug in self.agents or spec.slug in self._pending
        if not SLUG_RE.fullmatch(spec.slug) or taken:
            raise InjectionError(f"slug {spec.slug!r} is invalid or in use")
        if not DOMAIN_RE.fullmatch(spec.domain):
            raise InjectionError(f"invalid domain {spec.domain!r}")
        # Reserve the slug before the first await so a concurrent call sees it.
        self._pending.add(spec.slug)
        try:
            return await self._add_agent(spec, misconfigure)
        finally:
            self._pending.discard(spec.slug)

    def _step(self, agent_id: str, step: str, status: str, detail: Dict[str, Any]) -> None:
        self.bus.publish("registration.step", {
            "id": agent_id, "step": step, "status": status, "detail": detail,
        })

    async def _add_agent(self, spec: AgentSpec, misconfigure: str) -> ArenaAgent:
        acdp = self.ctx.acdp
        try:
            zone_result = await acdp.create_zone(spec.domain)
        except AcdpError as e:
            raise InjectionError(str(e)) from e

        identity = Identity(spec.slug, spec.domain)
        card = build_card(spec, identity, self.settings.base_url)
        agent = ArenaAgent(
            spec,
            identity,
            agent_base_url(self.settings.base_url, spec.slug),
            self.model_factory(spec.model, spec.slug),
            self.ctx,
        )
        store = InMemoryTaskStore()
        agent.task_store = store
        self.app.mount(
            f"/agents/{spec.slug}", build_a2a_app(card, InboxExecutor(agent.receive), store)
        )
        self.agents[spec.slug] = agent
        agent_id = identity.agent_id
        self.bus.publish("agent.registered", {
            "id": agent_id, "slug": spec.slug, "name": spec.name,
            "organization": spec.organization, "domain": spec.domain,
            "capability": spec.capability, "model": spec.model, "role": spec.role,
            "sector": spec.sector,
            "did": identity.did, "needs": list(spec.needs),
            "cadence": list(spec.cadence), "system_prompt": system_prompt(spec),
        })
        self._step(agent_id, "identity", "ok",
                   {"did": identity.did, "fingerprint": identity.fingerprint()})
        self._step(agent_id, "zone", "ok", {"zone": spec.domain, "result": zone_result})

        failed_step = "dns"
        try:
            if misconfigure == "no_txt":
                agent.dns = {"skipped": True}
                self._step(agent_id, "dns", "skipped", agent.dns)
            else:
                key = identity.fingerprint()
                if misconfigure == "wrong_key":
                    key = Identity(spec.slug, spec.domain).fingerprint()
                path = card_path(spec.slug)
                await acdp.publish_dns(
                    agent_id=agent_id, host=self.settings.host,
                    port=self.settings.port, capability=spec.capability,
                    description=spec.description, card_path=path, key=key,
                )
                agent.dns = {
                    "srv": f"{self.settings.host}:{self.settings.port}",
                    "txt": dns_txt(spec.capability, spec.description, path, key),
                }
                self._step(agent_id, "dns", "ok", agent.dns)
            self._step(agent_id, "card", "ok", {"card_url": agent.card_url})
            failed_step = "submitted"
            entry = await acdp.register(
                registration_payload(spec, identity, self.settings.base_url, card)
            )
            self._step(agent_id, "submitted", "ok", {})
        except AcdpError as e:
            self._step(agent_id, failed_step, "failed", {"error": str(e)})
            agent.verification = {"status": "failed", "reasons": [str(e)]}
            self._step(agent_id, "result", "failed", dict(agent.verification))
            self.bus.publish(
                "agent.verification_failed", {"id": agent_id, "reasons": [str(e)]}
            )
            return agent

        verification = entry.get("verification") or {}
        verified = verification.get("status") == "verified"
        self._step(agent_id, "checks", "ok" if verified else "failed", verification)
        agent.verification = {
            "status": "verified" if verified else "failed",
            "reasons": list(verification.get("reasons") or []),
        }
        self._step(agent_id, "result", "ok" if verified else "failed",
                   dict(agent.verification))
        if verified:
            self.bus.publish(
                "agent.verified", {"id": agent_id, "verification": verification}
            )
        else:
            self.bus.publish("agent.verification_failed", {
                "id": agent_id, "reasons": agent.verification["reasons"],
            })
        if self.live:
            self._launch(agent)
        return agent

    async def setup(self) -> None:
        """Register the cast in order, then open and seed the investigation thread."""
        for spec in self.cast.agents:
            try:
                await self.add_agent(spec)
            except InjectionError as e:
                self.bus.publish("agent.error", {"id": spec.agent_id, "error": str(e)})
        seed = self.cast.seed
        owner = self.agents[seed.owner]
        thread = self.ctx.threads.open(
            owner.agent_id, seed.title, closer=self.agents[seed.closer].agent_id,
            cap=owner.spec.thread_cap,
        )
        self.bus.publish("thread.opened", {
            "id": thread.id, "owner": thread.owner, "title": thread.title,
            "color": thread.color,
        })
        owner.seed(thread.id, seed.brief)
        self.bus.publish(
            "arena.started", {"agents": len(self.agents), "run_id": self.bus.run_id}
        )

    def _launch(self, agent: ArenaAgent) -> None:
        if agent.spec.slug not in self.tasks:
            self.tasks[agent.spec.slug] = asyncio.create_task(
                agent.run(), name=f"agent:{agent.spec.slug}"
            )

    def launch(self) -> None:
        """Start every agent loop and the run guard."""
        self.live = True
        self.ctx.running.set()
        for agent in self.agents.values():
            self._launch(agent)
        self._guard_task = asyncio.create_task(self._watch_guard(), name="run-guard")

    async def start(self) -> None:
        await self.setup()
        self.launch()

    def pause(self) -> None:
        self.ctx.running.clear()
        self.bus.publish("arena.paused", {})

    def resume(self) -> None:
        if self.ctx.stopped.is_set():
            return
        self.ctx.running.set()
        self.bus.publish("arena.resumed", {})

    async def stop(self, reason: str) -> None:
        """Stop every agent loop. Safe to call more than once."""
        if self.ctx.stopped.is_set():
            return
        self.ctx.stopped.set()
        self.ctx.running.clear()
        self.live = False
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.bus.publish("arena.stopped", {"reason": reason})

    async def _watch_guard(self) -> None:
        while not self.ctx.stopped.is_set():
            await asyncio.sleep(self.settings.guard_interval)
            reason = self.ctx.guard.exceeded()
            if reason:
                await self.stop(reason)
                return

    async def generate_prompt(
        self, name: str, organization: str, capability: str, agenda: str
    ) -> str:
        """Ask Sonnet to draft a system prompt for an injected agent."""
        agent = Agent(model=self.model_factory("sonnet", "_generator"), callback_handler=None)
        result = await agent.invoke_async(
            generate_request(name, organization, capability, agenda)
        )
        return str(result).strip()
