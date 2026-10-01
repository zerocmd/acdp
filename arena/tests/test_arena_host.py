"""Arena host: cast registration, card serving, injection rules, and lifecycle."""

import asyncio

import httpx
import pytest
from conftest import IMPOSTOR, INTEL, ISAC, SOC, make_arena, make_cast, spec_dict

from arena.cast import AgentSpec
from arena.host import InjectionError, Settings


def events(arena, kind):
    return [e["data"] for e in arena.bus.history if e["type"] == kind]


def test_setup_registers_cast_in_order_and_seeds_thread():
    arena = make_arena(make_cast(SOC, INTEL, ISAC, IMPOSTOR,
                                 owner="northgate-soc", closer="finshare-isac"))
    asyncio.run(arena.setup())
    registered = [e["slug"] for e in events(arena, "agent.registered")]
    assert registered == ["northgate-soc", "halcyon-intel", "finshare-isac", "lookalike-intel"]
    assert {e["id"] for e in events(arena, "agent.verified")} == {
        "northgate-soc.northgate.example", "halcyon-intel.halcyon-intel.example",
        "finshare-isac.finshare-isac.example",
    }
    failed = events(arena, "agent.verification_failed")
    assert failed == [{"id": "lookalike-intel.halcyon-inte1.example",
                       "reasons": ["organization registered under halcyon-intel.example"]}]
    thread = arena.ctx.threads.get("t1")
    assert thread.owner == "northgate-soc.northgate.example"
    assert thread.closer == "finshare-isac.finshare-isac.example"
    seed = arena.agents["northgate-soc"].inbox.get_nowait()
    assert (seed.thread_id, seed.text) == ("t1", "Brief.")
    assert arena.bus.history[-1]["type"] == "arena.started"


def test_two_agents_share_a_zone():
    procurement = dict(slug="northgate-procurement", capability="procurement",
                       model="haiku", role="agenda", cadence=[50, 70], needs=[])
    arena = make_arena(make_cast(SOC, procurement, owner="northgate-soc",
                                 closer="northgate-soc"))
    asyncio.run(arena.setup())
    assert arena.ctx.acdp.zones == {"northgate.example"}
    assert len(events(arena, "agent.verified")) == 2


def test_card_is_served_at_the_mounted_path():
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"))

    async def run():
        await arena.setup()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=arena.app)) as http:
            return await http.get(
                "http://arena:8080/agents/northgate-soc/.well-known/agent-card.json"
            )

    response = asyncio.run(run())
    assert response.status_code == 200
    assert response.json()["url"] == "http://arena:8080/agents/northgate-soc/"


@pytest.mark.parametrize(
    "change, message",
    [
        ({"slug": "northgate-soc"}, "in use"),
        ({"slug": "new-one", "domain": "bad_domain"}, "invalid domain"),
        ({"slug": "new-one", "domain": "x.invalid"}, "allowed suffix"),
    ],
)
def test_bad_injection_changes_nothing(change, message):
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"))
    asyncio.run(arena.setup())
    before = len(arena.bus.history)
    with pytest.raises(InjectionError, match=message):
        asyncio.run(arena.add_agent(AgentSpec.from_dict(spec_dict(**change))))
    assert len(arena.bus.history) == before
    assert set(arena.agents) == {"northgate-soc"}


@pytest.mark.parametrize(
    "mode, reason", [("no_txt", "txt record missing"), ("wrong_key", "key mismatch")]
)
def test_misconfigured_agent_fails_verification(mode, reason):
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"))
    asyncio.run(arena.setup())
    spec = AgentSpec.from_dict(spec_dict(
        slug="broken", organization="Broken Co", domain="broken.example"))
    asyncio.run(arena.add_agent(spec, misconfigure=mode))
    assert events(arena, "agent.verification_failed")[-1]["reasons"] == [reason]


def test_pause_resume_and_guard_stop():
    arena = make_arena(
        make_cast(SOC, owner="northgate-soc", closer="northgate-soc"),
        settings=Settings(max_calls=1, guard_interval=0.01),
    )

    async def run():
        await arena.setup()
        arena.launch()
        arena.pause()
        arena.resume()
        for _ in range(500):
            if arena.ctx.stopped.is_set():
                break
            await asyncio.sleep(0.01)

    asyncio.run(run())
    kinds = [e["type"] for e in arena.bus.history]
    assert kinds.index("arena.paused") < kinds.index("arena.resumed")
    assert events(arena, "arena.stopped") == [{"reason": "model call limit reached"}]
    assert all(task.done() for task in arena.tasks.values())


def test_generate_prompt_uses_sonnet_generator():
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"),
                       scripts={"_generator": lambda prompt: "You find mule accounts."})
    text = asyncio.run(arena.generate_prompt("Fraud Desk", "Coastal Bank", "fraud", "x"))
    assert text == "You find mule accounts."


def test_concurrent_injection_of_one_slug_admits_exactly_one():
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"))
    asyncio.run(arena.setup())
    acdp = arena.ctx.acdp
    original = acdp.create_zone

    async def slow_zone(zone):
        await asyncio.sleep(0.01)   # let the second request run its checks
        return await original(zone)

    acdp.create_zone = slow_zone
    spec = AgentSpec.from_dict(spec_dict(slug="twin", organization="Twin Co",
                                         domain="twin.example"))

    async def run():
        return await asyncio.gather(arena.add_agent(spec), arena.add_agent(spec),
                                    return_exceptions=True)

    results = asyncio.run(run())
    assert sum(isinstance(r, InjectionError) for r in results) == 1
    assert [e["slug"] for e in events(arena, "agent.registered")].count("twin") == 1
