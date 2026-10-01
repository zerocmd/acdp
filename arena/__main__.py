"""Run the arena: python -m arena"""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Callable, Mapping, Tuple

import httpx
import uvicorn
from discovery.dns_resolver import DNSResolver
from discovery.registry_client import RegistryClient
from runtime.models import build_model
from strands.models import Model

from arena.acdp import AcdpClient
from arena.api import register_routes
from arena.bus import EventBus
from arena.cast import DEFAULT_CAST, MODEL_IDS, load_cast
from arena.host import Arena, Settings

logger = logging.getLogger("arena")
UI_DIR = Path(__file__).with_name("ui")


def has_model_credentials(env: Mapping[str, str]) -> bool:
    return bool(env.get("ANTHROPIC_API_KEY")) or env.get("MODEL_PROVIDER") == "bedrock"


def make_model_factory(env: Mapping[str, str]) -> Callable[[str, str], Model]:
    """(tier, slug) to a Strands model for the configured provider."""
    provider = env.get("MODEL_PROVIDER", "anthropic")

    def factory(tier: str, slug: str) -> Model:
        if provider == "bedrock":
            model_id = env.get(f"MODEL_ID_{tier.upper()}")
            if not model_id:
                raise ValueError(f"MODEL_ID_{tier.upper()} is required for bedrock")
        else:
            model_id = MODEL_IDS[tier]
        return build_model({
            "provider": provider, "model_id": model_id, "max_tokens": 2000,
            "region": env.get("AWS_REGION"),
        })

    return factory


def create_arena(
    env: Mapping[str, str], cast_path: Path = DEFAULT_CAST
) -> Tuple[Arena, bool]:
    """Build the arena and its routes. Returns (arena, live)."""
    settings = Settings.from_env(env)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    live = has_model_credentials(env)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    bus = EventBus(run_id, settings.runs_dir / f"{run_id}.jsonl" if live else None)
    http_factory = lambda: httpx.AsyncClient(timeout=30)  # noqa: E731
    acdp = AcdpClient(
        env.get("DNS_API_URL", "http://bind:8053"),
        RegistryClient(env.get("REGISTRY_URL", "http://registry:5000")),
        DNSResolver(env.get("DNS_SERVER", "bind"), int(env.get("DNS_PORT", "53"))),
        http_factory,
        registry_url=env.get("REGISTRY_URL", "http://registry:5000"),
    )
    arena = Arena(
        load_cast(cast_path),
        acdp=acdp,
        http_factory=http_factory,
        model_factory=make_model_factory(env),
        settings=settings,
        bus=bus,
    )
    register_routes(arena, UI_DIR, settings.runs_dir)
    return arena, live


async def serve(arena: Arena, live: bool) -> None:
    """Start HTTP first. The registry fetches cards from it during registration."""
    server = uvicorn.Server(uvicorn.Config(
        arena.app, host="0.0.0.0", port=arena.settings.port, log_level="info"
    ))
    server_task = asyncio.create_task(server.serve())
    while not server.started and not server_task.done():
        await asyncio.sleep(0.1)
    if live:
        await arena.start()
    else:
        arena.bus.publish(
            "arena.idle", {"reason": "no model credentials; replay a saved run"},
            persist=False,
        )
    await server_task


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    arena, live = create_arena(os.environ)
    asyncio.run(serve(arena, live))


if __name__ == "__main__":
    main()
