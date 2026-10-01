# Arena Workbench UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the arena's force-graph-plus-transcript page with an engineering Workbench. The Workbench shows registration steps, discovery intent, registry state, Agent Cards, prompts, decisions, and A2A task state across four graph views and a threaded chat.

**Architecture:**
- **Phase 1 (backend):** the backend publishes richer events (registration steps, enriched discovery, decisions with prompts) and exposes read APIs for agents and the registry.
- **Phases 2–4 (UI):** a pure event store (`store.js`) feeds Preact + htm components loaded from a CDN, with no build step. Views share one selection model.
- **Phase 5 (A2A tasks):** `request` messages become A2A Tasks. Replies complete or reject them by a deterministic link rule, and requesters observe them with `tasks/get`.

**Tech Stack:**
- Backend: Python 3.12, FastAPI, a2a-sdk 0.3.x (`TaskUpdater`, `InMemoryTaskStore`, client `get_task`/`cancel_task`), Strands, httpx, pytest.
- UI: Preact + htm (`htm@3/preact/standalone.module.js`), `force-graph@1`, `@dagrejs/dagre@1`.
- JS tests: Node 22 `node --test`, dev-only, no bundling.

**Spec:** `docs/superpowers/specs/2026-10-01-arena-workbench-ui-design.md`. It builds on `docs/superpowers/specs/2026-10-01-acdp-agent-arena-design.md`. Read both before you start.

## Global Constraints

- No build step. The UI is ES modules served by `/ui/*`. CDN imports appear only in `arena/ui/preact.js` and `arena/ui/index.html`.
- CDN URLs (jsDelivr, major-pinned):
  - `https://cdn.jsdelivr.net/npm/htm@3/preact/standalone.module.js`
  - `https://cdn.jsdelivr.net/npm/force-graph@1/dist/force-graph.min.js`
  - `https://cdn.jsdelivr.net/npm/@dagrejs/dagre@1/dist/dagre.min.js`
- Pure modules (`arena/ui/store.js`, `arena/ui/palette.js`, `arena/ui/lib/*.js`) import nothing from a CDN and touch no DOM, so `node --test` can load them.
- JS tests live in `arena/ui/tests/*.test.mjs`. Run them with `node --test "arena/ui/tests/*.test.mjs"`. A directory argument does not work in Node 22.
- Python tests: `pytest` from the repo root (pytest.ini sets `pythonpath = agent .`). No test calls a live model or the network.
- `TurnDecision.looking_for` and `why_this_peer`: each at most 200 characters, default `""`.
- Discovery result `status`: the registry verification status, or `"unknown"` when the entry has none.
- Registration steps, in order: `identity`, `zone`, `dns`, `card`, `submitted`, `checks`, `result`. Step status is one of `ok`, `failed`, `skipped`.
- Final task states: `completed`, `rejected`, `canceled`, `failed`. Each agent polls at most 5 open requests per tick.
- The UI targets laptops and wide monitors. Phones are not a goal.
- Prose and comments use ASD-STE100 style. Code uses 4-space Python indentation, 2-space JS indentation, and 88-character Python lines.
- Use the existing test basename rule: every test file name is unique across the repo.

## Review Focus

1. **Replaying a log recorded before Phase 1.** Such logs have no `registration.step` or `decision.made` events, and `discovery.query.results` holds plain ids. Expected: the UI renders what the log contains and does not throw. Test: Task 6, `old-format discovery results are accepted`.
2. **Reconnecting while a run is live.** The server resends history, and history and live events can overlap. Expected: no message appears twice. Test: Task 6, `duplicate seq is ignored`.
3. **Registry down while the registry browser is open.** Expected: `/arena/registry` returns 502 with the reason, and the UI shows a banner. Test: Task 5, `test_registry_proxy_returns_502_when_unreachable`.
4. **The recipient completes a task, then the thread closes before the requester polls.** Expected: the requester reports `completed`, not `canceled`. Test: Task 17, `test_completed_task_is_not_canceled_on_thread_close`.
5. **A discovery result whose registry entry has no `verification`** (a legacy ACDP 1.0 entry). Expected: status `"unknown"`, with no crash. Test: Task 3, `test_discovery_result_without_verification_is_unknown`.

## File Map

| File | Change |
|---|---|
| `registry/services/verification.py`, `registry/app.py` | `OrgDirectory.all()`; `GET /orgs`. |
| `arena/decision.py`, `arena/prompts.py` | `looking_for`, `why_this_peer`; rule text. |
| `arena/agent.py` | Decision records, counters, state, query history, `seen` sets, `summary()`/`detail()`, DNS records; Phase 5: tasks, open requests, polling. |
| `arena/acdp.py` | `dns_txt()` helper; `registry_url` + `registry_get()`. |
| `arena/host.py` | Registration step events; `agent.registered` enrichment; per-agent task stores; per-agent thread cap for the seed thread. |
| `arena/api.py` | Read APIs and registry proxies. |
| `arena/inbox_executor.py`, `arena/transport.py`, `arena/tasks.py` (new) | Phase 5 task creation, linking, polling, cancel. |
| `arena/__main__.py` | Pass `registry_url` to `AcdpClient`. |
| `arena/ui/*` | New Workbench (replaces `graph.js`, `transcript.js`, `controls.js`, `app.js`). |
| `arena/scripts/make_demo_log.py` (new) | Writes a scripted, credit-free run log to `runs/demo.jsonl` for UI work. |
| `arena/tests/*` | New and updated tests. |
| `arena/README.md` | Workbench usage. |

---

### Task 1: Registry lists organizations

**Files:**
- Modify: `registry/services/verification.py` (`OrgDirectory`)
- Modify: `registry/app.py` (new route next to `GET /orgs/<normalized>`)
- Test: `registry/tests/test_registry_verification.py`

**Interfaces:**
- Produces: `OrgDirectory.all() -> List[Dict[str, str]]` sorted by organization. `GET /orgs` returns `200 {"orgs": [{"organization", "canonical_domain"}]}`.

- [ ] **Step 1: Write the failing test** (append to `registry/tests/test_registry_verification.py`)

```python
def test_orgs_list_endpoint(client):
    client.post("/registerAgent", json=registration())
    assert client.get("/orgs").get_json() == {"orgs": [
        {"organization": "Halcyon Intel", "canonical_domain": "halcyon-intel.example"}]}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest registry/tests/test_registry_verification.py -k orgs_list -v`
Expected: FAIL. The response is `404` HTML, so `get_json()` returns `None`.

- [ ] **Step 3: Implement**

In `OrgDirectory`, add:

```python
    def all(self) -> List[Dict[str, str]]:
        """Every organization and its canonical domain, sorted by name."""
        return sorted(self._entries.values(), key=lambda e: e["organization"].lower())
```

In `registry/app.py`, add above `@app.route("/orgs/<normalized>")`:

```python
@app.route("/orgs", methods=["GET"])
def list_orgs():
    """Every organization anchor (first registrant wins)."""
    return jsonify({"orgs": orgs.all()})
```

- [ ] **Step 4: Run tests**

Run: `pytest registry/tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add registry/
git commit -m "feat(registry): list organization anchors at GET /orgs"
```

---

### Task 2: Decisions carry intent; agents record decisions and counters

**Files:**
- Modify: `arena/decision.py`, `arena/prompts.py` (`RULES`), `arena/agent.py`
- Test: `arena/tests/test_arena_agent.py`, `arena/tests/test_arena_conversation.py`

**Interfaces:**
- Produces: `TurnDecision.looking_for: str`, `TurnDecision.why_this_peer: str`.
- Produces the event `decision.made {agent, prompt, decision, outcome}`. `decision` is `TurnDecision.model_dump(mode="json")`, or `None` for invalid output. `outcome` is one of `"sent"`, `"wait"`, `"failed: <error>"`, or `"rejected: <reason>"`.
- Produces: `message.sent` data gains `looking_for` and `why_this_peer`.
- Produces on `ArenaAgent`:
  - `last_prompt: str`, `last_decision: Optional[Dict]`, `decisions: Deque[Dict]` (maxlen 20);
  - `counters: Dict[str, int]` with keys `sent`, `received`, `rejected`, `errors`;
  - `state() -> str`: `stopped` | `paused` | `running`.
- The rate-limit pre-check skips the model, so it publishes `decision.rejected` only, with no `decision.made`. All other existing `decision.rejected` events stay.

- [ ] **Step 1: Write the failing tests**

Append to `arena/tests/test_arena_conversation.py`:

```python
def test_turn_decision_intent_fields():
    d = TurnDecision(action="send", looking_for="attribution", why_this_peer="only verified")
    assert (d.looking_for, d.why_this_peer) == ("attribution", "only verified")
    assert TurnDecision(action="wait").looking_for == ""
    with pytest.raises(ValidationError):
        TurnDecision(action="send", looking_for="x" * 201)
```

Append to `arena/tests/test_arena_agent.py`:

```python
def made(ctx):
    return [e["data"] for e in ctx.bus.history if e["type"] == "decision.made"]


def test_sent_decision_is_recorded_with_prompt_and_intent():
    decision = dict(send(), looking_for="campaign attribution", why_this_peer="only peer")
    agent, ctx, _, _ = make_agent(lambda prompt: decision)
    asyncio.run(agent.tick())
    record = made(ctx)[-1]
    assert record["outcome"] == "sent"
    assert record["decision"]["looking_for"] == "campaign attribution"
    assert "PEERS" in record["prompt"]
    sent = [e["data"] for e in ctx.bus.history if e["type"] == "message.sent"][-1]
    assert (sent["looking_for"], sent["why_this_peer"]) == ("campaign attribution", "only peer")
    assert agent.counters["sent"] == 1
    assert agent.last_prompt == record["prompt"]
    assert list(agent.decisions)[-1] == record


def test_wait_invalid_and_rejected_outcomes_are_recorded():
    agent, ctx, _, _ = make_agent(lambda prompt: {"action": "wait"})
    asyncio.run(agent.tick())
    assert made(ctx)[-1]["outcome"] == "wait"

    replies = iter([{"action": "maybe"}])
    agent, ctx, _, _ = make_agent(lambda prompt: next(replies, "no tool"))
    asyncio.run(agent.tick())
    assert made(ctx)[-1] == {"agent": agent.agent_id, "prompt": made(ctx)[-1]["prompt"],
                             "decision": None, "outcome": "rejected: invalid model output"}

    agent, ctx, _, _ = make_agent(lambda prompt: send(to="nobody.example"))
    asyncio.run(agent.tick())
    assert made(ctx)[-1]["outcome"] == "rejected: unknown target"
    assert agent.counters["rejected"] == 1


def test_failed_send_outcome_and_state():
    acdp = FakeAcdp()
    acdp.entries[PEER_ID] = PEER
    agent, ctx, _, _ = make_agent(lambda p: send(), ctx=make_ctx(acdp=acdp, sender=FakeSender(2)))
    asyncio.run(agent.tick())
    assert made(ctx)[-1]["outcome"].startswith("failed: ")
    assert agent.state() == "running"
    ctx.running.clear()
    assert agent.state() == "paused"
    ctx.stopped.set()
    assert agent.state() == "stopped"
```

Note: each `make_agent` call builds a new agent and context, so the final agent in `test_wait_invalid_and_rejected_outcomes_are_recorded` has exactly one rejection.

- [ ] **Step 2: Run to verify failure**

Run: `pytest arena/tests/test_arena_conversation.py arena/tests/test_arena_agent.py -k "intent or recorded or outcome" -v`
Expected: FAIL. `TurnDecision` rejects the unknown fields, and `decision.made` is never published.

- [ ] **Step 3: Implement**

`arena/decision.py`: add two fields after `body`:

```python
    looking_for: str = Field(default="", max_length=200)
    why_this_peer: str = Field(default="", max_length=200)
```

`arena/prompts.py`: add one line to `RULES`, before the line `- Keep "body" under 120 words.`:

```
- When you send, fill "looking_for" (what you need from this peer) and "why_this_peer" (why this peer and not another), each under 30 words.
```

`arena/agent.py`:

1. Add `from collections import deque` and `Deque` to the typing import.
2. In `ArenaAgent.__init__`, add:

```python
        self.last_prompt = ""
        self.last_decision: Optional[Dict[str, Any]] = None
        self.decisions: Deque[Dict[str, Any]] = deque(maxlen=20)
        self.counters = {"sent": 0, "received": 0, "rejected": 0, "errors": 0}
```

3. Add these methods:

```python
    def state(self) -> str:
        """stopped, paused, or running."""
        if self.ctx.stopped.is_set():
            return "stopped"
        return "running" if self.ctx.running.is_set() else "paused"

    def _record(
        self, prompt: str, decision: Optional[TurnDecision], outcome: str
    ) -> None:
        record = {
            "agent": self.agent_id,
            "prompt": prompt,
            "decision": decision.model_dump(mode="json") if decision else None,
            "outcome": outcome,
        }
        self.last_prompt = prompt
        self.last_decision = record["decision"]
        self.decisions.append(record)
        if outcome.startswith("rejected: "):
            self.counters["rejected"] += 1
        self.ctx.bus.publish("decision.made", record)
```

4. In `receive`, add `self.counters["received"] += 1` before the inbox put.
5. In `run`, in the `except` block, add `self.counters["errors"] += 1`.
6. In `_send`, return the error text so `tick` can record it. Change the signature to `async def _send(self, target, message) -> Optional[str]`. Return `None` on success and `str(e)` after the second failure. Publish `message.failed` as today.
7. In `tick`, record every model outcome. Replace the code from `decision = await self._decide(prompt)` through the final `return message` with:

```python
            decision = await self._decide(prompt)
        except BaseException:
            self._requeue(items)
            raise
        if decision is None:
            self._record(prompt, None, "rejected: invalid model output")
            self._requeue(items)
            return None
        if decision.action == "wait":
            self._record(prompt, decision, "wait")
            return None
        if not self.ctx.running.is_set():
            self._reject("paused")
            self._record(prompt, decision, "rejected: paused")
            self._requeue(items)
            return None
        reason = self._check(decision, targets)
        if reason:
            self._reject(reason)
            self._record(prompt, decision, f"rejected: {reason}")
            return None

        thread_id = decision.thread_id
        if thread_id == NEW_THREAD:
            thread = self.ctx.threads.open(
                self.agent_id, decision.body[:60], cap=self.spec.thread_cap
            )
            thread_id = thread.id
            self.ctx.bus.publish("thread.opened", {
                "id": thread.id, "owner": thread.owner,
                "title": thread.title, "color": thread.color,
            })
        target = targets[decision.to]
        message = ArenaMessage(
            id=uuid.uuid4().hex[:12],
            thread_id=thread_id,
            from_id=self.agent_id,
            to_id=decision.to,
            from_did=self.identity.did,
            to_did=target.did,
            ts=time.time(),
            intent=decision.intent,
            body=decision.body,
            card_url=self.card_url,
        ).signed(self.identity)
        error = await self._send(target, message)
        if error is not None:
            self._record(prompt, decision, f"failed: {error}")
            return None

        closed = self.ctx.threads.append(message)
        data = {k: v for k, v in message.payload().items() if k != "sig"}
        data["color"] = self.ctx.threads.get(thread_id).color
        data["looking_for"] = decision.looking_for
        data["why_this_peer"] = decision.why_this_peer
        self.counters["sent"] += 1
        self._record(prompt, decision, "sent")
        self.ctx.bus.publish("message.sent", data)
        if closed:
            self.ctx.bus.publish("thread.closed", {"id": thread_id, "reason": closed})
        return message
```

Keep the existing lines before `decision = await self._decide(prompt)` unchanged. They are the rate pre-check, `_drain`, `try:`, `_discover`, `for_agent`, and the `turn_prompt` build into `prompt`. `_decide` stays as it is: it still publishes `decision.rejected` for invalid output. The `cap=self.spec.thread_cap` argument also fixes the carried-over minor (spec §11): the per-agent thread cap was unused.

- [ ] **Step 4: Run tests**

Run: `pytest arena/tests -v`
Expected: PASS. If an existing test checks `ctx.bus.history[-1]` after a rejection, it now sees `decision.made` last, so that test fails. Change it to look up the last `decision.rejected` event:
`[e for e in ctx.bus.history if e["type"] == "decision.rejected"][-1]["data"]`.
Record this as a test adaptation in the ledger. The behavior is unchanged; only the event order grew.

- [ ] **Step 5: Commit**

```bash
git add arena/decision.py arena/prompts.py arena/agent.py arena/tests/
git commit -m "feat(arena): record every decision with prompt and outcome; intent fields"
```

---

### Task 3: Enriched discovery events and query history

**Files:**
- Modify: `arena/agent.py` (`_discover`)
- Modify: `arena/tests/test_arena_integration.py` (results are now objects)
- Test: `arena/tests/test_arena_agent.py`

**Interfaces:**
- Produces: `discovery.query {agent, capability, results: [{id, name, organization, domain, status, new}]}`.
- Produces on `ArenaAgent`: `queries: Deque[Dict]` (maxlen 20, each `{ts, capability, results}`) and `seen: Dict[str, Set[str]]`.

- [ ] **Step 1: Write the failing tests** (append to `arena/tests/test_arena_agent.py`)

```python
def queries(ctx):
    return [e["data"] for e in ctx.bus.history if e["type"] == "discovery.query"]


def test_discovery_results_carry_status_and_new_flag():
    agent, ctx, _, _ = make_agent(lambda p: {"action": "wait"})
    asyncio.run(agent.tick())
    first = queries(ctx)[-1]["results"]
    assert first == [{"id": PEER_ID, "name": "Threat Intel Analyst",
                      "organization": "Halcyon Intel", "domain": "halcyon-intel.example",
                      "status": "verified", "new": True}]
    asyncio.run(agent.tick())
    assert queries(ctx)[-1]["results"][0]["new"] is False
    assert len(agent.queries) == 2
    assert agent.queries[-1]["capability"] == "threat-intel"


def test_discovery_result_without_verification_is_unknown():
    legacy = {k: v for k, v in PEER.items() if k != "verification"}
    acdp = FakeAcdp()
    acdp.entries[PEER_ID] = legacy
    agent, ctx, _, _ = make_agent(lambda p: {"action": "wait"}, ctx=make_ctx(acdp=acdp))
    asyncio.run(agent.tick())
    assert queries(ctx)[-1]["results"][0]["status"] == "unknown"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest arena/tests/test_arena_agent.py -k discovery -v`
Expected: FAIL. `results` is a list of id strings.

- [ ] **Step 3: Implement**

In `ArenaAgent.__init__`, add:

```python
        self.queries: Deque[Dict[str, Any]] = deque(maxlen=20)
        self.seen: Dict[str, Set[str]] = {}
```

Add `Set` to the typing import. In `_discover`, replace the per-capability loop body with:

```python
        for capability in self.spec.needs:
            seen_before = self.seen.get(capability, set())
            results = []
            for entry in await self.ctx.acdp.find(capability):
                url = (entry.get("a2a") or {}).get("url")
                if entry["id"] == self.agent_id or not url or entry["id"] in targets:
                    continue
                targets[entry["id"]] = Target(url, entry.get("did", ""))
                peers.append(entry)
                results.append({
                    "id": entry["id"],
                    "name": entry.get("name", ""),
                    "organization": entry.get("organization", ""),
                    "domain": entry.get("domain", ""),
                    "status": (entry.get("verification") or {}).get("status", "unknown"),
                    "new": entry["id"] not in seen_before,
                })
            self.seen[capability] = {r["id"] for r in results}
            self.queries.append(
                {"ts": time.time(), "capability": capability, "results": results}
            )
            self.ctx.bus.publish("discovery.query", {
                "agent": self.agent_id, "capability": capability, "results": results,
            })
```

In `arena/tests/test_arena_integration.py`, the two discovery assertions now compare ids. Replace:

```python
    assert NEW_ID not in queries[0]["results"]
    assert NEW_ID in queries[-1]["results"]
```

with:

```python
    assert NEW_ID not in [r["id"] for r in queries[0]["results"]]
    newest = {r["id"]: r for r in queries[-1]["results"]}
    assert newest[NEW_ID]["new"] is True
```

- [ ] **Step 4: Run tests**

Run: `pytest arena/tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add arena/agent.py arena/tests/
git commit -m "feat(arena): discovery events carry status and new flags; keep query history"
```

---

### Task 4: Registration step events

**Files:**
- Modify: `arena/acdp.py` (add `dns_txt`), `arena/host.py` (`add_agent`/`_add_agent`), `arena/agent.py` (`dns`, `verification` attributes)
- Test: `arena/tests/test_arena_host.py`

**Interfaces:**
- Produces: `registration.step {id, step, status, detail}` in the order `identity, zone, dns, card, submitted, checks, result`. The detail for each step is in spec §4.1.
- Produces: `agent.registered` gains `system_prompt`, `needs`, `cadence`.
- Produces on `ArenaAgent`: `dns: Dict` (`{"srv", "txt"}` or `{"skipped": True}`) and `verification: Dict` (`{"status", "reasons"}`).
- Produces: `arena.acdp.dns_txt(capability, description, card_path, key) -> List[str]`. It returns the TXT strings in the order `update_zone.sh` writes them.

- [ ] **Step 1: Write the failing tests** (append to `arena/tests/test_arena_host.py`)

```python
def steps(arena, agent_id):
    return [e["data"] for e in arena.bus.history
            if e["type"] == "registration.step" and e["data"]["id"] == agent_id]


def test_registration_publishes_seven_steps_in_order():
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"))
    asyncio.run(arena.setup())
    soc = steps(arena, "northgate-soc.northgate.example")
    assert [s["step"] for s in soc] == [
        "identity", "zone", "dns", "card", "submitted", "checks", "result"]
    assert all(s["status"] == "ok" for s in soc[:-1])
    by = {s["step"]: s["detail"] for s in soc}
    agent = arena.agents["northgate-soc"]
    assert by["identity"] == {"did": agent.identity.did,
                              "fingerprint": agent.identity.fingerprint()}
    assert by["zone"] == {"zone": "northgate.example", "result": "created"}
    assert by["dns"]["srv"] == "arena:8080"
    assert f"key={agent.identity.fingerprint()}" in by["dns"]["txt"]
    assert by["card"]["card_url"].endswith("/agents/northgate-soc/.well-known/agent-card.json")
    assert by["checks"]["status"] == "verified"
    assert soc[-1] == {"id": "northgate-soc.northgate.example", "step": "result",
                       "status": "ok", "detail": {"status": "verified", "reasons": []}}
    assert agent.dns == by["dns"]
    assert agent.verification == {"status": "verified", "reasons": []}
    registered = events(arena, "agent.registered")[0]
    assert registered["system_prompt"].startswith("You lead the investigation.")
    assert registered["needs"] == ["threat-intel"]


def test_no_txt_marks_dns_skipped_and_result_failed():
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"))
    asyncio.run(arena.setup())
    spec = AgentSpec.from_dict(spec_dict(slug="broken", organization="Broken Co",
                                         domain="broken.example"))
    asyncio.run(arena.add_agent(spec, misconfigure="no_txt"))
    b = {s["step"]: s for s in steps(arena, "broken.broken.example")}
    assert b["dns"]["status"] == "skipped"
    assert b["checks"]["status"] == "failed"
    assert b["result"] == {"id": "broken.broken.example", "step": "result",
                           "status": "failed",
                           "detail": {"status": "failed", "reasons": ["txt record missing"]}}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest arena/tests/test_arena_host.py -k "steps or skipped" -v`
Expected: FAIL. `steps(...)` returns `[]`.

- [ ] **Step 3: Implement**

In `arena/acdp.py`, add a module-level function:

```python
def dns_txt(capability: str, description: str, card_path: str, key: str) -> List[str]:
    """TXT strings as update_zone.sh writes them (for display; DNS is the source)."""
    clean = "".join(ch for ch in description if ch.isprintable() and ch not in '"\\')[:200]
    txt = ["ver=1.1", f"caps={capability}", f"desc={clean}", "proto=a2a/0.3",
           f"a2a={card_path}"]
    if key:
        txt.append(f"key={key}")
    return txt
```

In `ArenaAgent.__init__`, add:

```python
        self.dns: Dict[str, Any] = {}
        self.verification: Dict[str, Any] = {"status": "pending", "reasons": []}
```

In `arena/host.py`, rewrite `_add_agent`. Keep `add_agent` (validation and slug reservation) unchanged.

```python
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
        self.app.mount(
            f"/agents/{spec.slug}", build_a2a_app(card, InboxExecutor(agent.receive))
        )
        self.agents[spec.slug] = agent
        agent_id = identity.agent_id
        self.bus.publish("agent.registered", {
            "id": agent_id, "slug": spec.slug, "name": spec.name,
            "organization": spec.organization, "domain": spec.domain,
            "capability": spec.capability, "model": spec.model, "role": spec.role,
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
```

Add these imports to `host.py`: `from arena.acdp import AcdpError, dns_txt` and `from arena.prompts import generate_request, system_prompt`.

Note: `zone_result` is now the return value of `create_zone`. `FakeAcdp.create_zone` already returns `"created"` or `"exists"`.

In the same task, update the seed thread in `Arena.setup` so it uses the owner's cap (carried-over minor). Change the `open(...)` call to pass `cap=owner.spec.thread_cap`.

- [ ] **Step 4: Run tests**

Run: `pytest arena/tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add arena/acdp.py arena/host.py arena/agent.py arena/tests/test_arena_host.py
git commit -m "feat(arena): publish seven registration steps with DNS and registry check detail"
```

---

### Task 5: Read APIs and registry proxies

**Files:**
- Modify: `arena/acdp.py` (`registry_url` param, `registry_get`), `arena/agent.py` (`summary`, `detail`), `arena/api.py` (routes), `arena/__main__.py` (pass `registry_url`)
- Modify: `arena/tests/conftest.py` (`FakeAcdp.registry_get`)
- Test: `arena/tests/test_arena_api.py`, `arena/tests/test_arena_acdp.py`

**Interfaces:**
- Produces: `AcdpClient(..., registry_url: str = "")`. `async registry_get(path: str) -> Tuple[int, Any]` returns `(status, json body)`. It raises `AcdpError` when the registry cannot be reached.
- Produces: `ArenaAgent.summary() -> Dict` and `ArenaAgent.detail() -> Dict` (keys in the test below).
- Produces (HTTP): `GET /arena/agents`, `GET /arena/agents/{slug}` (404 when unknown), `GET /arena/registry`, `GET /arena/registry/agents/{agent_id}/card`, `GET /arena/registry/orgs`. Proxy routes return the registry's status and body, or `502 {"error"}`.

- [ ] **Step 1: Write the failing tests**

Append to `arena/tests/test_arena_acdp.py`:

```python
def test_registry_get_returns_status_and_body_or_raises():
    def handler(request):
        if request.url.path == "/agents":
            return httpx.Response(200, json={"agents": []})
        return httpx.Response(404, json={"error": "Agent not found"})

    acdp = AcdpClient("http://bind:8053", FakeRegistry(), FakeResolver(),
                      lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                      sleep=no_sleep, registry_url="http://registry:5000")
    assert asyncio.run(acdp.registry_get("/agents")) == (200, {"agents": []})
    assert asyncio.run(acdp.registry_get("/agents/x/card"))[0] == 404

    def down(request):
        raise httpx.ConnectError("down", request=request)

    broken = AcdpClient("http://bind:8053", FakeRegistry(), FakeResolver(),
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(down)),
                        sleep=no_sleep, registry_url="http://registry:5000")
    with pytest.raises(AcdpError, match="registry unreachable"):
        asyncio.run(broken.registry_get("/agents"))
```

Append to `arena/tests/test_arena_api.py`:

```python
def test_agent_list_and_detail(setup):
    arena, client, _ = setup
    asyncio_run_setup(arena, client)
    listed = client.get("/arena/agents").json()["agents"]
    assert [a["slug"] for a in listed] == ["northgate-soc"]
    assert set(listed[0]) >= {"id", "slug", "name", "organization", "domain", "capability",
                              "needs", "model", "role", "state", "counters", "verification"}
    detail = client.get("/arena/agents/northgate-soc").json()
    assert set(detail) >= {"system_prompt", "last_prompt", "last_decision", "decisions",
                           "threads", "inbox", "trust", "queries", "dns"}
    assert detail["dns"]["srv"] == "arena:8080"
    assert detail["threads"][0]["id"] == "t1"
    assert detail["inbox"] == [{"sender": "system", "intent": "seed", "trust": None,
                                "thread_id": "t1"}]
    assert client.get("/arena/agents/nobody").status_code == 404


def test_registry_proxies(setup):
    arena, client, _ = setup
    asyncio_run_setup(arena, client)
    entries = client.get("/arena/registry").json()["agents"]
    assert entries[0]["verification"]["status"] == "verified"
    card = client.get("/arena/registry/agents/northgate-soc.northgate.example/card")
    assert card.json()["name"] == "SOC Investigator"
    assert client.get("/arena/registry/agents/nobody.example/card").status_code == 404
    assert client.get("/arena/registry/orgs").json()["orgs"][0]["organization"] == \
        "Northgate Bank"


def test_registry_proxy_returns_502_when_unreachable(setup):
    arena, client, _ = setup

    async def down(path):
        from arena.acdp import AcdpError
        raise AcdpError("registry unreachable: connection refused")

    arena.ctx.acdp.registry_get = down
    response = client.get("/arena/registry")
    assert response.status_code == 502
    assert "registry unreachable" in response.json()["error"]
```

Add this helper near the top of `arena/tests/test_arena_api.py`, after the imports:

```python
def asyncio_run_setup(arena, client):
    """Run arena.setup() on the TestClient's event loop."""
    client.portal.call(arena.setup)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest arena/tests/test_arena_api.py arena/tests/test_arena_acdp.py -k "registry or detail" -v`
Expected: FAIL. `AcdpClient` has no `registry_url`, and the routes return 404.

- [ ] **Step 3: Implement**

`arena/acdp.py`: add the parameter `registry_url: str = ""` to `AcdpClient.__init__` (last), store it as `self.registry_url = registry_url.rstrip("/")`, and add:

```python
    async def registry_get(self, path: str) -> Tuple[int, Any]:
        """GET a registry path. Returns (status, json body).

        Raises:
            AcdpError: The registry cannot be reached.
        """
        async with self.http_factory() as http:
            try:
                response = await http.get(f"{self.registry_url}{path}")
            except httpx.HTTPError as e:
                raise AcdpError(f"registry unreachable: {e}") from e
        try:
            body = response.json()
        except ValueError:
            body = {"error": response.text[:200]}
        return response.status_code, body
```

Add `Tuple` to the typing import.

`arena/__main__.py`: pass `registry_url=env.get("REGISTRY_URL", "http://registry:5000")` to `AcdpClient(...)`.

`arena/tests/conftest.py`: add to `FakeAcdp`:

```python
    async def registry_get(self, path: str):
        if path == "/agents":
            return 200, {"agents": [
                {k: v for k, v in e.items() if k != "agent_card"}
                for e in self.entries.values()]}
        if path == "/orgs":
            return 200, {"orgs": sorted(self.orgs.values(),
                                        key=lambda o: o["organization"].lower())}
        if path.startswith("/agents/") and path.endswith("/card"):
            entry = self.entries.get(path[len("/agents/"):-len("/card")])
            if entry is None:
                return 404, {"error": "Agent not found"}
            return 200, entry["agent_card"]
        return 404, {"error": "not found"}
```

`arena/agent.py`: add these methods to `ArenaAgent`:

```python
    def summary(self) -> Dict[str, Any]:
        """Short view for the agent list."""
        spec = self.spec
        return {
            "id": self.agent_id, "slug": spec.slug, "name": spec.name,
            "organization": spec.organization, "domain": spec.domain,
            "capability": spec.capability, "needs": list(spec.needs),
            "model": spec.model, "role": spec.role, "state": self.state(),
            "counters": dict(self.counters), "verification": dict(self.verification),
        }

    def detail(self) -> Dict[str, Any]:
        """Full view for the agent drawer (live mode)."""
        # asyncio.Queue keeps its items in a deque; read it without draining.
        pending = list(self.inbox._queue)
        inbox = [
            {"sender": item.message.from_id, "intent": item.message.intent.value,
             "trust": item.trust.status if item.trust else None,
             "thread_id": item.message.thread_id}
            if item.message else
            {"sender": "system", "intent": "seed", "trust": None,
             "thread_id": item.thread_id}
            for item in pending
        ]
        threads = [
            {"id": t.id, "title": t.title, "owner": t.owner, "open": not t.closed,
             "count": len(t.messages)}
            for t in self.ctx.threads.for_agent(self.agent_id)
        ]
        return {
            **self.summary(),
            "system_prompt": system_prompt(self.spec),
            "last_prompt": self.last_prompt,
            "last_decision": self.last_decision,
            "decisions": list(self.decisions),
            "threads": threads,
            "inbox": inbox,
            "trust": {k: {"status": v.status, "reason": v.reason}
                      for k, v in self.trust.items()},
            "queries": list(self.queries),
            "dns": dict(self.dns),
        }
```

`arena/api.py`: add these inside `register_routes`. Add `from fastapi import HTTPException` and `from arena.acdp import AcdpError`.

```python
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
```

`test_agent_list_and_detail` expects `detail["threads"][0]["id"] == "t1"`. `t1` is the seed thread, which `setup` opens with the owner as participant, so this holds.

- [ ] **Step 4: Run tests**

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add arena/acdp.py arena/agent.py arena/api.py arena/__main__.py arena/tests/
git commit -m "feat(arena): agent detail and registry proxy read APIs"
```

---

### Task 6: Pure event store, palette, demo log, and contract test

**Files:**
- Create: `arena/ui/store.js`, `arena/ui/palette.js`, `arena/ui/tests/store.test.mjs`, `arena/ui/tests/palette.test.mjs`
- Create: `arena/scripts/make_demo_log.py`, `arena/tests/test_arena_demo_log.py`
- Modify: `arena/tests/test_arena_ui.py` (contract now checks `store.js`)

**Interfaces:**
- Produces (`store.js`):
  - `HANDLED: string[]`, `initialState()`, `apply(state, event) -> state`, `select(state, patch) -> state`.
  - Selectors `chatItems(state)` and `agentsByCompany(state)`.
  - `createStore()` returning `{get, dispatch, reset, select, setMode, subscribe}`.
  - State shape as in the code below. Later tasks read `state.agents[id]` (`steps`, `queries`, `decisions`, `trust`, `counters`, `lastPrompt`, `lastDecision`, `systemPrompt`), `state.threads`, `state.threadOrder`, `state.messages` (items of kind `message` or `system`), `state.tasks`, `state.taskByMessage`, `state.timeline`, `state.highlight`, `state.lastQuery`, and `state.selection` (`agent`, `thread`, `allThreads`, `range`, `view`, `tab`, `adding`, `allQueries`).
- Produces (`palette.js`): `COMPANY_COLORS`, `THREAD_COLORS`, `companyColor(domain)`, `threadColor(index)`, `TRUST_TOKENS`.
- Produces: `arena/scripts/make_demo_log.py [--out runs/demo.jsonl]`. It writes a scripted run with registration, discovery, decisions, messages, an impostor decline, a live injection, and a verdict. Event timestamps are spaced 2 s apart.

- [ ] **Step 1: Write the failing JS tests**

`arena/ui/tests/store.test.mjs`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { apply, chatItems, createStore, HANDLED, initialState, select } from "../store.js";

let seq = 0;
const ev = (type, data, ts = 1000 + seq) => ({ seq: seq++, ts, run_id: "r", type, data });
const agent = (id, extra = {}) => ev("agent.registered", {
  id, slug: id.split(".")[0], name: id.split(".")[0], organization: "Org " + id,
  domain: id.split(".").slice(1).join("."), capability: "cap", model: "sonnet",
  role: "investigation", did: "did", needs: [], system_prompt: "SP", ...extra,
});
const run = (events) => events.reduce((s, e) => apply(s, e), initialState());

test("registration steps are recorded and result sets status", () => {
  const s = run([
    agent("a.x.example"),
    ev("registration.step", { id: "a.x.example", step: "zone", status: "ok", detail: { zone: "x.example", result: "created" } }),
    ev("registration.step", { id: "a.x.example", step: "result", status: "failed", detail: { status: "failed", reasons: ["key mismatch"] } }),
  ]);
  const a = s.agents["a.x.example"];
  assert.equal(a.steps.zone.detail.result, "created");
  assert.equal(a.status, "failed");
  assert.deepEqual(a.reasons, ["key mismatch"]);
  assert.equal(a.systemPrompt, "SP");
  assert.equal(s.timeline.filter((t) => t.lane === "register").length, 3);
});

test("old-format discovery results are accepted", () => {
  const s = run([agent("a.x.example"), ev("discovery.query", { agent: "a.x.example", capability: "cap", results: ["b.y.example"] })]);
  const q = s.agents["a.x.example"].queries[0];
  assert.deepEqual(q.results, [{ id: "b.y.example", name: "b.y.example", organization: "", domain: "", status: "unknown", new: false }]);
  assert.equal(s.highlight, null);
  assert.equal(s.lastQuery.capability, "cap");
});

test("new discovery results set the highlight", () => {
  const s = run([agent("a.x.example"), ev("discovery.query", { agent: "a.x.example", capability: "cap",
    results: [{ id: "b.y.example", name: "B", organization: "Y", domain: "y.example", status: "verified", new: true }] })]);
  assert.equal(s.highlight.agent, "a.x.example");
});

test("duplicate seq is ignored", () => {
  const msg = ev("message.sent", { id: "m1", thread_id: "t1", from_id: "a", to_id: "b", intent: "request", body: "hi", color: 0 });
  const s = run([msg, msg]);
  assert.equal(s.messages.filter((m) => m.kind === "message").length, 1);
});

test("bus.reset enters replay mode and replayed lifecycle events keep it", () => {
  const s = run([ev("bus.reset", { run_id: "replay-x", log: "x" }), ev("arena.started", { agents: 1 }), ev("arena.stopped", { reason: "done" })]);
  assert.equal(s.mode, "replay");
  assert.equal(s.log, "x");
});

test("live lifecycle events set mode", () => {
  let s = run([ev("arena.started", { agents: 1, run_id: "r1" })]);
  assert.equal(s.mode, "live");
  s = apply(s, ev("arena.stopped", { reason: "time limit reached" }));
  assert.equal(s.mode, "stopped");
  assert.equal(s.stopReason, "time limit reached");
});

test("messages get trust from the earlier peer check and reply links", () => {
  const s = run([
    ev("thread.opened", { id: "t1", owner: "a", title: "case", color: 0 }),
    ev("verification.peer_check", { agent: "b", sender: "a", message_id: "m1", status: "verified", reason: "" }),
    ev("message.sent", { id: "m1", thread_id: "t1", from_id: "a", to_id: "b", intent: "request", body: "q", color: 0, looking_for: "x", why_this_peer: "y" }),
    ev("message.sent", { id: "m2", thread_id: "t1", from_id: "b", to_id: "a", intent: "reply", body: "r", color: 0 }),
  ]);
  const [m1, m2] = s.messages.filter((m) => m.kind === "message");
  assert.deepEqual(m1.trust, { status: "verified", reason: "" });
  assert.equal(m1.lookingFor, "x");
  assert.equal(m2.replyTo, "m1");
  assert.deepEqual(s.agents.b.trust.a, { status: "verified", reason: "" });
});

test("chat items follow the thread, all-threads, agent, and range filters", () => {
  let s = run([
    ev("thread.opened", { id: "t1", owner: "a", title: "one", color: 0 }, 1),
    ev("thread.opened", { id: "t2", owner: "c", title: "two", color: 1 }, 2),
    ev("message.sent", { id: "m1", thread_id: "t1", from_id: "a", to_id: "b", intent: "request", body: "1", color: 0, ts: 3 }, 3),
    ev("message.sent", { id: "m2", thread_id: "t2", from_id: "c", to_id: "d", intent: "request", body: "2", color: 1, ts: 4 }, 4),
  ]);
  const ids = (st) => chatItems(st).filter((m) => m.kind === "message").map((m) => m.id);
  assert.deepEqual(ids(s), ["m1"]);
  assert.equal(s.threads.t2.unread, 1);
  s = select(s, { thread: "t2" });
  assert.equal(s.threads.t2.unread, 0);
  s = select(s, { allThreads: true });
  assert.deepEqual(ids(s), ["m1", "m2"]);
  s = select(s, { agent: "d" });
  assert.deepEqual(ids(s), ["m2"]);
  s = select(s, { agent: null, range: [0, 3.5] });
  assert.deepEqual(ids(s), ["m1"]);
});

test("decisions, tasks, and unknown events", () => {
  const s = run([
    agent("a.x.example"),
    ev("decision.made", { agent: "a.x.example", prompt: "P", decision: { action: "wait" }, outcome: "wait" }),
    ev("task.created", { task_id: "k1", requester: "a", recipient: "b", message_id: "m1", thread_id: "t1" }),
    ev("task.updated", { task_id: "k1", state: "completed", artifact: "done" }),
    ev("something.new", {}),
  ]);
  const a = s.agents["a.x.example"];
  assert.equal(a.lastPrompt, "P");
  assert.equal(a.decisions.length, 1);
  assert.equal(s.tasks.k1.state, "completed");
  assert.equal(s.taskByMessage.m1, "k1");
  assert.equal(s.unknown, 1);
});

test("store notifies subscribers and reset keeps the view", () => {
  const store = createStore();
  let calls = 0;
  store.subscribe(() => { calls += 1; });
  store.select({ view: "matrix" });
  store.dispatch(ev("arena.idle", { reason: "no key" }));
  store.reset();
  assert.equal(store.get().selection.view, "matrix");
  assert.equal(store.get().mode, "connecting");
  assert.equal(calls, 3);
  assert.ok(HANDLED.includes("registration.step"));
});
```

`arena/ui/tests/palette.test.mjs`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { COMPANY_COLORS, companyColor, THREAD_COLORS, threadColor } from "../palette.js";

test("company colors are stable and from the palette", () => {
  assert.equal(companyColor("northgate.example"), companyColor("northgate.example"));
  assert.ok(COMPANY_COLORS.includes(companyColor("halcyon-inte1.example")));
});

test("thread colors wrap", () => {
  assert.equal(threadColor(THREAD_COLORS.length), THREAD_COLORS[0]);
  assert.equal(threadColor(undefined), THREAD_COLORS[0]);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `node --test "arena/ui/tests/*.test.mjs"`
Expected: FAIL with `Cannot find module '.../arena/ui/store.js'`.

- [ ] **Step 3: Implement `arena/ui/palette.js`**

```js
// Colors shared by every view. Pure: Node tests import it.
export const COMPANY_COLORS = ["#3b5bdb", "#0ca678", "#f08c00", "#7048e8", "#1098ad",
  "#e8590c", "#5c940d", "#c2255c", "#495057", "#1c7ed6"];
export const THREAD_COLORS = ["#3b5bdb", "#0ca678", "#f08c00", "#7048e8", "#1098ad",
  "#e8590c", "#5c940d", "#c2255c", "#495057", "#1c7ed6", "#9c36b5", "#2b8a3e"];
// CSS custom properties defined in style.css (light and dark).
export const TRUST_TOKENS = { verified: "--ok", pending: "--pending", failed: "--bad", unknown: "--muted" };

export function companyColor(domain) {
  let hash = 0;
  for (const ch of domain || "") hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return COMPANY_COLORS[hash % COMPANY_COLORS.length];
}

export function threadColor(index) {
  return THREAD_COLORS[(index ?? 0) % THREAD_COLORS.length];
}
```

- [ ] **Step 4: Implement `arena/ui/store.js`**

```js
// Workbench event store. Pure: no DOM, no network, no CDN imports.
// The WebSocket feeds events into apply(); components read the state.

export const HANDLED = [
  "bus.reset", "arena.started", "arena.idle", "arena.paused", "arena.resumed", "arena.stopped",
  "agent.registered", "agent.verified", "agent.verification_failed", "agent.error",
  "registration.step", "discovery.query", "decision.made", "decision.rejected",
  "thread.opened", "thread.closed", "message.sent", "message.failed",
  "verification.peer_check", "task.created", "task.updated",
];

const MAX_MESSAGES = 2000;
const MAX_TIMELINE = 4000;
const KEEP = 20;
const LANE = {
  "agent.registered": "register", "registration.step": "register",
  "discovery.query": "discover",
  "verification.peer_check": "verify", "agent.verified": "verify",
  "agent.verification_failed": "verify",
  "message.sent": "message", "message.failed": "message",
  "task.created": "message", "task.updated": "message",
};

function initialSelection() {
  return { agent: null, thread: "t1", allThreads: false, range: null, view: "network",
    tab: "overview", adding: false, allQueries: false };
}

export function initialState() {
  return {
    mode: "connecting", runId: "", log: "", stopReason: "", paused: false,
    lastSeq: -1, unknown: 0,
    agents: {}, order: [], threads: {}, threadOrder: [], messages: [],
    trustByMessage: {}, tasks: {}, taskByMessage: {}, timeline: [],
    highlight: null, lastQuery: null, selection: initialSelection(),
  };
}

function agentRecord(id) {
  return {
    id, slug: id.split(".")[0], name: id, organization: "", domain: id.split(".").slice(1).join("."),
    capability: "", needs: [], model: "", role: "", cadence: null, did: "", systemPrompt: "",
    status: "pending", reasons: [], steps: {}, trust: {}, queries: [], decisions: [],
    counters: { sent: 0, received: 0, rejected: 0, errors: 0 }, lastPrompt: "", lastDecision: null,
  };
}

function ensureAgent(state, id) {
  if (!state.agents[id]) {
    state.agents[id] = agentRecord(id);
    state.order.push(id);
  }
  return state.agents[id];
}

function keepLast(list, item, size = KEEP) {
  list.push(item);
  if (list.length > size) list.splice(0, list.length - size);
}

function system(state, event, text, threadId = null) {
  keepLast(state.messages, { kind: "system", id: `s${event.seq}`, seq: event.seq, ts: event.ts, threadId, text }, MAX_MESSAGES);
}

function laneAgent(type, d) {
  if (type === "verification.peer_check" || type === "discovery.query") return d.agent;
  if (type === "message.sent") return d.from_id;
  if (type === "message.failed") return d.from_id;
  if (type === "task.created") return d.requester;
  return d.id || d.agent || null;
}

function laneLabel(type, d) {
  switch (type) {
    case "registration.step": return `${d.id}: ${d.step} ${d.status}`;
    case "agent.registered": return `${d.name} joined`;
    case "discovery.query": return `${d.agent} searched ${d.capability}`;
    case "verification.peer_check": return `${d.agent} checked ${d.sender}: ${d.status}${d.reason ? ` (${d.reason})` : ""}`;
    case "message.sent": return `${d.from_id} → ${d.to_id} (${d.intent})`;
    case "task.created": return `task ${d.task_id} working`;
    case "task.updated": return `task ${d.task_id} ${d.state}`;
    default: return type;
  }
}

function laneFailed(type, d) {
  return d.status === "failed" || type === "agent.verification_failed" || type === "message.failed"
    || (type === "message.sent" && (d.intent === "decline" || d.intent === "challenge"));
}

function normalizeResult(r) {
  if (typeof r === "string") return { id: r, name: r, organization: "", domain: "", status: "unknown", new: false };
  return { id: r.id, name: r.name || r.id, organization: r.organization || "", domain: r.domain || "",
    status: r.status || "unknown", new: Boolean(r.new) };
}

export function apply(state, event) {
  const { type, seq, ts } = event;
  const d = event.data || {};
  if (type === "bus.reset") {
    const next = initialState();
    next.mode = "replay";
    next.log = d.log || "";
    next.lastSeq = seq;
    next.selection = { ...initialSelection(), view: state.selection.view };
    return next;
  }
  if (typeof seq === "number") {
    if (seq <= state.lastSeq) return state;
    state.lastSeq = seq;
  }
  if (!HANDLED.includes(type)) {
    state.unknown += 1;
    return state;
  }
  if (LANE[type]) {
    keepLast(state.timeline, { seq, ts, lane: LANE[type], type, agent: laneAgent(type, d),
      label: laneLabel(type, d), failed: laneFailed(type, d) }, MAX_TIMELINE);
  }
  const replay = state.mode === "replay";
  switch (type) {
    case "arena.started":
      if (!replay) state.mode = "live";
      state.runId = d.run_id || state.runId;
      break;
    case "arena.idle":
      if (!replay) state.mode = "idle";
      system(state, event, `Arena idle: ${d.reason}`);
      break;
    case "arena.paused": state.paused = true; break;
    case "arena.resumed": state.paused = false; break;
    case "arena.stopped":
      state.stopReason = d.reason || "";
      if (!replay) state.mode = "stopped";
      system(state, event, `Arena stopped: ${d.reason}`);
      break;
    case "agent.registered": {
      const a = ensureAgent(state, d.id);
      Object.assign(a, {
        slug: d.slug || a.slug, name: d.name || a.name, organization: d.organization || "",
        domain: d.domain || a.domain, capability: d.capability || "", needs: d.needs || [],
        model: d.model || "", role: d.role || "", cadence: d.cadence || null, did: d.did || "",
        systemPrompt: d.system_prompt || a.systemPrompt,
      });
      system(state, event, `${a.name} (${a.organization}, ${a.domain}) joined`);
      break;
    }
    case "registration.step": {
      const a = ensureAgent(state, d.id);
      a.steps[d.step] = { status: d.status, detail: d.detail || {}, ts };
      if (d.step === "result") {
        a.status = (d.detail || {}).status === "verified" ? "verified" : "failed";
        a.reasons = (d.detail || {}).reasons || [];
      }
      break;
    }
    case "agent.verified":
      ensureAgent(state, d.id).status = "verified";
      system(state, event, `${state.agents[d.id].name} verified by the registry`);
      break;
    case "agent.verification_failed": {
      const a = ensureAgent(state, d.id);
      a.status = "failed";
      a.reasons = d.reasons || [];
      system(state, event, `${a.name} failed verification: ${a.reasons.join("; ")}`);
      break;
    }
    case "agent.error":
      ensureAgent(state, d.id).counters.errors += 1;
      system(state, event, `${d.id} error: ${d.error}`);
      break;
    case "discovery.query": {
      const a = ensureAgent(state, d.agent);
      const query = { seq, ts, agent: d.agent, capability: d.capability, results: (d.results || []).map(normalizeResult) };
      keepLast(a.queries, query);
      state.lastQuery = query;
      if (query.results.some((r) => r.new)) state.highlight = query;
      break;
    }
    case "decision.made": {
      const a = ensureAgent(state, d.agent);
      keepLast(a.decisions, { ...d, seq, ts });
      a.lastPrompt = d.prompt || "";
      a.lastDecision = d.decision || null;
      break;
    }
    case "decision.rejected": break;
    case "thread.opened":
      state.threads[d.id] = { id: d.id, owner: d.owner, title: d.title, color: d.color,
        closed: false, reason: "", count: 0, unread: 0 };
      state.threadOrder.push(d.id);
      system(state, event, `Thread ${d.id} opened: ${d.title}`, d.id);
      break;
    case "thread.closed":
      if (state.threads[d.id]) Object.assign(state.threads[d.id], { closed: true, reason: d.reason });
      system(state, event, `Thread ${d.id} closed (${d.reason})`, d.id);
      break;
    case "verification.peer_check": {
      const trust = { status: d.status, reason: d.reason || "" };
      state.trustByMessage[d.message_id] = trust;
      ensureAgent(state, d.agent).trust[d.sender] = trust;
      const known = state.messages.find((m) => m.id === d.message_id);
      if (known) known.trust = trust;
      break;
    }
    case "message.sent": {
      const earlier = [...state.messages].reverse().find((m) => m.kind === "message"
        && m.threadId === d.thread_id && m.from === d.to_id && m.to === d.from_id);
      const message = {
        kind: "message", id: d.id, seq, ts, threadId: d.thread_id,
        from: d.from_id, to: d.to_id, intent: d.intent, body: d.body, color: d.color,
        lookingFor: d.looking_for || "", whyThisPeer: d.why_this_peer || "",
        trust: state.trustByMessage[d.id] || null, replyTo: earlier ? earlier.id : null,
      };
      keepLast(state.messages, message, MAX_MESSAGES);
      const thread = state.threads[d.thread_id];
      if (thread) {
        thread.count += 1;
        const visible = state.selection.allThreads || state.selection.thread === d.thread_id;
        if (!visible) thread.unread += 1;
      }
      ensureAgent(state, d.from_id).counters.sent += 1;
      ensureAgent(state, d.to_id).counters.received += 1;
      break;
    }
    case "message.failed":
      system(state, event, `Message ${d.from_id} → ${d.to_id} failed: ${d.error}`);
      break;
    case "task.created":
      state.tasks[d.task_id] = { id: d.task_id, requester: d.requester, recipient: d.recipient,
        messageId: d.message_id, threadId: d.thread_id, state: "working", artifact: "", reason: "" };
      state.taskByMessage[d.message_id] = d.task_id;
      break;
    case "task.updated":
      if (state.tasks[d.task_id]) Object.assign(state.tasks[d.task_id], {
        state: d.state, artifact: d.artifact || "", reason: d.reason || "" });
      break;
    default: break;
  }
  return state;
}

export function select(state, patch) {
  state.selection = { ...state.selection, ...patch };
  if (patch.thread && state.threads[patch.thread]) state.threads[patch.thread].unread = 0;
  if (patch.allThreads) for (const t of Object.values(state.threads)) t.unread = 0;
  return state;
}

export function chatItems(state) {
  const { thread, allThreads, agent, range } = state.selection;
  return state.messages.filter((m) => {
    if (range && (m.ts < range[0] || m.ts > range[1])) return false;
    if (agent) return m.kind === "message" && (m.from === agent || m.to === agent);
    if (allThreads) return true;
    return m.threadId === thread || (m.kind === "system" && m.threadId === null);
  });
}

export function agentsByCompany(state) {
  const groups = new Map();
  for (const id of state.order) {
    const a = state.agents[id];
    if (!groups.has(a.domain)) groups.set(a.domain, { domain: a.domain, organization: a.organization, agents: [] });
    groups.get(a.domain).agents.push(a);
  }
  return [...groups.values()];
}

export function createStore() {
  let state = initialState();
  const subscribers = new Set();
  const notify = () => subscribers.forEach((fn) => fn());
  return {
    get: () => state,
    dispatch(event) { state = apply(state, event); notify(); },
    reset() {
      const view = state.selection.view;
      state = initialState();
      state.selection.view = view;
      notify();
    },
    select(patch) { state = select(state, patch); notify(); },
    setMode(mode) { state.mode = mode; notify(); },
    subscribe(fn) { subscribers.add(fn); return () => subscribers.delete(fn); },
  };
}
```

- [ ] **Step 5: Run the JS tests**

Run: `node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS (12 tests).

- [ ] **Step 6: Contract test and demo log**

Replace `test_app_handles_every_event_type` and the `EVENT_TYPES` list in `arena/tests/test_arena_ui.py` with the code below. Put `import re` with the other imports at the top of the file.

```python
ARENA = Path(__file__).resolve().parents[1]


def emitted_event_types():
    """Every event type the runtime publishes, read from the source."""
    found = set()
    for path in ARENA.glob("*.py"):
        found.update(re.findall(r'publish\(\s*"([a-z_]+\.[a-z_]+)"', path.read_text()))
    return found


def test_store_handles_every_emitted_event_type():
    source = (UI / "store.js").read_text()
    handled = set(re.findall(r'"([a-z_]+\.[a-z_]+)"', source.split("];", 1)[0]))
    emitted = emitted_event_types()
    assert "registration.step" in emitted and "bus.reset" in emitted
    assert emitted - handled == set()
```

Keep `test_ui_files_are_served` unchanged for now. Task 7 rewrites it.

Create `arena/scripts/make_demo_log.py`:

```python
"""Write a scripted arena run to a JSONL log for UI work (no model, no network).

    PYTHONPATH=agent:. python arena/scripts/make_demo_log.py --out runs/demo.jsonl

The run uses the test doubles from arena/tests/conftest.py: an in-memory
registry and DNS, scripted models, and real A2A between agents in one process.
"""

import argparse
import asyncio
import itertools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from conftest import IMPOSTOR, INTEL, ISAC, SOC, make_arena, make_cast, spec_dict  # noqa: E402

from arena.cast import AgentSpec  # noqa: E402

SOC_ID = "northgate-soc.northgate.example"
INTEL_ID = "halcyon-intel.halcyon-intel.example"
FAKE_ID = "lookalike-intel.halcyon-inte1.example"


def case_thread(prompt: str) -> str:
    match = re.search(r"^- (t\d+) Phishing case \(owner", prompt, re.MULTILINE)
    return match.group(1) if match else "new"


def send(prompt, to, intent, body, looking_for="", why=""):
    return {"action": "send", "to": to, "thread_id": case_thread(prompt), "intent": intent,
            "body": body, "looking_for": looking_for, "why_this_peer": why}


def soc(prompt):
    if "trust=failed (domain mismatch)" in prompt:
        return send(prompt, FAKE_ID, "decline", "Your domain does not match Halcyon Intel.",
                    "nothing", "sender failed verification: domain mismatch")
    return send(prompt, INTEL_ID, "request",
                "Do invoices-northgate.example and secure-docs-share.example match a campaign?",
                "campaign attribution for two sender domains",
                "only verified threat-intel peer; the lookalike failed registry checks")


SCRIPTS = {
    "northgate-soc": soc,
    "halcyon-intel": lambda p: send(p, SOC_ID, "share", "Both domains overlap with the InvoiceDrop kit."),
    "lookalike-intel": lambda p: send(p, SOC_ID, "share", "Copy me on your findings."),
    "finshare-isac": lambda p: send(p, SOC_ID, "verdict", "Credential phishing. Revoke tokens and consent."),
}


async def scripted_run(arena) -> None:
    await arena.setup()
    arena.ctx.running.set()
    a = arena.agents
    for slug in ("northgate-soc", "halcyon-intel", "lookalike-intel", "northgate-soc"):
        await a[slug].tick()
    await arena.add_agent(AgentSpec.from_dict(spec_dict(
        slug="northwind-intel", name="Northwind Intel", organization="Northwind Threat Labs",
        domain="northwind.example", capability="threat-intel", needs=[], model="haiku",
        role="agenda", cadence=[40, 60])))
    for slug in ("northgate-soc", "finshare-isac"):
        await a[slug].tick()
    arena.bus.publish("arena.stopped", {"reason": "demo complete"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("runs/demo.jsonl"))
    args = parser.parse_args()
    arena = make_arena(make_cast(SOC, INTEL, ISAC, IMPOSTOR,
                                 owner="northgate-soc", closer="finshare-isac"), SCRIPTS)
    ticks = itertools.count()
    arena.bus.clock = lambda: 1_790_000_000.0 + 2.0 * next(ticks)
    asyncio.run(scripted_run(arena))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(e) + "\n" for e in arena.bus.history))
    print(f"wrote {len(arena.bus.history)} events to {args.out}")


if __name__ == "__main__":
    main()
```

Create `arena/tests/test_arena_demo_log.py`:

```python
"""The demo log script produces every event family the Workbench shows."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_demo_log_contains_the_workbench_event_families(tmp_path):
    out = tmp_path / "demo.jsonl"
    env = dict(os.environ, PYTHONPATH=f"{ROOT / 'agent'}{os.pathsep}{ROOT}")
    env.pop("ANTHROPIC_API_KEY", None)
    subprocess.run([sys.executable, str(ROOT / "arena/scripts/make_demo_log.py"), "--out", str(out)],
                   check=True, env=env, cwd=ROOT)
    events = [json.loads(line) for line in out.read_text().splitlines()]
    types = {e["type"] for e in events}
    assert {"registration.step", "discovery.query", "decision.made", "message.sent",
            "verification.peer_check", "thread.closed", "arena.stopped"} <= types
    gaps = {round(b["ts"] - a["ts"], 3) for a, b in zip(events, events[1:])}
    assert gaps == {2.0}
```

- [ ] **Step 7: Run all tests**

Run: `pytest -v && node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS. If the contract test finds an event type that is not in `HANDLED`, add it to `HANDLED` with a `case` in `apply`. Do not weaken the test.

- [ ] **Step 8: Commit**

```bash
git add arena/ui/store.js arena/ui/palette.js arena/ui/tests arena/scripts/make_demo_log.py \
  arena/tests/test_arena_demo_log.py arena/tests/test_arena_ui.py
git commit -m "feat(arena-ui): pure event store, palette, demo log, and event contract test"
```

---

### Task 7: Workbench shell

**Files:**
- Create: `arena/ui/preact.js`, `arena/ui/api.js`, `arena/ui/app.js` (replaces the old file), `arena/ui/index.html` (replaces), `arena/ui/style.css` (replaces)
- Create: `arena/ui/components/topbar.js`, `sidebar.js`, `viewswitch.js`, `legend.js`, `addagent.js`, `chat.js` (minimal; Task 11 replaces it)
- Create: `arena/ui/views/network.js` (port of today's graph; Task 13 extends it)
- Delete: `arena/ui/graph.js`, `arena/ui/transcript.js`, `arena/ui/controls.js`
- Modify: `arena/tests/test_arena_ui.py` (`test_ui_files_are_served`)

**Interfaces:**
- Consumes: `createStore`, `chatItems`, `agentsByCompany` (Task 6), `companyColor`, `threadColor`, `TRUST_TOKENS`.
- Produces:
  - `api.js`: `getJson(path)` and `postJson(path, body)`. Both throw `Error(message)` on a non-2xx response.
  - `app.js`: `VIEWS` (`{key: [label, Component]}`), `RIGHT` (the right-column component chooser), and `ROOT` (`#root`).
  - Every component receives `{store, state}` props.

- [ ] **Step 1: Write the failing test** (replace `test_ui_files_are_served` in `arena/tests/test_arena_ui.py`)

```python
UI_FILES = ["preact.js", "api.js", "app.js", "store.js", "palette.js", "style.css",
            "components/topbar.js", "components/sidebar.js", "components/viewswitch.js",
            "components/legend.js", "components/addagent.js", "components/chat.js",
            "views/network.js"]


def test_ui_files_are_served(tmp_path):
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"))
    register_routes(arena, UI, tmp_path)
    client = TestClient(arena.app)
    index = client.get("/").text
    for url in ("cdn.jsdelivr.net/npm/force-graph@1", "cdn.jsdelivr.net/npm/@dagrejs/dagre@1"):
        assert url in index
    assert 'import("/ui/app.js")' in index
    assert "htm@3/preact/standalone.module.js" in (UI / "preact.js").read_text()
    for name in UI_FILES:
        assert client.get(f"/ui/{name}").status_code == 200, name
    for old in ("graph.js", "transcript.js", "controls.js"):
        assert not (UI / old).exists(), old
```

Run: `pytest arena/tests/test_arena_ui.py -v`
Expected: FAIL (`dagre` is not in the index).

- [ ] **Step 2: Write `arena/ui/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ACDP Arena Workbench</title>
  <link rel="stylesheet" href="/ui/style.css">
  <script src="https://cdn.jsdelivr.net/npm/force-graph@1/dist/force-graph.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@dagrejs/dagre@1/dist/dagre.min.js"></script>
</head>
<body>
  <div id="root"></div>
  <div id="boot-error" class="boot-error" hidden></div>
  <script type="module">
    const fail = (what) => {
      const box = document.getElementById("boot-error");
      box.textContent = `The Workbench could not load ${what}. Check access to cdn.jsdelivr.net, then reload.`;
      box.hidden = false;
    };
    if (typeof ForceGraph === "undefined") fail("force-graph");
    else if (typeof dagre === "undefined") fail("dagre");
    else import("/ui/app.js").catch((e) => fail(`the UI modules (${e.message})`));
  </script>
</body>
</html>
```

- [ ] **Step 3: Write `arena/ui/preact.js` and `arena/ui/api.js`**

`preact.js`:

```js
// The only module that imports Preact and htm from the CDN.
export {
  html, render, useState, useEffect, useMemo, useRef, useCallback,
} from "https://cdn.jsdelivr.net/npm/htm@3/preact/standalone.module.js";
```

`api.js`:

```js
// Small fetch helpers. Errors carry the server's message.
async function parse(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.error || (body.detail && JSON.stringify(body.detail)) || response.status;
    throw new Error(String(detail));
  }
  return body;
}

export async function getJson(path) {
  return parse(await fetch(path, { cache: "no-store" }));
}

export async function postJson(path, body) {
  return parse(await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  }));
}
```

- [ ] **Step 4: Write `arena/ui/style.css`**

```css
:root {
  --bg: #f7f7f5; --panel: #ffffff; --panel-2: #f1f1ee; --text: #1d1d1b; --muted: #6b6b66;
  --line: #e2e2dc; --ok: #2f9e44; --pending: #e8a317; --bad: #d6336c; --accent: #3b5bdb;
  --search: #7048e8; --left-w: 230px; --right-w: 440px;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #141413; --panel: #1e1e1c; --panel-2: #262623; --text: #ececea; --muted: #9a9a94;
    --line: #33332f; --ok: #51cf66; --pending: #fcc419; --bad: #f06595; --accent: #748ffc;
    --search: #9775fa;
  }
}
:root[data-theme="dark"] {
  --bg: #141413; --panel: #1e1e1c; --panel-2: #262623; --text: #ececea; --muted: #9a9a94;
  --line: #33332f; --ok: #51cf66; --pending: #fcc419; --bad: #f06595; --accent: #748ffc;
  --search: #9775fa;
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; }
body { font: 13px/1.45 system-ui, sans-serif; background: var(--bg); color: var(--text); }
button, select, input, textarea { font: inherit; color: inherit; background: var(--panel);
  border: 1px solid var(--line); border-radius: 6px; padding: 3px 8px; }
button:disabled { opacity: .5; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button.link { border: 0; background: none; color: var(--accent); padding: 0; cursor: pointer; }
.muted { color: var(--muted); }
.spacer { flex: 1; }
.chip { padding: 1px 8px; border-radius: 10px; background: var(--panel-2); font-size: 12px; }
.boot-error { position: fixed; inset: 40% 20% auto; padding: 16px; background: var(--panel);
  border: 2px solid var(--bad); border-radius: 8px; }
pre { white-space: pre-wrap; word-break: break-word; background: var(--panel-2);
  padding: 8px; border-radius: 6px; font-size: 12px; max-height: 360px; overflow: auto; }

.wb { display: grid; grid-template-rows: auto 1fr auto; height: 100vh; }
.topbar { display: flex; gap: 8px; align-items: center; padding: 6px 12px; flex-wrap: wrap;
  background: var(--panel); border-bottom: 1px solid var(--line); }
.wb-body { display: grid; grid-template-columns: var(--left-w) 1fr 5px var(--right-w); min-height: 0; }
.splitter { cursor: col-resize; background: var(--line); }
.sidebar { overflow: auto; padding: 8px; background: var(--panel); border-right: 1px solid var(--line); }
.sidebar h3 { margin: 8px 0 4px; font-size: 12px; text-transform: uppercase; color: var(--muted); }
.company { margin-bottom: 8px; }
.company-name { font-weight: 600; border-left: 4px solid; padding-left: 6px; }
.agent-row { display: flex; gap: 6px; align-items: center; width: 100%; text-align: left;
  border: 0; background: none; padding: 3px 6px; border-radius: 6px; cursor: pointer; }
.agent-row.selected, .agent-row:hover { background: var(--panel-2); }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--pending); flex: none; }
.dot.verified { background: var(--ok); } .dot.failed { background: var(--bad); }
.badge { font-size: 10px; font-weight: 700; border: 1px solid var(--line); border-radius: 4px; padding: 0 3px; }
.wb-center { display: grid; grid-template-rows: auto 1fr 130px; min-width: 0; min-height: 0; position: relative; }
.viewswitch { display: flex; gap: 4px; padding: 6px 8px; border-bottom: 1px solid var(--line); background: var(--panel); }
.viewswitch button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.view { position: relative; min-height: 0; overflow: hidden; }
.view.scroll { overflow: auto; }
.timeline-slot { border-top: 1px solid var(--line); background: var(--panel); min-height: 0; }
.legend { position: absolute; left: 8px; bottom: 138px; background: var(--panel);
  border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; font-size: 12px; z-index: 2; }
.legend summary { cursor: pointer; }
.legend .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
.right { min-width: 0; min-height: 0; display: flex; flex-direction: column; background: var(--panel);
  border-left: 1px solid var(--line); }
.debug { font-size: 11px; color: var(--muted); padding: 2px 12px; }
dialog { border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--text);
  width: min(480px, calc(100vw - 32px)); }
dialog form { display: flex; flex-direction: column; gap: 8px; }
dialog label { display: flex; flex-direction: column; gap: 2px; }
dialog .actions { display: flex; justify-content: flex-end; gap: 8px; }
.error { color: var(--bad); }
```

Tasks 8–11 append their own style blocks to this file.

- [ ] **Step 5: Write `arena/ui/app.js`**

```js
// Workbench layout and the event stream.
import { html, render, useEffect, useState } from "./preact.js";
import { createStore } from "./store.js";
import { Topbar } from "./components/topbar.js";
import { Sidebar } from "./components/sidebar.js";
import { ViewSwitch } from "./components/viewswitch.js";
import { Legend } from "./components/legend.js";
import { AddAgent } from "./components/addagent.js";
import { Chat } from "./components/chat.js";
import { NetworkView } from "./views/network.js";

const store = createStore();

// Tasks 10, 13, 14, and 15 add entries.
export const VIEWS = { network: ["Network", NetworkView] };

// Task 9 shows the drawer when an agent is selected.
export function RIGHT(state) {
  return Chat;
}

// Task 8 replaces this with the timeline.
export function TIMELINE() {
  return null;
}

function useStoreState() {
  const [, setTick] = useState(0);
  useEffect(() => {
    let frame = 0;
    return store.subscribe(() => {
      if (frame) return;
      frame = requestAnimationFrame(() => { frame = 0; setTick((n) => n + 1); });
    });
  }, []);
  return store.get();
}

function Splitter() {
  const start = (event) => {
    const body = event.currentTarget.parentElement;
    const move = (e) => {
      const width = Math.min(800, Math.max(300, body.getBoundingClientRect().right - e.clientX));
      body.style.setProperty("--right-w", `${width}px`);
    };
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };
  return html`<div class="splitter" onMouseDown=${start}></div>`;
}

function App() {
  const state = useStoreState();
  const view = VIEWS[state.selection.view] || VIEWS.network;
  const View = view[1];
  const Right = RIGHT(state);
  const Timeline = TIMELINE();
  return html`<div class="wb">
    <${Topbar} store=${store} state=${state} />
    <div class="wb-body">
      <${Sidebar} store=${store} state=${state} />
      <main class="wb-center">
        <${ViewSwitch} store=${store} state=${state} views=${VIEWS} />
        <div class="view"><${View} store=${store} state=${state} /></div>
        <div class="timeline-slot">${Timeline ? html`<${Timeline} store=${store} state=${state} />` : null}</div>
        <${Legend} />
      </main>
      <${Splitter} />
      <aside class="right"><${Right} store=${store} state=${state} /></aside>
    </div>
    <div class="debug">${state.unknown ? `${state.unknown} unknown events ignored` : ""}</div>
    <${AddAgent} store=${store} state=${state} />
  </div>`;
}

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws`);
  socket.onopen = () => store.reset();
  socket.onmessage = (message) => store.dispatch(JSON.parse(message.data));
  socket.onclose = () => { store.setMode("reconnecting"); setTimeout(connect, 2000); };
}

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") store.select({ agent: null, range: null, adding: false });
});

render(html`<${App} />`, document.getElementById("root"));
connect();
```

- [ ] **Step 6: Write the shell components**

`components/topbar.js`:

```js
import { html, useEffect, useState } from "../preact.js";
import { getJson, postJson } from "../api.js";

function modeLabel(state) {
  if (state.mode === "replay") return `replay ${state.log}`;
  if (state.mode === "live") return state.paused ? "live · paused" : "live";
  if (state.mode === "stopped") return `stopped: ${state.stopReason}`;
  return state.mode;
}

export function Topbar({ store, state }) {
  const [logs, setLogs] = useState([]);
  const [log, setLog] = useState("");
  const [speed, setSpeed] = useState(2);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    getJson("/arena/logs").then((d) => { setLogs(d.logs); setLog((cur) => cur || d.logs[0] || ""); })
      .catch(() => setLogs([]));
  }, [state.mode]);
  const messages = state.messages.filter((m) => m.kind === "message").length;
  const open = Object.values(state.threads).filter((t) => !t.closed).length;
  const pause = () => postJson(state.paused ? "/arena/resume" : "/arena/pause").catch((e) => setError(e.message));
  const replay = async () => {
    setBusy(true);
    setError("");
    try { await postJson("/arena/replay", { log, speed }); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  return html`<header class="topbar">
    <strong>ACDP Arena Workbench</strong>
    <span class="chip">${modeLabel(state)}</span>
    <span class="muted">${state.order.length} agents · ${messages} messages · ${open} open threads</span>
    ${error ? html`<span class="error">${error}</span>` : null}
    <span class="spacer"></span>
    <button onClick=${pause} disabled=${state.mode !== "live"}>${state.paused ? "Resume" : "Pause"}</button>
    <select value=${log} onChange=${(e) => setLog(e.target.value)} aria-label="Saved run">
      ${logs.map((name) => html`<option value=${name}>${name}</option>`)}
    </select>
    <label class="muted">Speed <input type="range" min="1" max="10" value=${speed}
      onInput=${(e) => setSpeed(Number(e.target.value))} /></label>
    <button onClick=${replay} disabled=${!log || busy}>Replay</button>
    <button class="primary" onClick=${() => store.select({ adding: true })}>+ Agent</button>
  </header>`;
}
```

`components/sidebar.js`:

```js
import { html } from "../preact.js";
import { agentsByCompany } from "../store.js";
import { companyColor } from "../palette.js";

export function Sidebar({ store, state }) {
  const all = Object.values(state.agents);
  const verified = all.filter((a) => a.status === "verified").length;
  const failed = all.filter((a) => a.status === "failed").length;
  return html`<nav class="sidebar">
    <h3>Agents</h3>
    ${agentsByCompany(state).map((group) => html`<div class="company">
      <div class="company-name" style=${`border-color:${companyColor(group.domain)}`}>
        ${group.organization}<div class="muted">${group.domain}</div>
      </div>
      ${group.agents.map((a) => html`<button
          class=${`agent-row${state.selection.agent === a.id ? " selected" : ""}`}
          onClick=${() => store.select({ agent: a.id, tab: "overview" })}>
        <span class=${`dot ${a.status}`}></span>
        <span class="badge">${a.model === "sonnet" ? "S" : "H"}</span>
        <span>${a.name}</span>
      </button>`)}
    </div>`)}
    <h3>Registry</h3>
    <button class="link" onClick=${() => store.select({ view: "registry" })}>
      ${all.length} entries · ${verified} verified · ${failed} failed
    </button>
  </nav>`;
}
```

`components/viewswitch.js`:

```js
import { html } from "../preact.js";

export function ViewSwitch({ store, state, views }) {
  return html`<div class="viewswitch">
    ${Object.entries(views).map(([key, [label]]) => html`<button
      class=${state.selection.view === key ? "on" : ""}
      onClick=${() => store.select({ view: key })}>${label}</button>`)}
    <span class="spacer"></span>
    ${state.selection.range ? html`<button onClick=${() => store.select({ range: null })}>Clear time range</button>` : null}
  </div>`;
}
```

`components/legend.js`:

```js
import { html } from "../preact.js";

export function Legend() {
  return html`<details class="legend">
    <summary>Legend</summary>
    <div><span class="swatch" style="background:var(--ok)"></span>verified</div>
    <div><span class="swatch" style="background:var(--pending)"></span>pending</div>
    <div><span class="swatch" style="background:var(--bad)"></span>failed / decline / challenge</div>
    <div><span class="swatch" style="background:var(--search)"></span>discovery search</div>
    <div><span class="badge">S</span> Sonnet · <span class="badge">H</span> Haiku</div>
    <div class="muted">Edge color = thread · width = messages</div>
  </details>`;
}
```

`components/addagent.js`:

```js
import { html, useEffect, useRef, useState } from "../preact.js";
import { postJson } from "../api.js";

export function AddAgent({ store, state }) {
  const dialog = useRef(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const el = dialog.current;
    if (state.selection.adding && !el.open) { setError(""); el.showModal(); }
    if (!state.selection.adding && el.open) el.close();
  }, [state.selection.adding]);
  const submit = async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    const body = { ...data, generate: data.generate === "on",
      needs: (data.needs || "").split(",").map((s) => s.trim()).filter(Boolean) };
    setBusy(true);
    try {
      await postJson("/arena/agents", body);
      event.currentTarget.reset();
      store.select({ adding: false });
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  return html`<dialog ref=${dialog} onClose=${() => store.select({ adding: false })}>
    <form onSubmit=${submit}>
      <h2>Add agent</h2>
      <label>Name <input name="name" required maxlength="60" /></label>
      <label>Organization <input name="organization" required maxlength="80" /></label>
      <label>Domain <input name="domain" required placeholder="coastal-bank.example" /></label>
      <label>Capability <input name="capability" required pattern="[a-z0-9-]{1,40}" /></label>
      <label>Needs (comma-separated) <input name="needs" placeholder="soc-investigation" /></label>
      <label>Model <select name="model"><option value="haiku">Haiku</option><option value="sonnet">Sonnet</option></select></label>
      <label>Agenda <textarea name="agenda" rows="3" maxlength="1000"></textarea></label>
      <label><input type="checkbox" name="generate" /> Generate prompt with Sonnet</label>
      <label>Misconfigure <select name="misconfigure">
        <option value="none">None</option><option value="no_txt">Missing TXT record</option>
        <option value="wrong_key">Wrong key in DNS</option></select></label>
      <p class="error" role="alert">${error}</p>
      <div class="actions">
        <button type="button" onClick=${() => store.select({ adding: false })}>Cancel</button>
        <button type="submit" class="primary" disabled=${busy}>${busy ? "Adding…" : "Add"}</button>
      </div>
    </form>
  </dialog>`;
}
```

`components/chat.js` (minimal; Task 11 replaces it):

```js
import { html } from "../preact.js";
import { chatItems } from "../store.js";

export function Chat({ state }) {
  const name = (id) => state.agents[id]?.name || id;
  return html`<div class="view scroll" style="padding:8px">
    ${chatItems(state).map((m) => m.kind === "system"
      ? html`<div class="muted">${m.text}</div>`
      : html`<div><strong>${name(m.from)} → ${name(m.to)}</strong> <span class="chip">${m.intent}</span><div>${m.body}</div></div>`)}
  </div>`;
}
```

- [ ] **Step 7: Write `arena/ui/views/network.js`** (port of today's graph; Task 13 extends it)

```js
// Network view: force-directed graph clustered by domain.
import { html, useEffect, useRef } from "../preact.js";
import { companyColor, threadColor, TRUST_TOKENS } from "../palette.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function createNetwork(el, onSelect) {
  const nodes = new Map();
  const links = new Map();
  let lastMessageSeq = -1;
  const graph = ForceGraph()(el)
    .nodeId("id")
    .nodeLabel((n) => `${n.name} — ${n.organization} (${n.domain})`)
    .nodeCanvasObject((n, ctx, scale) => {
      ctx.beginPath(); ctx.arc(n.x, n.y, 7, 0, 2 * Math.PI);
      ctx.fillStyle = css("--panel"); ctx.fill();
      ctx.lineWidth = 2.5; ctx.strokeStyle = css(TRUST_TOKENS[n.status] || "--pending"); ctx.stroke();
      ctx.fillStyle = css("--text"); ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.font = `bold ${10 / scale}px system-ui`;
      ctx.fillText(n.model === "sonnet" ? "S" : "H", n.x, n.y);
      ctx.font = `${10 / scale}px system-ui`;
      ctx.fillText(n.name, n.x, n.y + 7 + 9 / scale);
    })
    .linkColor((l) => l.color)
    .linkWidth((l) => Math.min(6, 1 + l.count / 2))
    .linkDirectionalParticleColor((l) => l.color)
    .linkDirectionalParticleWidth(4)
    .onNodeClick((n) => onSelect(n.id))
    .cooldownTicks(120)
    .onEngineStop(() => graph.zoomToFit(400, 60));
  graph.d3Force("charge").strength(-260);
  const fit = () => graph.width(el.clientWidth).height(el.clientHeight);
  const observer = new ResizeObserver(fit);
  observer.observe(el);
  fit();

  function update(state) {
    let changed = false;
    for (const id of state.order) {
      const a = state.agents[id];
      if (!nodes.has(id)) { nodes.set(id, { id }); changed = true; }
      Object.assign(nodes.get(id), { name: a.name, organization: a.organization,
        domain: a.domain, model: a.model, status: a.status });
    }
    const fresh = [];
    for (const m of state.messages) {
      if (m.kind !== "message" || m.seq <= lastMessageSeq) continue;
      lastMessageSeq = m.seq;
      if (!nodes.has(m.from) || !nodes.has(m.to)) continue;
      const key = `${m.from}>${m.to}`;
      if (!links.has(key)) { links.set(key, { source: m.from, target: m.to, count: 0 }); changed = true; }
      const link = links.get(key);
      link.count += 1;
      const critical = m.intent === "decline" || m.intent === "challenge";
      link.color = critical ? css("--bad") : threadColor(m.color);
      fresh.push(link);
    }
    // A particle needs its link in the graph data, so update the data first.
    if (changed) graph.graphData({ nodes: [...nodes.values()], links: [...links.values()] });
    fresh.forEach((link) => graph.emitParticle(link));
  }

  return { graph, update, destroy() { observer.disconnect(); graph._destructor?.(); } };
}

export function NetworkView({ store, state }) {
  const el = useRef(null);
  const net = useRef(null);
  useEffect(() => {
    net.current = createNetwork(el.current, (id) => store.select({ agent: id, tab: "overview" }));
    return () => net.current.destroy();
  }, []);
  useEffect(() => { net.current.update(state); });
  return html`<div style="position:absolute;inset:0" ref=${el}></div>`;
}
```

- [ ] **Step 8: Remove the old files and run the tests**

```bash
git rm arena/ui/graph.js arena/ui/transcript.js arena/ui/controls.js
```

Run: `pytest arena/tests/test_arena_ui.py -v && node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS.

- [ ] **Step 9: Manual check against the demo log**

```bash
PYTHONPATH=agent:. python arena/scripts/make_demo_log.py --out runs/demo.jsonl
env -u ANTHROPIC_API_KEY PYTHONPATH=agent:. ARENA_RUNS_DIR=runs python -m arena
```

Open `http://localhost:8080`, select `demo`, and click Replay. Check:
- The mode chip reads `replay demo`.
- The sidebar groups agents by company, and the impostor dot is red.
- The network shows nodes and edges, and clicking a node selects it in the sidebar.
- The chat lists the messages.
- `+ Agent` opens the dialog, and Esc closes it.
- There are no errors in the browser console.

Stop the server.

- [ ] **Step 10: Commit**

```bash
git add arena/ui arena/tests/test_arena_ui.py
git commit -m "feat(arena-ui): Workbench shell with Preact, sidebar, view switch, and network port"
```

---

### Task 8: Timeline strip

**Files:**
- Create: `arena/ui/lib/layout.js` (starts with `scaleTime`), `arena/ui/tests/layout.test.mjs`, `arena/ui/components/timeline.js`
- Modify: `arena/ui/app.js` (`TIMELINE`), `arena/ui/style.css` (append), `arena/tests/test_arena_ui.py` (`UI_FILES`)

**Interfaces:**
- Produces: `scaleTime(t0, t1, width) -> {x(ts), t(x)}`. `x` maps a time to pixels; `t` inverts it. When `t1 == t0`, every `x` is `width / 2`.
- Produces: the `Timeline` component. Clicking a dot calls `store.select({agent, tab})`, and the tab depends on the lane. Dragging calls `store.select({range: [t0, t1]})`.

- [ ] **Step 1: Write the failing test**

`arena/ui/tests/layout.test.mjs`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { scaleTime } from "../lib/layout.js";

test("scaleTime maps and inverts", () => {
  const s = scaleTime(100, 200, 1000);
  assert.equal(s.x(150), 500);
  assert.equal(s.t(250), 125);
});

test("scaleTime handles a single instant", () => {
  assert.equal(scaleTime(5, 5, 800).x(5), 400);
});
```

Run: `node --test "arena/ui/tests/*.test.mjs"`
Expected: FAIL (`lib/layout.js` missing).

- [ ] **Step 2: Implement `arena/ui/lib/layout.js`**

```js
// Pure layout helpers shared by the views. Node tests import this module.

export function scaleTime(t0, t1, width) {
  const span = t1 - t0;
  if (span <= 0) return { x: () => width / 2, t: () => t0 };
  return { x: (ts) => ((ts - t0) / span) * width, t: (x) => t0 + (x / width) * span };
}
```

- [ ] **Step 3: Implement `arena/ui/components/timeline.js`**

```js
import { html, useRef, useState } from "../preact.js";
import { scaleTime } from "../lib/layout.js";

const LANES = [["register", "Register"], ["discover", "Discover"], ["verify", "Verify"], ["message", "Message"]];
const TAB_FOR_LANE = { register: "overview", discover: "discovery", verify: "discovery", message: "activity" };
const LEFT = 70;
const LANE_H = 26;

export function Timeline({ store, state }) {
  const svg = useRef(null);
  const [drag, setDrag] = useState(null);
  const items = state.timeline;
  const width = Math.max(200, (svg.current?.clientWidth || 800) - LEFT - 10);
  const t0 = items.length ? items[0].ts : 0;
  const t1 = items.length ? items[items.length - 1].ts : 1;
  const scale = scaleTime(t0, t1, width);
  const range = state.selection.range;
  const localX = (e) => e.clientX - svg.current.getBoundingClientRect().left - LEFT;
  const down = (e) => setDrag({ from: localX(e), to: localX(e) });
  const move = (e) => drag && setDrag({ ...drag, to: localX(e) });
  const up = () => {
    if (drag && Math.abs(drag.to - drag.from) > 4) {
      const a = scale.t(Math.min(drag.from, drag.to));
      const b = scale.t(Math.max(drag.from, drag.to));
      store.select({ range: [a, b] });
    }
    setDrag(null);
  };
  return html`<svg class="timeline" ref=${svg} onMouseDown=${down} onMouseMove=${move} onMouseUp=${up}>
    ${LANES.map(([lane, label], i) => html`<g>
      <text x="6" y=${i * LANE_H + 18} class="lane-label">${label}</text>
      <line x1=${LEFT} x2=${LEFT + width} y1=${i * LANE_H + 14} y2=${i * LANE_H + 14} class="lane-line" />
    </g>`)}
    ${range ? html`<rect class="range" x=${LEFT + scale.x(range[0])} y="0"
      width=${Math.max(2, scale.x(range[1]) - scale.x(range[0]))} height=${LANES.length * LANE_H} />` : null}
    ${drag ? html`<rect class="range" x=${LEFT + Math.min(drag.from, drag.to)} y="0"
      width=${Math.abs(drag.to - drag.from)} height=${LANES.length * LANE_H} />` : null}
    ${items.map((it) => {
      const lane = LANES.findIndex(([key]) => key === it.lane);
      const selected = it.agent && it.agent === state.selection.agent;
      return html`<circle cx=${LEFT + scale.x(it.ts)} cy=${lane * LANE_H + 14} r=${selected ? 5 : 3.5}
        class=${`tl-dot ${it.lane}${it.failed ? " failed" : ""}${selected ? " selected" : ""}`}
        onMouseDown=${(e) => e.stopPropagation()}
        onClick=${() => it.agent && store.select({ agent: it.agent, tab: TAB_FOR_LANE[it.lane] })}>
        <title>${it.label}</title></circle>`;
    })}
  </svg>`;
}
```

Append to `style.css`:

```css
.timeline { width: 100%; height: 100%; display: block; user-select: none; }
.lane-label { font-size: 11px; fill: var(--muted); }
.lane-line { stroke: var(--line); }
.tl-dot { cursor: pointer; }
.tl-dot.register { fill: var(--ok); } .tl-dot.discover { fill: var(--search); }
.tl-dot.verify { fill: var(--ok); } .tl-dot.message { fill: var(--accent); }
.tl-dot.failed { fill: var(--bad); } .tl-dot.selected { stroke: var(--text); stroke-width: 1.5; }
.range { fill: var(--accent); opacity: .12; }
```

In `app.js`, add `import { Timeline } from "./components/timeline.js";` and change `TIMELINE` to `return Timeline;`. Add `"components/timeline.js"` and `"lib/layout.js"` to `UI_FILES` in `test_arena_ui.py`.

- [ ] **Step 4: Run tests**

Run: `pytest arena/tests/test_arena_ui.py -v && node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS.

- [ ] **Step 5: Manual check (demo replay)**

Check:
- Dots appear in four lanes, and the impostor's registration result dot is red.
- Hovering a dot shows its label. Clicking a dot selects the agent.
- Dragging across a span shows a shaded range, filters the chat, and shows "Clear time range". Clicking that clears the range.

- [ ] **Step 6: Commit**

```bash
git add arena/ui arena/tests/test_arena_ui.py
git commit -m "feat(arena-ui): timeline strip with lanes, selection, and time range"
```

---

### Task 9: Agent drawer

**Files:**
- Create: `arena/ui/components/drawer.js`, `arena/ui/components/steps.js`
- Modify: `arena/ui/app.js` (`RIGHT`), `arena/ui/style.css` (append), `arena/tests/test_arena_ui.py` (`UI_FILES`)

**Interfaces:**
- Consumes: `GET /arena/agents/{slug}` (Task 5) in live mode, the live card at `/agents/{slug}/.well-known/agent-card.json`, and `GET /arena/registry/agents/{id}/card` as the fallback.
- Produces:
  - `Drawer` (tabs `overview`, `card`, `prompts`, `activity`, `discovery`).
  - `Stepper({agent})` and `STEP_LABELS` in `steps.js`. The registry browser (Task 10) reuses the check rendering through `Checks({verification})`.
  - `extensionParams(card)` in `drawer.js`. Task 10 reuses it.

- [ ] **Step 1: Write `components/steps.js`**

```js
import { html } from "../preact.js";

export const STEP_LABELS = [
  ["identity", "Identity minted"], ["zone", "Zone ready"], ["dns", "DNS published"],
  ["card", "Agent Card served"], ["submitted", "Submitted to registry"],
  ["checks", "Registry checks"], ["result", "Result"],
];

const mark = (ok) => (ok ? "✓" : "✕");

export function Checks({ verification }) {
  if (!verification) return null;
  const v = verification;
  const rows = [
    ["card re-fetched", v.card_fetched], ["TXT record found", v.dns_found],
    ["key matches DNS", v.key_matches_dns],
    ["organization anchor", v.org_conflict === undefined ? undefined : !v.org_conflict],
  ];
  return html`<ul class="checks">
    ${rows.filter(([, ok]) => ok !== undefined).map(([label, ok]) =>
      html`<li class=${ok ? "ok" : "bad"}>${mark(ok)} ${label}</li>`)}
    ${v.canonical_domain ? html`<li class="muted">canonical domain: ${v.canonical_domain}</li>` : null}
    ${(v.reasons || []).map((r) => html`<li class="bad">${r}</li>`)}
    ${v.checked_at ? html`<li class="muted">checked ${v.checked_at}</li>` : null}
  </ul>`;
}

function detail(step, d) {
  switch (step) {
    case "identity": return html`<div><code>${d.did}</code><div class="muted">fingerprint <code>${d.fingerprint}</code></div></div>`;
    case "zone": return html`<code>${d.zone}</code> <span class="muted">(${d.result})</span>`;
    case "dns": return d.skipped ? html`<span class="muted">skipped (no TXT record)</span>`
      : d.error ? html`<span class="bad">${d.error}</span>`
      : html`<div>SRV <code>${d.srv}</code><div>TXT ${(d.txt || []).map((t) => html`<code class="txt">${t}</code>`)}</div></div>`;
    case "card": return html`<a href=${new URL(d.card_url).pathname} target="_blank">${new URL(d.card_url).pathname}</a>`;
    case "checks": return html`<${Checks} verification=${d} />`;
    case "result": return html`<span class=${d.status === "verified" ? "ok" : "bad"}>${d.status}</span>
      ${(d.reasons || []).length ? html` — ${d.reasons.join("; ")}` : null}`;
    default: return d.error ? html`<span class="bad">${d.error}</span>` : null;
  }
}

export function Stepper({ agent }) {
  return html`<ol class="stepper">
    ${STEP_LABELS.map(([step, label]) => {
      const s = agent.steps[step];
      const cls = !s ? "pending" : s.status === "ok" ? "ok" : s.status === "skipped" ? "skipped" : "bad";
      return html`<li class=${cls}><strong>${label}</strong>${s ? html`<div>${detail(step, s.detail)}</div>` : html`<div class="muted">—</div>`}</li>`;
    })}
  </ol>`;
}
```

- [ ] **Step 2: Write `components/drawer.js`**

```js
import { html, useEffect, useState } from "../preact.js";
import { getJson } from "../api.js";
import { companyColor } from "../palette.js";
import { Stepper } from "./steps.js";

const TABS = [["overview", "Overview"], ["card", "Card"], ["prompts", "Prompts"],
  ["activity", "Activity"], ["discovery", "Discovery"]];
const REPLAY_ONLY = html`<p class="muted">Not available in replay.</p>`;

export function extensionParams(card) {
  const exts = card?.capabilities?.extensions || [];
  return (exts.find((e) => e.params && e.params.id) || {}).params || {};
}

function useLiveDetail(agent, mode) {
  const [detail, setDetail] = useState(null);
  useEffect(() => {
    setDetail(null);
    if (mode === "replay") return undefined;
    let stop = false;
    const load = () => getJson(`/arena/agents/${agent.slug}`).then((d) => !stop && setDetail(d)).catch(() => {});
    load();
    const timer = setInterval(load, 5000);
    return () => { stop = true; clearInterval(timer); };
  }, [agent.slug, mode]);
  return detail;
}

function Overview({ agent, live, state }) {
  const counters = live?.counters || agent.counters;
  return html`<div>
    <dl class="facts">
      <dt>Role</dt><dd>${agent.role}</dd>
      <dt>Capability</dt><dd>${agent.capability}</dd>
      <dt>Needs</dt><dd>${agent.needs.join(", ") || "—"}</dd>
      <dt>Cadence</dt><dd>${agent.cadence ? `${agent.cadence[0]}–${agent.cadence[1]} s` : "—"}</dd>
      <dt>State</dt><dd>${live ? live.state : state.mode === "replay" ? "replay" : "—"}</dd>
      <dt>Counters</dt><dd>sent ${counters.sent} · received ${counters.received} · rejected ${counters.rejected} · errors ${counters.errors}</dd>
    </dl>
    <h4>Registration</h4>
    <${Stepper} agent=${agent} />
  </div>`;
}

function CardTab({ agent }) {
  const [card, setCard] = useState(null);
  const [source, setSource] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    setCard(null); setError("");
    getJson(`/agents/${agent.slug}/.well-known/agent-card.json`)
      .then((c) => { setCard(c); setSource("live"); })
      .catch((e) => {
        setError(`Live card unavailable: ${e.message}`);
        getJson(`/arena/registry/agents/${agent.id}/card`)
          .then((c) => { setCard(c); setSource("registry (stored)"); })
          .catch(() => {});
      });
  }, [agent.slug]);
  if (!card) return html`<p class="muted">${error || "Loading…"}</p>`;
  const p = extensionParams(card);
  return html`<div>
    ${error ? html`<p class="error">${error}</p>` : null}
    <p class="muted">Source: ${source}</p>
    <dl class="facts">
      <dt>Name</dt><dd>${card.name}</dd>
      <dt>Provider</dt><dd>${card.provider?.organization}</dd>
      <dt>URL</dt><dd><code>${card.url}</code></dd>
      <dt>Skills</dt><dd>${(card.skills || []).map((s) => s.id).join(", ")}</dd>
      <dt>DID</dt><dd><code>${p.did}</code></dd>
      <dt>Domain</dt><dd>${p.domain}</dd>
      <dt>Key (x)</dt><dd><code>${p.publicKeyJwk?.x}</code></dd>
      <dt>Model</dt><dd>${p.model}</dd>
    </dl>
    <button onClick=${() => navigator.clipboard?.writeText(JSON.stringify(card, null, 2))}>Copy JSON</button>
    <pre>${JSON.stringify(card, null, 2)}</pre>
  </div>`;
}

function Prompts({ agent, live }) {
  const last = agent.decisions[agent.decisions.length - 1];
  return html`<div>
    <h4>System prompt</h4><pre>${agent.systemPrompt || live?.system_prompt || "—"}</pre>
    <h4>Last turn prompt</h4><pre>${agent.lastPrompt || live?.last_prompt || "—"}</pre>
    <h4>Last decision</h4>
    ${last ? html`<p>Outcome: <strong>${last.outcome}</strong></p><pre>${JSON.stringify(last.decision, null, 2)}</pre>`
      : html`<p class="muted">No decision yet.</p>`}
  </div>`;
}

function Activity({ agent, live, state, store }) {
  const threads = state.threadOrder.map((id) => state.threads[id]).filter((t) =>
    t.owner === agent.id || state.messages.some((m) => m.kind === "message" && m.threadId === t.id
      && (m.from === agent.id || m.to === agent.id)));
  return html`<div>
    <h4>Agenda</h4><pre>${(agent.systemPrompt || "").split("\n\n")[0] || "—"}</pre>
    <h4>Threads</h4>
    <ul>${threads.map((t) => html`<li><button class="link" onClick=${() => store.select({ agent: null, thread: t.id, allThreads: false })}>
      ${t.id} ${t.title}</button> <span class="muted">${t.owner === agent.id ? "owner" : "participant"} · ${t.closed ? "closed" : "open"} · ${t.count} msgs</span></li>`)}</ul>
    <h4>Pending inbox</h4>
    ${live ? html`<ul>${live.inbox.map((i) => html`<li>${i.sender} · ${i.intent} · ${i.trust || "—"}</li>`)}</ul>${live.inbox.length ? null : html`<p class="muted">Empty.</p>`}`
      : REPLAY_ONLY}
    <h4>Recent decisions</h4>
    <ul>${[...agent.decisions].reverse().map((d) => html`<li><span class="chip">${d.outcome}</span>
      ${d.decision ? html` ${d.decision.action}${d.decision.to ? ` → ${d.decision.to}` : ""}${d.decision.intent ? ` (${d.decision.intent})` : ""}` : null}</li>`)}</ul>
  </div>`;
}

function Discovery({ agent, state }) {
  const choices = state.messages.filter((m) => m.kind === "message" && m.from === agent.id && (m.lookingFor || m.whyThisPeer));
  return html`<div>
    <h4>Queries</h4>
    ${[...agent.queries].reverse().map((q) => html`<div class="query">
      <div><strong>${q.capability}</strong> <span class="muted">${new Date(q.ts * 1000).toLocaleTimeString()}</span></div>
      <ul>${q.results.map((r) => html`<li><span class=${`dot ${r.status}`}></span> ${r.name}
        <span class="muted">${r.organization} · ${r.domain}</span>${r.new ? html` <span class="chip new">new</span>` : null}</li>`)}</ul>
      ${q.results.length ? null : html`<p class="muted">No results.</p>`}
    </div>`)}
    <h4>Choices</h4>
    <ul>${choices.map((m) => html`<li>→ ${state.agents[m.to]?.name || m.to}: <em>${m.lookingFor}</em><div class="muted">${m.whyThisPeer}</div></li>`)}</ul>
    <h4>Trust map</h4>
    <ul>${Object.entries(agent.trust).map(([sender, t]) => html`<li><span class=${`dot ${t.status}`}></span>
      ${state.agents[sender]?.name || sender} <span class="muted">${t.status}${t.reason ? ` · ${t.reason}` : ""}</span></li>`)}</ul>
  </div>`;
}

const VIEW = { overview: Overview, card: CardTab, prompts: Prompts, activity: Activity, discovery: Discovery };

export function Drawer({ store, state }) {
  const agent = state.agents[state.selection.agent];
  const live = useLiveDetail(agent || { slug: "" }, agent ? state.mode : "replay");
  if (!agent) return null;
  const tab = state.selection.tab || "overview";
  const Tab = VIEW[tab] || Overview;
  return html`<section class="drawer">
    <header class="drawer-head">
      <span class="avatar" style=${`background:${companyColor(agent.domain)}`}>${agent.model === "sonnet" ? "S" : "H"}</span>
      <div><strong>${agent.name}</strong> · ${agent.organization}
        <div class="muted">${agent.id} · ${agent.model} · <span class=${agent.status === "verified" ? "ok" : agent.status === "failed" ? "bad" : ""}>${agent.status}</span></div></div>
      <span class="spacer"></span>
      <button aria-label="Close" onClick=${() => store.select({ agent: null })}>×</button>
    </header>
    <nav class="tabs">${TABS.map(([key, label]) => html`<button class=${tab === key ? "on" : ""}
      onClick=${() => store.select({ tab: key })}>${label}</button>`)}</nav>
    <div class="drawer-body"><${Tab} agent=${agent} live=${live} state=${state} store=${store} /></div>
  </section>`;
}
```

Append to `style.css`:

```css
.drawer { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.drawer-head { display: flex; gap: 8px; align-items: center; padding: 8px; border-bottom: 1px solid var(--line); }
.avatar { width: 28px; height: 28px; border-radius: 50%; color: #fff; display: flex;
  align-items: center; justify-content: center; font-weight: 700; flex: none; }
.tabs { display: flex; gap: 4px; padding: 6px 8px; border-bottom: 1px solid var(--line); }
.tabs button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.drawer-body { overflow: auto; padding: 8px 12px; min-height: 0; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; margin: 0; }
.facts dt { color: var(--muted); }
.stepper { padding-left: 20px; margin: 0; }
.stepper li { margin: 6px 0; }
.stepper li.ok::marker { color: var(--ok); } .stepper li.bad::marker { color: var(--bad); }
.stepper li.pending { color: var(--muted); }
.checks { list-style: none; padding: 0; margin: 4px 0; }
.ok { color: var(--ok); } .bad { color: var(--bad); }
code.txt { display: inline-block; margin: 1px 4px 1px 0; }
.chip.new { background: var(--search); color: #fff; }
.query { border-bottom: 1px solid var(--line); padding: 4px 0; }
```

In `app.js`, add `import { Drawer } from "./components/drawer.js";` and change `RIGHT` to:

```js
export function RIGHT(state) {
  return state.selection.agent && state.agents[state.selection.agent] ? Drawer : Chat;
}
```

Add `"components/drawer.js"` and `"components/steps.js"` to `UI_FILES`.

- [ ] **Step 3: Run tests**

Run: `pytest arena/tests/test_arena_ui.py -v && node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS.

- [ ] **Step 4: Manual check (demo replay, then a free live dry run)**

Demo replay. Click each agent and check:
- Overview shows seven steps. The impostor's checks show "✕ organization anchor" and the reason.
- Card loads the live card. Copy works.
- Prompts shows the system prompt, the last turn prompt, and the last decision with its outcome.
- Activity lists threads and decisions, and shows "Not available in replay" for the inbox.
- Discovery shows queries with status dots, "new" badges, choices with the "looking for / why" text, and the trust map.
- Esc closes the drawer.

Then run `ARENA_MAX_MODEL_CALLS=0 docker compose up -d --build`. In the drawer, check that State shows a live value and the Activity inbox shows the seed for the SOC agent. Run `docker compose down`.

- [ ] **Step 5: Commit**

```bash
git add arena/ui arena/tests/test_arena_ui.py
git commit -m "feat(arena-ui): agent drawer with registration stepper, card, prompts, activity, discovery"
```

---

### Task 10: Registry browser

**Files:**
- Create: `arena/ui/components/registry.js`, `arena/ui/lib/diff.js`, `arena/ui/tests/diff.test.mjs`
- Modify: `arena/ui/app.js` (`VIEWS`), `arena/ui/style.css` (append), `arena/tests/test_arena_ui.py` (`UI_FILES`)

**Interfaces:**
- Consumes: `GET /arena/registry`, `GET /arena/registry/orgs`, `GET /arena/registry/agents/{id}/card`, and the live card URL. Reuses `Checks` (Task 9) and `extensionParams` (Task 9).
- Produces: `diffKeys(a, b) -> string[]`, the sorted top-level keys whose JSON values differ. Also produces the `RegistryView` component, registered as `VIEWS.registry`.

- [ ] **Step 1: Write the failing test**

`arena/ui/tests/diff.test.mjs`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { diffKeys } from "../lib/diff.js";

test("diffKeys lists differing and missing top-level keys", () => {
  assert.deepEqual(diffKeys({ a: 1, b: { c: 2 }, d: 3 }, { a: 1, b: { c: 9 }, e: 4 }), ["b", "d", "e"]);
  assert.deepEqual(diffKeys({ a: [1] }, { a: [1] }), []);
  assert.deepEqual(diffKeys(null, { a: 1 }), ["a"]);
});
```

Run: `node --test "arena/ui/tests/*.test.mjs"`
Expected: FAIL (`lib/diff.js` missing).

- [ ] **Step 2: Implement `arena/ui/lib/diff.js`**

```js
// Top-level JSON difference between two objects. Pure.
export function diffKeys(a, b) {
  const left = a || {};
  const right = b || {};
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
  return [...keys].filter((k) => JSON.stringify(left[k]) !== JSON.stringify(right[k])).sort();
}
```

- [ ] **Step 3: Implement `arena/ui/components/registry.js`**

```js
import { html, useEffect, useState } from "../preact.js";
import { getJson } from "../api.js";
import { diffKeys } from "../lib/diff.js";
import { Checks } from "./steps.js";

function CardCompare({ entry }) {
  const [stored, setStored] = useState(null);
  const [live, setLive] = useState(null);
  const slug = entry.id.split(".")[0];
  useEffect(() => {
    getJson(`/arena/registry/agents/${entry.id}/card`).then(setStored).catch(() => setStored(null));
    getJson(`/agents/${slug}/.well-known/agent-card.json`).then(setLive).catch(() => setLive(null));
  }, [entry.id]);
  const differ = diffKeys(stored, live);
  return html`<div class="compare">
    <p>${stored && live ? (differ.length ? html`<span class="bad">Stored and live cards differ in: ${differ.join(", ")}</span>`
      : html`<span class="ok">Stored card matches the live card.</span>`) : html`<span class="muted">Loading cards…</span>`}</p>
    <div class="split2">
      <div><h5>Stored in registry</h5><pre>${stored ? JSON.stringify(stored, null, 2) : "—"}</pre></div>
      <div><h5>Live</h5><pre>${live ? JSON.stringify(live, null, 2) : "—"}</pre></div>
    </div>
  </div>`;
}

function Organizations({ orgs, entries }) {
  return html`<table class="grid">
    <tr><th>Organization</th><th>Canonical domain</th><th>Agents claiming it</th></tr>
    ${orgs.map((o) => {
      const claims = entries.filter((e) => e.organization === o.organization);
      return html`<tr><td>${o.organization}</td><td>${o.canonical_domain}</td>
        <td>${claims.map((e) => html`<div class=${e.domain === o.canonical_domain ? "" : "bad"}>${e.id}</div>`)}</td></tr>`;
    })}
  </table>`;
}

export function RegistryView({ store }) {
  const [entries, setEntries] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [open, setOpen] = useState(null);
  const [tab, setTab] = useState("entries");
  const load = () => {
    setError("");
    getJson("/arena/registry").then((d) => setEntries(d.agents || [])).catch((e) => setError(e.message));
    getJson("/arena/registry/orgs").then((d) => setOrgs(d.orgs || [])).catch(() => {});
  };
  useEffect(load, []);
  const q = query.toLowerCase();
  const shown = entries.filter((e) => {
    const s = (e.verification || {}).status || "unknown";
    if (status !== "all" && s !== status) return false;
    return !q || [e.name, e.organization, e.domain, ...(e.capabilities || [])].join(" ").toLowerCase().includes(q);
  });
  return html`<div class="view scroll registry">
    ${error ? html`<div class="banner">Registry unreachable: ${error}</div>` : null}
    <div class="toolbar">
      <button class=${tab === "entries" ? "on" : ""} onClick=${() => setTab("entries")}>Entries</button>
      <button class=${tab === "orgs" ? "on" : ""} onClick=${() => setTab("orgs")}>Organizations</button>
      <input placeholder="search name, org, capability, domain" value=${query} onInput=${(e) => setQuery(e.target.value)} />
      <select value=${status} onChange=${(e) => setStatus(e.target.value)}>
        <option value="all">All</option><option value="verified">Verified</option><option value="failed">Failed</option></select>
      <button onClick=${load}>Refresh</button>
    </div>
    ${tab === "orgs" ? html`<${Organizations} orgs=${orgs} entries=${entries} />` : html`<table class="grid">
      <tr><th>Agent</th><th>Organization</th><th>Capability</th><th>Status</th><th>Last update</th></tr>
      ${shown.map((e) => {
        const v = e.verification || {};
        return html`<tr class="row" onClick=${() => setOpen(open === e.id ? null : e.id)}>
            <td>${e.name}<div class="muted">${e.id}</div></td><td>${e.organization}</td>
            <td>${(e.capabilities || []).join(", ")}</td>
            <td class=${v.status === "verified" ? "ok" : v.status === "failed" ? "bad" : "muted"}>${v.status || "unknown"}</td>
            <td>${e.last_update ? new Date(e.last_update * 1000).toLocaleTimeString() : "—"}</td>
          </tr>
          ${open === e.id ? html`<tr><td colspan="5">
            <button class="link" onClick=${() => store.select({ agent: e.id, tab: "overview" })}>Open agent</button>
            <h5>Verification</h5><${Checks} verification=${v} />
            <h5>Stored entry</h5><pre>${JSON.stringify(e, null, 2)}</pre>
            <${CardCompare} entry=${e} />
          </td></tr>` : null}`;
      })}
    </table>`}
  </div>`;
}
```

Append to `style.css`:

```css
.registry { padding: 8px; }
.toolbar { display: flex; gap: 6px; margin-bottom: 8px; }
.toolbar input { flex: 1; }
.toolbar button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.grid { width: 100%; border-collapse: collapse; }
.grid th { text-align: left; color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--line); }
.grid td { border-bottom: 1px solid var(--line); padding: 4px; vertical-align: top; }
.grid tr.row { cursor: pointer; } .grid tr.row:hover { background: var(--panel-2); }
.banner { background: var(--bad); color: #fff; padding: 6px 10px; border-radius: 6px; margin-bottom: 8px; }
.split2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
```

In `app.js`, add `import { RegistryView } from "./components/registry.js";` and add `registry: ["Registry", RegistryView]` to `VIEWS`. Add `"components/registry.js"` and `"lib/diff.js"` to `UI_FILES`.

- [ ] **Step 4: Run tests**

Run: `pytest arena/tests/test_arena_ui.py -v && node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS.

- [ ] **Step 5: Manual check**

In replay without Docker, the registry is unreachable, so check that the banner appears. Then run `ARENA_MAX_MODEL_CALLS=0 docker compose up -d --build` and check:
- 10 entries, of which search and filter show 9 verified and 1 failed.
- Expanding the impostor row shows "✕ organization anchor".
- The stored card matches the live card.
- The Organizations tab shows "Halcyon Intel" with the lookalike id in red.

Run `docker compose down`.

- [ ] **Step 6: Commit**

```bash
git add arena/ui arena/tests/test_arena_ui.py
git commit -m "feat(arena-ui): registry browser with checks, card compare, and organizations"
```

---

### Task 11: Chat

**Files:**
- Modify: `arena/ui/components/chat.js` (full rewrite), `arena/ui/style.css` (append)

**Interfaces:**
- Consumes: `chatItems`, `select` (Task 6), `companyColor`, `threadColor`, and `state.tasks` / `state.taskByMessage` (task chips appear once Phase 5 publishes task events).
- Produces: `Chat` (thread chips, "All threads", bubbles, dividers, follow and "new messages" pill).

- [ ] **Step 1: Rewrite `components/chat.js`**

```js
import { html, useEffect, useRef, useState } from "../preact.js";
import { chatItems } from "../store.js";
import { companyColor, threadColor } from "../palette.js";

function Chips({ store, state }) {
  const { thread, allThreads } = state.selection;
  return html`<div class="chips">
    ${state.threadOrder.map((id) => {
      const t = state.threads[id];
      const on = !allThreads && thread === id;
      return html`<button class=${`chip-btn${on ? " on" : ""}`} style=${`--tc:${threadColor(t.color)}`}
        onClick=${() => store.select({ thread: id, allThreads: false, agent: null })}>
        ${id} ${t.title.slice(0, 24)} · ${t.count}${t.closed ? " ✓" : ""}${t.unread ? html` <span class="unread"></span>` : null}
      </button>`;
    })}
    <button class=${`chip-btn${allThreads ? " on" : ""}`} onClick=${() => store.select({ allThreads: true, agent: null })}>All threads</button>
  </div>`;
}

function Bubble({ m, state, all }) {
  const from = state.agents[m.from] || { name: m.from, organization: "", domain: "", model: "" };
  const to = state.agents[m.to] || { name: m.to };
  const failed = m.trust && m.trust.status !== "verified";
  const taskId = state.taskByMessage[m.id];
  const task = taskId ? state.tasks[taskId] : null;
  return html`<div class=${`msg${m.replyTo ? " reply" : ""}${all ? " rail" : ""}`} style=${`--tc:${threadColor(m.color)}`}>
    <span class="avatar" style=${`background:${companyColor(from.domain)}`}>${from.model === "sonnet" ? "S" : "H"}</span>
    <div class="msg-main">
      <div class="msg-head"><strong>${from.name}</strong>
        <span class="muted">${from.organization} → ${to.name} · ${m.intent} · ${new Date(m.ts * 1000).toLocaleTimeString()}${all ? ` · ${m.threadId}` : ""}</span>
        ${m.trust ? html`<span class=${`trust ${failed ? "bad" : "ok"}`}>${failed ? `✕ ${m.trust.reason}` : "✓ verified"}</span>` : null}
        ${task ? html`<span class=${`chip task ${task.state}`}>${task.state}</span>` : null}
      </div>
      <div class=${`bubble${failed ? " failed" : ""}`}>${m.body}</div>
      ${m.lookingFor || m.whyThisPeer ? html`<div class="intent-line">looking for: ${m.lookingFor || "—"} · why: ${m.whyThisPeer || "—"}</div>` : null}
    </div>
  </div>`;
}

export function Chat({ store, state }) {
  const box = useRef(null);
  const [follow, setFollow] = useState(true);
  const items = chatItems(state);
  const all = state.selection.allThreads;
  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  });
  const onScroll = () => {
    const el = box.current;
    setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };
  return html`<div class="chat">
    <${Chips} store=${store} state=${state} />
    <div class="feed" ref=${box} onScroll=${onScroll}>
      ${items.map((m) => m.kind === "system"
        ? html`<div class="divider"><span>${m.text}</span></div>`
        : html`<${Bubble} m=${m} state=${state} all=${all} />`)}
      ${items.length ? null : html`<p class="muted">No messages in this view yet.</p>`}
    </div>
    ${follow ? null : html`<button class="pill" onClick=${() => setFollow(true)}>New messages ↓</button>`}
  </div>`;
}
```

Append to `style.css`:

```css
.chat { display: flex; flex-direction: column; height: 100%; min-height: 0; position: relative; }
.chips { display: flex; gap: 4px; flex-wrap: wrap; padding: 6px 8px; border-bottom: 1px solid var(--line); }
.chip-btn { border-radius: 12px; border-left: 4px solid var(--tc, var(--line)); font-size: 12px; }
.chip-btn.on { background: var(--panel-2); font-weight: 600; }
.unread { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
.feed { overflow: auto; padding: 8px; flex: 1; min-height: 0; }
.msg { display: flex; gap: 8px; margin: 8px 0; }
.msg.reply { margin-left: 28px; }
.msg.rail { border-left: 4px solid var(--tc); padding-left: 6px; }
.msg-main { min-width: 0; flex: 1; }
.msg-head { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; font-size: 12px; }
.bubble { background: var(--panel-2); border-radius: 10px; padding: 6px 10px; margin-top: 2px;
  white-space: pre-wrap; word-break: break-word; }
.bubble.failed { border: 1px dashed var(--bad); background: transparent; }
.trust { font-size: 11px; }
.intent-line { color: var(--search); font-size: 12px; margin-top: 2px; }
.divider { text-align: center; color: var(--muted); font-size: 12px; margin: 8px 0; }
.divider span { background: var(--panel); padding: 0 8px; }
.pill { position: absolute; bottom: 12px; left: 50%; transform: translateX(-50%);
  border-radius: 14px; background: var(--accent); color: #fff; border-color: var(--accent); }
.chip.task.working { background: var(--pending); color: #000; }
.chip.task.completed { background: var(--ok); color: #fff; }
.chip.task.rejected, .chip.task.canceled, .chip.task.failed { background: var(--bad); color: #fff; }
```

- [ ] **Step 2: Run tests**

Run: `pytest arena/tests/test_arena_ui.py -v && node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS.

- [ ] **Step 3: Manual check (demo replay)**

Check:
- The `t1` chip is active by default. Chips show counts, and closed threads show ✓.
- Bubbles show avatars, trust badges, and the purple "looking for / why" line on the SOC's request.
- The impostor's bubble has a dashed red border and "✕ domain mismatch".
- Replies are indented. Joins and verifications show as centered dividers.
- "All threads" shows colored rails and thread ids.
- Scrolling up stops the auto-follow, and the "New messages ↓" pill returns to the bottom.
- Selecting an agent in the sidebar and closing the drawer returns to the chat.

- [ ] **Step 4: Commit**

```bash
git add arena/ui
git commit -m "feat(arena-ui): threaded chat with bubbles, trust badges, intent lines, and follow"
```

---

### Task 12: Layout helpers for the graph views

**Files:**
- Modify: `arena/ui/lib/layout.js` (append), `arena/ui/tests/layout.test.mjs` (append)

**Interfaces:**
- Produces:
  - `expandPoints(points, pad) -> points`: four points per input, at ±`pad`.
  - `convexHull(points) -> points`: monotone chain. Inputs with fewer than 3 points come back unchanged.
  - `hullLabelPoint(hull) -> {x, y}`: the top-most point; on a tie, the left-most.
  - `threadLinks(messages) -> [{key, source, target, thread, color, count, critical, curvature}]`: one link per unordered agent pair per thread. Parallel links get curvature 0, 0.25, -0.25, 0.5, and so on.
  - `matrixCells(messages, ids) -> {ids, cells: {"from>to": {count, failed, verified, bodies}}, max}`.
  - `flowGraph(messages, threadId) -> {nodes: ids in first-appearance order, edges: [{from, to, count, intents}], root}`.
  - `sequenceRows(messages, markers) -> rows`: messages and markers merged by `seq`. Each row is `{index, kind: "message"|"marker", ...item}`.
- `messages` are store items of kind `message` (fields `id`, `seq`, `threadId`, `from`, `to`, `intent`, `color`, `trust`, `body`). `markers` are `{seq, agent, lane, label}`, taken from `state.timeline`.

- [ ] **Step 1: Write the failing tests** (append to `arena/ui/tests/layout.test.mjs`)

```js
import { convexHull, expandPoints, flowGraph, hullLabelPoint, matrixCells, sequenceRows, threadLinks } from "../lib/layout.js";

const msg = (seq, from, to, threadId = "t1", intent = "share", trust = null) =>
  ({ kind: "message", id: `m${seq}`, seq, threadId, from, to, intent, color: 0, trust, body: `b${seq}` });

test("convexHull drops interior points", () => {
  const hull = convexHull([{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 4 }, { x: 0, y: 4 }, { x: 2, y: 2 }]);
  assert.equal(hull.length, 4);
  assert.ok(!hull.some((p) => p.x === 2 && p.y === 2));
});

test("expandPoints and hullLabelPoint", () => {
  const pts = expandPoints([{ x: 10, y: 10 }], 5);
  assert.equal(pts.length, 4);
  assert.deepEqual(hullLabelPoint(convexHull(pts)), { x: 5, y: 5 });
});

test("threadLinks aggregates per pair and thread with spread curvature", () => {
  const links = threadLinks([msg(1, "a", "b"), msg(2, "b", "a"), msg(3, "a", "b", "t2", "decline")]);
  assert.equal(links.length, 2);
  const t1 = links.find((l) => l.thread === "t1");
  assert.equal(t1.count, 2);
  assert.equal(t1.curvature, 0);
  const t2 = links.find((l) => l.thread === "t2");
  assert.equal(t2.critical, true);
  assert.equal(t2.curvature, 0.25);
});

test("matrixCells counts and flags trust", () => {
  const m = matrixCells([msg(1, "a", "b", "t1", "share", { status: "verified" }),
    msg(2, "c", "b", "t1", "share", { status: "failed", reason: "domain mismatch" }),
    msg(3, "a", "b")], ["a", "b", "c"]);
  assert.equal(m.cells["a>b"].count, 2);
  assert.equal(m.cells["a>b"].verified, true);
  assert.equal(m.cells["c>b"].failed, true);
  assert.equal(m.max, 2);
});

test("flowGraph orders nodes by first appearance and keeps loops", () => {
  const g = flowGraph([msg(1, "soc", "intel"), msg(2, "intel", "soc", "t1", "reply"),
    msg(3, "soc", "isac"), msg(4, "isac", "soc", "t1", "verdict"), msg(5, "x", "y", "t2")], "t1");
  assert.deepEqual(g.nodes, ["soc", "intel", "isac"]);
  assert.equal(g.root, "soc");
  assert.deepEqual(g.edges.find((e) => e.from === "isac").intents, ["verdict"]);
  assert.equal(g.edges.length, 4);
});

test("sequenceRows merges messages and markers by seq", () => {
  const rows = sequenceRows([msg(2, "a", "b"), msg(5, "b", "a")], [{ seq: 3, agent: "a", lane: "discover", label: "q" }]);
  assert.deepEqual(rows.map((r) => [r.index, r.kind, r.seq]), [[0, "message", 2], [1, "marker", 3], [2, "message", 5]]);
});
```

Run: `node --test "arena/ui/tests/*.test.mjs"`
Expected: FAIL (`convexHull` is not exported).

- [ ] **Step 2: Implement** (append to `arena/ui/lib/layout.js`)

```js
export function expandPoints(points, pad) {
  return points.flatMap((p) => [
    { x: p.x - pad, y: p.y - pad }, { x: p.x + pad, y: p.y - pad },
    { x: p.x + pad, y: p.y + pad }, { x: p.x - pad, y: p.y + pad },
  ]);
}

export function convexHull(points) {
  const pts = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  if (pts.length < 3) return pts;
  const cross = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const half = (list) => {
    const out = [];
    for (const p of list) {
      while (out.length >= 2 && cross(out[out.length - 2], out[out.length - 1], p) <= 0) out.pop();
      out.push(p);
    }
    out.pop();
    return out;
  };
  return half(pts).concat(half([...pts].reverse()));
}

export function hullLabelPoint(hull) {
  return hull.reduce((best, p) => (p.y < best.y || (p.y === best.y && p.x < best.x) ? p : best), hull[0]);
}

export function threadLinks(messages) {
  const links = new Map();
  for (const m of messages) {
    if (m.kind !== "message") continue;
    const [a, b] = [m.from, m.to].sort();
    const key = `${a}|${b}|${m.threadId}`;
    if (!links.has(key)) links.set(key, { key, source: m.from, target: m.to, thread: m.threadId,
      color: m.color, count: 0, critical: false, curvature: 0 });
    const link = links.get(key);
    link.count += 1;
    if (m.intent === "decline" || m.intent === "challenge") link.critical = true;
  }
  const perPair = new Map();
  for (const link of links.values()) {
    const pair = [link.source, link.target].sort().join("|");
    const i = perPair.get(pair) || 0;
    perPair.set(pair, i + 1);
    link.curvature = i === 0 ? 0 : (i % 2 ? 1 : -1) * 0.25 * Math.ceil(i / 2);
  }
  return [...links.values()];
}

export function matrixCells(messages, ids) {
  const cells = {};
  let max = 0;
  for (const m of messages) {
    if (m.kind !== "message") continue;
    const key = `${m.from}>${m.to}`;
    const cell = cells[key] || (cells[key] = { count: 0, failed: false, verified: false, bodies: [] });
    cell.count += 1;
    if (m.trust?.status === "failed") cell.failed = true;
    if (m.trust?.status === "verified") cell.verified = true;
    if (cell.bodies.length < 5) cell.bodies.push(`${m.intent}: ${m.body}`);
    max = Math.max(max, cell.count);
  }
  return { ids, cells, max };
}

export function flowGraph(messages, threadId) {
  const ms = messages.filter((m) => m.kind === "message" && m.threadId === threadId);
  const nodes = [];
  const edges = new Map();
  for (const m of ms) {
    for (const id of [m.from, m.to]) if (!nodes.includes(id)) nodes.push(id);
    const key = `${m.from}>${m.to}`;
    if (!edges.has(key)) edges.set(key, { from: m.from, to: m.to, count: 0, intents: [] });
    const e = edges.get(key);
    e.count += 1;
    if (!e.intents.includes(m.intent)) e.intents.push(m.intent);
  }
  return { nodes, edges: [...edges.values()], root: ms[0]?.from || null };
}

export function sequenceRows(messages, markers) {
  const items = [
    ...messages.filter((m) => m.kind === "message").map((m) => ({ ...m, kind: "message" })),
    ...markers.map((m) => ({ ...m, kind: "marker" })),
  ].sort((a, b) => a.seq - b.seq);
  return items.map((item, index) => ({ ...item, index }));
}
```

- [ ] **Step 3: Run tests**

Run: `node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add arena/ui/lib/layout.js arena/ui/tests/layout.test.mjs
git commit -m "feat(arena-ui): pure layout helpers for hulls, links, matrix, flow, and sequence"
```

---

### Task 13: Network view: company hulls, per-thread edges, and discovery highlight

**Files:**
- Modify: `arena/ui/views/network.js` (rewrite `createNetwork`), `arena/ui/style.css` (append)

**Interfaces:**
- Consumes: `threadLinks`, `convexHull`, `expandPoints`, `hullLabelPoint` (Task 12); `state.highlight`, `state.lastQuery`, `state.selection.allQueries`, `state.selection.agent`, `state.selection.range`, and `chatItems`-style messages from `state.messages`.
- Produces: `NetworkView`, with an overlay checkbox "show every search" (`selection.allQueries`).

- [ ] **Step 1: Rewrite `arena/ui/views/network.js`**

```js
// Network view: companies as hulls, one curved edge per pair per thread,
// and a 2-second highlight for each discovery search.
import { html, useEffect, useRef } from "../preact.js";
import { companyColor, threadColor, TRUST_TOKENS } from "../palette.js";
import { convexHull, expandPoints, hullLabelPoint, threadLinks } from "../lib/layout.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const HIGHLIGHT_MS = 2000;

export function createNetwork(el, onSelect) {
  const nodes = new Map();
  let links = new Map();
  let search = { agent: null, ids: new Set(), fresh: new Set(), links: [], until: 0 };
  let selected = null;
  let lastMessageSeq = -1;
  let lastHighlightSeq = -1;
  let signature = "";

  const active = () => Date.now() < search.until;
  const graph = ForceGraph()(el)
    .nodeId("id")
    .nodeLabel((n) => `${n.name} — ${n.organization} (${n.domain})`)
    .nodeCanvasObject((n, ctx, scale) => {
      const dim = active() && n.id !== search.agent && !search.ids.has(n.id);
      ctx.globalAlpha = dim ? 0.25 : 1;
      if (active() && n.id === search.agent) {
        ctx.beginPath(); ctx.arc(n.x, n.y, 14, 0, 2 * Math.PI);
        ctx.strokeStyle = css("--search"); ctx.lineWidth = 2 / scale; ctx.stroke();
      }
      ctx.beginPath(); ctx.arc(n.x, n.y, 7, 0, 2 * Math.PI);
      ctx.fillStyle = css("--panel"); ctx.fill();
      ctx.lineWidth = n.id === selected ? 4 : 2.5;
      ctx.strokeStyle = css(TRUST_TOKENS[n.status] || "--pending"); ctx.stroke();
      ctx.fillStyle = css("--text"); ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.font = `bold ${10 / scale}px system-ui`;
      ctx.fillText(n.model === "sonnet" ? "S" : "H", n.x, n.y);
      ctx.font = `${10 / scale}px system-ui`;
      ctx.fillText(n.name, n.x, n.y + 7 + 9 / scale);
      if (active() && search.fresh.has(n.id)) {
        ctx.fillStyle = css("--search");
        ctx.fillText("new", n.x, n.y - 7 - 8 / scale);
      }
      ctx.globalAlpha = 1;
    })
    .linkColor((l) => (l.kind === "search" ? css("--search") : l.critical ? css("--bad") : threadColor(l.color)))
    .linkWidth((l) => (l.kind === "search" ? 1.5 : Math.min(6, 1 + l.count / 2)))
    .linkLineDash((l) => (l.kind === "search" ? [4, 3] : null))
    .linkCurvature((l) => l.curvature || 0)
    .linkCanvasObjectMode((l) => (l.kind === "search" ? "after" : undefined))
    .linkCanvasObject((l, ctx, scale) => {
      const s = l.source; const t = l.target;
      if (s.x == null || t.x == null) return;
      ctx.font = `${10 / scale}px system-ui`; ctx.fillStyle = css("--search");
      ctx.textAlign = "center"; ctx.fillText(l.label, (s.x + t.x) / 2, (s.y + t.y) / 2 - 4 / scale);
    })
    .linkDirectionalParticleColor((l) => (l.critical ? css("--bad") : threadColor(l.color)))
    .linkDirectionalParticleWidth(4)
    .onRenderFramePre((ctx, scale) => drawHulls(ctx, scale))
    .onNodeClick((n) => onSelect(n.id))
    .cooldownTicks(120)
    .onEngineStop(() => graph.zoomToFit(400, 60));
  graph.d3Force("charge").strength(-260);
  const fit = () => graph.width(el.clientWidth).height(el.clientHeight);
  const observer = new ResizeObserver(fit);
  observer.observe(el);
  fit();

  function drawHulls(ctx, scale) {
    const groups = new Map();
    for (const n of nodes.values()) {
      if (n.x == null) continue;
      if (!groups.has(n.domain)) groups.set(n.domain, []);
      groups.get(n.domain).push(n);
    }
    for (const [domain, members] of groups) {
      const hull = convexHull(expandPoints(members.map((n) => ({ x: n.x, y: n.y })), 22));
      const color = companyColor(domain);
      ctx.beginPath();
      hull.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
      ctx.closePath();
      ctx.fillStyle = `${color}14`; ctx.fill();
      const failed = members.every((n) => n.status === "failed");
      ctx.setLineDash(failed ? [4 / scale, 3 / scale] : []);
      ctx.strokeStyle = failed ? css("--bad") : `${color}66`; ctx.lineWidth = 1 / scale; ctx.stroke();
      ctx.setLineDash([]);
      const p = hullLabelPoint(hull);
      // Screen-constant size: the label does not grow with zoom.
      ctx.font = `${11 / scale}px system-ui`; ctx.fillStyle = css("--muted");
      ctx.textAlign = "left"; ctx.textBaseline = "bottom";
      ctx.fillText(`${members[0].organization} · ${domain}`, p.x, p.y - 2 / scale);
    }
  }

  function refresh() {
    graph.graphData({ nodes: [...nodes.values()], links: [...links.values(), ...(active() ? search.links : [])] });
  }

  function update(state) {
    selected = state.selection.agent;
    let changed = false;
    for (const id of state.order) {
      const a = state.agents[id];
      if (!nodes.has(id)) { nodes.set(id, { id }); changed = true; }
      Object.assign(nodes.get(id), { name: a.name, organization: a.organization,
        domain: a.domain, model: a.model, status: a.status });
    }
    const range = state.selection.range;
    const visible = state.messages.filter((m) => m.kind === "message" && nodes.has(m.from)
      && nodes.has(m.to) && (!range || (m.ts >= range[0] && m.ts <= range[1])));
    const sig = `${visible.length}|${range ? range.join() : ""}`;
    if (sig !== signature) {
      signature = sig;
      const next = new Map();
      for (const l of threadLinks(visible)) next.set(l.key, Object.assign(links.get(l.key) || {}, l));
      links = next;
      changed = true;
    }
    const query = state.selection.allQueries ? state.lastQuery : state.highlight;
    if (query && query.seq > lastHighlightSeq && nodes.has(query.agent)) {
      lastHighlightSeq = query.seq;
      const hits = query.results.filter((r) => nodes.has(r.id));
      search = {
        agent: query.agent, ids: new Set(hits.map((r) => r.id)),
        fresh: new Set(hits.filter((r) => r.new).map((r) => r.id)),
        links: hits.map((r) => ({ source: query.agent, target: r.id, kind: "search", label: query.capability })),
        until: Date.now() + HIGHLIGHT_MS,
      };
      changed = true;
      setTimeout(refresh, HIGHLIGHT_MS + 50);
    }
    if (changed) refresh();
    if (!range) {
      for (const m of visible) {
        if (m.seq <= lastMessageSeq) continue;
        lastMessageSeq = m.seq;
        const [a, b] = [m.from, m.to].sort();
        const link = links.get(`${a}|${b}|${m.threadId}`);
        if (link) graph.emitParticle(link);
      }
    }
  }

  return { graph, update, destroy() { observer.disconnect(); graph._destructor?.(); } };
}

export function NetworkView({ store, state }) {
  const el = useRef(null);
  const net = useRef(null);
  useEffect(() => {
    net.current = createNetwork(el.current, (id) => store.select({ agent: id, tab: "overview" }));
    return () => net.current.destroy();
  }, []);
  useEffect(() => { net.current.update(state); });
  return html`<div style="position:absolute;inset:0">
    <div style="position:absolute;inset:0" ref=${el}></div>
    <label class="overlay"><input type="checkbox" checked=${state.selection.allQueries}
      onChange=${(e) => store.select({ allQueries: e.target.checked })} /> show every search</label>
  </div>`;
}
```

Append to `style.css`:

```css
.overlay { position: absolute; top: 8px; right: 8px; background: var(--panel); border: 1px solid var(--line);
  border-radius: 6px; padding: 2px 8px; font-size: 12px; z-index: 2; }
```

- [ ] **Step 2: Run tests**

Run: `pytest arena/tests/test_arena_ui.py -v && node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS.

- [ ] **Step 3: Manual check (demo replay)**

Check:
- **Labels:** company outlines with small labels that keep their size when you zoom (the oversized-domain bug is gone). The impostor's outline is dashed red.
- **Edges:** each pair has one edge per thread, curved when parallel. The decline edge is red.
- **Discovery:** when Northwind joins, the SOC's next search draws a pulse ring and dashed purple lines labelled `threat-intel`, with a "new" label on Northwind. Other nodes dim for about 2 s.
- **Toggle:** "show every search" highlights every query.
- **Selection:** a selected node has a thicker border.
- **Time range:** a range on the timeline limits the edges.

- [ ] **Step 4: Commit**

```bash
git add arena/ui
git commit -m "feat(arena-ui): network hulls with fixed-size labels, per-thread edges, discovery highlight"
```

---

### Task 14: Sequence view

**Files:**
- Create: `arena/ui/views/sequence.js`
- Modify: `arena/ui/app.js` (`VIEWS`), `arena/ui/style.css` (append), `arena/tests/test_arena_ui.py` (`UI_FILES`)

**Interfaces:**
- Consumes: `sequenceRows` (Task 12), `agentsByCompany`, `chatItems` (Task 6), and `state.timeline` (markers).
- Produces: `SequenceView` (`VIEWS.sequence`). Task 18 adds task brackets through `taskBrackets(rows, state)`, a function defined here that returns `[]` until then.

- [ ] **Step 1: Write `arena/ui/views/sequence.js`**

```js
// Sequence view: one lane per agent, time flows down.
import { html, useEffect, useRef, useState } from "../preact.js";
import { agentsByCompany, chatItems } from "../store.js";
import { companyColor, threadColor } from "../palette.js";
import { sequenceRows } from "../lib/layout.js";

const LANE_W = 120;
const ROW_H = 26;
const TOP = 44;
const LEFT = 20;

// Task 18 fills this in.
export function taskBrackets(rows, state) {
  return [];
}

export function SequenceView({ store, state }) {
  const box = useRef(null);
  const [follow, setFollow] = useState(true);
  const lanes = agentsByCompany(state).flatMap((g) => g.agents);
  const laneX = new Map(lanes.map((a, i) => [a.id, LEFT + i * LANE_W + LANE_W / 2]));
  const messages = chatItems(state).filter((m) => m.kind === "message");
  const first = messages[0]?.seq ?? -1;
  const last = messages[messages.length - 1]?.seq ?? -1;
  const markers = state.timeline.filter((t) => (t.lane === "discover" || t.lane === "verify")
    && laneX.has(t.agent) && t.seq >= first && t.seq <= last);
  const rows = sequenceRows(messages, markers);
  const width = LEFT * 2 + lanes.length * LANE_W;
  const height = TOP + rows.length * ROW_H + 20;
  useEffect(() => { if (follow && box.current) box.current.scrollTop = box.current.scrollHeight; });
  const onScroll = () => {
    const el = box.current;
    setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };
  return html`<div class="view scroll" ref=${box} onScroll=${onScroll}>
    <svg class="sequence" width=${width} height=${height}>
      <defs>${["normal", "bad", "verdict"].map((k) => html`<marker id=${`arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5"
        markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class=${`arrowhead ${k}`} /></marker>`)}</defs>
      ${lanes.map((a) => html`<g class="lane" onClick=${() => store.select({ agent: a.id, tab: "overview" })}>
        <text x=${laneX.get(a.id)} y="16" class=${`lane-name ${a.status}`}>${a.name}</text>
        <text x=${laneX.get(a.id)} y="30" class="lane-org" fill=${companyColor(a.domain)}>${a.organization}</text>
        <line x1=${laneX.get(a.id)} x2=${laneX.get(a.id)} y1=${TOP - 6} y2=${height} class="lane-axis" />
      </g>`)}
      ${taskBrackets(rows, state).map((b) => html`<path d=${b.path} class=${`bracket ${b.state}`}><title>${b.label}</title></path>`)}
      ${rows.map((r) => {
        const y = TOP + r.index * ROW_H + 10;
        if (r.kind === "marker") {
          const x = laneX.get(r.agent);
          return html`<g><rect x=${x - 4} y=${y - 4} width="8" height="8" transform=${`rotate(45 ${x} ${y})`}
            class=${`seq-marker ${r.lane}${r.failed ? " failed" : ""}`} /><title>${r.label}</title></g>`;
        }
        const x1 = laneX.get(r.from); const x2 = laneX.get(r.to);
        if (x1 == null || x2 == null) return null;
        const failed = r.trust && r.trust.status !== "verified";
        const kind = r.intent === "verdict" ? "verdict" : failed || r.intent === "decline" || r.intent === "challenge" ? "bad" : "normal";
        return html`<g class="seq-msg" onClick=${() => store.select({ thread: r.threadId, allThreads: false, agent: null })}>
          <line x1=${x1} x2=${x2 + (x2 > x1 ? -6 : 6)} y1=${y} y2=${y} class=${`seq-line ${kind}${failed ? " dashed" : ""}`}
            stroke=${kind === "normal" ? threadColor(r.color) : null} marker-end=${`url(#arrow-${kind})`} />
          <text x=${(x1 + x2) / 2} y=${y - 4} class="seq-label">${r.intent}</text>
          <title>${r.body}</title>
        </g>`;
      })}
    </svg>
  </div>`;
}
```

Append to `style.css`:

```css
.sequence { display: block; }
.lane { cursor: pointer; }
.lane-name { font-size: 12px; font-weight: 600; text-anchor: middle; fill: var(--text); }
.lane-name.failed { fill: var(--bad); }
.lane-org { font-size: 10px; text-anchor: middle; }
.lane-axis { stroke: var(--line); stroke-dasharray: 3 3; }
.seq-line { stroke-width: 1.6; }
.seq-line.bad { stroke: var(--bad); } .seq-line.verdict { stroke: var(--ok); stroke-width: 3; }
.seq-line.dashed { stroke-dasharray: 5 3; }
.arrowhead.normal { fill: var(--muted); } .arrowhead.bad { fill: var(--bad); } .arrowhead.verdict { fill: var(--ok); }
.seq-label { font-size: 10px; text-anchor: middle; fill: var(--muted); }
.seq-msg { cursor: pointer; }
.seq-marker.discover { fill: var(--search); } .seq-marker.verify { fill: var(--ok); }
.seq-marker.failed { fill: var(--bad); }
.bracket { fill: none; stroke-width: 2; }
.bracket.working { stroke: var(--pending); } .bracket.completed { stroke: var(--ok); }
.bracket.rejected, .bracket.canceled, .bracket.failed { stroke: var(--bad); }
```

In `app.js`, add `import { SequenceView } from "./views/sequence.js";` and add `sequence: ["Sequence", SequenceView]` to `VIEWS` after `network`. Add `"views/sequence.js"` to `UI_FILES`.

- [ ] **Step 2: Run tests**

Run: `pytest arena/tests/test_arena_ui.py -v && node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS.

- [ ] **Step 3: Manual check (demo replay)**

Check:
- Lanes are grouped by company, and the impostor's lane name is red.
- With `t1` selected, arrows show request, share, decline, and verdict. The decline is red, the verdict is thick green, and the impostor's arrow is dashed red.
- Purple diamonds mark discovery and green diamonds mark verification.
- Hovering an arrow shows the message body. Clicking a lane opens the drawer.
- With "All threads", every thread shows.
- The view follows new rows unless you scroll up.

- [ ] **Step 4: Commit**

```bash
git add arena/ui arena/tests/test_arena_ui.py
git commit -m "feat(arena-ui): sequence view with lanes, intent arrows, and discovery markers"
```

---

### Task 15: Flow view, matrix view, and the pair filter

**Files:**
- Create: `arena/ui/views/flow.js`, `arena/ui/views/matrix.js`
- Modify: `arena/ui/store.js` (`selection.pair`, `chatItems`), `arena/ui/tests/store.test.mjs` (append), `arena/ui/app.js` (`VIEWS`), `arena/ui/style.css` (append), `arena/tests/test_arena_ui.py` (`UI_FILES`)

**Interfaces:**
- Consumes: `flowGraph`, `matrixCells` (Task 12), and the global `dagre`.
- Produces: `selection.pair: [from, to] | null`. `chatItems` filters to messages from `from` to `to` when it is set. A selection that sets `agent`, `thread`, or `allThreads` clears `pair`.
- Produces: `FlowView` (`VIEWS.flow`) and `MatrixView` (`VIEWS.matrix`).

- [ ] **Step 1: Write the failing store test** (append to `store.test.mjs`)

```js
test("pair filter shows one direction and clears on other selections", () => {
  let s = run([
    ev("message.sent", { id: "p1", thread_id: "t1", from_id: "a", to_id: "b", intent: "share", body: "1", color: 0 }),
    ev("message.sent", { id: "p2", thread_id: "t1", from_id: "b", to_id: "a", intent: "reply", body: "2", color: 0 }),
  ]);
  s = select(s, { pair: ["a", "b"] });
  assert.deepEqual(chatItems(s).filter((m) => m.kind === "message").map((m) => m.id), ["p1"]);
  s = select(s, { thread: "t1" });
  assert.equal(s.selection.pair, null);
});
```

Run: `node --test "arena/ui/tests/*.test.mjs"`
Expected: FAIL (the pair is ignored).

- [ ] **Step 2: Update `store.js`**

In `initialSelection()`, add `pair: null`. In `select`, after the line that merges the patch, add:

```js
  if (patch.pair === undefined && ("agent" in patch || "thread" in patch || "allThreads" in patch)) {
    state.selection.pair = null;
  }
```

In `chatItems`, destructure `pair` and add this as the first check inside the filter callback, after the range check:

```js
    if (pair) return m.kind === "message" && m.from === pair[0] && m.to === pair[1];
```

- [ ] **Step 3: Write `arena/ui/views/flow.js`**

```js
// Flow view: one thread as a layered graph, left to right. Loops curve back.
import { html, useMemo } from "../preact.js";
import { chatItems } from "../store.js";
import { flowGraph } from "../lib/layout.js";

const NODE_W = 140;
const NODE_H = 36;

function layoutFlow(g) {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: "LR", nodesep: 30, ranksep: 90, marginx: 20, marginy: 20 });
  graph.setDefaultEdgeLabel(() => ({}));
  g.nodes.forEach((id) => graph.setNode(id, { width: NODE_W, height: NODE_H }));
  g.edges.forEach((e) => graph.setEdge(e.from, e.to, { ...e, width: 70, height: 14 }));
  dagre.layout(graph);
  const nodes = graph.nodes().map((id) => ({ id, ...graph.node(id) }));
  const x = new Map(nodes.map((n) => [n.id, n.x]));
  const edges = graph.edges().map((k) => {
    const e = graph.edge(k);
    return { ...e, back: x.get(e.from) > x.get(e.to) };
  });
  return { nodes, edges, width: graph.graph().width || 0, height: graph.graph().height || 0 };
}

function pathFor(points) {
  const [first, ...rest] = points;
  if (rest.length < 2) return `M${first.x},${first.y} L${rest.map((p) => `${p.x},${p.y}`).join(" ")}`;
  let d = `M${first.x},${first.y}`;
  for (let i = 0; i < rest.length - 1; i += 1) {
    const mid = { x: (rest[i].x + rest[i + 1].x) / 2, y: (rest[i].y + rest[i + 1].y) / 2 };
    d += ` Q${rest[i].x},${rest[i].y} ${mid.x},${mid.y}`;
  }
  const end = rest[rest.length - 1];
  return `${d} L${end.x},${end.y}`;
}

export function FlowView({ store, state }) {
  const { allThreads, thread } = state.selection;
  const threadId = allThreads ? (state.threads.t1 ? "t1" : state.threadOrder[0]) : thread;
  const messages = chatItems({ ...state, selection: { ...state.selection, allThreads: true, agent: null, pair: null } });
  const g = flowGraph(messages, threadId);
  const layout = useMemo(() => (g.nodes.length ? layoutFlow(g) : null),
    [state.lastSeq, threadId, String(state.selection.range)]);
  if (!layout) return html`<p class="muted" style="padding:12px">No messages on ${threadId || "this thread"} yet.</p>`;
  const name = (id) => state.agents[id]?.name || id;
  return html`<div class="view scroll">
    <p class="muted" style="margin:6px 12px">Thread ${threadId}: ${state.threads[threadId]?.title || ""}${allThreads ? " (flow shows one thread)" : ""}</p>
    <svg class="flow" width=${layout.width + 40} height=${layout.height + 40}>
      <defs><marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
        orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="flow-head" /></marker></defs>
      ${layout.edges.map((e) => {
        const mid = e.points[Math.floor(e.points.length / 2)];
        const bad = e.intents.includes("decline") || e.intents.includes("challenge");
        return html`<g>
          <path d=${pathFor(e.points)} class=${`flow-edge${e.back ? " back" : ""}${bad ? " bad" : ""}${e.intents.includes("verdict") ? " verdict" : ""}`}
            marker-end="url(#flow-arrow)" />
          <text x=${mid.x} y=${mid.y - 4} class="flow-label">${e.intents.join("/")} ×${e.count}</text>
        </g>`;
      })}
      ${layout.nodes.map((n) => {
        const a = state.agents[n.id] || {};
        return html`<g class="flow-node" onClick=${() => store.select({ agent: n.id, tab: "overview" })}>
          <rect x=${n.x - NODE_W / 2} y=${n.y - NODE_H / 2} width=${NODE_W} height=${NODE_H} rx="8"
            class=${`flow-box ${a.status || ""}${n.id === g.root ? " root" : ""}${n.id === state.selection.agent ? " selected" : ""}`} />
          <text x=${n.x} y=${n.y + 4} class="flow-name">${name(n.id)}</text>
        </g>`;
      })}
    </svg>
  </div>`;
}
```

- [ ] **Step 4: Write `arena/ui/views/matrix.js`**

```js
// Matrix view: senders by recipients. Shade = count, border = trust result.
import { html } from "../preact.js";
import { agentsByCompany, chatItems } from "../store.js";
import { matrixCells } from "../lib/layout.js";

const CELL = 34;
const HEAD = 130;

export function MatrixView({ store, state }) {
  const ids = agentsByCompany(state).flatMap((g) => g.agents.map((a) => a.id));
  const messages = chatItems({ ...state, selection: { ...state.selection, allThreads: true, agent: null, pair: null } });
  const m = matrixCells(messages, ids);
  const name = (id) => state.agents[id]?.name || id;
  const size = HEAD + ids.length * CELL + 10;
  return html`<div class="view scroll">
    <svg class="matrix" width=${size} height=${size}>
      ${ids.map((id, i) => html`<g>
        <text x=${HEAD - 6} y=${HEAD + i * CELL + CELL / 2 + 4} class=${`m-row ${state.agents[id].status}`}
          onClick=${() => store.select({ agent: id, tab: "overview" })}>${name(id)}</text>
        <text transform=${`translate(${HEAD + i * CELL + CELL / 2 + 4}, ${HEAD - 6}) rotate(-60)`}
          class=${`m-col ${state.agents[id].status}`}>${name(id)}</text>
      </g>`)}
      ${ids.flatMap((from, r) => ids.map((to, c) => {
        const cell = m.cells[`${from}>${to}`];
        const alpha = cell ? 0.15 + 0.85 * (cell.count / m.max) : 0;
        const cls = cell ? (cell.failed ? "failed" : cell.verified ? "verified" : "") : "";
        return html`<rect x=${HEAD + c * CELL} y=${HEAD + r * CELL} width=${CELL - 2} height=${CELL - 2}
          class=${`m-cell ${cls}${from === to ? " self" : ""}`} fill-opacity=${alpha}
          onClick=${() => cell && store.select({ pair: [from, to], agent: null, allThreads: true })}>
          <title>${cell ? `${name(from)} → ${name(to)}: ${cell.count}\n${cell.bodies.join("\n")}` : `${name(from)} → ${name(to)}: none`}</title>
        </rect>`;
      }))}
    </svg>
  </div>`;
}
```

The pair click passes `allThreads: true` and `agent: null` together with `pair`. The `select` rule in Step 2 clears `pair` only when the patch does not set `pair` itself, so this click keeps the pair.

Append to `style.css`:

```css
.flow-edge { fill: none; stroke: var(--muted); stroke-width: 1.6; }
.flow-edge.back { stroke-dasharray: 5 3; }
.flow-edge.bad { stroke: var(--bad); } .flow-edge.verdict { stroke: var(--ok); stroke-width: 3; }
.flow-head { fill: var(--muted); }
.flow-label { font-size: 10px; text-anchor: middle; fill: var(--muted); }
.flow-node { cursor: pointer; }
.flow-box { fill: var(--panel); stroke: var(--pending); stroke-width: 2; }
.flow-box.verified { stroke: var(--ok); } .flow-box.failed { stroke: var(--bad); }
.flow-box.root { stroke-width: 3.5; } .flow-box.selected { fill: var(--panel-2); }
.flow-name { font-size: 12px; text-anchor: middle; fill: var(--text); }
.m-row { font-size: 11px; text-anchor: end; fill: var(--text); cursor: pointer; }
.m-col { font-size: 11px; fill: var(--text); }
.m-row.failed, .m-col.failed { fill: var(--bad); }
.m-cell { fill: var(--accent); stroke: var(--line); cursor: pointer; }
.m-cell.verified { stroke: var(--ok); stroke-width: 2; } .m-cell.failed { stroke: var(--bad); stroke-width: 2.5; }
.m-cell.self { fill: var(--panel-2); fill-opacity: 1; }
```

In `app.js`, import both views and add `flow: ["Flow", FlowView]` and `matrix: ["Matrix", MatrixView]` to `VIEWS`, after `sequence` and before `registry`. Add `"views/flow.js"` and `"views/matrix.js"` to `UI_FILES`.

- [ ] **Step 5: Run tests**

Run: `pytest arena/tests/test_arena_ui.py -v && node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS.

- [ ] **Step 6: Manual check (demo replay)**

Check:
- **Flow:** `t1` is laid out left to right with the SOC as the root (thick border). Replies run back as dashed curves, the decline edge is red, and the verdict edge is thick green. Labels read like `share ×1`. Clicking a node opens the drawer. With "All threads", the view shows `t1` with the note.
- **Matrix:** rows and columns are grouped by company. The cell from the lookalike to the SOC has a red border. Hovering a cell lists messages. Clicking a cell filters the chat to that pair, and choosing a thread chip clears the filter.

- [ ] **Step 7: Commit**

```bash
git add arena/ui arena/tests/test_arena_ui.py
git commit -m "feat(arena-ui): flow view with dagre, matrix view, and pair filter"
```

---

### Task 16: A2A tasks on the receive side and in the sender

**Files:**
- Create: `arena/tasks.py`, `arena/tests/test_arena_tasks.py`
- Modify: `arena/inbox_executor.py`, `arena/transport.py`, `arena/host.py` (per-agent task store), `arena/agent.py` (`receive(message, task_id=None)`, `task_store`), `arena/tests/conftest.py` (`FakeSender` returns `SendResult`), `arena/tests/test_arena_transport.py` (reply type)

**Interfaces:**
- Produces (`arena/tasks.py`):
  - `FINAL = {"completed", "rejected", "canceled", "failed"}`.
  - `async finish_task(store, task_id, state: str, text: str, reply_id: str = "") -> bool`. It sets a final state and returns False if the task is missing or already final.
  - `task_outcome(task) -> Tuple[str, str, str]`, returning `(state, text, reply_id)`.
- Produces: `InboxExecutor(deliver)`, where `deliver(message, task_id)` takes an optional task id.
  - For intent `request`, it returns a Task in state `working` with the ack as its status message.
  - For other intents, it returns a Message ack.
  - `cancel` sets the task to `canceled`.
- Produces: `build_a2a_app(card, executor, store=None)`. When `store` is None it creates its own.
- Produces (`transport.py`):
  - `SendResult(text: str, task_id: Optional[str])`. `A2ASender.send` returns it.
  - `async get_task(base_url, task_id) -> Tuple[str, str, str]`, returning `(state, text, reply_id)`.
  - `async cancel_task(base_url, task_id) -> str`, returning the state.
- Produces: `ArenaAgent.task_store` (an a2a-sdk `InMemoryTaskStore`), which the host sets.

- [ ] **Step 1: Write the failing tests**

`arena/tests/test_arena_tasks.py`:

```python
"""A2A tasks: created for requests, finished by the arena, read and canceled over A2A."""

import asyncio

import httpx
from a2a.server.tasks import InMemoryTaskStore
from fastapi import FastAPI

from arena.card import agent_base_url, build_card
from arena.cast import AgentSpec
from arena.envelope import ArenaMessage, Intent
from arena.identity import Identity
from arena.inbox_executor import InboxExecutor, build_a2a_app
from arena.tasks import finish_task
from arena.transport import A2ASender
from arena.verify import Trust

BASE = "http://arena:8080"
SPEC = AgentSpec.from_dict({
    "slug": "halcyon-intel", "name": "Threat Intel Analyst", "organization": "Halcyon Intel",
    "domain": "halcyon-intel.example", "capability": "threat-intel", "description": "d",
    "needs": [], "model": "sonnet", "role": "investigation", "cadence": [15, 20],
    "system_prompt": "p",
})


def host():
    delivered = []

    async def deliver(message, task_id):
        delivered.append((message.id, task_id))
        return Trust("verified")

    store = InMemoryTaskStore()
    app = FastAPI()
    card = build_card(SPEC, Identity(SPEC.slug, SPEC.domain), BASE)
    app.mount(f"/agents/{SPEC.slug}", build_a2a_app(card, InboxExecutor(deliver), store))
    sender = A2ASender(lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app)))
    return delivered, store, sender, agent_base_url(BASE, SPEC.slug)


def message(intent, msg_id="m1"):
    return ArenaMessage(
        id=msg_id, thread_id="t1", from_id="northgate-soc.northgate.example",
        to_id="halcyon-intel.halcyon-intel.example", from_did="d1", to_did="d2", ts=1.0,
        intent=intent, body="Do these domains match?", card_url=f"{BASE}/c", sig="s")


def test_request_creates_a_working_task_and_other_intents_do_not():
    delivered, _, sender, base = host()
    result = asyncio.run(sender.send(base, message(Intent.REQUEST)))
    assert result.task_id
    assert result.text == "ack m1 verified"
    assert delivered == [("m1", result.task_id)]
    state, _, _ = asyncio.run(sender.get_task(base, result.task_id))
    assert state == "working"
    share = asyncio.run(sender.send(base, message(Intent.SHARE, "m2")))
    assert share.task_id is None and share.text == "ack m2 verified"
    assert delivered[-1] == ("m2", None)


def test_finished_task_is_read_back_over_a2a():
    _, store, sender, base = host()
    task_id = asyncio.run(sender.send(base, message(Intent.REQUEST))).task_id
    assert asyncio.run(finish_task(store, task_id, "completed", "Overlap with InvoiceDrop.", "r9"))
    assert asyncio.run(sender.get_task(base, task_id)) == ("completed", "Overlap with InvoiceDrop.", "r9")
    assert not asyncio.run(finish_task(store, task_id, "rejected", "late"))


def test_rejected_and_canceled_tasks():
    _, store, sender, base = host()
    first = asyncio.run(sender.send(base, message(Intent.REQUEST))).task_id
    asyncio.run(finish_task(store, first, "rejected", "Sender failed verification."))
    assert asyncio.run(sender.get_task(base, first))[:2] == ("rejected", "Sender failed verification.")
    second = asyncio.run(sender.send(base, message(Intent.REQUEST, "m3"))).task_id
    assert asyncio.run(sender.cancel_task(base, second)) == "canceled"
```

In `arena/tests/test_arena_transport.py`:
- The three assertions that compare the reply to a string now compare `.text`. For example, `asyncio.run(sender.send(...)).text == "ack m1 verified"`.
- In `host_with_inbox`, change `deliver(message)` to `deliver(message, task_id=None)`.

- [ ] **Step 2: Run to verify failure**

Run: `pytest arena/tests/test_arena_tasks.py -v`
Expected: FAIL (`arena.tasks` missing).

- [ ] **Step 3: Implement `arena/tasks.py`**

```python
"""A2A task helpers: finish a task in a local store, read a task's outcome."""

import uuid
from typing import Tuple

from a2a.server.tasks import TaskStore
from a2a.types import Artifact, Part, Task, TaskState, TaskStatus, TextPart
from a2a.utils import new_agent_text_message

FINAL = {"completed", "rejected", "canceled", "failed"}


async def finish_task(
    store: TaskStore, task_id: str, state: str, text: str, reply_id: str = ""
) -> bool:
    """Move a task to a final state.

    Args:
        store: The recipient's task store.
        task_id: The task to finish.
        state: "completed" or "rejected".
        text: The reply body (artifact for completed, status message for rejected).
        reply_id: Id of the arena message that answered the request.

    Returns:
        False when the task does not exist or is already final.
    """
    task = await store.get(task_id)
    if task is None or task.status.state.value in FINAL:
        return False
    task.status = TaskStatus(
        state=TaskState(state),
        message=new_agent_text_message(text, context_id=task.context_id, task_id=task.id),
    )
    if state == "completed":
        task.artifacts = [Artifact(
            artifact_id=uuid.uuid4().hex, name="reply",
            parts=[Part(root=TextPart(text=text))], metadata={"reply_id": reply_id},
        )]
    else:
        task.metadata = {**(task.metadata or {}), "reply_id": reply_id}
    await store.save(task)
    return True


def task_outcome(task: Task) -> Tuple[str, str, str]:
    """(state, text, reply_id) of a task read over A2A."""
    state = task.status.state.value
    if task.artifacts:
        artifact = task.artifacts[-1]
        text = "".join(p.root.text for p in artifact.parts if isinstance(p.root, TextPart))
        return state, text, (artifact.metadata or {}).get("reply_id", "")
    message = task.status.message
    text = "".join(p.root.text for p in message.parts if isinstance(p.root, TextPart)) if message else ""
    return state, text, (task.metadata or {}).get("reply_id", "")
```

- [ ] **Step 4: Update `arena/inbox_executor.py`**

Replace the `Deliver` alias, `execute`, `cancel`, and `build_a2a_app` with:

```python
Deliver = Callable[[ArenaMessage, Optional[str]], Awaitable[Trust]]


class InboxExecutor(AgentExecutor):
    """Executor that hands each envelope to the recipient agent's inbox.

    A `request` gets an A2A Task in state working. The arena finishes it later
    when the recipient answers. Other intents get a Message ack.

    Args:
        deliver: The recipient's receive coroutine (message, task_id) -> Trust.
    """

    def __init__(self, deliver: Deliver) -> None:
        self._deliver = deliver

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        metadata = (context.message.metadata or {}) if context.message else {}
        raw = metadata.get("arena")
        if raw is None:
            await self._reply(context, event_queue, "rejected: missing arena envelope")
            return
        try:
            message = ArenaMessage.model_validate(raw)
        except ValidationError:
            await self._reply(context, event_queue, "rejected: invalid envelope")
            return
        if message.intent is not Intent.REQUEST:
            trust = await self._deliver(message, None)
            await self._reply(context, event_queue, f"ack {message.id} {trust.status}")
            return
        task = context.current_task or new_task(context.message)
        await event_queue.enqueue_event(task)
        trust = await self._deliver(message, task.id)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.update_status(
            TaskState.working,
            message=updater.new_agent_message(
                [Part(root=TextPart(text=f"ack {message.id} {trust.status}"))]
            ),
        )

    async def _reply(self, context: RequestContext, event_queue: EventQueue, text: str) -> None:
        await event_queue.enqueue_event(
            new_agent_text_message(text, context_id=context.context_id)
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            raise ServerError(error=UnsupportedOperationError())
        await TaskUpdater(event_queue, task.id, task.context_id).cancel()


def build_a2a_app(
    card: AgentCard, executor: AgentExecutor, store: Optional[TaskStore] = None
) -> FastAPI:
    """A2A JSON-RPC app that serves the card at /.well-known/agent-card.json."""
    handler = DefaultRequestHandler(
        agent_executor=executor, task_store=store or InMemoryTaskStore()
    )
    return A2AFastAPIApplication(agent_card=card, http_handler=handler).build()
```

Update the imports:

```python
from typing import Awaitable, Callable, Optional

from a2a.server.tasks import InMemoryTaskStore, TaskStore, TaskUpdater
from a2a.types import AgentCard, Part, TaskState, TextPart, UnsupportedOperationError
from a2a.utils import new_agent_text_message, new_task
from arena.envelope import ArenaMessage, Intent
```

Keep the existing `ValidationError`, `FastAPI`, and `ServerError` imports.

- [ ] **Step 5: Update `arena/transport.py`**

```python
@dataclass(frozen=True)
class SendResult:
    text: str
    task_id: Optional[str] = None
```

In `send_raw`, return `SendResult` and read the task id when the final event is a `(Task, update)` tuple:

```python
        if isinstance(final, tuple):
            task = final[0]
            return SendResult(task_outcome(task)[1], task.id)
        return SendResult(_reply_text(final))
```

The `send` method's return type becomes `SendResult`. Add the methods `get_task` and `cancel_task`. They share a `_client` helper that resolves the card and builds the client:

```python
    async def _with_client(self, base_url: str, call):
        async with self._http_factory() as http:
            try:
                card = await A2ACardResolver(httpx_client=http, base_url=base_url).get_agent_card()
                client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)
                return await call(client)
            except Exception as e:  # a2a-sdk raises several client error types
                raise SendError(f"A2A call to {base_url} failed: {e}") from e

    async def get_task(self, base_url: str, task_id: str) -> Tuple[str, str, str]:
        task = await self._with_client(base_url, lambda c: c.get_task(TaskQueryParams(id=task_id)))
        return task_outcome(task)

    async def cancel_task(self, base_url: str, task_id: str) -> str:
        task = await self._with_client(base_url, lambda c: c.cancel_task(TaskIdParams(id=task_id)))
        return task.status.state.value
```

Rewrite `send_raw` to use `_with_client`. It replaces the earlier version, including the `SendResult` lines above:

```python
    async def send_raw(
        self, base_url: str, metadata: Optional[Dict[str, Any]], text: str
    ) -> SendResult:
        a2a_message = Message(
            role=Role.user,
            message_id=str(uuid.uuid4()),
            parts=[Part(root=TextPart(text=text))],
            metadata=metadata,
        )

        async def call(client):
            final = None
            async for event in client.send_message(a2a_message):
                final = event
            return final

        final = await self._with_client(base_url, call)
        if isinstance(final, tuple):
            task = final[0]
            return SendResult(task_outcome(task)[1], task.id)
        return SendResult(_reply_text(final))
```

Update the imports to include `dataclass`, `Optional`, `Tuple`, `TaskIdParams`, `TaskQueryParams`, and `from arena.tasks import task_outcome`.

- [ ] **Step 6: Wire the store and the new deliver signature**

In `arena/agent.py`:
- Change `receive(self, message)` to `receive(self, message, task_id=None)`. The body is unchanged in this task; Task 17 uses `task_id`.
- Add `self.task_store = None` in `__init__`.
- In `_send`, the sender now returns a `SendResult`. Keep the success path unchanged: `await self.ctx.sender.send(...)` still counts as success.

In `arena/host.py` `_add_agent`, create `store = InMemoryTaskStore()`, set `agent.task_store = store`, and call `build_a2a_app(card, InboxExecutor(agent.receive), store)`. Add `from a2a.server.tasks import InMemoryTaskStore`.

In `arena/tests/conftest.py`, make `FakeSender.send` return `SendResult(f"ack {message.id} verified", None)`. Add `from arena.transport import SendError, SendResult` and drop the local import in `send`.

- [ ] **Step 7: Run tests**

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add arena/ arena/tests/
git commit -m "feat(arena): A2A tasks for requests, task store per agent, sender task API"
```

---

### Task 17: Task linking, polling, and cancellation in the agent loop

**Files:**
- Modify: `arena/agent.py`, `arena/tests/conftest.py` (`FakeSender` task methods)
- Test: `arena/tests/test_arena_tasks_flow.py`

**Interfaces:**
- Consumes: `finish_task`, `FINAL` (Task 16); `SendResult`; `sender.get_task` and `sender.cancel_task`.
- Produces: `task.created {task_id, requester, recipient, message_id, thread_id}`. The recipient publishes it in `receive`, when `task_id` is set.
- Produces: `task.updated {task_id, state, artifact, reason, reply_id}`. The requester publishes it when it observes a final state through `tasks/get` or `tasks/cancel`.
- Produces on `ArenaAgent`:
  - `open_requests: Dict[str, Dict]`, keyed by task id. Each entry is `{task_id, recipient, thread_id, message_id, base_url}`.
  - `received_tasks: Dict[Tuple[str, str], List[str]]`, keyed by `(requester, thread_id)`, oldest first.
  - `async poll_tasks() -> None`, called at the start of `tick`.
- Link rule: after a successful send of `reply`, `share`, `decline`, or `challenge` to X on thread T, the sender pops the oldest entry in `received_tasks[(X, T)]`. `reply`/`share` complete it. `decline`/`challenge` reject it. The text is the body, and `reply_id` is the message id.

- [ ] **Step 1: Write the failing tests**

`arena/tests/test_arena_tasks_flow.py`:

```python
"""Request → task → reply → observed by the requester, with real in-process A2A."""

import asyncio

from conftest import INTEL, SOC, make_arena, make_cast

SOC_ID = "northgate-soc.northgate.example"
INTEL_ID = "halcyon-intel.halcyon-intel.example"


def decision(to, intent, body, thread_id="t1"):
    return {"action": "send", "to": to, "thread_id": thread_id, "intent": intent, "body": body}


def updates(arena):
    return [e["data"] for e in arena.bus.history if e["type"] == "task.updated"]


def created(arena):
    return [e["data"] for e in arena.bus.history if e["type"] == "task.created"]


def build(scripts):
    arena = make_arena(make_cast(SOC, INTEL, owner="northgate-soc", closer="northgate-soc"), scripts)
    asyncio.run(arena.setup())
    arena.ctx.running.set()
    return arena


def test_reply_completes_the_request_and_the_requester_observes_it():
    steps = iter([decision(INTEL_ID, "request", "Seen these domains?"), {"action": "wait"}])
    arena = build({"northgate-soc": lambda p: next(steps),
                   "halcyon-intel": lambda p: decision(SOC_ID, "reply", "Yes: InvoiceDrop.")})
    soc, intel = arena.agents["northgate-soc"], arena.agents["halcyon-intel"]
    asyncio.run(soc.tick())
    task = created(arena)[0]
    assert (task["requester"], task["recipient"]) == (SOC_ID, INTEL_ID)
    assert task["task_id"] in soc.open_requests
    asyncio.run(intel.tick())
    asyncio.run(soc.tick())
    reply_id = [e["data"]["id"] for e in arena.bus.history
                if e["type"] == "message.sent" and e["data"]["from_id"] == INTEL_ID][0]
    assert updates(arena) == [{"task_id": task["task_id"], "state": "completed",
                               "artifact": "Yes: InvoiceDrop.", "reason": "", "reply_id": reply_id}]
    assert soc.open_requests == {}


def test_decline_rejects_and_the_oldest_request_is_answered_first():
    steps = iter([decision(INTEL_ID, "request", "first"), decision(INTEL_ID, "request", "second"),
                  {"action": "wait"}])
    arena = build({"northgate-soc": lambda p: next(steps),
                   "halcyon-intel": lambda p: decision(SOC_ID, "decline", "Not sharing.")})
    soc, intel = arena.agents["northgate-soc"], arena.agents["halcyon-intel"]
    asyncio.run(soc.tick())
    asyncio.run(soc.tick())
    first, second = [t["task_id"] for t in created(arena)]
    asyncio.run(intel.tick())
    asyncio.run(soc.tick())
    assert updates(arena) == [{"task_id": first, "state": "rejected", "artifact": "",
                               "reason": "Not sharing.", "reply_id": updates(arena)[0]["reply_id"]}]
    assert list(soc.open_requests) == [second]


def test_open_task_is_canceled_when_thread_closes():
    steps = iter([decision(INTEL_ID, "request", "q"), {"action": "wait"}])
    arena = build({"northgate-soc": lambda p: next(steps)})
    soc = arena.agents["northgate-soc"]
    asyncio.run(soc.tick())
    task_id = created(arena)[0]["task_id"]
    thread = arena.ctx.threads.get("t1")
    thread.closed, thread.close_reason = True, "verdict"
    asyncio.run(soc.tick())
    assert updates(arena)[0]["task_id"] == task_id
    assert updates(arena)[0]["state"] == "canceled"


def test_completed_task_is_not_canceled_on_thread_close():
    steps = iter([decision(INTEL_ID, "request", "q"), {"action": "wait"}])
    arena = build({"northgate-soc": lambda p: next(steps),
                   "halcyon-intel": lambda p: decision(SOC_ID, "reply", "answer")})
    soc, intel = arena.agents["northgate-soc"], arena.agents["halcyon-intel"]
    asyncio.run(soc.tick())
    asyncio.run(intel.tick())
    thread = arena.ctx.threads.get("t1")
    thread.closed, thread.close_reason = True, "verdict"
    asyncio.run(soc.tick())
    assert [u["state"] for u in updates(arena)] == ["completed"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest arena/tests/test_arena_tasks_flow.py -v`
Expected: FAIL (`open_requests` attribute missing).

- [ ] **Step 3: Implement in `arena/agent.py`**

Add the imports `from arena.tasks import FINAL, finish_task` and `List`, `Tuple` from typing. In `__init__`:

```python
        self.open_requests: Dict[str, Dict[str, str]] = {}
        self.received_tasks: Dict[Tuple[str, str], List[str]] = {}
```

At the end of `receive`, before the `return trust`, add:

```python
        if task_id:
            self.received_tasks.setdefault((message.from_id, message.thread_id), []).append(task_id)
            self.ctx.bus.publish("task.created", {
                "task_id": task_id, "requester": message.from_id, "recipient": self.agent_id,
                "message_id": message.id, "thread_id": message.thread_id,
            })
```

Add these methods:

```python
    async def _finish_received(self, message: ArenaMessage) -> None:
        """Link rule: an answer finishes the oldest open request from that agent."""
        if message.intent.value not in ("reply", "share", "decline", "challenge"):
            return
        queue = self.received_tasks.get((message.to_id, message.thread_id)) or []
        if not queue or self.task_store is None:
            return
        task_id = queue.pop(0)
        state = "completed" if message.intent.value in ("reply", "share") else "rejected"
        await finish_task(self.task_store, task_id, state, message.body, message.id)

    def _observed(self, task_id: str, state: str, text: str, reply_id: str) -> None:
        self.open_requests.pop(task_id, None)
        self.ctx.bus.publish("task.updated", {
            "task_id": task_id, "state": state,
            "artifact": text if state == "completed" else "",
            "reason": "" if state == "completed" else text, "reply_id": reply_id,
        })

    async def poll_tasks(self) -> None:
        """Read up to 5 open requests over A2A; cancel those on closed threads."""
        for request in list(self.open_requests.values())[:5]:
            thread = self.ctx.threads.get(request["thread_id"])
            try:
                state, text, reply_id = await self.ctx.sender.get_task(
                    request["base_url"], request["task_id"])
                if state in FINAL:
                    self._observed(request["task_id"], state, text, reply_id)
                elif thread is not None and thread.closed:
                    state = await self.ctx.sender.cancel_task(
                        request["base_url"], request["task_id"])
                    self._observed(request["task_id"], state, "thread closed", "")
            except SendError as e:
                logger.warning(f"{self.agent_id}: task poll failed: {e}")
```

In `tick`, call `await self.poll_tasks()` as the first statement, before the rate pre-check. In the success path of `tick`, after `closed = self.ctx.threads.append(message)`, add:

```python
        await self._finish_received(message)
```

Change `_send` so it keeps the `SendResult`. On success, store the task id:

```python
            try:
                result = await self.ctx.sender.send(target.base_url, message)
                if result.task_id:
                    self.open_requests[result.task_id] = {
                        "task_id": result.task_id, "recipient": message.to_id,
                        "thread_id": message.thread_id, "message_id": message.id,
                        "base_url": target.base_url,
                    }
                return None
```

In `arena/tests/conftest.py`, add to `FakeSender`:

```python
    async def get_task(self, base_url, task_id):
        return "working", "", ""

    async def cancel_task(self, base_url, task_id):
        return "canceled"
```

- [ ] **Step 4: Run tests**

Run: `pytest -v`
Expected: PASS. If `test_arena_integration.py` now sees extra `task.*` events, its assertions still hold: it filters by event type.

- [ ] **Step 5: Commit**

```bash
git add arena/agent.py arena/tests/
git commit -m "feat(arena): link replies to A2A tasks, poll with tasks/get, cancel on thread close"
```

---

### Task 18: Tasks in the UI

**Files:**
- Modify: `arena/ui/store.js` (`replyId`), `arena/ui/tests/store.test.mjs` (append), `arena/ui/components/drawer.js` (Activity tasks), `arena/ui/views/sequence.js` (`taskBrackets`)

**Interfaces:**
- Consumes: `task.created` and `task.updated` (now with `reply_id`).
- Produces: `state.tasks[id].replyId`, task lists in the Activity tab, and brackets in the Sequence view.

- [ ] **Step 1: Write the failing test** (append to `store.test.mjs`)

```js
test("task updates keep the reply id", () => {
  const s = run([
    ev("task.created", { task_id: "k2", requester: "a", recipient: "b", message_id: "m1", thread_id: "t1" }),
    ev("task.updated", { task_id: "k2", state: "completed", artifact: "x", reason: "", reply_id: "m2" }),
  ]);
  assert.equal(s.tasks.k2.replyId, "m2");
});
```

Run: `node --test "arena/ui/tests/*.test.mjs"`
Expected: FAIL (`replyId` is undefined).

- [ ] **Step 2: Update `store.js`**

In the `task.created` case, add `replyId: ""` to the new task object. In `task.updated`, add `replyId: d.reply_id || ""` to the `Object.assign` call.

- [ ] **Step 3: Activity tab tasks** (in `components/drawer.js`, inside `Activity`, after the "Recent decisions" list)

```js
    <h4>Tasks</h4>
    ${(() => {
      const mine = Object.values(state.tasks).filter((t) => t.requester === agent.id || t.recipient === agent.id);
      if (!mine.length) return html`<p class="muted">No A2A tasks.</p>`;
      return html`<ul>${mine.map((t) => html`<li><span class=${`chip task ${t.state}`}>${t.state}</span>
        ${t.requester === agent.id ? `→ ${state.agents[t.recipient]?.name || t.recipient}` : `← ${state.agents[t.requester]?.name || t.requester}`}
        <span class="muted"> ${t.threadId}${t.reason ? ` · ${t.reason}` : ""}</span></li>`)}</ul>`;
    })()}
```

- [ ] **Step 4: Sequence brackets** (replace `taskBrackets` in `views/sequence.js`)

```js
export function taskBrackets(rows, state) {
  const rowOf = new Map(rows.filter((r) => r.kind === "message").map((r) => [r.id, r]));
  const brackets = [];
  for (const task of Object.values(state.tasks)) {
    const start = rowOf.get(task.messageId);
    if (!start) continue;
    const end = task.replyId ? rowOf.get(task.replyId) : rows[rows.length - 1];
    if (!end) continue;
    const lanes = agentsByCompany(state).flatMap((g) => g.agents.map((a) => a.id));
    const x = LEFT + lanes.indexOf(task.requester) * LANE_W + LANE_W / 2 - 14;
    const y1 = TOP + start.index * ROW_H + 10;
    const y2 = TOP + end.index * ROW_H + 10;
    brackets.push({ path: `M${x + 8},${y1} H${x} V${y2} H${x + 8}`, state: task.state,
      label: `task ${task.id}: ${task.state}${task.reason ? ` (${task.reason})` : ""}` });
  }
  return brackets;
}
```

- [ ] **Step 5: Run tests**

Run: `pytest arena/tests/test_arena_ui.py -v && node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS.

- [ ] **Step 6: Regenerate the demo log and check manually**

```bash
PYTHONPATH=agent:. python arena/scripts/make_demo_log.py --out runs/demo.jsonl
```

In the demo replay, check:
- The SOC's request bubble shows a task chip that changes to `completed` or `rejected` when the requester observes it.
- The Sequence view draws a bracket on the SOC's lane from the request to the answer.
- The Activity tab lists the task with its state.

- [ ] **Step 7: Commit**

```bash
git add arena/ui
git commit -m "feat(arena-ui): show A2A task state in chat, activity, and sequence brackets"
```

---

### Task 19: Documentation and final checks

**Files:**
- Modify: `arena/README.md` (Step 5 "Open the UI", Step 6, a new "Workbench views" section), `README.md` (one line)
- Modify (local only, gitignored): `CLAUDE.md` (the `ui/` bullet)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Update `arena/README.md`**

Replace "Step 5: Open the UI" with a Workbench description, in STE style:
- The layout: top bar, sidebar (agents and registry summary), view switch (Network, Sequence, Flow, Matrix, Registry), timeline strip (Register, Discover, Verify, Message), and right column (chat, or the agent drawer).
- The selection rules: click to select; drag on the timeline to set a range; Esc clears.
- The drawer tabs and what each shows.
- The registry browser and its Organizations tab.
- A2A tasks: request bubbles show the task state.
- How to make a credit-free demo: `PYTHONPATH=agent:. python arena/scripts/make_demo_log.py`, then replay `demo`.
- Note the log size: run logs include full turn prompts, about 5–10 MB for a 20-minute run.

In Step 6 "Watch the run", add what the discovery highlight shows. Add `node --test "arena/ui/tests/*.test.mjs"` to "Run the tests".

- [ ] **Step 2: Update `CLAUDE.md` (local only)**

Replace the `ui/` bullet with: `ui/: Workbench (Preact + htm from a CDN, no build). store.js is the pure event store; components/ and views/ render it; lib/ holds pure layout helpers. JS tests: node --test "arena/ui/tests/*.test.mjs".`

- [ ] **Step 3: Full verification**

Run: `pytest && node --test "arena/ui/tests/*.test.mjs"`
Expected: PASS for both.

Then run a free live dry run: `ARENA_MAX_MODEL_CALLS=0 docker compose up -d --build`. Open the Workbench and check:
- Every agent's registration stepper.
- The registry browser.
- The live card.

Run `docker compose down`.

- [ ] **Step 4: Commit**

```bash
git add arena/README.md README.md
git commit -m "docs(arena): Workbench guide, demo log, and JS tests"
```

---

## Spec Coverage

| Spec section | Tasks |
|---|---|
| §1 criteria 1 (registration steps) | 4, 9 |
| §1 criteria 2 (discovery intent) | 2, 3, 9, 13 |
| §1 criteria 3 (agent detail) | 2, 5, 9 |
| §1 criteria 4 (registry browser) | 1, 5, 10 |
| §1 criteria 5 (four views + selection) | 7, 12, 13, 14, 15 |
| §1 criteria 6 (chat) | 11 |
| §1 criteria 7 (A2A tasks) | 16, 17, 18 |
| §1 criteria 8 (replay) | 6 (prompts in log, old-format tolerance), 9 ("not available in replay") |
| §1 criteria 9 (tests) | every task |
| §4 backend observability | 1–5 |
| §5 shell, selection, drawer, registry | 6–10 |
| §6 chat | 11 |
| §7 views | 12–15 |
| §8 A2A tasks | 16–18 |
| §9 error handling | 5 (404/502), 7 (CDN failure, unknown events), 9 (card fallback), 10 (registry banner), 17 (poll failure, cancel) |
| §10 testing | 6 (contract, node --test), all tasks |
| §11 carried-over minors | 2 + 4 (thread cap), 6 (replay mode label) |
