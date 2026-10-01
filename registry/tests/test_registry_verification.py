"""Registry verification: card re-fetch, DNS key pin, organization anchor."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as registry_app  # noqa: E402
from services import verification  # noqa: E402

X = "iojj3XQJ8ZX9UtstPLpdcspnCb8dlBIb83SIAbQPb1w"
FP = "NHUPmL1Z_PyUbaRaqr6TO-FUpLUJThxKv0KGZQXzyX4"


def card(organization="Halcyon Intel", domain="halcyon-intel.example", x=X):
    return {
        "name": "Threat Intel Analyst",
        "url": "http://arena:8080/agents/halcyon-intel/",
        "capabilities": {"extensions": [{
            "uri": verification.ACDP_EXTENSION_URI,
            "params": {
                "id": f"halcyon-intel.{domain}",
                "did": f"did:web:{domain}:agents:halcyon-intel",
                "organization": organization,
                "domain": domain,
                "publicKeyJwk": {"kty": "OKP", "crv": "Ed25519", "x": x},
            },
        }]},
    }


def registration(domain="halcyon-intel.example", organization="Halcyon Intel"):
    c = card(organization, domain)
    return {
        "id": f"halcyon-intel.{domain}",
        "name": "Threat Intel Analyst",
        "capabilities": ["threat-intel"],
        "interfaces": {"a2a": c["url"]},
        "a2a": {"url": c["url"], "card_url": c["url"] + ".well-known/agent-card.json"},
        "agent_card": c,
    }


def test_fingerprint_matches_known_vector():
    assert verification.fingerprint_jwk({"x": X}) == FP


def test_extension_uri_matches_agent_card_module():
    from runtime.a2a_card import ACDP_EXTENSION_URI

    assert verification.ACDP_EXTENSION_URI == ACDP_EXTENSION_URI


def test_verified_when_card_dns_and_org_agree():
    data = registration()
    result = verification.verify_registration(
        data, lambda url: data["agent_card"], lambda name: [f"key={FP}"],
        verification.OrgDirectory(),
    )
    assert result["status"] == "verified"
    assert result["reasons"] == []


@pytest.mark.parametrize(
    "fetch, txt, reason",
    [
        (lambda url: None, [f"key={FP}"], "card unreachable"),
        ("card", None, "txt record missing"),
        ("card", ["key=" + "A" * 43], "key mismatch"),
    ],
)
def test_failures_are_recorded(fetch, txt, reason):
    data = registration()
    fetcher = (lambda url: data["agent_card"]) if fetch == "card" else fetch
    result = verification.verify_registration(
        data, fetcher, lambda name: txt, verification.OrgDirectory()
    )
    assert result["status"] == "failed"
    assert reason in result["reasons"]


def test_fetched_card_wins_over_submitted_card():
    data = registration()
    fetched = card(x="A" * 43)
    result = verification.verify_registration(
        data, lambda url: fetched, lambda name: [f"key={FP}"],
        verification.OrgDirectory(),
    )
    assert result["key_matches_dns"] is False


def test_first_registrant_owns_the_organization():
    orgs = verification.OrgDirectory()
    real = registration()
    fake = registration(domain="halcyon-inte1.example")
    for data in (real, fake):
        result = verification.verify_registration(
            data, lambda url, d=data: d["agent_card"], lambda name: [f"key={FP}"], orgs
        )
    assert result["org_conflict"] is True
    assert result["canonical_domain"] == "halcyon-intel.example"
    assert result["status"] == "failed"


@pytest.fixture
def client(monkeypatch):
    registry_app.agents.clear()
    registry_app.orgs.clear()
    monkeypatch.setattr(registry_app, "fetch_card", lambda url: card())
    monkeypatch.setattr(registry_app, "lookup_txt", lambda name: [f"key={FP}"])
    registry_app.app.config["TESTING"] = True
    return registry_app.app.test_client()


def test_registration_stores_verification_and_accepts_failures(client, monkeypatch):
    response = client.post("/registerAgent", json=registration())
    assert response.status_code == 200
    assert response.get_json()["agent"]["verification"]["status"] == "verified"

    monkeypatch.setattr(registry_app, "lookup_txt", lambda name: None)
    response = client.post("/registerAgent", json=registration(domain="other.example"))
    assert response.status_code == 200
    assert response.get_json()["agent"]["verification"]["status"] == "failed"

    listed = client.get("/agents?capability=threat-intel").get_json()["agents"]
    assert {a["verification"]["status"] for a in listed} == {"verified", "failed"}


def test_orgs_endpoint(client):
    client.post("/registerAgent", json=registration())
    body = client.get("/orgs/halcyonintel").get_json()
    assert body == {"organization": "Halcyon Intel",
                    "canonical_domain": "halcyon-intel.example"}
    assert client.get("/orgs/nobody").status_code == 404
