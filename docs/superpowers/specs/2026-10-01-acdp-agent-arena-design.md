# ACDP Agent Arena — Design Spec

Date: 2026-10-01. Owner: Dean De Beer. Status: draft for review.
Source: `docs/acdp-agent-arena-design-v0.1.md`. This spec refines that design and resolves the gaps between it and the ACDP code.

## 1. Purpose

The arena shows that agents from different companies discover each other through ACDP, verify who they talk to, and hold live multi-party conversations without a central orchestrator. It demonstrates discovery and trust. It does not demonstrate task execution.

### Success criteria

1. `docker compose up` starts DNS, registry, and the arena. The UI at `http://localhost:8080` shows 10 agents in 8 domain clusters within 60 seconds. The impostor has its own cluster (`halcyon-inte1.example`).
2. All agents except the impostor reach `verified`. The impostor shows `failed: domain mismatch`.
3. Thread 1 (the phishing investigation) receives findings from at least 3 investigation agents. The ISAC Coordinator closes it with a `verdict` message within 20 minutes.
4. At least one Sonnet agent sends `decline` or `challenge` to the impostor.
5. An operator adds an agent from the UI. The agent appears, reaches `verified`, and another agent discovers it, with no restart.
6. A saved event log replays in the UI with no API key.
7. `pytest` passes with no API key and no containers.

## 2. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Extend ACDP in place (DNS API, registry, card). Do not wrap it. | The arena must exercise and improve the real implementation. |
| D2 | Ed25519 signed messages. DNS TXT pins the key fingerprint. | The impostor fails a deterministic check, not a model judgment. |
| D3 | One HTTP server. Each agent's A2A app is mounted at `/agents/<slug>/`. | Live injection mounts a path. Agents still use real HTTP A2A. |
| D4 | Strands agent with structured `TurnDecision` output on a timer. Inbound messages go to an inbox. | The model makes judgment calls. Code does routing, rate limits, and verification. |
| D5 | Static UI with no build step. `force-graph` from a CDN. | The repo has no JS toolchain. |
| D6 | The arena is the default `docker-compose.yml`. The PoC moves to `archive/poc/`. | One clean stack. Shared modules stay in `agent/`. |
| D7 | The registry accepts cards that fail verification and records the failure. | Design v0.1: peers catch the impostor, not the registry. |
| D8 | First registrant of an organization name owns its canonical domain. | Gives `verify` a source of truth for "claimed org → domain". |

Models: Sonnet is `claude-sonnet-5-5`. Haiku is `claude-haiku-4-5-20251001`. `MODEL_PROVIDER=bedrock` stays supported through the existing `build_model`.

## 3. Architecture

```
Browser UI ──WS /ws──► arena service (one process, port 8080)
            ──POST /arena/*──►  ├─ host.py   FastAPI: /, /ws, /arena/*, /agents/<slug>/ (A2A)
                                ├─ agent.py  one asyncio task per agent (tick loop)
                                ├─ bus.py    pub/sub + JSONL log + replay
                                └─ verify.py signature + DNS key pin + org check
                                     │ register / discover        │ TXT lookup
                                     ▼                            ▼
                                 registry (Flask) ──fetch card──► bind (BIND9 + DNS API)
```

## 4. ACDP changes

### 4.1 DNS API (`dns/scripts/dns_api.py`, `dns/named.conf`, `dns/zones/`)

- `ACDP_ZONES` (comma-separated) replaces the single `AGENT_ZONE`. A name is valid when it is under one of the configured zones. The default is `agents.local`, which keeps current behavior.
- The DNS API creates a zone for a new company domain on request: `POST /zones {"zone": "<domain>"}`. The zone name must match the label regex and be in an allow-list suffix set (`ACDP_ZONE_SUFFIXES`, default `.example,.local,extrahop.com,tenable.com`).
- The TXT record gains `key=<fp>`, where `fp` is the base64url SHA-256 of the raw Ed25519 public key (43 characters). `key` is validated with `^[A-Za-z0-9_-]{43}$`.
- All existing injection protections stay. New fields get the same strict validation.

### 4.2 Registry (`registry/app.py`)

On `POST /registerAgent` with an `agent_card`, the registry:

1. Fetches the card from its advertised URL (timeout 5 s).
2. Resolves the TXT record for the agent's domain through `bind`.
3. Stores `verification`:

```json
{"status": "verified|failed|pending",
 "card_fetched": true, "dns_found": true, "key_matches_dns": true,
 "org_conflict": false, "reasons": [], "checked_at": "<iso8601>"}
```

`status` is `verified` only when all three checks are true and `org_conflict` is false.

4. Maintains `org_domain`: the first registration of an `organization` value records its domain. A later registration with the same normalized organization (lowercase, alphanumeric only) and a different domain sets `org_conflict: true`. The response includes `canonical_domain`.
5. Accepts the registration in all cases (D7). `GET /agents`, `GET /agents/<id>`, and capability search include `verification`.
6. Adds `GET /orgs/<normalized>` → `{"organization", "canonical_domain"}`.

### 4.3 Card (`agent/runtime/a2a_card.py`)

The ACDP extension params gain `did` (`did:web:<domain>:agents:<slug>`), `organization`, `domain`, `publicKeyJwk` (OKP/Ed25519), and `model`.

## 5. Arena package (`arena/`)

| File | Responsibility |
|---|---|
| `identity.py` | `Identity` with key generation, `did`, `fingerprint()`, `sign(envelope)`, `verify(envelope, jwk)`. Canonical form: JSON with sorted keys, no whitespace, `sig` field removed. |
| `envelope.py` | Pydantic `ArenaMessage`: `id`, `thread_id`, `from_did`, `to_did`, `ts`, `intent`, `body`, `card_url`, `sig`. `Intent` enum: `request`, `reply`, `share`, `decline`, `challenge`, `verdict`, `close`. |
| `verify.py` | `verify_inbound(msg) -> Trust`. Checks: (1) fetch the sender card, (2) signature against the card key, (3) card key fingerprint equals DNS `key=` under the card domain, (4) registry canonical domain for the card's organization equals the card domain. Returns `Trust(status, reason)`. Reasons: `bad signature`, `key not in dns`, `domain mismatch`, `card unreachable`. |
| `cast.py` + `cast.yaml` | Loads agent definitions: slug, name, organization, domain, capability, `needs` (capabilities it queries), model tier, cadence range, system prompt, per-thread cap. |
| `agent.py` | `ArenaAgent`: inbox (`asyncio.Queue`), tick loop, prompt build, Strands call with `TurnDecision`, decision checks, sign and send. |
| `decision.py` | Pydantic `TurnDecision`: `action` (`send`/`wait`), `to` (agent id), `thread_id` (id or `"new"`), `intent`, `body` (max 1200 characters). |
| `threads.py` | `ThreadRegistry`: open, append, close, caps, color index. Closes thread 1 on `verdict` from the ISAC Coordinator. |
| `rate.py` | Arena-wide token bucket (10 messages per minute) and run guard (`ARENA_MAX_MINUTES=20`, `ARENA_MAX_MODEL_CALLS=600`). |
| `inbox_executor.py` | a2a-sdk `AgentExecutor` that runs `verify_inbound`, puts the message in the inbox, and returns an ack. It makes no model call. |
| `host.py` | FastAPI app: static UI at `/`, `GET /ws`, `POST /arena/agents`, `POST /arena/pause`, `POST /arena/resume`, `POST /arena/replay`, A2A apps mounted at `/agents/<slug>/`. |
| `bus.py` | `EventBus`: `publish(type, data)`, assigns `seq`, appends to `runs/<run-id>.jsonl`, fans out to WebSocket clients. `replay(path, speed)`. |
| `prompts.py` | Prompt templates and the Sonnet "generate agent" prompt. |
| `__main__.py` | Loads the cast, starts the host, registers the agents, seeds thread 1. |

The A2A receive side uses the a2a-sdk server application directly with `InboxExecutor`. The Strands `A2AServer` invokes the model on every inbound message, which conflicts with D4. The send side uses the a2a-sdk client.

### Reused from `agent/`

`runtime/a2a_card` (extended), `discovery/registry_client`, `discovery/dns_resolver`, `discovery/discovery_service`, `utils/dns_utils` (extended with `key=`), `utils/endpoints`.

Two reused modules import PoC code. The plan fixes both before the archive move:

- `runtime/a2a_card.py` imports `ACDP_EXTENSION_URI` from `runtime/delegation.py`. Move the constant into `a2a_card.py`. `delegation.py` imports it from there.
- `runtime/strands_agent.py` imports `build_tools` from `runtime/tools.py`. Move `build_model` and `ModelFactory` into a new `runtime/models.py`. `strands_agent.py` imports them from there and moves to the archive.

## 6. Data flow

### 6.1 Registration (startup and injection)

1. `host` creates an `Identity` and mounts the A2A app at `/agents/<slug>/`.
2. The DNS API creates the zone if it is missing, then writes SRV and TXT (`a2a=`, `key=`, `cap=`).
3. The agent registers its card. The registry verifies it (4.2).
4. Events: `agent.registered`, then `agent.verified` or `agent.verification_failed` with `reasons`.

### 6.2 Tick

1. Drain the inbox. Each item carries its `Trust`.
2. Query the registry for each capability in `needs`. Emit `discovery.query` with the result ids.
3. Build the prompt: system prompt, inbox items (sender name, organization, domain, trust), history of the agent's threads (last 10 messages per thread), and candidate peers with their verification status.
4. Call the model for a `TurnDecision`.
5. Check the decision in code: the target is a discovered peer, the intent is valid, and the thread is open and under its cap. The arena bucket must have a token. If a check fails, the agent waits and the runtime emits `decision.rejected` with the reason.
6. Sign the `ArenaMessage`, then send it over A2A with the envelope in `Message.metadata["arena"]` and the body in a `TextPart`. Emit `message.sent`.

### 6.3 Receive

`InboxExecutor` runs `verify_inbound`, emits `verification.peer_check`, puts the message in the inbox with its `Trust`, and returns an ack. A failed check does not drop the message. The recipient model sees the failure and decides how to respond.

### 6.4 Impostor

Lookalike Intel registers organization "Halcyon Intel" with domain `halcyon-inte1.example`. Halcyon Intel registered first, so the registry sets `org_conflict: true` and `canonical_domain: halcyon-intel.example`. The impostor's DNS record and key are valid for its own domain. Check (4) in `verify_inbound` fails with `domain mismatch`. Sonnet system prompts tell the agent to decline or challenge senders whose trust is not `verified`.

### 6.5 Event types

`arena.started`, `arena.paused`, `arena.resumed`, `arena.stopped`, `agent.registered`, `agent.verified`, `agent.verification_failed`, `agent.error`, `discovery.query`, `thread.opened`, `thread.closed`, `message.sent`, `message.failed`, `verification.peer_check`, `decision.rejected`. Each event: `{seq, ts, run_id, type, data}`.

## 7. Threads, cadence, injection, replay

- **Seed.** At start, the runtime opens thread 1 (owner: SOC Investigator) and puts the incident brief in the SOC Investigator's inbox as a system item.
- **Threads.** `thread_id: "new"` opens a thread owned by the sender. A thread closes on `close` from its owner, `verdict` on thread 1 from the ISAC Coordinator, or 12 messages (configurable per agent in `cast.yaml`).
- **Cadence.** Tick interval is uniform random within the agent's range: investigation 15–20 s, agenda 50–70 s, impostor 120–180 s. The arena bucket caps the arena at 10 messages per minute. The run guard emits `arena.stopped` and stops all ticks.
- **Pause.** Pause stops new ticks. In-flight model calls complete, and their decisions are dropped.
- **Injection.** `POST /arena/agents` with `{name, organization, domain, capability, needs, model, agenda, generate, misconfigure}`. `generate: true` asks Sonnet for a system prompt from the name, capability, and agenda. `misconfigure` is one of `none`, `no_txt`, or `wrong_key`. The response is `201` with the agent id, or `400` with a reason and no state change. The slug must be unique and the domain must pass DNS API validation.
- **Replay.** `POST /arena/replay {"log": "<run-id>", "speed": 1-10}` switches the arena to replay mode and streams the saved log over `/ws` at the given speed. Live agents stay stopped in replay mode. The arena starts in replay mode when `ANTHROPIC_API_KEY` is not set.
- **Catch-up.** A new WebSocket client gets all events from `seq 0`, then live events.

## 8. Cast (`arena/cast.yaml`)

| Slug | Organization (domain) | Capability | Needs | Model |
|---|---|---|---|---|
| northgate-soc | Northgate Bank (northgate.example) | soc-investigation | threat-intel, identity, network-detection, coordination | Sonnet |
| halcyon-intel | Halcyon Intel (halcyon-intel.example) | threat-intel | soc-investigation | Sonnet |
| keystone-identity | Keystone IdP (keystone-id.example) | identity | soc-investigation | Sonnet |
| extrahop-ndr | ExtraHop (extrahop.com) | network-detection | soc-investigation | Sonnet |
| meridian-soc | Meridian Credit Union (meridian-cu.example) | soc-investigation | threat-intel, coordination | Sonnet |
| finshare-isac | FinShare ISAC (finshare-isac.example) | coordination | soc-investigation, threat-intel | Sonnet |
| northgate-procurement | Northgate Bank (northgate.example) | procurement | sales | Haiku |
| tenable-exposure | Tenable (tenable.com) | exposure | soc-investigation, identity | Haiku |
| halcyon-sales | Halcyon Intel (halcyon-intel.example) | sales | procurement, soc-investigation | Haiku |
| lookalike-intel | Halcyon Intel (halcyon-inte1.example) | threat-intel | soc-investigation | Haiku |

Registration order puts `halcyon-intel` before `lookalike-intel` (D8). ExtraHop and Tenable agents describe only generic capabilities. They make no product claims.

## 9. UI (`arena/ui/`)

- **Files:** `index.html`, `app.js` (WS client, event store, filters), `graph.js`, `transcript.js`, `controls.js`, `style.css`. `force-graph` is loaded from a CDN.
- **Graph (left, about 65% width):** nodes in clusters by domain (cluster force plus label). The cluster label shows the organization and the domain, so the impostor's cluster reads "Halcyon Intel (halcyon-inte1.example)". Badge shows `S` or `H`. Border colors: green verified, amber pending, red failed. A particle in the thread color moves along the edge for each `message.sent`. `decline` and `challenge` edges are red. A click on a node filters the transcript.
- **Transcript (right):** sender → recipient, thread chip, intent tag, body. System lines for registration, verification, and threads. Filters: thread, agent, company, intent. Filters combine.
- **Control bar (top):** agent, message, and open-thread counts. Pause and resume. Live/replay switch with log picker and speed slider. An "Add agent" modal with "Generate prompt" and a "Misconfigure" select.
- **State:** derived only from events. Target: laptop and projector widths. Phone width is not a goal.

## 10. Error handling

| Condition | Behavior |
|---|---|
| Model call error or timeout (60 s) | Emit `agent.error`, skip the tick, back off (×2, maximum 120 s). Other agents continue. |
| `TurnDecision` fails validation | Treat as `wait`. Emit `decision.rejected`. |
| A2A send fails | Retry once after 2 s, then emit `message.failed`. |
| Inbound verification fails | Deliver with `trust: failed`. Emit `verification.peer_check`. |
| Registry or DNS API unreachable at registration | Retry for 30 s, then mark the agent `failed`. The runtime continues. |
| Invalid injection request | `400` with reason. No state change. |
| Run guard limit reached | Emit `arena.stopped`. Stop all ticks. The UI stays connected. |

## 11. Archive (D6)

- Move `docker-compose.yml` to `archive/poc/docker-compose.yml`. The new `docker-compose.yml` runs `bind`, `registry`, and `arena` (port 8080).
- Move `agent/node.py`, `agent/agent.py`, `agent/acdp_routes.py`, `agent/handlers/`, `agent/services/`, `agent/peers/`, `agent/runtime/{strands_agent,tools,delegation,peer_client,a2a_server}.py`, `agent/monitor_collaboration.py`, `agent/test_*.py`, and the PoC tests to `archive/poc/agent/`. The plan confirms this list with an import audit.
- Set `pytest.ini` `testpaths` to `agent/tests registry/tests dns/tests arena/tests`. Archived tests do not run.
- Update `README.md` and `CLAUDE.md` for the arena stack.

## 12. Testing

No automated test calls a live model. Tests use a scripted Strands model, as the existing integration tests do.

- **Unit (`arena/tests/`):** sign/verify round trip. A tampered body fails. Fingerprint length and alphabet. `verify_inbound` returns `domain mismatch` for the impostor fixture and `key not in dns` for a missing TXT. `TurnDecision` validation. Token bucket and thread cap. Event-log `seq` order and replay order. Injection request validation.
- **ACDP (`dns/tests/`, `registry/tests/`):** multi-zone accept and reject. Zone creation allow-list. `key=` validation. The existing injection tests still pass. Registry verification states: card unreachable, TXT missing, key mismatch, org conflict, verified.
- **Integration (`arena/tests/test_arena_integration.py`):** in process. Three scripted agents plus the impostor. Registry and DNS are stubbed at the HTTP boundary. Assert: the impostor is `failed: domain mismatch`. The scripted Sonnet stand-in sends `decline` to it. An agent injected mid-run appears in another agent's next `discovery.query`. Thread 1 closes on `verdict`.
- **Live smoke (`arena/scripts/smoke.py`, manual):** runs the compose stack for 5 minutes. The impostor first sends after 120–180 s, so 3 minutes can miss the decline. Assert at least 1 `message.sent` on thread 1, at least 1 `decline` or `challenge` sent to `lookalike-intel`, and 0 `agent.error` events.

## 13. Out of scope

mTLS, verifiable-credential signing, key rotation, persistence beyond the JSONL log, UI authentication, tool calls against external systems, phone layout, real DNS changes.

## 14. Risks

- **Model cost.** The run guard caps a run at 600 model calls. Haiku runs the high-frequency loops.
- **Org-name anchor (D8) is a demo trust model.** First-registrant-wins is open to registration races. The spec accepts this for the demo. ACDP.md records it as a known gap.
- **Real brand names.** ExtraHop and Tenable appear by name. The impostor mimics only the fictional Halcyon Intel. Agent prompts make no claims about real products.
