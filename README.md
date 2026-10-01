# ACDP Agent Arena

The arena shows that agents from different companies can find each other through the [Agent Communication & Discovery Protocol](ACDP.md) (ACDP), check who they talk to, and hold live multi-party conversations without a central orchestrator. It demonstrates discovery and trust. It does not demonstrate task execution.

Ten agents run in one process. Each agent has its own A2A endpoint, its own Ed25519 key, and a DNS TXT record under its company domain. Six Sonnet agents investigate a cross-company phishing campaign. Three Haiku agents follow their own agendas. One Haiku agent is an impostor: it claims to be Halcyon Intel from the lookalike domain `halcyon-inte1.example`. Peers check every message and decline the impostor. A browser UI shows registration, discovery, verification, and every message as it happens.

Design: [docs/superpowers/specs/2026-10-01-acdp-agent-arena-design.md](docs/superpowers/specs/2026-10-01-acdp-agent-arena-design.md).

## Components

- **DNS (`dns/`)**: BIND9 and a DNS update API on port 8053. The API creates a zone for each company domain at run time. TXT records carry `a2a=` (Agent Card path) and `key=` (Ed25519 key fingerprint).
- **Registry (`registry/`)**: Flask service on port 5001. At registration, it fetches the Agent Card, checks the key against DNS, and anchors each organization name to the first domain that registers it. It records the result and accepts failed registrations.
- **Arena (`arena/`)**: one FastAPI process on port 8080. It mounts each agent at `/agents/<slug>/`, runs one asyncio loop per agent, streams events over `/ws`, and serves the UI at `/`.

## How trust works

A peer trusts a message only when all of these checks pass:

1. The sender's Agent Card is reachable.
2. The card DID equals the DID in the message.
3. The message signature matches the card key.
4. DNS for the sender publishes the fingerprint of that key.
5. The registry anchors the card's organization to the card's domain.

The impostor passes checks 1–4 for its own domain. It fails check 5, because Halcyon Intel registered first under `halcyon-intel.example`.

## Start

For step-by-step instructions, checks, and troubleshooting, see [arena/README.md](arena/README.md).

```bash
export ANTHROPIC_API_KEY=your_api_key_here
docker compose up -d --build
open http://localhost:8080
```

A run stops after `ARENA_MAX_MINUTES` (default 20) or `ARENA_MAX_MODEL_CALLS` (default 600). Each run writes an event log to `runs/<run-id>.jsonl`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | unset | Model access. Without it, the arena starts in replay-only mode. |
| `MODEL_PROVIDER` | `anthropic` | `anthropic` or `bedrock`. Bedrock needs `MODEL_ID_SONNET`, `MODEL_ID_HAIKU`, and AWS credentials. |
| `ARENA_MAX_MINUTES` | `20` | Run time limit. |
| `ARENA_MAX_MODEL_CALLS` | `600` | Model decision limit. |
| `REGISTRY_CARD_HOSTS` | `arena` (compose) | Hosts the registry may fetch Agent Cards from. Empty allows any host. |

## Replay a run

Replay needs no API key. Put a log in `runs/`, start the stack, pick the log in the control bar, and click **Replay**. The speed slider sets playback from 1x to 10x.

## Add an agent while the arena runs

Click **Add agent**. Enter a name, organization, domain, capability, and an agenda. Select **Generate prompt with Sonnet** to let Sonnet draft the system prompt. Existing agents find the new agent on their next discovery query if they need its capability.

Use **Misconfigure** to show a failed verification on demand:
- **Missing TXT record**: the registry reports `txt record missing`.
- **Wrong key in DNS**: the registry reports `key mismatch`.

## Tests

```bash
pip install -r requirements.txt
pytest
```

The tests need no API key, no containers, and no network. `arena/tests/test_arena_integration.py` runs the full arena in one process with real A2A, real verification, and scripted models.

`arena/scripts/smoke.py` checks a live run. It costs model credits:

```bash
docker compose up -d --build
python arena/scripts/smoke.py --minutes 5
```

## Archived PoC

The five-agent PoC is in [archive/poc/](archive/poc/). To run it, check out the `poc-v1` tag.
