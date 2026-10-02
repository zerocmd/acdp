# ACDP Arena Comms Map and Expanded Cast — Design Spec

Date: 2026-10-02. Owner: Dean De Beer. Status: draft for review.
Builds on: `docs/superpowers/specs/2026-10-01-arena-workbench-ui-design.md` (the Workbench spec) and `docs/superpowers/specs/2026-10-01-acdp-agent-arena-design.md` (the arena spec). This spec replaces the Network and Flow views of the Workbench spec (§7) and changes the chat, drawer, Sequence, and Matrix presentation.

## 1. Purpose

Engineers find the current Workbench hard to read. The force-directed Network view moves and is hard to control. The Flow view is small and static. Communication between agents is not visible enough. Text is small. The drawer is a plain list.

This spec makes agent-to-agent communication the center of the UI: a structured, animated Comms Map, a richer Sequence view, readable chat and drawer, and a larger cast with several concurrent activities.

Audience: unchanged (engineers on laptops and wide monitors).

### Success criteria

1. The Comms Map shows every organization as a box and every agent inside its box. Positions do not move during a run.
2. Each message animates as a pulse from sender to recipient, with a popup that shows the sender, recipient, intent, and the start of the body.
3. Ribbon width grows with the message count between two agents on a thread. Each ribbon shows its count.
4. Selecting a thread (chat chip, ribbon, arrow, or message) dims everything outside that thread on the map, in the Sequence view, and in the Matrix.
5. The Sequence view shows real time, thinking intervals, decision outcomes, and arrow thickness by message size.
6. Chat and drawer text follow the type scale in §6. A text-size control scales the whole UI from 85% to 130%.
7. The cast has 34 agents in six concurrent scenarios plus two impostors. All agents except the two impostors pass verification.
8. A replay of the demo log shows all of the above, except live-only data.
9. `pytest` and `node --test "arena/ui/tests/*.test.mjs"` pass with no API key and no network.

## 2. Decisions

| # | Decision | Reason |
|---|---|---|
| C1 | One Comms Map replaces the Network and Flow views. | Both answered "who talks to whom". One strong view is easier to make readable. |
| C2 | Layout: organization boxes in three sector bands (member, provider, assurance), with a thread focus that dims everything else. | Stable positions; the focus gives the "follow one conversation" behavior of the hub layout. |
| C3 | SVG rendering with built-in zoom and pan. | Crisp text, per-element animation and events, no new library. |
| C4 | Sankey-style ribbons: one per agent pair per thread, width on a log scale. | Volume stays readable without huge bands. |
| C5 | Animations: pulses, popups, discovery rings, registration rings, verdict bursts, decline shakes, task badges. Honor `prefers-reduced-motion`. | Communication must be visible as it happens. |
| C6 | Sections and chips use an even 1 px border in their color and a light fill of the same color (about 10%). No one-sided colored borders. | Operator preference; reads as a coherent card style. |
| C7 | Type scale: reading text 15 px, UI text 13.5 px, headings 18 px, section labels 11 px uppercase; all scaled by `--text-scale` (0.85–1.3), stored per browser. | Larger text where people read; dense surfaces stay compact; people can adjust. |
| C8 | New backend event `decision.started {agent}`. | Gives the Sequence view a thinking interval per decision. |
| C9 | Agents carry a `sector` (`member`, `provider`, `assurance`); the map bands use it. Injected agents default to `provider`. | Placement by capability is ambiguous when one organization has many capabilities. |
| C10 | Cast grows from 10 to 34 agents (24 new, almost all Haiku) in six scenarios and two impostors. Arena rate 40 messages/min, run cap 2000 decisions, run time 20 minutes. | Several concurrent activities exercise discovery, trust, and the map. |
| C11 | A chord ring view (organizations as arcs, ribbons as chords) is a later, optional phase. | Visually appealing; reuses the ribbon data. Not required for the core goal. |

## 3. Phases

1. Foundations: `decision.started`, `sector`, type tokens, text-size control, card and chip styles (`components/cards.js`).
2. Expanded cast: 24 new agents, seeds list, pacing defaults.
3. Comms Map: layout, ribbons, badges, zoom and pan, thread focus; then animations. It becomes the default view. Network and Flow views and the `force-graph` and `dagre` scripts are removed.
4. Sequence: time axis, thickness, thinking bands, decision dots, live drawing, popups on hover, lane filtering.
5. Chat and drawer redesign.
6. Matrix and Registry readability pass.
7. Chord ring view (optional; the operator decides whether this phase runs in this round).

## 4. Backend changes

### 4.1 `decision.started`

`ArenaAgent._decide` publishes `decision.started {agent}` immediately before the model call. Every `decision.made` follows the `decision.started` of the same agent, except when the call raises (timeout or provider error). Then `agent.error` follows, and the store closes the interval at that event.

### 4.2 `sector`

`AgentSpec` gains `sector: str` with values `member`, `provider`, `assurance`; default `provider`. `cast.yaml` sets it for every agent. `agent.registered` carries `sector`. The add-agent request gains an optional `sector` field (default `provider`) and the dialog gains a select.

### 4.3 Seeds

`cast.yaml` replaces `seed:` with `seeds:` (a list). Each seed has `owner`, `closer`, `title`, `brief`. `Arena.setup` opens one thread per seed in list order and seeds each owner's inbox. The phishing seed stays first, so its thread stays `t1`.

### 4.4 Pacing defaults

| Setting | Old | New |
|---|---|---|
| `ARENA_RATE_PER_MIN` | 10 | 40 |
| `ARENA_MAX_MODEL_CALLS` | 600 | 2000 |
| Agenda cadence | 50–70 s | 60–90 s |
| New role `incident` cadence | — | 30–45 s |

`docker-compose.yml` defaults and `Settings.from_env` defaults change to match.

## 5. Expanded cast

Roles: `investigation` (phishing case, 15–20 s), `incident` (ransomware case, 30–45 s), `agenda` (60–90 s), `impostor` (120–180 s).

Existing agents keep their slugs and prompts. Changes: `northgate-procurement` needs `sales, legal, finance`; every existing agent gets a `sector`; existing agenda agents move to 60–90 s.

New organizations and agents (H = Haiku, S = Sonnet):

| Slug | Organization (domain) | Sector | Capability | Needs | Model | Role |
|---|---|---|---|---|---|---|
| coastline-sales | Coastline MDR (coastlinemdr.example) | provider | sales | procurement | H | agenda |
| coastline-trust | Coastline MDR (coastlinemdr.example) | provider | vendor-security | third-party-risk | H | agenda |
| brightmail-sales | Brightmail (brightmail.example) | provider | sales | procurement | H | agenda |
| corvid-intel | Corvid Labs (corvidlabs.example) | provider | intel-feed | ioc-sharing | H | agenda |
| corvid-sales | Corvid Labs (corvidlabs.example) | provider | sales | procurement | H | agenda |
| keystone-vendorsec | Keystone IdP (keystone-id.example) | provider | vendor-security | third-party-risk | H | agenda |
| keystone-sales | Keystone IdP (keystone-id.example) | provider | sales | procurement | H | agenda |
| ironclad-ir | Ironclad IR (ironclad-ir.example) | provider | incident-response | ransomware-case | S | incident |
| northgate-legal | Northgate Bank (northgate.example) | member | legal | procurement | H | agenda |
| northgate-finance | Northgate Bank (northgate.example) | member | finance | procurement | H | agenda |
| northgate-compliance | Northgate Bank (northgate.example) | member | compliance | audit, underwriting | H | agenda |
| northgate-tprm | Northgate Bank (northgate.example) | member | third-party-risk | vendor-security | H | agenda |
| meridian-compliance | Meridian Credit Union (meridian-cu.example) | member | compliance | audit, underwriting | H | agenda |
| meridian-ciso | Meridian Credit Union (meridian-cu.example) | member | ransomware-case | incident-response, cyber-insurance, breach-counsel | S | incident |
| meridian-legal | Meridian Credit Union (meridian-cu.example) | member | breach-counsel | ransomware-case | H | incident |
| pinecrest-soc | Pinecrest Bank (pinecrest.example) | member | ioc-sharing | ioc-sharing, intel-feed | H | agenda |
| pinecrest-procurement | Pinecrest Bank (pinecrest.example) | member | procurement | sales | H | agenda |
| harborview-soc | Harborview Bank (harborview.example) | member | ioc-sharing | ioc-sharing, intel-feed | H | agenda |
| harborview-compliance | Harborview Bank (harborview.example) | member | compliance | audit, underwriting | H | agenda |
| finshare-sharing | FinShare ISAC (finshare-isac.example) | assurance | ioc-sharing | ioc-sharing, intel-feed | H | agenda |
| ledgerline-audit | Ledgerline Audit (ledgerline.example) | assurance | audit | compliance | H | agenda |
| sentinel-insurance | Sentinel Mutual (sentinelmutual.example) | assurance | cyber-insurance | ransomware-case | H | incident |
| sentinel-underwriter | Sentinel Mutual (sentinelmutual.example) | assurance | underwriting | compliance | H | agenda |
| coastline-impostor | Coastline MDR (coastline-mdr.example) | provider | sales | procurement | H | impostor |

Scenarios: vendor sourcing (procurement × three vendor sales agents and Corvid and Keystone sales; Legal and Finance review), compliance audit (Ledgerline × three compliance agents; underwriting asks the same agents), threat-intel exchange (Pinecrest, Harborview, the ISAC sharing desk, Corvid feed), third-party risk (Northgate TPRM × Keystone and Coastline vendor-security), ransomware incident at Meridian (CISO, Ironclad IR, Sentinel Mutual, Meridian Legal), plus the existing phishing case and agendas.

Second seed (ransomware): owner `meridian-ciso`, closer `ironclad-ir`, title "Ransomware on Meridian file servers", brief: file servers at Meridian encrypted at 02:10 UTC, ransom note names "BlackFen", backups for two shares are intact, a domain admin account logged in from an unknown host at 01:52 UTC; ask IR to scope, notify the insurer, and ask counsel about notification duties.

Registration order: real organizations before impostors. `coastline-sales` registers before `coastline-impostor`, so the registry anchors "Coastline MDR" to `coastlinemdr.example`.

Constraint: no prompt makes claims about real products. ExtraHop and Tenable keep generic capabilities. Impostors mimic only fictional organizations.

## 6. Visual system

- Type tokens: `--fs-read: calc(15px * var(--text-scale))`, `--fs-ui: calc(13.5px * var(--text-scale))`, `--fs-head: calc(18px * var(--text-scale))`, `--fs-label: calc(11px * var(--text-scale))`. Reading text (chat bubbles, drawer card bodies, popups) uses `--fs-read`. UI text (sidebar, toolbars, tables, chips, map and sequence labels) uses `--fs-ui`.
- Text-size control in the top bar: A− / A+ in steps of 0.05 from 0.85 to 1.3, reset on double-click. Stored in `localStorage` (wrapped in try/catch; default 1.0).
- Card and chip style: `border: 1px solid <color>; background: color-mix(in srgb, <color> 10%, var(--panel));` No one-sided borders.
- Colors: company color per domain (existing palette); thread colors (existing); trust colors (existing tokens). Light and dark variants as today.

## 7. Comms Map (Phase 3)

### 7.1 Layout

- Three bands left to right: member, provider, assurance. Each band holds organization boxes in a grid (as many columns as fit, minimum box width 180 px).
- An organization box contains its agents in a vertical list. The box border and fill use the company color (C6).
- An organization whose agents all failed verification draws a dashed red border and sorts to the end of its band.
- Agent node: circle filled with the company color, a ring in the trust color, `S`/`H` badge, name label at `--fs-ui`. Radius grows from 14 to 20 px with activity (messages sent plus received, log scale).
- Positions are a pure function of the agent list and the view size. A new agent changes positions only inside its own box and band.

### 7.2 Ribbons

- One ribbon per unordered agent pair per thread. A ribbon is a filled band between two cubic curves.
- Width: `2 + 4 * log2(1 + count)` px, capped at 18 px.
- Color: the thread color; red when the pair-thread has a `decline` or `challenge`.
- Parallel ribbons for the same pair offset side by side.
- Count badge at the ribbon midpoint (`×N`). Hover lists the last three messages.

### 7.3 Interaction

- Zoom with the wheel (0.4×–4×), pan by dragging the background, "Fit" button.
- Thread focus: selecting a thread dims ribbons outside it to 10% opacity and dims agents not in it to 30%. A "Clear focus" chip removes it.
- Hovering a chat message makes its ribbon glow. Clicking an agent opens the drawer. Clicking a ribbon focuses its thread.

### 7.4 Animations

| Event | Animation |
|---|---|
| `message.sent` | A pulse (6 px dot with a short trail) travels from sender to recipient along the ribbon in 1.2 s; the ribbon flashes. |
| popup | A card near the ribbon midpoint: sender → recipient, intent chip, first 100 characters. Visible 4 s. At most 3; the oldest fades first; slots never overlap. |
| decline / challenge | Red pulse; the recipient node shakes (300 ms). |
| verdict | Green ring bursts from the recipient (800 ms). |
| `discovery.query` with new results (or every query when the toggle is on) | Purple ring on the searcher; dashed purple lines to each result for 2 s; "new" tag on new results. |
| `registration.step` | The node fades in with an amber ring; on `result` the ring turns green, or red with a short shake. |
| tasks | A badge at the requester end of the ribbon: spinner while `working`, ✓ when `completed`, ✕ when `rejected`/`canceled`/`failed`. |

Limits: at most 20 pulses at once (extras are skipped; badges still update). Animations run only for events newer than the view's last animated `seq`. On connect, replay load, or `generation` change, the view draws the final state without animating history. `prefers-reduced-motion`: no pulses, shakes, or bursts; popups and highlights remain.

## 8. Sequence view (Phase 4)

- Time axis on the left with clock labels. Rows are placed by real time; gaps over 20 s compress to a marked "⋯ N s" spacer.
- Arrow thickness by body length: short (< 120 characters) 2 px, medium (< 400) 3.5 px, long 5 px. Verdict thick green, decline/challenge red, failed trust dashed red.
- Each lane has an activity band: filled segments for thinking intervals (`decision.started` → `decision.made`), and decision outcome dots (gray wait, orange rejected, blue sent). Discovery (purple) and verification (green) diamonds remain.
- New arrows draw from sender to recipient (400 ms); the newest row pulses; a "now" line moves while the run is live.
- Hover an arrow: the same popup card as the map. Click: focus its thread.
- Lane filtering: by default only lanes of agents active in the focused thread, or in the visible time range when no thread is focused. A "Show all lanes" toggle shows every lane.
- Task brackets remain. The selected agent's lane is highlighted.

## 9. Chat and drawer (Phase 5)

Chat:
- Reading text at `--fs-read`.
- System events for registration and verification collapse into one "Setup" card per run: agent count, verified and failed chips, "show details" to expand. Thread open and close events stay as compact dividers.
- Larger avatars (32 px). Chips for trust, task state, and the looking-for / why line, in the C6 style.
- The message animating on the map has a "live" glow until its pulse ends.
- Hover a message: its ribbon glows on the map. Click: focus its thread.
- Bubbles have keys (by message id).

Drawer:
- Header: 40 px avatar, name at `--fs-head`, organization, domain, model, status chip.
- Overview cards: Activity (stat tiles: sent, received, rejected, errors; state chip; cadence), Role (capability and needs chips, sector), Registration (seven step chips; a click expands that step's detail), Identity (DID and fingerprint in code boxes with copy), DNS records (SRV line and TXT fields as a table; key marked ✓ when it matches the card), Registry checks (chips).
- Card tab: Provider card, Skills chips, ACDP extension card (DID, domain, fingerprint, model), raw JSON collapsed.
- Prompts and Discovery tabs: the same card style; prompts in scrollable code boxes.

## 10. Matrix and Registry (Phase 6)

- Matrix: cells and labels at `--fs-ui`, larger cells (40 px); the selected agent's row and column highlighted; thread focus filters the counts; a new message flashes its cell.
- Registry: the C6 card style and type scale; no functional change.

## 11. Chord ring (Phase 7, optional)

Organizations as arcs around a circle, sized by agent count; agents as sub-arcs; ribbons as chords with the §7.2 width rule; the same pulses, popups, focus, and reduced-motion rules. A view-switch entry "Chord".

## 12. Removed

`views/network.js`, `views/flow.js`, store and layout helpers used only by them, and the `force-graph` and `dagre` scripts in `index.html`. `index.html` loads only the Preact module.

## 13. Error handling and performance

- Many messages: ribbons aggregate by pair and thread, so SVG element count stays bounded by pairs × threads.
- Pulse and popup caps as in §7.4.
- A missing agent for a message (for example, an old log) skips that message on the map; the chat still shows it.
- `localStorage` failure: the text scale stays at 1.0 for the session.

## 14. Testing

- Node: `lib/commsmap.js` (band assignment by sector including default and failed organizations; positions inside bounds with no overlap; ribbon width rule and parallel offsets; popup slots ≤ 3 with no overlap and oldest replaced; animation filtering by last seq and generation). `lib/sequence.js` (gap compression; thickness buckets; lane filtering). Store (thinking intervals from `decision.started`/`decision.made`/`agent.error`; `sector`; text scale default).
- Python: `decision.started` precedes `decision.made`; `sector` in `agent.registered` and injection; seeds list opens one thread per seed in order; cast tests for 34 agents, unique slugs, registration order of real before impostor organizations, needs resolvable, cadence by role, two impostors anchored to the real organizations; the event contract test.
- Manual: a browser checklist per phase against the regenerated demo log in a visible tab, including reduced motion and 85% and 130% text scale.

## 15. Out of scope

Presenter mode, mobile layout, sound, exporting animations as video or GIF.
