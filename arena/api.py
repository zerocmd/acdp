"""HTTP and WebSocket surface of the arena: UI, event stream, and controls."""

import asyncio
import contextlib
import logging
import re
from pathlib import Path
from typing import List, Literal

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from arena.acdp import AcdpError
from arena.bus import load_log, replay
from arena.cast import AgentSpec
from arena.host import Arena, InjectionError

logger = logging.getLogger(__name__)

INJECTED_CADENCE = [40, 60]


class InjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    organization: str = Field(min_length=1, max_length=80)
    domain: str = Field(min_length=3, max_length=200)
    capability: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    needs: List[str] = Field(default_factory=list)
    model: Literal["sonnet", "haiku"] = "haiku"
    agenda: str = Field(default="", max_length=1000)
    generate: bool = False
    misconfigure: Literal["none", "no_txt", "wrong_key"] = "none"
    sector: Literal["member", "provider", "assurance"] = "provider"


class ReplayRequest(BaseModel):
    log: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    speed: float = Field(default=2.0, ge=1, le=10)


class NoCacheStaticFiles(StaticFiles):
    """Static files that the browser must revalidate on every load.

    Without this, browsers cache UI modules by heuristic, and after an upgrade a
    page can run a mix of old and new modules.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def slugify(name: str) -> str:
    """Lowercase, hyphenated, at most 32 characters. "agent" when empty."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32].strip("-")
    return slug or "agent"


def register_routes(arena: Arena, ui_dir: Path, runs_dir: Path) -> None:
    """Add the UI, event stream, and control routes to arena.app."""
    app = arena.app

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(ui_dir / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/ui", NoCacheStaticFiles(directory=ui_dir), name="ui")

    @app.websocket("/ws")
    async def events(socket: WebSocket) -> None:
        await socket.accept()
        queue = arena.bus.subscribe()
        try:
            for event in list(arena.bus.history):
                await socket.send_json(event)
            while arena.bus.is_subscribed(queue):
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    continue
                await socket.send_json(event)
            await socket.close(code=1013)  # dropped as a slow client; it reconnects
        except WebSocketDisconnect:
            pass
        finally:
            arena.bus.unsubscribe(queue)

    @app.post("/arena/agents", status_code=201)
    async def inject(body: InjectRequest):
        if not body.agenda and not body.generate:
            return JSONResponse({"error": "agenda or generate is required"}, status_code=400)
        prompt = body.agenda
        if body.generate:
            try:
                prompt = await arena.generate_prompt(
                    body.name, body.organization, body.capability, body.agenda
                )
            except Exception as e:  # model providers raise many error types
                logger.exception("Prompt generation failed")
                return JSONResponse(
                    {"error": f"prompt generation failed: {e}"}, status_code=502
                )
        try:
            spec = AgentSpec.from_dict({
                "slug": slugify(body.name),
                "name": body.name,
                "organization": body.organization,
                "domain": body.domain,
                "capability": body.capability,
                "description": (body.agenda or body.capability)[:200],
                "needs": body.needs,
                "model": body.model,
                "role": "agenda",
                "sector": body.sector,
                "cadence": INJECTED_CADENCE,
                "system_prompt": prompt,
            })
            agent = await arena.add_agent(spec, body.misconfigure)
        except (ValueError, InjectionError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return {"id": agent.agent_id, "slug": spec.slug}

    @app.get("/arena/agents")
    async def list_agents() -> dict:
        return {"agents": [a.summary() for a in arena.agents.values()]}

    @app.get("/arena/agents/{slug}")
    async def agent_detail(slug: str) -> dict:
        agent = arena.agents.get(slug)
        if agent is None:
            raise HTTPException(status_code=404, detail="unknown agent")
        return agent.detail()

    async def proxy(path: str):
        try:
            status, body = await arena.ctx.acdp.registry_get(path)
        except AcdpError as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        return JSONResponse(body, status_code=status)

    @app.get("/arena/registry")
    async def registry_agents():
        return await proxy("/agents")

    @app.get("/arena/registry/orgs")
    async def registry_orgs():
        return await proxy("/orgs")

    @app.get("/arena/registry/agents/{agent_id}/card")
    async def registry_card(agent_id: str):
        return await proxy(f"/agents/{agent_id}/card")

    @app.post("/arena/pause")
    async def pause() -> dict:
        arena.pause()
        return {"status": "paused"}

    @app.post("/arena/resume")
    async def resume() -> dict:
        arena.resume()
        return {"status": "running"}

    @app.get("/arena/logs")
    async def logs() -> dict:
        files = sorted(runs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        return {"logs": [p.stem for p in files]}

    @app.post("/arena/replay", status_code=202)
    async def start_replay(body: ReplayRequest):
        path = runs_dir / f"{body.log}.jsonl"
        if not path.is_file():
            return JSONResponse({"error": "log not found"}, status_code=404)
        events = load_log(path)
        previous = arena.replay_task
        if previous is not None and not previous.done():
            previous.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await previous
        await arena.stop("replay")
        arena.bus.reset(f"replay-{body.log}", note={"log": body.log, "speed": body.speed})
        arena.replay_task = asyncio.create_task(replay(events, arena.bus, body.speed))
        return {"status": "replaying"}
