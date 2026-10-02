"""The launch cast: shape, order, and cross-references."""

import pytest

from arena.cast import MODEL_IDS, AgentSpec, load_cast


@pytest.fixture(scope="module")
def cast():
    return load_cast()


IMPOSTORS = {"lookalike-intel": "halcyon-intel", "coastline-impostor": "coastline-sales"}


def test_thirty_four_agents_with_unique_slugs(cast):
    slugs = [a.slug for a in cast.agents]
    assert len(slugs) == 34
    assert len(set(slugs)) == 34


def test_roles_and_models(cast):
    count = lambda **kw: sum(  # noqa: E731
        all(getattr(a, k) == v for k, v in kw.items()) for a in cast.agents)
    assert count(role="investigation") == 6
    assert count(role="investigation", model="sonnet") == 6
    assert count(role="incident") == 4 and count(role="incident", model="sonnet") == 2
    assert count(role="agenda") == 22 and count(role="agenda", model="haiku") == 22
    assert count(role="impostor") == 2 and count(role="impostor", model="haiku") == 2


def test_real_organizations_register_before_their_impostors(cast):
    order = [a.slug for a in cast.agents]
    for impostor, real in IMPOSTORS.items():
        assert order.index(real) < order.index(impostor)
        fake, genuine = cast.by_slug(impostor), cast.by_slug(real)
        assert fake.organization == genuine.organization
        assert fake.domain != genuine.domain


def test_seeds_and_needs_resolve(cast):
    assert [s.title for s in cast.seeds] == [
        "Credential phishing against finance staff",
        "Ransomware on Meridian file servers",
    ]
    assert (cast.seeds[1].owner, cast.seeds[1].closer) == ("meridian-ciso", "ironclad-ir")
    for seed in cast.seeds:
        cast.by_slug(seed.owner), cast.by_slug(seed.closer)
    provided = {a.capability for a in cast.agents}
    for agent in cast.agents:
        assert set(agent.needs) <= provided, agent.slug


def test_cadence_and_sector_follow_rules(cast):
    expected = {"investigation": (15, 20), "incident": (30, 45), "agenda": (60, 90),
                "impostor": (120, 180)}
    for agent in cast.agents:
        assert agent.cadence == expected[agent.role], agent.slug
        assert agent.sector in ("member", "provider", "assurance"), agent.slug
    assert sum(a.sector == "member" for a in cast.agents) >= 10
    assert all(a.domain.endswith(".example") or a.domain in ("extrahop.com", "tenable.com")
               for a in cast.agents)


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
