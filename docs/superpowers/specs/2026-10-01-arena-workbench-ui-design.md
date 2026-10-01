# ACDP Arena Workbench UI — Design Spec

Date: 2026-10-01. Owner: Dean De Beer. Status: draft for review.
Builds on: `docs/superpowers/specs/2026-10-01-acdp-agent-arena-design.md` (the arena spec). This spec replaces §9 (UI) of that spec and extends §5–§7.

## 1. Purpose

Engineers use the arena internally to study how agents register, discover, verify, and talk. The current UI shows only a force graph and a flat transcript. It hides the registration steps, the discovery steps, the registry state, the Agent Cards, and the model's prompts and decisions. This spec makes all of that visible and explorable.

Audience: engineers on laptops and wide monitors, exploring at their own pace. Not a presenter mode.

### Success criteria

1. A user can follow one agent's registration through seven named steps, including each registry check with its result.
2. A user can see each discovery query: capability, results with registry status, the peer the model picked, and the model's stated need and reason.
3. A user can open any agent and read its live Agent Card, system prompt, last turn prompt, last decisions, threads, inbox, discovery history, and trust map.
4. A user can browse the registry: entries, verification records, stored versus live cards, and organization anchors.
5. A user can switch between four graph views (Network, Sequence, Flow, Matrix) without losing the selection.
6. The transcript reads as chat, one thread at a time, with an "All threads" view.
7. `request` messages create A2A Tasks. Their state (working, completed, rejected, canceled) is visible in the chat, the Activity tab, and the Sequence view.
8. A replay of a saved run shows all of the above except live-only data, which is labelled "not available in replay".
9. `pytest` and `node --test` pass with no API key and no network.

## 2. Decisions

| # | Decision | Reason |
|---|---|---|
| U1 | Workbench layout: left sidebar, center view area with timeline strip, right chat column, agent drawer over the chat. | One screen for engineers on wide monitors; the drawer keeps the graph visible. |
| U2 | Four graph views: Network, Sequence, Flow, Matrix. | Topology, time, investigation shape, and dense overview each answer a different question. |
| U3 | Chat shows one thread at a time with thread chips, plus an "All threads" chip for the merged feed. | One conversation reads clearly; the merged feed shows concurrency on demand. |
| U4 | Search intent comes from the model: `TurnDecision` gains `looking_for` and `why_this_peer`. Discovery queries stay deterministic (`needs`). | Shows intent without changing the agent loop or adding model calls. |
| U5 | Full turn prompts are written to the event log. | Replays show prompts. Cost: logs grow about 5–10x. |
| U6 | UI stack: Preact + htm from a CDN, ES modules, no build step. `force-graph@1` and `dagre` from jsDelivr. | Components for a larger UI, and the repo keeps no Node toolchain. |
| U7 | `request` messages create A2A Tasks; replies complete or reject them by a deterministic link rule. | Exercises the A2A task model; makes open requests visible. Built last. |

## 3. Phases

1. **Backend observability** (§4).
2. **Workbench shell** (§5): store, layout, sidebar, legend, timeline, drawer, registry browser, add-agent dialog.
3. **Chat** (§6).
4. **Graph views** (§7).
5. **A2A tasks** (§8).

Each phase leaves the arena working. The current UI stays until Phase 2 replaces it.

## 4. Backend observability (Phase 1)

### 4.1 Events

All events go to the bus and the JSONL log.

| Event | Data | Notes |
|---|---|---|
| `registration.step` | `{id, step, status, detail}` | `step` is one of `identity`, `zone`, `dns`, `card`, `submitted`, `checks`, `result`. `status` is `ok`, `failed`, or `skipped`. |
| `agent.registered` | add `system_prompt`, `needs`, `cadence`, `capability` | Emitted at the `identity` step, as today. |
| `discovery.query` | `{agent, capability, results: [{id, name, organization, domain, status, new}]}` | `status` is the registry verification status. `new` is true when the agent did not see that id in its previous query for the same capability. |
| `decision.made` | `{agent, prompt, decision, outcome}` | Every model output, including `wait`. `outcome` is `sent`, `wait`, or `rejected: <reason>`. `prompt` is the full turn prompt. |
| `message.sent` | add `looking_for`, `why_this_peer` | Copied from the decision. |

`registration.step` detail by step:

| Step | Detail |
|---|---|
| `identity` | `did`, `fingerprint` |
| `zone` | `zone`, `result` (`created` or `exists`) |
| `dns` | `srv` (`host:port`), `txt` (the TXT strings as published), or `skipped` for `no_txt` |
| `card` | `card_url` |
| `submitted` | none |
| `checks` | the registry's `verification` record unchanged (`card_fetched`, `dns_found`, `key_matches_dns`, `org_conflict`, `canonical_domain`, `reasons`, `checked_at`) |
| `result` | `status` (`verified` or `failed`), `reasons` |

`agent.verified` and `agent.verification_failed` stay for compatibility.

### 4.2 Decision fields

`TurnDecision` gains `looking_for: str` and `why_this_peer: str`, each at most 200 characters, default empty. `RULES` adds: "When you send, fill looking_for (what you need from this peer) and why_this_peer (why this peer and not another)."

### 4.3 Per-agent state

`ArenaAgent` keeps, in memory: last turn prompt, last decision, the last 20 `decision.made` records, the last 20 discovery queries, counters (`sent`, `received`, `rejected`, `errors`), DNS records as published, and state (`running`, `paused`, `waiting`, `stopped`).

### 4.4 Read APIs

| Method and path | Response |
|---|---|
| `GET /arena/agents` | List of agent summaries: id, slug, name, organization, domain, capability, needs, model, role, state, counters, verification status. |
| `GET /arena/agents/{slug}` | Detail: summary plus system prompt, last prompt, last decision, last 20 decisions, threads (id, title, owner, open, count), pending inbox (sender, intent, trust), trust map, last 20 queries, DNS records. `404` for an unknown slug. |
| `GET /arena/registry` | Proxy of registry `GET /agents`. `502 {"error"}` when the registry is unreachable. |
| `GET /arena/registry/agents/{id}/card` | Proxy of registry `GET /agents/{id}/card` (the stored card). `404` or `502` as above. |
| `GET /arena/registry/orgs` | Proxy of the new registry `GET /orgs`. |

Registry change: `GET /orgs` returns `{"orgs": [{"organization", "canonical_domain"}]}`.

The live card needs no new endpoint: `GET /agents/{slug}/.well-known/agent-card.json`.

## 5. Workbench shell (Phase 2)

### 5.1 Files (`arena/ui/`)

| File | Responsibility |
|---|---|
| `index.html` | Loads Preact, htm, force-graph, dagre from jsDelivr (major-pinned) and `app.js`. Shows a clear message if a library fails to load. |
| `store.js` | One state object built only from events: agents, registration steps, threads, messages, decisions, queries, tasks, timeline entries, selection (agent, thread, time range), mode (live, replay, idle). Pure reducer `apply(state, event)`; subscribers re-render. Resets on WebSocket connect and on `bus.reset`. |
| `app.js` | Layout and WebSocket connection. |
| `palette.js` | Company colors, thread colors, trust colors as CSS tokens with dark-mode variants. |
| `components/topbar.js` | Run id, mode, counters, Pause/Resume, replay picker and speed, "+ Agent". |
| `components/sidebar.js` | Agent list (status dot, model badge, company color), registry summary (counts). |
| `components/viewswitch.js` | Network, Sequence, Flow, Matrix, Registry. |
| `components/timeline.js` | Four lanes: Register, Discover, Verify, Message. Hover shows a summary; click selects; drag sets the time range. |
| `components/drawer.js` | Agent drawer with tabs Overview, Card, Prompts, Activity, Discovery. |
| `components/registry.js` | Registry table with search and status filter, expandable rows, Organizations sub-tab. |
| `components/chat.js` | §6. |
| `components/legend.js` | Collapsible legend in the graph area. |
| `components/addagent.js` | Add-agent dialog (inputs unchanged from the arena README). |
| `views/network.js`, `views/sequence.js`, `views/flow.js`, `views/matrix.js` | §7. |
| `lib/layout.js` | Pure functions: flow layering, matrix aggregation, hull label position, sequence time scale. |

### 5.2 Selection model

One selection drives everything. Selecting an agent (node, lane, matrix row, sidebar row, chat avatar, registry row) highlights it in every view, opens its drawer, and filters the chat to messages it sent or received. Selecting a thread (chat chip) filters the views that use threads. Dragging on the timeline sets a time range; views and chat show only events in that range. Esc clears the selection.

### 5.3 Drawer tabs

| Tab | Content | Source |
|---|---|---|
| Overview | Role, capability, needs, cadence, state, counters; seven-step registration stepper; DNS records. | Store (registration steps); `/arena/agents/{slug}` for state in live mode. |
| Card | Rendered card summary (name, provider, skills, ACDP extension: DID, domain, fingerprint, model) and raw JSON with copy. On fetch failure: the error and the stored registry card. | Live card URL; registry proxy as fallback. |
| Prompts | System prompt; last turn prompt; last decision JSON and its outcome. | Store (`decision.made`, `agent.registered`). |
| Activity | Agenda; threads; pending inbox (live only); last 20 decisions with outcomes; tasks (Phase 5). | Store; `/arena/agents/{slug}` for the inbox. |
| Discovery | Each query: capability, results with status and "new" badge, the peer picked, `looking_for`, `why_this_peer`. Trust map with reasons. | Store. |

In replay, data that only the live API provides shows "not available in replay".

### 5.4 Registry browser

Replaces the graph area when selected. Table columns: agent, organization, capability, status, last seen. Search over name, organization, capability, domain; filter All / Verified / Failed. An expanded row shows the stored entry, each verification check with ✓/✕ and reasons, the organization anchor, and the stored card beside the live card with differences highlighted. Organizations sub-tab: organization → canonical domain → agents that claim it. If the registry is unreachable, a banner says so.

## 6. Chat (Phase 3)

- Thread chips: one per thread (title, message count, unread dot, closed marker) and "All threads". Default: `t1`.
- Message bubble: company-color avatar with S/H, sender name and organization, recipient, intent, time, trust badge (the recipient's check result). A purple line shows `looking_for` and `why_this_peer` when present.
- Replies to a previous message from the other party are indented. Failed-trust bubbles have a dashed red border.
- System events (joins, verification, thread open/close) are centered divider lines.
- The feed follows new messages unless the user scrolls up; a "new messages" pill jumps to the end.
- "All threads" shows every message in time order with a colored thread rail.

## 7. Graph views (Phase 4)

| View | Layout | Encodings |
|---|---|---|
| Network | `force-graph` with company clusters. Each company is a convex hull with a label on its edge in screen-space pixels (it does not grow with zoom). | Node: short name, S/H badge, trust border. Edge: one curved edge per pair per thread, width = message count; decline/challenge in red. Discovery highlight: pulse ring and dashed purple lines to each result with the capability label for about 2 s; others dimmed; "new" badge on new results. Toggle: highlight every query (default: only queries with new results). |
| Sequence | SVG lanes, one per agent, grouped by company; time flows down. | Arrows labelled with intent; failed trust as dashed red; verdict as thick green. Small markers for discovery and verification on the searcher's lane. Follows live unless scrolled. Filters to the selected thread. |
| Flow | `dagre`, left to right, for one thread (the selected thread, or `t1` under "All threads"). Layers by first contact; the opener is the root. | Forward edges go right; replies and loops curve back. Edge labels: intent and count. |
| Matrix | SVG grid: senders × recipients. | Cell shade = message count; border = the recipient's trust result. Hover lists messages; click filters chat to the pair. |

All views honor the selection model (§5.2).

## 8. A2A tasks (Phase 5)

- **Receive:** for intent `request`, `InboxExecutor` returns a Task with state `working` and the ack as its status message. Other intents return a Message ack as today.
- **Send:** `A2ASender.send` returns the reply and, when present, the task id. The requesting agent records an open request `{task_id, recipient, thread_id, message_id, base_url}`.
- **Link rule:** when an agent sends `reply`, `share`, `decline`, or `challenge` to another agent on a thread, the arena finds the sender's oldest open received task from that recipient on that thread. `reply`/`share` → `completed` with the body as an artifact. `decline`/`challenge` → `rejected` with the body as the reason.
- **Poll:** each tick, the requester calls `tasks/get` for up to 5 open requests. A final state emits `task.updated` and removes the request. A failed poll leaves the request open.
- **Cancel:** when a thread closes, the arena cancels its open tasks through `tasks/cancel`. `InboxExecutor.cancel` sets the task to `canceled`.
- **Store:** the a2a-sdk `InMemoryTaskStore` per agent app, as today.
- **Events:** `task.created {task_id, requester, recipient, message_id, thread_id}`; `task.updated {task_id, state, artifact?, reason?}`.
- **UI:** Activity tab lists outgoing and incoming tasks with state chips; Sequence view draws a bracket from request to completing reply; chat shows a state chip on request bubbles.

## 9. Error handling

| Condition | Behavior |
|---|---|
| Unknown slug on `/arena/agents/{slug}` | `404`. |
| Registry unreachable on a proxy route | `502 {"error"}`; UI banner "registry unreachable". |
| Live card fetch fails | Card tab shows the error and offers the stored registry card. |
| A CDN library fails to load | Page shows one message naming the library. |
| Unknown event type in the UI | Ignored and counted in a debug footer. |
| `tasks/get` fails | Request stays open; retried next tick. |
| A task never reaches a final state | Canceled when its thread closes. |

## 10. Testing

- Python: tests for each new event and its data, the decision fields, per-agent state, each read API (including 404/502), the registry `GET /orgs`, and A2A task create/complete/reject/cancel/poll in process.
- Contract: every event type the runtime emits is handled in `store.js` (extends the current UI contract test).
- JS: `node --test` for `store.js` reducers and `lib/layout.js`. No bundling; Node is a dev-only test runner.
- Manual: a browser checklist per phase, run against a replay of a recorded run (no credits).

## 11. Carried-over minors

Fixed in this round because the phases rewrite that code:
- Replayed `arena.started`/`arena.stopped` events change the UI mode label (Phase 2 rewrites the mode handling).
- Per-agent `thread_cap` in `cast.yaml` is unused (Phase 5 touches thread handling).

The other deferred minors from the arena review stay deferred.

## 12. Out of scope (future)

- Searchable capability discovery for large registries (free-text search over capabilities and skills; the registry already supports `query=` and `skill=`).
- Model-driven discovery: the model chooses what to search for each turn.
- Presenter mode, mobile layout, UI authentication.
