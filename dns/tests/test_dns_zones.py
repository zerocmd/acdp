"""Multi-zone DNS API tests: zone validation, key field, zone creation."""

import http.client
import importlib.util
import json
import os
import shutil
import socketserver
import stat
import subprocess
import threading

import pytest

SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
_spec = importlib.util.spec_from_file_location(
    "dns_api_zones", os.path.join(SCRIPTS, "dns_api.py")
)
dns_api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dns_api)

FP = "NHUPmL1Z_PyUbaRaqr6TO-FUpLUJThxKv0KGZQXzyX4"
UPDATE = {
    "domain": "northgate-soc.northgate.example",
    "host": "arena",
    "port": 8080,
    "capabilities": "soc-investigation",
    "a2a": "/agents/northgate-soc/.well-known/agent-card.json",
    "version": "1.1",
    "key": FP,
}


@pytest.fixture(autouse=True)
def zones(monkeypatch):
    monkeypatch.setattr(dns_api, "ZONES", {"agents.local", "northgate.example"})
    monkeypatch.setattr(dns_api, "ZONE_SUFFIXES", [".example", ".local", "extrahop.com"])


def test_zone_for_picks_longest_matching_zone(monkeypatch):
    dns_api.ZONES.add("example")
    assert dns_api.zone_for("northgate-soc.northgate.example") == "northgate.example"


def test_update_under_new_zone_is_accepted_and_carries_key_and_zone():
    clean = dns_api.validate_update(dict(UPDATE))
    assert clean["zone"] == "northgate.example"
    assert clean["key"] == FP


@pytest.mark.parametrize(
    "field, value",
    [
        ("domain", "northgate-soc.unknown.example"),
        ("domain", "northgate.example"),
        ("key", FP[:-1]),
        ("key", FP[:-1] + '"'),
        ("key", FP + "\nsend"),
    ],
)
def test_bad_domain_or_key_is_rejected(field, value):
    with pytest.raises(dns_api.ValidationError):
        dns_api.validate_update(dict(UPDATE, **{field: value}))


def test_key_is_optional():
    data = dict(UPDATE)
    del data["key"]
    assert dns_api.validate_update(data)["key"] == ""


@pytest.mark.parametrize("zone", ["halcyon-intel.example", "extrahop.com", "x.extrahop.com"])
def test_allowed_zone_names(zone):
    assert dns_api.validate_zone(zone) == zone


@pytest.mark.parametrize(
    "zone", ["example", "evil.com", "bad zone.example", "a.example\nsend", "-x.example"]
)
def test_rejected_zone_names(zone):
    with pytest.raises(dns_api.ValidationError):
        dns_api.validate_zone(zone)


def _fake_tools(tmp_path):
    log = tmp_path / "calls.log"
    for tool, body in (
        ("rndc", f'echo "rndc $*" >> {log}'),
        ("nsupdate", 'cat "$1"'),
        ("dig", "true"),
        ("chown", "true"),
    ):
        path = tmp_path / tool
        path.write_text(f"#!/bin/bash\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}"), log


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_add_zone_script_is_idempotent(tmp_path):
    env, log = _fake_tools(tmp_path)
    zone_dir = tmp_path / "zones"
    script = os.path.join(SCRIPTS, "add_zone.sh")
    first = subprocess.run(
        ["bash", script, "northgate.example", str(zone_dir)],
        capture_output=True, text=True, check=True, env=env,
    ).stdout
    second = subprocess.run(
        ["bash", script, "northgate.example", str(zone_dir)],
        capture_output=True, text=True, check=True, env=env,
    ).stdout
    assert first.strip() == "created"
    assert second.strip() == "exists"
    zone_file = (zone_dir / "db.northgate.example").read_text()
    assert "ns.northgate.example. admin.northgate.example." in zone_file
    calls = log.read_text().splitlines()
    assert len(calls) == 1
    assert calls[0].startswith("rndc addzone northgate.example")


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_update_script_uses_zone_and_key(tmp_path):
    env, _ = _fake_tools(tmp_path)
    clean = dns_api.validate_update(dict(UPDATE))
    args = [clean[k] for k in dns_api.SCRIPT_FIELDS]
    out = subprocess.run(
        ["bash", os.path.join(SCRIPTS, "update_zone.sh"), *args],
        capture_output=True, text=True, check=True, env=env,
    ).stdout
    assert "zone northgate.example" in out
    assert f'"key={FP}"' in out
    assert "SRV 0 0 8080 arena." in out


def test_post_zones_runs_script_and_registers_zone(tmp_path, monkeypatch):
    script = tmp_path / "add_zone.sh"
    script.write_text('#!/bin/bash\necho created\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(dns_api, "ADD_ZONE_SCRIPT", str(script))
    server = socketserver.TCPServer(("127.0.0.1", 0), dns_api.DNSUpdateHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        conn.request("POST", "/zones", json.dumps({"zone": "keystone-id.example"}),
                      {"Content-Type": "application/json"})
        response = conn.getresponse()
        body = json.loads(response.read())
        assert response.status == 200
        assert body == {"status": "success", "zone": "keystone-id.example", "result": "created"}
        assert "keystone-id.example" in dns_api.ZONES

        conn.request("POST", "/zones", json.dumps({"zone": "evil.com"}),
                     {"Content-Type": "application/json"})
        response = conn.getresponse()
        assert response.status == 400
        response.read()
    finally:
        server.shutdown()
        server.server_close()
