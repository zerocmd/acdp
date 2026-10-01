# ACDP Agent Arena — Design v0.1

Exported 1 Oct 2026. Owner: Dean De Beer, Command Zero. Status: open questions resolved; ready for SDD spec and implementation plan.

## Purpose and scope

The arena proves that agents from different companies can discover each other through ACDP, verify who they are talking to, and hold real multi-party conversations without a central orchestrator. It demonstrates the discovery and trust story, not task execution.

In scope:

- 10 agents at launch across 8 or more companies, each registering into ACDP via an A2A AgentCard and a DNS TXT record
- Live Anthropic models (Sonnet and Haiku) driving every message, no scripted dialogue
- One shared cross-org phishing investigation plus independent agendas running concurrently
- A browser UI showing registration, discovery, and message content in real time
- Adding a new agent while the arena is running, with no restart
- One deliberately untrustworthy agent so peers are seen declining or challenging

Out of scope:

- Tool calling or any real action against external systems
- Production-grade identity (mTLS, VC signing) beyond what ACDP already provides
- Persistence across runs beyond a replayable event log
- Multi-tenant auth on the UI

## Architecture

```
+--------------------------------------------------------------------------+
|  Arena UI (browser)                                                      |
|  company-clustered graph | colour-coded threads | live transcript        |
|  add-agent control  ---------------------------------------------+       |
+------------------------------^-----------------------------------|-------+
                               | stream                            |
+------------------------------|-----------------------------------|-------+
|  Event bus (WebSocket): registrations, discoveries, messages,    |       |
|  verifications, verdicts                                         |       |
+------------------------------^-----------------------------------|-------+
                               | every event                       | add agent
+------------------------------|-----------------------------------v-------+
|  Agent runtime (one process, one async task per agent)                   |
|                                                                          |
|  [Investigation agents] <-A2A-> [Agenda agents] <-A2A-> [Impostor agent] |
|   6 x Sonnet                     3 x Haiku                1 x Haiku      |
|   cross-org phishing case        procurement, compliance, lookalike      |
|   verify peers before reply      sales: independent loops intel vendor   |
+--------------|---------------------------------^-------------------------+
     register card                         discover peers
+--------------v---------------------------------|-------------------------+
|  ACDP registry                                                           |
|  A2A AgentCards + DNS TXT records under each company domain              |
+--------------------------------------------------------------------------+
```

Four layers: ACDP as the registry, a single runtime hosting one async task per agent, one event bus, and a browser UI. Each agent task has its own system prompt, a model loop against the Anthropic API, and an A2A endpoint; agents talk to each other directly, and the bus only observes. The UI never routes messages, it only renders them and can ask the runtime to spawn a new agent.

## Registration and discovery

Every agent announces itself two ways, and peers trust an agent only when both agree.

1. On startup the agent publishes an A2A AgentCard at its well-known path: name, company, domain, capabilities, A2A endpoint, model tier, and a public key.
2. The arena's DNS stub serves a TXT record under the agent's company domain pointing at that card (the ACDP pattern already in the repo). A fictional company gets a fictional zone; the stub resolver is part of the runtime, so no real DNS changes are needed.
3. The agent registers the card with ACDP. ACDP stores it, re-fetches it from the advertised endpoint, and records whether the DNS record and the card agree.
4. Discovery is a capability query against ACDP: an agent asks for peers with a capability (threat-intel, identity, email-security) and gets back cards plus ACDP's verification status.
5. Before trusting a reply, a Sonnet agent re-checks the sender's domain against DNS. The impostor passes step 3 with a lookalike domain but fails this check, which is what the arena is built to show.

Registration, verification results, and discovery queries all emit events to the bus so the UI can show an agent appearing, being verified, and being found.

## Agent cast

Ten agents at launch across nine companies: two real partners (ExtraHop, Tenable) and seven fictional ones. Fictional names and domains are placeholders; rename freely.

| Agent | Company (domain) | Capability | Model | Role in the arena |
| --- | --- | --- | --- | --- |
| SOC Investigator | Northgate Bank (northgate.example) | SOC investigation | Sonnet | Trigger: spots a phishing campaign, opens the cross-org investigation |
| Threat Intel Analyst | Halcyon Intel (halcyon-intel.example) | Threat intelligence | Sonnet | Attributes infrastructure and campaign overlap |
| Identity Guardian | Keystone IdP (keystone-id.example) | Identity and access | Sonnet | Reports affected accounts and token activity |
| Network Detection | ExtraHop (extrahop.com) | Network detection and response | Sonnet | Confirms beaconing and lateral movement from the compromised host |
| Peer SOC | Meridian Credit Union (meridian-cu.example) | SOC investigation | Sonnet | Second victim; corroborates and shares its own findings |
| ISAC Coordinator | FinShare ISAC (finshare-isac.example) | Cross-org coordination | Sonnet | Merges findings and closes the investigation with a verdict |
| Procurement Agent | Northgate Bank (northgate.example) | Procurement | Haiku | Own agenda: sourcing a vendor quote |
| Exposure Auditor | Tenable (tenable.com) | Exposure and compliance | Haiku | Own agenda: polling peers for patch and attestation status |
| Sales Agent | Halcyon Intel (halcyon-intel.example) | Sales outreach | Haiku | Own agenda: offering services to anyone with a card |
| Lookalike Intel | Halcyon-Intel Services (halcyon-inte1.example) | Threat intelligence | Haiku | Impostor: registers a near-identical card under a wrong domain |

## Conversation model

Every message is generated live by an Anthropic model; nothing is scripted beyond each agent's system prompt and the opening incident seed.

**Agent loop.** Each agent runs the same cycle on its own timer: read inbox, query ACDP for peers matching its current need, decide whether to reply, initiate, or wait, then send. The model receives its system prompt, the sender's AgentCard and verification status, the thread history, and a short list of peers it could contact. It returns a message plus a target and a thread id.

**Threads.** A thread is a conversation id carried in every A2A message. The investigation seed creates thread 1; agenda agents open their own threads. Agents can join an existing thread or start a new one, so the number of concurrent conversations grows organically. The ISAC Coordinator closes thread 1 with a verdict once the other investigation agents have reported; agenda threads end when their owner's goal is met or abandoned.

**Model split.** Sonnet agents handle anything that requires weighing evidence or deciding whether to trust a peer. Haiku agents handle high-frequency, low-stakes loops. The model name travels in the AgentCard so the UI can show it.

**Message schema.** Each A2A message carries: thread id, sender DID, recipient DID, timestamp, intent (request, reply, share, decline, challenge), body text, and a reference to the sender's card. Decline and challenge are first-class so the UI can colour them.

**Seed incident.** Northgate's SOC Investigator starts with a short brief: a credential-phishing lure hitting finance staff, a suspicious OAuth consent, and two sender domains. Everything after that is the models talking.

**Rate control.** Target 6 to 10 messages per minute across the arena: the investigation thread at one message every 15 to 20 seconds, each agenda agent at about one per minute, the impostor every 2 to 3 minutes. Each agent also carries a per-thread cap so no single conversation runs away.

## Live agent injection

A new agent joins a running arena in under a minute with no restart, and the UI shows every step of it arriving.

1. The operator fills in the add-agent form: name, company, domain, capability, model (Sonnet or Haiku), and a one-paragraph agenda. A generate button asks Sonnet to draft the agenda and system prompt from just the name and capability.
2. The runtime starts a new agent task, mints its key and DID, writes its AgentCard, and adds the DNS TXT record to the stub resolver.
3. The agent registers with ACDP; the UI shows the node appear in its company cluster, then flip to verified.
4. Existing agents pick it up on their next discovery query. No agent holds a static peer list, so nothing needs to be told.
5. The new agent starts its own loop and either joins an existing thread or opens one.

The same form can register a deliberately misconfigured agent (wrong domain, missing TXT record) to demonstrate a failed verification on demand.

## Interface

One screen, three panes, built to let a viewer follow the investigation thread through the noise.

**Graph pane (left, largest).** Agents as nodes, grouped into labelled company clusters. Node badge shows model tier; node border shows verification state (verified, pending, failed). An edge animates from sender to recipient as each message is sent, coloured by thread. Declines and challenges draw in the critical colour. The impostor sits in its own cluster with a failed-verification border.

**Transcript pane (right).** A scrolling feed of message content: sender, recipient, thread colour chip, intent, and body. Filters: by thread, by agent, by company, by intent. Clicking a node or edge filters to it. Registration and verification events appear inline as system lines.

**Control bar (top).** Arena status (agent count, message count, threads open), pause and resume, replay speed for the event log, and the add-agent button that opens the injection form.

**Stack.** Single-page app over the WebSocket event bus; a force-directed graph library for the node view; no backend state beyond the event log, so a refresh replays and catches up.

## Decisions

Resolved 1 Oct 2026.

- **Reuse ACDP directly.** The registry API, DNS resolver, and card schema come from the ACDP repo as-is, with no arena wrapper. Part of the point is to exercise the real implementation and surface any issues in it.
- **Impostor is caught peer-side.** ACDP accepts the lookalike card at registration; Sonnet agents catch it on their own DNS check before trusting a reply. Ideally the registry would catch it earlier; for the demo the later catch tells the better story.
- **The ISAC Coordinator closes the investigation.** It ends thread 1 with a verdict message once the participating agents have shared their findings.
- **One runtime, one async task per agent.** Simpler for live injection than a process per agent.
- **Replay mode is in.** Every event is logged; the UI can replay a saved log at adjustable speed for repeatable demos.
- **Cadence.** Arena-wide target of 6 to 10 messages per minute. Investigation thread: one message every 15 to 20 seconds. Each agenda agent: about one message per minute. Impostor: one attempt every 2 to 3 minutes. Tunable per agent from the runtime config.
- **Real partner names.** ExtraHop and Tenable replace two fictional vendors in the cast. The impostor still mimics a fictional vendor so no real brand is impersonated in the demo.
