"""The launch cast: shape, order, and cross-references."""

import pytest

from arena.cast import MODEL_IDS, AgentSpec, load_cast


@pytest.fixture(scope="module")
def cast():
    return load_cast()


def test_ten_agents_with_unique_slugs(cast):
    slugs = [a.slug for a in cast.agents]
    assert len(slugs) == 10
    assert len(set(slugs)) == 10


def test_models_and_roles(cast):
    count = lambda **kw: sum(  # noqa: E731
        all(getattr(a, k) == v for k, v in kw.items()) for a in cast.agents
    )
    assert count(model="sonnet", role="investigation") == 6
    assert count(model="haiku", role="agenda") == 3
    assert count(model="haiku", role="impostor") == 1


def test_real_halcyon_registers_before_the_impostor(cast):
    order = [a.slug for a in cast.agents]
    assert order.index("halcyon-intel") < order.index("lookalike-intel")
    impostor = cast.by_slug("lookalike-intel")
    assert impostor.organization == "Halcyon Intel"
    assert impostor.domain == "halcyon-inte1.example"


def test_seed_references_and_needs_resolve(cast):
    assert cast.by_slug(cast.seeds[0].owner).capability == "soc-investigation"
    assert cast.by_slug(cast.seeds[0].closer).capability == "coordination"
    provided = {a.capability for a in cast.agents}
    for agent in cast.agents:
        assert set(agent.needs) <= provided, agent.slug


def test_cadence_follows_role(cast):
    expected = {"investigation": (15, 20), "agenda": (50, 70), "impostor": (120, 180)}
    for agent in cast.agents:
        assert agent.cadence == expected[agent.role]


def test_agent_id():
    spec = AgentSpec.from_dict(_spec_dict())
    assert spec.agent_id == "x.x.example"
    assert MODEL_IDS[spec.model] == "claude-haiku-4-5-20251001"


@pytest.mark.parametrize(
    "change", [{"model": "opus"}, {"role": "boss"}, {"cadence": [5]}, {"slug": "Bad Slug"}]
)
def test_bad_spec_is_rejected(change):
    with pytest.raises(ValueError):
        AgentSpec.from_dict(_spec_dict(**change))


def _spec_dict(**change):
    data = {
        "slug": "x", "name": "X", "organization": "X Co", "domain": "x.example",
        "capability": "sales", "description": "d", "needs": ["procurement"],
        "model": "haiku", "role": "agenda", "cadence": [50, 70], "system_prompt": "p",
    }
    data.update(change)
    return data


def test_sector_defaults_and_validation():
    assert AgentSpec.from_dict(_spec_dict()).sector == "provider"
    assert AgentSpec.from_dict(_spec_dict(sector="member")).sector == "member"
    with pytest.raises(ValueError, match="sector"):
        AgentSpec.from_dict(_spec_dict(sector="vendor"))


def test_incident_role_is_valid():
    spec = AgentSpec.from_dict(_spec_dict(role="incident", cadence=[30, 45]))
    assert spec.role == "incident"
