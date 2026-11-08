# AgentOfEmpire – Design

Formerly "Il Consiglio del Regno – Handoff di design" (Claude Docs).

> **Reconstructed on 2026-11-07.** The original doc was deleted by mistake. This version is rebuilt from the session transcript: every section read in full or written during the session is complete. Parts of the **game vision** were only ever seen as an outline. Those parts are marked **[Lost]**, with the fragments that survive, and need to be rewritten. Numbers in the prototype sections match the code as of this date (`engine/config.toml`, `server/council.toml`).

Part 1 is the vision for the full game. Part 2 is the specification of what is built (the prototype). The UI mockups are in [`mockups/`](mockups/) (Design canvas files, Italian text).

---

# Part 1 – Game vision

## Concept

A strategy game in which the player is the **sovereign** and governs through a **council of ministers**, each an LLM agent with a personality, by giving orders, approving plans and intervening in the debate. *[Lost: the rest of the first paragraph.]*

Multiplayer *[Lost: details]*: each player leads a **state**, formed by **a single city**.

## Actors

- **Sovereign** (player): orders, approvals, interventions in the debate, incognito outings in the square.
- **Ministers** (LLM): Treasurer (economy), Marshal (army), Architect (construction), Ambassador (diplomacy). Each with a personality, a level of trust from the sovereign and a dedicated model.
- **Chancellor**: routes the orders, collects the plans, detects resource conflicts, proposes compromises. Decided: an LLM. The arithmetic checks (sum of costs, comparison with resources) are done by the engine and handed to it already computed.
- **People**: social classes with mood and trust towards the sovereign and towards each minister.
- **Voice of the square** (LLM): tells the story of the people through pleas, market rumours and delegations. Decides nothing.
- **Tribune** (optional): spokesperson of the people who can appear before the council.
- **Other states**: other human players and automatic states led by a sovereign agent with the same architecture.

## Character personalities

**The layers of a counsellor** (2026-11-07):

| Layer | What it holds | Changes | Where today |
| --- | --- | --- | --- |
| Manual (shared) | how the realm works | only with the config | `server/council/manual.py` |
| Role | duties, obligations, allowed orders | never | `ROLE_DUTIES`, `ROLE_ACTIONS`, the role's prompt template |
| Craft | what the office's training teaches: good practice, not laws | per role; later per person (résumé) | `prompts/expertise_<role>.txt` |
| Person | name, gender, traits (how well and how boldly the craft is applied), story, model, salary | with the person | `server/council/personas.toml`, copied into `actors.personality` |
| Mandate | the sovereign's standing lines, rewritten by the chancellery | when changed | `mandates` |

Each role also sees different information: the Treasurer the consumption at every ration and the registry (children coming of age, free places in the houses), which the Architect needs and has to ask for, in council or in a note.

**Persons** (2026-11-07): a catalog of persons (`server/council/personas.toml`), small test set of 12: per role 2 moderates (drawn at game start, by the game's seed, never the same person in two realms) and 2 extremes (for hiring later). Each brings name, gender (the office title follows it: Tesoriere or Tesoriera, Architetto or Architetta, Cancelliere or Cancelliera), the five traits, a short story in its prompt, **a tier of mind** (`low`, `medium`, `high`: brilliant persons are `high`) and **a salary**. The persona never names a model: `[model_tiers]` in `council.toml` maps each tier to a model (later a settings page, so a player who does not care about models never sees them). For now all three tiers are DeepSeek V4.1 Flash; a weaker model will be tested as `low` to see how much a game suffers before the tiers are set. Salaries are paid by the engine every month after the buildings' upkeep (`council_salary` in the state; `salaries_unpaid` event, council level): a moderate council costs about 10 gold a month, so at 5 % taxes the treasury empties in about a year. Games created before persons keep their generated traits, the old names and no salary. Next (phase 3–4): hiring and dismissal, persons moving between realms with their lessons and memories, separating the person from the post.

**Role and person** (principle, 2026-11-07): a role is the office (title, duties, obligations such as the Chancellor's impartiality, allowed orders) and never changes during a game; a person fills it and has its own traits, résumé and, later, name. Today the role lives in the code (`ROLE_TITLES`, `ROLE_DUTIES`, `ROLE_ACTIONS` in `server/council/meeting.py`) and in the role's prompt templates; the person in the `actors` row of the game (traits). When counsellors can be hired and dismissed, the role data moves to one file (e.g. `server/council/roles.toml`) and persons stay in the database.


*[Lost: intro sentence, beginning "Every minister…".]* A personality has three layers:

1. **Role** (fixed): skills, allowed actions, visibility level of information. The same for every Treasurer.
2. **Traits** (numeric axes): caution/boldness, loyalty, ambition, honesty, competence.
3. **Résumé**: origin, class of origin, past experience, possible vices or ties with other states.

Lifecycle:

- **Game start**: random personalities with traits drawn near the centre, so ministers are moderate.
- **Hiring**: the sovereign picks from a list of candidates with résumés. The most extreme profiles, brilliant but risky, appear only here. **The résumé can lie**: real competence and loyalty emerge over time. Jev can judge the consistency between what was declared and the behaviour.
- **Dismissal has a cost**: the outgoing minister keeps the council-level secrets and can sell them to another player or stir up their class of origin.
- **Evolution**: traits change slowly with events (a minister who is often overruled becomes less loyal).

## Turn structure

A year of play is **12 turns** (one turn = one month). *[Lost: rest of the sentence.]*

- **In-season turns (8 per year)**: diplomacy, military strategy, construction, other operations. Possibly a main theme per season (e.g. summer for military campaigns, winter for diplomacy and preparation).
- **Season-end turns (4 per year)**: season report: demography, class mood, harvest, story from the Voice of the square.
- **Asynchronous multiplayer**: each player sends orders before a deadline, then the turn resolves for everyone at the same time.
- **The game is no longer real-time**: between turns the deterministic engine simulates the month. Ministers work at the start of each turn.

### Role of Jev

With turns, Jev is used mainly to **reduce costs**, not to *[Lost: rest of the paragraph]*. See also "Architecture" and the Jev decision under "Decisions".

## Map, states and automatic states

A game has **8 states**, some *[Lost]*, on a **200 × 200** *[grid]* with seas, *[Lost]*.

- **Sizing**: each state starts from a core of about 16 × 16 tiles and can grow to about 40 × 40. Symmetric starts: similar resources and at least one reachable neighbour. The size adapts to the number of players.
- **Main screen**: your own state in tiles, with fortifications, town hall, public square, production (sawmill, mill…) and a military area, with resources that change over time. Zooming out or a button opens the world map with the other states.
- *[Lost: four more items.]*
- **First step, approved 2026-11-08**: see "Territory: map, town plan, expansion" in Part 2.

### Automatic states

Automatic states use **the same architecture as human players**, with a sovereign agent (cheap model) instead of the human. Advantages: a single codebase; a player absent for a turn passes to the automatic sovereign without blocking the game; automatic sovereigns have personalities with the same three-layer system as the ministers (e.g. warmonger king, peaceful merchant).

The automatic sovereign comes in two versions, technically identical (same council reports, orders through the Chancellor); only personality and permissions change.

- *[Lost: first version.]*
- **Full sovereign**: leads the automatic states, with a three-layer personality and the same powers as a human.
- *[Lost: two more items.]*

## Military dynamics

War is about **preparation** *[Lost: rest of the paragraph, beginning "the sovereign…"]*.

- *[Lost: four items.]*
- **Information**: the army sits in reserved tiles. The enemy estimates it through spies and border observation, with estimates that may be old or wrong; the Marshal can inflate them to get resources. Deceptions are possible, such as proclaiming in the square a mobilisation that does not exist.
- *[Lost: one item.]*

### Randomness

*[Lost: five items.]*

## Victory conditions

The modes *[Lost]*. **No victory** *[Lost]* at the end *[Lost]*.

### Modes

*[Lost: six items.]*

### Rules

*[Lost: five items.]*

## Economy and trade

Five resources: **food, wood, stone, gold** and a **rare resource** (e.g. iron or salt) unevenly spread across the map, which pushes towards trade or war.

- **Market square**: dynamic prices from supply and demand. It is public: other states see what you buy and sell and can guess your weaknesses.
- **Trade routes**: with open or controlled borders they pay every turn; they can be cut, raided or blocked by an embargo.
- **Bilateral agreements**: negotiated by the Ambassador (e.g. grain in exchange for passage on the river) and recorded in the game as treaties.
- **Consequences**: merchants are a class and get angry if trade stops; depending on a neighbour for food is comfortable in peace and dangerous in war; Treasurer and Ambassador can hold opposite views of the same agreement.

## Diplomacy

Each state has a **reputation** *[Lost]*, similar to *[Lost]*.

*[Lost: three items.]*

## Espionage

The spy does not *[Lost]*; **the engine** *[Lost]*. No *[Lost]*.

- **Two kinds of** *[spies / information]*: *[Lost: two items.]*
- **Access and** *[Lost]*: *[Lost: three items.]*
- **Missions**: *[Lost: four items.]*
- **Discovery**: *[Lost: three items.]*
- **Double agents**: *[Lost: three items.]*

## Progress

- **Three eras** (e.g. village, town, kingdom): moving up needs resources and key buildings, unlocks buildings and units and changes the look of the city. It is public: everyone sees who has advanced.
- **Press by era** (idea, 2026-11-07): how information spreads depends on the era.
  - **First era, no press**: nothing is announced. The people, and the other states, know only rumours (the Voice of the square, travellers, spies).
  - **Second era, the press is born**: the government can issue **communiqués** that the people read, also as propaganda, and send communiqués to other states. A communiqué may lie: when the facts contradict it, the square notices and trust in the sovereign falls. Foreign press brings other states' communiqués.
  - **Third era, journalism**: besides the government's press an **independent channel** appears, which publishes what it finds out (leaks, spies, unhappy ministers), including what the sovereign would rather hide.
  - Fits the existing pieces: visibility levels (a communiqué moves a fact to public or foreign), leaks, reputation and diplomacy. Open: cost of a journalist agent (one more call per turn, cheap tier), how credibility is measured, how much the sovereign has to read.
- *[Lost: four items.]*

## Revolt and coup

- **Revolt by degrees**: if a class's mood stays low for several turns, it goes from protests in the square to strikes (lower production) up to open revolt, with tiles slipping out of the sovereign's control.
- **Responses**: repression (Marshal) works at once but leaves resentment; concessions (Treasurer) cost but really calm things down.
- **Coup**: if the sovereign loses the trust of both people and council, an ambitious minister can try to seize power with the support of a discontented class.
- **Nobody is left out**: whoever loses the throne does not leave the game, but starts again as the leader of a faction in exile trying to win back the kingdom.
- **Today (prototype)**: revolt is automatic and final. Six months in a row below the threshold → revolt → game over. Protests have no effect, a strike costs 30 % of all production (taxes are still collected in full).
- **Revolt as odds, and regimes** (idea, 2026-11-07, for when soldiers exist): reaching "revolt" opens a contest instead of ending the game. Each month, with the engine's seeded generator (replay stays exact), the strength of the revolt (how deep and how long the discontent, how many are angry, whether a leader or a faction backs it) is weighed against the strength of order (soldiers and their loyalty, guards, fortifications, propaganda once the press exists). Outcomes by degrees: riots and damaged buildings, tiles out of control, a siege of the castle, and only at the end deposition, after which the sovereign leads a faction in exile.
  - **A militarised regime** lowers the odds of a popular revolt, but every soldier costs upkeep, soldiers are a class with their own mood (unpaid or misused, they join the revolt), repression leaves a long resentment (longer for classes with a long memory), the Marshal's ambition makes a coup more likely as the army grows, and reputation abroad falls. So "regime" becomes a real way to govern, stable in the short run and fragile to its own army.
  - The sovereign never sees the odds: the signals come from the square, the Marshal's reports and the spies.

## Architecture

1. **Game server (source of truth)**: a deterministic engine that, when each turn closes, simulates the next month. The validator accepts only predefined actions and checks costs. The summariser prepares compact briefings per role. An event bus records attacks, shortages, treaties and deaths of the month.
2. **Economic decisions (Jev, during the month's simulation)**: Jev receives the compact state and the active policies and returns a choice with a confidence. Above the threshold the command goes to the validator; below it, the matter goes on the council's agenda for the next turn. Fallback to fixed rules if Jev does not answer. Main goal: lower costs than an LLM.
3. **Council (LLM via OpenRouter, one meeting per turn)**: one model per role (strong for strategy, small and fast for operational roles). At season-end turns the meeting is devoted to the report.
4. **Browser**: map, council chat, reports, sending orders before the turn deadline. No API key in the client.

### Main flows

- **Turn opening**: the engine produces the briefings → the council meets → the ministers present reports and proposals to the sovereign.
- **Order**: sovereign → Chancellor → ministers → plans → conflicts shown in the UI → approval → the plans become **policies for Jev** plus any direct commands.
- **Turn closing**: at the deadline (or when every player has confirmed) the turn resolves at the same time for all states: the engine simulates the month, Jev takes the micro-decisions according to the policies, the validator applies the commands.
- **Events**: what happens in the month goes to the event bus and opens the next turn as a report or an alarm.
- **Rejections**: the validator returns the reason to the council, so the ministers correct their plans.

The step from *[Lost]* to **approved plan**: an order *[Lost]* during the *[Lost]*.

## People and demography

- **Classes**: peasants, artisans/merchants, clergy, soldiers. Each with its own needs, mood and trust.
- **Chosen level of detail**: aggregated classes plus a few recurring **named citizens**, who are born, age and die under the same rules.
- **Demography entirely in the engine**, deterministic, updated every season. Three age groups per class (children, adults, elders), so 12 numbers.
- Births depend on adults, food, mood and housing. Deaths per group from base mortality plus hunger, disease and cold. War deaths come from the combat engine.
- Compressed ageing (a childhood of 2–3 game years) to make consequences visible.
- Values as floats or with fractional accumulators so births are not lost to rounding. (The prototype uses integer accumulators in thousandths.)
- Links: deaths lower mood, recruitment moves adults from peasants to soldiers, discontent causes lower production, emigration, protests and revolts.
- Jev judges the impact of events and decisions on each class. The LLM narrates, the numbers decide.
- Filtered information: the sovereign knows the people's mood mostly through the ministers, who report it partially.
- **Memory horizon per class** (idea, 2026-11-07, for when more classes arrive): each class remembers over its own horizon. Peasants live month to month and remember the last 2–3 months; merchants and clergy, who keep accounts and chronicles, remember a year or more and notice slow trends the peasants miss. The square then becomes a choir of voices with different, sometimes contradictory memories, and the sovereign has to judge whom to believe. Today the only class has `PEASANT_MEMORY_MONTHS = 3` in `server/council/voice.py`.

## Persistence

- **PostgreSQL** in a Docker container on the home server, next to the game server. The database never enters the game loop: it saves, remembers and analyses.
- Contents: state snapshots at season end, append-only logs of commands and events (with seed for deterministic replay), ministers' memory, model call log (tokens, costs, latency, confidence), named citizens.
- **Every piece of information is born with a label**: owning state, audience that may know it, confidentiality level.
- Levels: **sovereign's secret**, **council**, **court**, **public**, **foreign**.
- Each agent's context is built by querying the database **with its permissions only** (PostgreSQL row-level security). An agent cannot reveal what it never received.
- **Leaks** as a mechanic: spies, unhappy ministers or gossip move a piece of information to a wider level or to another state.
- States communicate only through explicit channels: ambassadors, trade, spies.

## UX (mockups)

Canvas "Il Consiglio del Regno" with four screens, now in [`mockups/`](mockups/): the kingdom in real time (map, Jev's quick decisions, ministers' chat, order bar); the council hall (ministers, debate, decision); one order with four interpretations (with a conflict warning); intercepts and alarms. A screen for the square / the people is still missing.

The mockups predate the switch to monthly turns (they show weeks and real-time rates). The prototype UI keeps their style: dark ground `#14120E`, gold `#D4AF5A`, Cormorant Garamond for titles, Inter for text, one colour per council member.

## Lessons from *[Lost]*

*[Lost: section title and four items.]*

## Models and costs

Each actor has a **level of** *[Lost]* given by *[Lost]*.

| Tier | Example | Price (input / output per 1M tokens) | Proposed use |
| --- | --- | --- | --- |
| Top | DeepSeek V4 Pro | $0.75 / $1.50 (OpenRouter price list, 6 November 2026) | Chancellor |
| Medium | GLM 5.3 (cheap provider) | ~$0.08 / ~$1.40 | Ministers |
| Cheap | GPT-OSS and similar | a few cents | Voice of the square, quick decisions until Jev arrives |

- **Choice**: no top-end models (e.g. Opus); the most capable model is a DeepSeek and we scale down from there.
- **Per state and per turn** (estimate with the tiers above): Chancellor about 15k tokens read and 2k written (~$0.03), four ministers ~$0.01, cheap tier a few tenths of a cent; with dialogues with the sovereign about **$0.04–0.07**.
- **10-year game (120 turns)**: 4 states about **$20–35**; 6 states about **$30–50**.
- **Saving levers**: prompt caching on briefings and personalities; full council only at season-end turns.
- **Today** (prototype): every role uses `deepseek/deepseek-v4.1-flash` (reasoning `low`, Voice `none`), about $0.01 per turn for one state.

Sources: OpenRouter model list and price pages (links lost).

## Decisions

1. **Chancellor**: decided LLM. Planned tiers `deepseek/deepseek-v4-pro` for the Chancellor and `z-ai/glm-5.3` for the ministers; for now every role uses `deepseek/deepseek-v4.1-flash` (in `server/council.toml`).
2. Personality, models and budget of the automatic sovereigns. *(open)*
3. **Length**: 10 years as reference (120 turns, up to about 4 months at one turn a day, less with multi-turn evenings), configurable at game start (e.g. 5 years for a short game). Decided: one turn a day; immediate advance if everyone has confirmed (even several turns in one evening); absent for 3 days, then up to 3 days of automatic sovereign; on the seventh day the player is deposed and restarts as a faction in exile. **Vacation mode**: whoever knows they will be away (e.g. 10 days) declares it, leaves directives and their state proceeds automatically; while a vacation is active, no more than one turn a day. **Global pause**: a player can propose to suspend the game (e.g. Christmas holidays); during the pause no turns resolve and absence counters stop. Proposal: approval by the human players and no pause during a victory countdown. **Unannounced absence**: the game does not stop; the turn closes at the end of the day and the state continues with the last orders for 3 days, then the automatic sovereign takes over.
4. Concrete choice of the models for each of the three tiers and check of the cost estimate by playing. *(open, end of phase 2)*
5. **Jev**: decided a decision service with Jev's interface (state + typed questions → probability and confidence) and three interchangeable implementations: fixed rules, cheap LLM via OpenRouter, Jev as soon as available; a log compares cost and quality. Still open: technical details and the waiting-list sign-up.
6. Table schema, snapshot format and action catalogue: done for the prototype (Part 2). The policy schema for Jev is still open.
7. **Security** (approved for now): no open port on the router, access through a tunnel (Tailscale in use), personal invite-only accounts, OpenRouter key only on the server with a monthly spending cap, automatic database backups.

## Next steps (original list)

1. Engine specification: state, action catalogue, validator, demography. **Done.**
2. Database schema with visibility levels. **Done.**
3. Minimal prototype: one city, Chancellor and two ministers, one class, no Jev (fixed-rule fallback only). **Done, and more.**
4. Gradual addition of full council, people, multiplayer and Jev. **See the phases in [`PLAN.md`](../PLAN.md).**

---

# Part 2 – Prototype specification

## Engine

The prototype must show that a year of play (12 turns) is readable and interesting with one city, the Chancellor and two ministers (Treasurer and Architect), a single class (peasants) and fixed-rule automatic decisions instead of Jev. No war. The Chancellor is an LLM from the prototype on because it is the heart of the council: it routes the sovereign's orders to the ministers, collects the plans and proposes compromises; sums of costs and the comparison with resources are computed by the engine and handed over ready. Every numeric value is a starting value in a config file, to be tuned by experiment.

### Stack

- **Server**: Python with FastAPI; calls to OpenRouter with an async client (`httpx`), because a blocking call would stop the server for seconds.
- **Engine**: a pure Python package (`engine/`), with no database, network or LLM: it receives state + orders + seed and returns the new state + events. Inside it uses plain dataclasses; Pydantic models stay at the edges (API, LLM replies).
- **Database**: PostgreSQL in Docker, accessed with psycopg and handwritten SQL (no ORM, so queries and row-level security stay visible).
- **Browser**: planned in TypeScript with types generated from FastAPI's OpenAPI schema (`openapi-typescript`). For the prototype, replaced by server-rendered pages (see "Web UI").
- **Lab**: scripts in `lab/` that import the engine and simulate whole games without a UI; tests with pytest and Hypothesis.

### Game state

Every value is an **integer**, to get an identical replay from the same seed. Fractions (births, deaths, ageing) accumulate in thousandths and become people only when they pass 1000, so nothing is lost to rounding.

| Field | Unit | Range | Notes |
| --- | --- | --- | --- |
| `turn` | turn number | 1–12 | turns 3, 6, 9, 12 end a season |
| `rng_seed` | integer | — | stored in the log; the engine's only random generator |
| `food`, `wood`, `stone`, `gold` | whole units | ≥ 0 | the rare resource is outside the prototype |
| `children`, `adults`, `elders` | people | ≥ 0 | the three age groups of the peasants |
| `birth_acc`, `death_acc[3]`, `aging_acc[2]` | thousandths of a person | 0–999 | fractional accumulators |
| `workers` | adults per sector (food, wood, stone) | sum ≤ `adults` | unassigned adults produce nothing |
| `buildings` | list of (kind, status, turns left) | ≤ free tiles | kinds: farm, sawmill, quarry, house |
| `tax_rate` | percent | 0–30 | policy in force until changed |
| `ration` | level | reduced, normal, abundant | policy in force |
| `mood` | per mille | 0–1000 | peasants' mood |
| `low_mood_turns` | consecutive turns | ≥ 0 | below threshold, feeds the revolt by degrees |
| `unrest` | level | calm, protests, strike, revolt | |

### Action catalogue

Five actions are enough to test economy, demography and mood. Each order is a Pydantic model with an `action` field that identifies it; the same JSON schema is given to the LLMs as the required reply format.

| Action | Parameters | Cost | Effect | Minister |
| --- | --- | --- | --- | --- |
| `build` | building kind | wood + stone (+ gold for a house), from config | site completed after N turns | Architect |
| `assign_workers` | adults per sector (food, wood, stone) | none | replaces the assignment in force | Architect |
| `set_tax` | rate 0–30 % | none | more gold each turn, lower mood | Treasurer |
| `set_ration` | reduced, normal, abundant | none | changes food eaten per person and mood | Treasurer |
| `hold_feast` | gold to spend | the given gold | immediate mood boost, with diminishing returns | Treasurer |

### Validator

An order is **all or nothing**: it passes whole or is rejected with a code and a message that goes back to the minister. The orders of a turn are validated in a fixed order (priority given by the sovereign, then submission time), subtracting resources as they go: two sites that together exceed the available wood give one accepted and one rejected, always the same one.

| Code | When |
| --- | --- |
| `UNKNOWN_ACTION` | action not in the catalogue |
| `INVALID_PARAM` | parameter missing, of the wrong type or out of range |
| `INSUFFICIENT_RESOURCES` | the cost exceeds what is left after the orders already accepted |
| `NOT_ENOUGH_WORKERS` | the sum of assigned adults exceeds the adults present |
| `NO_FREE_TILE` | no free tile for the building |
| `DUPLICATE_POLICY` | a second `set_tax` or `set_ration` in the same turn |

An LLM reply that does not match the schema is already rejected by Pydantic, before the validator, and counts as `INVALID_PARAM`.

The validator also has a **dry-run** mode (`check_plans(state, orders)`): it runs the same checks without applying anything and returns, for each order, accepted or rejected with a code, plus the total cost and the resources left. This is the conflict report the engine hands to the Chancellor.

### Turn resolution

One turn = one month, resolved by a single function `resolve_turn(state, orders, seed) -> (new_state, events)`. The order of the steps is fixed and part of the spec: changing it changes the results, so every change is versioned (`ENGINE_VERSION`).

1. **Orders**: validated and applied in the fixed order; costs subtracted, policies updated, sites opened.
2. **Fixed rules (instead of Jev)**: automatic micro-decisions following the policies, e.g. moving unassigned adults to food when the reserve covers less than 2 months. Every decision produces an event, so you can see what the engine chose.
3. **Construction sites**: advance one turn; completed buildings work from this month.
4. **Taxes and upkeep**: gold = adults × rate / 20, then the upkeep of active buildings is paid. This comes before production because unpaid upkeep halves the output of the same month.
5. **Production**: workers × the sector building's output, reduced by season (farms only), strike and unpaid upkeep.
6. **Food consumption**: per person and per age group, times the ration. If food is short, everything is eaten and the missing part becomes hunger. Then the remaining stock loses 2 % to spoilage.
7. **Demography**: first deaths per group (base mortality + hunger), then ageing of the survivors (children → adults in about 30 turns, adults → elders more slowly), finally births (adults, mood; zero with hunger or full housing). Everything goes through the thousandth accumulators.
8. **Workers**: if the assigned workers exceed the adults left, they are reduced proportionally.
9. **Mood**: a target mood is computed from food, taxes, ration, housing and deaths; the real mood moves towards the target by a fixed fraction per turn, so changes have inertia. A feast is added at once, after this move, and a famine is subtracted at once (shock per point of missing food and per death).
10. **Unrest**: while mood stays below the threshold, `low_mood_turns` grows and `unrest` rises one level every N turns (protests → strike → revolt); above the threshold it goes down.
11. **Closing**: events to the bus; at season-end turns a full snapshot is marked.

### Edge cases

- **Negative resources**: impossible by construction. The validator blocks spending, consumption stops at zero and records the shortage as an event.
- **Deaths among workers**: if after demography the assigned exceed the adults, they are reduced proportionally with the largest-remainder method, which is deterministic.
- **Population zero**: game over with an explicit event; no division by zero in per-capita formulas.
- **Not enough housing**: no births and a mood malus, no direct deaths.
- **Revolt in the prototype**: stops production and ends the game as a defeat. Factions in exile and coups stay outside the prototype.
- **No orders in a turn**: the policies in force apply; the month is simulated anyway.
- **Replay**: given the same initial state, the same orders and the same seed, the result must be identical byte for byte; the engine never reads the clock, the environment or other random generators.

### Experiments and tests

- **Property tests (Hypothesis)**: thousands of random order sequences; checks that no resource or age group goes below zero, that workers never exceed adults and that replay is identical.
- **Simulations in `lab/`**: games of 12 and 120 turns without a UI, with handwritten strategies (e.g. maximum taxes, reduced rations) to find dominant strategies or death spirals.
- **Charts per turn**: population per age group, resources, mood and unrest, to see whether consequences arrive with the right delay.
- **LLM council only afterwards**: once the engine holds up on its own, Chancellor, Treasurer and Architect are connected together and validator rejections, cost and latency per turn are measured.

### Starting values

The values live in `engine/config.toml`, read with the standard library's `tomllib` (no extra dependency). They are a starting point meant to create tension from the first winter: food produced at the start is a little below consumption, and taxes above 20 % lead towards revolt. Percentages are integers: ‰ = per thousand, % = per hundred.

#### Start

| Parameter | Value |
| --- | --- |
| Population (children / adults / elders) | 30 / 60 / 10 |
| Food / wood / stone / gold | 1600 / 150 / 100 / 100 (food was 2000 until 2026-11-07) |
| Buildings | 4 farms, 1 sawmill, 1 quarry, 6 houses |
| Free tiles | 7 |
| Workers (food / wood / stone) | 54 / 4 / 2 |
| Tax rate / ration | 10 % / normal |
| Mood | 500 ‰, equal to the base (was 600: it drifted down by itself and the square read the drift as a sorrow without a cause) |
| First turn | January (winter) |

#### Buildings

| Building | Cost (wood / stone / gold) | Build turns | Jobs | Output per worker per month |
| --- | --- | --- | --- | --- |
| Farm | 40 / 10 / 0 | 2 | 15 | 15 food |
| Sawmill | 30 / 20 / 0 | 2 | 10 | 6 wood |
| Quarry | 40 / 10 / 0 | 2 | 10 | 4 stone |
| House | 30 / 30 / 20 | 3 | — | houses 20 people |

**Upkeep (approved rule)**: 1 gold per building per month, paid at the tax step; if gold runs short, buildings produce half that month. Without a fixed cost, zero taxes would always be the best choice.

#### Consumption and seasons

| Parameter | Value |
| --- | --- |
| Food per month per child / adult / elder | 6 / 10 / 8 |
| Ration multiplier (reduced / normal / abundant) | 70 % / 100 % / 130 % |
| Farm output by season (winter / spring / summer / autumn) | 50 % / 100 % / 120 % / 130 % |
| Taxes | gold per month = adults × rate / 20 |
| Fixed rule instead of Jev | if the reserve covers less than 2 months, idle adults go to food |

**Seasons (approved rule)**: the variable output applies only to farms and averages 100 % over the year. It makes the first winter the critical moment and gives stocks a purpose.

**Spoilage (approved rule)**: every month, after consumption, food stocks lose 2 % (`food_spoilage_pct`). Hoarding has a cost: with a surplus of 100 a month, stocks settle around 5000. 3 % was tried and changes little compared with 2 %.

#### Demography (per month)

| Parameter | Value |
| --- | --- |
| Births | 15 ‰ per adult; × 50 % with mood below 300 ‰, × 120 % above 700 ‰; zero with hunger or full housing |
| Base mortality (children / adults / elders) | 3 ‰ / 2 ‰ / 15 ‰ |
| Hunger mortality, extra for every group | 2 ‰ per point % of missing food (50 % missing = +100 ‰) |
| Children → adults | 33 ‰ (about 30 turns of childhood) |
| Adults → elders | 4 ‰ |

#### Mood and unrest

Target mood = 500 ‰ + sum of modifiers; the real mood moves 25 % of the distance each turn.

| Modifier | Value |
| --- | --- |
| Reduced / abundant ration | −150 / +100 |
| Taxes | −10 per point above 5 % (10 % = −50, 30 % = −250) |
| Hunger | −6 per point % of missing food, at most −400 |
| Food reserve over 3 months | +50 |
| Full housing | −100 |
| Deaths | −5 per death in the month |
| Feast | +1 per 2 gold spent, at most +100; half effect if there was a feast the turn before |
| Famine shock (immediate, not through the target) | −4 per point % of missing food, −10 per death of the month (approved 2026-11-07 after game 2 and the lab: without it a famine that killed 8 % of the people left the unrest calm) |

| Unrest | Condition | Effect |
| --- | --- | --- |
| Threshold | mood below 350 ‰ | `low_mood_turns` +1; above threshold −1 |
| Protests | `low_mood_turns` ≥ 2 | events and narration only |
| Strike | `low_mood_turns` ≥ 4 | production −30 % |
| Revolt | `low_mood_turns` ≥ 6 | game over (defeat) |

#### Hand check of the first year

With no orders from the sovereign, the first year should go like this (`tests/test_first_year.py`):

- **Food**: at full output 54 × 15 = 810 units are produced per month and 860 eaten; then 2 % of the stock spoils. Winter takes the reserve from 1600 to about 195, spring holds it near 100, and the year closes at about 1150, helped by the fixed rule that sends new adults to the 6 free farm jobs. Without orders the second winter is a famine and the people revolt at turn 20: a passive sovereign loses in the second year.
- **Population**: +8 people in the first year (108); the houses (120 places) last about 2 years.
- **Mood**: from 500 to about 430 ‰ at year end with taxes at 10 %, always above the threshold.
- **Gold**: +30 from taxes, −12 upkeep, so +18 per month.
- **Wood**: 4 workers × 6 = 24 per month, so a farm (40 wood) costs almost two months of production.

The first real choice is between food and construction: almost all adults are needed in the fields, and every worker moved to wood or stone cuts the winter stocks. With a simple handwritten player (`lab/compare_variants.py`) food after two years reaches 3128 instead of 11660 with the earlier values, and wood becomes the bottleneck.

Open points from the simulations:

- Gold still piles up (about 600 in two years) because it is spent only on houses and feasts; it needs other uses. Decision deferred until the game is more complete; options considered: a simple market with fixed prices and a margin (preferred), concessions during unrest, higher recurring costs, expensive goals (eras, army, spies).
- 5–8 adults stay idle without orders, because the fixed rule sends them only to the farms.

## Database

The database saves, remembers and filters: it never takes part in computing the turn, which stays entirely in the engine. The schema covers the prototype (one game, one state, Chancellor and two ministers) but already has the `game_id` and `realm_id` columns, so multiplayer does not require redoing the tables. Outside the prototype: named citizens, spies, treaties, policies for Jev.

### Tables

| Table | Content | Written by | Notes |
| --- | --- | --- | --- |
| `games` | game: seed, copy of the config (jsonb), engine version, status (running, paused, finished) | server | the config is copied, so tuning `config.toml` does not change games already started |
| `players` | human players: name, invite date | server | authentication outside this spec |
| `realms` | states of the game: name, player (empty if automatic) | server | |
| `actors` | Chancellor, ministers and Voice of the square of a state: role, model, personality (jsonb), sovereign's trust | server | |
| `turns` | one turn per game: number, status (open, resolving, resolved), deadline, resolution time | server | |
| `snapshots` | full state of a realm per turn (jsonb), format and engine version | server | one per turn, see below |
| `orders` | **append-only log** of orders: raw JSON received, who gave it, priority, submission time | server | replay source with snapshots and seed; outcomes are in `order_results`, also append-only, so orders are never modified |
| `events` | **append-only log** of engine events (kind, jsonb data) with a visibility label | server | the stored event bus |
| `council_messages` | council chat: speaker, text, turn, visibility, `kind`, `round`, `payload` | server | |
| `memories` | memory written by the LLM: text, turn, visibility | server | reserved for later |
| `lessons` | secret lessons of each council member, with their history | server | no visibility level, no access for `agent_reader` |
| `audiences` | private audiences | server | same secrecy as `lessons` |
| `model_calls` | model call log: model, input and output tokens, USD cost, latency in ms, status, error, refused reply excerpt, prompts | server | basis for cost checks |
| `schema_migrations` | migrations already applied | migration script | |

IDs are `bigint` generated by the database; times in `timestamptz`; costs in `numeric(10,6)` so fractions of a cent are not lost. Append-only tables have a trigger that rejects `UPDATE` and `DELETE`.

### Visibility

Every row of `events`, `council_messages` and `memories` carries its owning state (`realm_id`) and a level (`visibility`, a PostgreSQL enum). A reader has a **clearance**; they see a row of their own state if its level does not exceed their clearance.

| Level | Sovereign | Chancellor and ministers | Court (Voice of the square, Tribune) | Other states |
| --- | --- | --- | --- | --- |
| sovereign's secret | yes | no | no | no |
| council | yes | yes | no | no |
| court | yes | yes | yes | no |
| public | yes | yes | yes | yes |
| foreign | only the receiving state (`audience_realm_id`), at council level | | | |

In the prototype there is only one state, so the foreign level exists in the schema but is not used yet.

**How row-level security enforces it**:

- Two database roles: `game_admin` owns the tables, applies migrations and writes everything (the owner is not subject to policies; in the development container it is the superuser, on the home server it will be a role without superuser privileges); `agent_reader` can only read and is always filtered.
- To build an agent's context the server opens a transaction, switches to `agent_reader` with `SET LOCAL ROLE` and sets `app.game_id`, `app.realm_id` and `app.clearance` (4 sovereign, 3 council, 2 court, 1 outsider). At the end of the transaction everything is back as before.
- The policy reads the settings with `current_setting` without a fallback: if the server forgets to set them, the query fails with an error instead of showing too much or too little.
- An agent cannot reveal what it never received: the filter is in the database, not in the prompt.

### Snapshots and replay

- **Format**: the engine's `GameState` converted to JSON with sorted keys, plus `format_version` and `engine_version`. The engine has a function to save it and one to load it, with a test that a round trip gives the same state.
- **One snapshot per turn** (the vision said season end only): the server needs the current state every turn, and the cost is small (about 2 KB × 120 turns × 8 states = about 2 MB per game). The snapshot of turn N is the state at the start of that turn (turn 1 = new game). A column marks season-end snapshots, which remain the ones used for reports.
- **Replay**: snapshot at turn T + orders of the following turns + config stored in the game must give exactly the snapshot at turn N. A lab command checks it on a whole game; if it fails, the engine is no longer deterministic.
- **Raw orders**: the JSON is saved as it arrived, even when parsing rejects it. It is the record of what the LLM really answered, useful for debugging.
- **Format change**: if `GameState` changes, `format_version` goes up and a function converts old snapshots; without conversion an old game does not load.

### Migrations and Docker

- **Postgres in `compose.yaml`**: image with a pinned version (18.6), `pgdata` volume for the data, port published only on `127.0.0.1` (for psql or a GUI client from the PC, never to the network). Password in a `.env` file that must not be shared.
- **Migrations**: numbered SQL files in `db/migrations/` (`001_init.sql` … `006_square_voice_and_prompts.sql`), applied in order by a short Python script that records the applied ones in `schema_migrations`, each in a transaction. No Alembic: it would need SQLAlchemy, which we do not use.
- **Access from Python**: psycopg 3 and handwritten SQL, in a `server/db/` module separate from the engine.
- **Tests**: the `tests` service starts after Postgres and uses a test database created from scratch on every run. Dedicated tests for every level/clearance combination of the table above.
- **Backup**: periodic `pg_dump`, together with going live on the home server.

**Hidden costs**:

- Row-level security filters **silently**: with wrong settings an agent sees zero rows, not an error. Hence the tests per level and clearance.
- `SET LOCAL` only holds inside a transaction: a query outside a transaction would not have the expected filter. The access module offers a single function to open an agent's context (`agent_context`).
- The scripts in Postgres's `docker-entrypoint-initdb.d` run only with an empty volume, so they cannot evolve the schema: hence the migration script.

### Engine and database together

Resolving a turn is **a single transaction** (`resolve_open_turn`): it locks the turn row, resolves each realm in id order, saves order outcomes, events and the new snapshot, closes the turn and opens the next one. If anything fails nothing is written and the turn stays open.

- Orders are stored as they arrive and interpreted only at resolution; the priority is the column's, not any priority written in the JSON.
- A paused game, or one created with another engine version, is not resolved: with different rules the results would change.
- The game ends when no realm is still in play (in the prototype: revolt or extinction of the only realm).
- `lab/replay.py <id>` replays a game from the stored orders and reports the first turn that does not match.

Visibility of engine events (approved). An event kind not listed here stops resolution with an error, so every new event needs an explicit decision.

| Level | Events |
| --- | --- |
| public | `famine`, `unrest_changed`, `game_over` |
| court | `building_completed`, `season_end`, `demography` (births and deaths are seen by everyone in a small town) |
| council | `food_spoiled`, `upkeep_unpaid`, `rule_workers_to_food`, `workers_rescaled` |

The `audience` event (**public**: the fact that the sovereign received a counsellor is not a secret, only the words are) is written by the audience module, not by the engine, so it is not in this table (`EVENT_VISIBILITY` in `server/db/games.py`). Events already stored keep their level: the table is append-only.

## HTTP server

The FastAPI server runs in Docker, applies migrations at start and reloads on every code change. Interactive docs at `/docs`. It binds `127.0.0.1:8000` and the PC's Tailscale address. Approved decisions: no authentication while the server is reachable only from the owner's devices; turn resolved by hand.

| Method and path | What it does |
| --- | --- |
| `POST /games` | creates a game with the current config |
| `GET /games/{id}` | game status, open turn, realms |
| `GET /realms/{id}/state` | latest snapshot, filtered for the sovereign (see "Sovereign view") |
| `POST /realms/{id}/orders/check` | dry run: outcome of each order, costs and resources left |
| `POST /realms/{id}/orders` | stores an order in the open turn (409 if closed, 422 if malformed) |
| `GET /realms/{id}/orders?turn=N` | orders of the turn with their outcomes |
| `GET /realms/{id}/events?turn=N` | events read with the same row-level security as the agents, sovereign clearance |
| `POST /games/{id}/turns/resolve` | resolves the open turn (409 if there is none, if the game is paused or if the engine version differs) |

Endpoints are synchronous with a pool of 10 connections; LLM calls are asynchronous.

## LLM council

One meeting per turn: Treasurer and Architect propose, the Chancellor puts it together, the sovereign decides. A normal meeting costs **3 calls** (plus the Voice of the square); each directive from the sovereign adds 3, up to 2 directives per turn. The engine always computes the numbers: the LLMs read and write words and orders, they do no arithmetic.

### Flow

1. **Briefing**: for each role the server prepares a compact briefing from the snapshot, the events of the previous turn (read with `agent_context`, council clearance) and its recent proposals with their outcome.
2. **Ministers**: Treasurer and Architect each reply with a short report for the sovereign and a list of proposed orders.
3. **Check**: the server drops malformed orders or orders outside the role, then runs `check_plans` on all proposals together and gets costs, conflicts and resources left.
4. **Chancellor**: receives reports, proposals and the conflict report; writes a summary for the sovereign and a **plan** (a list of orders, each with the minister who proposed it), which is checked again with `check_plans`.
5. **Sovereign**: approves the plan, possibly removing single orders, or writes a **directive** in free text ("save wood, winter will be long"): steps 2–4 repeat with the directive in the briefing.
6. **Approval**: the approved orders become the turn's orders, recorded with the minister who proposed them (needed later for trust).

### Roles and permissions

| Role | Actions it may propose | What it sees in the briefing |
| --- | --- | --- |
| Treasurer | `set_tax`, `set_ration`, `hold_feast` | gold, income and upkeep, food, consumption, months it would last without harvest, **harvest expected this month and where the store would end** (`expected_output` in the engine, exact when the turn has no orders), tax rate, ration, unrest level (no mood number) |
| Architect | `build`, `assign_workers` | wood, stone, buildings and sites, free tiles, workers and jobs per sector, idle adults, **jobs without workers** ("a new building adds jobs, not workers"), **output expected this month**, housing and population |
| Chancellor | no actions of its own: it recombines the ministers' | everything above, plus the turn's reports, proposals and conflicts |

Everyone sees turn, season and months to winter, and council-level events. An order proposed outside one's role is dropped and noted.

**Orders that change nothing** (a tax rate, ration or worker assignment equal to the one in force) are dropped from the plan the sovereign reads, recorded as discarded with `NO_CHANGE`. They were in most plans of games 1 and 2.

**Facts every counsellor prompt states** (added after game 2): there is no market yet, so gold cannot buy food and a feast only lifts the mood; use the months to winter and the expected harvest; nobody knows the mood as a number. Ministers speak only of their own orders, cite the two or three numbers that matter, and bring back a refused measure when the situation has clearly changed (hunger, deaths, protests, strike) instead of treating a refusal as a taboo. The Architect builds only where free adults can fill the new jobs.

### Personality in the prototype

- Only the first and second layers: fixed **role** and five **traits** (caution, loyalty, ambition, honesty, competence) from 0 to 1000, drawn near the centre at game start with the game's seed.
- Traits enter the prompt as words ("rather cautious", "very ambitious"), not numbers. Résumé, trait evolution and variable trust come later.

### Reply format

- Each reply is a JSON object validated with Pydantic: `report` (text for the sovereign, at most about 120 words, in Italian) and `proposals` (orders from the catalogue, optional). The Chancellor replies with `summary` and `plan`.
- Structured JSON is requested from OpenRouter; if the model or provider does not support it, JSON is requested in the prompt and validated anyway. An invalid reply gets **one retry**, with a reminder explaining what was wrong; then the minister is absent for that turn.
- Prompts are written in English in editable text files (`server/council/prompts/`); the reply language is a parameter (Italian). The fixed part of the prompt (role, personality, rules) comes first, so providers that cache the prefix reuse it from turn to turn.

### Models and budget

- **Models**: today every role uses `deepseek/deepseek-v4.1-flash`, reasoning effort `low` (Voice of the square `none`). Planned tiers once prompts are tuned: `deepseek/deepseek-v4-pro` for the Chancellor, `z-ai/glm-5.3` for the ministers. They live in `server/council.toml`: changing them needs no code.
- **Reasoning effort**: compared on real runs: default (78 s, $0.0062 per meeting), ministers at `none` (32 s, less coherent), all `low` (33 s, $0.0030). Chosen: all `low`.
- **Cap per game**: $1. Before every call the server adds up the costs already recorded in `model_calls`; past the cap the council falls back to no-LLM mode for the rest of the game and tells the sovereign.
- **Monthly cap**: set on the OpenRouter key from its dashboard. The key lives only in `.env` and reaches only the server container.
- **Cost of each call**: tokens and cost as returned by OpenRouter, stored in `model_calls` with latency and status (ok, timeout, invalid reply, budget exhausted).

### Fallback and timing

- **Absent minister** (timeout, invalid reply twice, budget exhausted): no proposals, an "absent" report generated by the server.
- **Timeout**: a deadline of 90 seconds on the **whole** call (`timeout_seconds`). httpx's own timeout bounds only each network wait, and OpenRouter keeps the connection alive while the model reasons: in game 7 a call ran 221 s with a 60 s timeout. The client reads the answer in chunks and gives up past the deadline (worst case about twice the deadline if the server goes silent). Hidden cost: OpenRouter may bill the tokens generated before the abort, which we never see.
- **Output cap**: `max_output_tokens = 8000` per call, reasoning included (normal replies stay under ~6500). In game 7 a model looped up to 131,072 tokens ($0.074, 31 % of the game). A reply cut by the cap is incomplete JSON and is retried like any invalid reply. When a reply ran up to the cap, the retry goes without reasoning (`none`): DeepSeek V4.1 Flash supports only reasoning levels, not a reasoning budget (OpenRouter `supported_efforts`: max, high, low, none), and 5 of the 6 refusals in games 5–7 were such runaways.
- **Absent Chancellor**: the server writes a fixed-template summary with the ministers' proposals and the `check_plans` conflicts; the plan is the list of proposals that pass the check.
- **Meetings run in the background** (see "Web UI"); through the JSON API they run inside the request.
- **Fake LLM**: a deterministic client that returns test proposals, used in tests and to play without spending. Chosen in the server config (`provider = "fake"`, overridden by `COUNCIL_PROVIDER`).

### Stored data

- Migration `002`: `council_messages` gets `kind` (directive, report, summary, later voice), `round` (1 = meeting, 2–3 = after a directive) and `payload` (jsonb: proposed orders or plan, with dropped orders and the reason). Visibility: council.
- Migration `004`: `model_calls` gets `error` and an excerpt of refused replies.

### Endpoints

| Method and path | What it does |
| --- | --- |
| `POST /realms/{id}/council/meeting` | opens the meeting of the open turn (one per turn, otherwise 409) |
| `POST /realms/{id}/council/directives` | sovereign's directive and a new round (at most 2 per turn, then 409) |
| `GET /realms/{id}/council?turn=N` | council messages of the turn |
| `POST /realms/{id}/council/approve` | approves the latest plan, with the list of orders to remove |

### Tests

With the fake LLM, no network: full meeting stored; out-of-role orders dropped; invalid reply with one retry then absent minister; budget exceeded with fallback; directives beyond the limit refused; approval that records the orders with the proposing minister. Real runs with OpenRouter are done by hand, only when needed, to check format, cost and timing.

### Memory and lessons

Ministers and Chancellor learn from experience in two ways, without knowing the engine's rules.

- **Consequences in the briefing** (no extra calls): for the previous 6 turns each council member sees what it proposed, what was carried out, what else was decided in the same turn and how its numbers changed in the next two months (Treasurer: food, gold; Architect: food, wood, stone, idle adults; Chancellor: food, gold, wood, stone; never the mood), with the relevant events it could know. The Chancellor also sees which orders of its plan the sovereign removed and which directives were given: this is how it learns the sovereign's preferences.
- **Season-end review** (1 call per council member per season): at the first meeting of turns 4, 7, 10, … each council member rereads the season and, for each lesson, picks a reasoned action: confirm, revise (the old version stays in the history), drop, or nothing; it can also add new ones. At most 10 active lessons, no automatic forgetting.
- **Visible strength**: in the briefing each lesson shows how many times and when it was confirmed ("confirmed 2 times, last in turn 10"), so a settled habit weighs more than a recent impression.
- **Invalid replies**: only malformed JSON (or a missing key) is retried, with a reminder explaining what was wrong; if it fails again the lessons stay as they were. A single bad action (non-existent lesson number, revise or drop without a reason, revise without text) is **discarded on its own** and the other actions apply; new lessons beyond 10 are cut. Small slips are tolerated (key case and spaces, a lesson number as a string). What was discarded is noted in the `error` column of the accepted call. Decided after game 7, where a single revise without a reason cost a whole season.
- **Lessons are secret**: table `lessons` (migration `003`) with no visibility level and no access for `agent_reader`; no endpoint returns it. The server reads it only for the briefing of the member who wrote it.
- **Trial** (game 6, turns 1–10, DeepSeek V4.1 Flash, $0.082 in total): the Treasurer revised "reducing rations does not stop the fall of food" citing the numbers of turn 6; the Architect revised "a farm pays off only after months" after seeing food rise at once; the Chancellor updated what it knows of the sovereign's choices. Some wrong beliefs that were never disproved also remain ("the proposed tax is not always applied in full"). That is expected and part of the character.

### Private audiences

The sovereign can speak privately with a council member (Treasurer, Architect or Chancellor) during the open turn. Approved decisions: **words only**, orders always go through the council; **the fact is public** (decided on 2026-11-07: meeting a counsellor in private is not a secret act), the content stays secret; the member **may stay silent or embellish** according to character, but never change the numbers.

**Flow**

1. The sovereign writes a line; the member answers (5–20 seconds, in the background like the meeting).
2. The member receives its briefing (the same numbers and its secret lessons), the audiences with the sovereign of the last 3 turns and the new line. It may use its lessons, but decides itself whether to reveal them.
3. It answers in plain text, not JSON (fewer refused replies), in Italian, at most about 120 words. It may say what it intends to propose in council, not give orders.
4. If the answer does not arrive (timeout, error, budget exhausted), the sovereign's line stays and the panel says so; the next line gets an answer to both.

**Effects in the game**

- **On proposals**: at the next meeting that member's briefing includes the recent audiences ("in private audience the sovereign told you…"), so what was said changes its proposals.
- **On the others**: the other members see only the fact ("this month the sovereign received the Architect in private"); the fact is public, so it also goes to the chronicle and the Voice of the square can mention it.
- **On lessons**: at the season-end review the member also rereads the season's audiences, and can learn what the sovereign really wants.

**Limits and costs**

- At most **6 sovereign lines per member per turn** (`max_audience_messages_per_turn` in `council.toml`).
- Each answer: about 2–3 thousand input tokens, $0.001–0.003 with DeepSeek Flash; it counts towards the cap per game.
- One model job per realm at a time: during the council meeting audiences wait, and vice versa.

**Data and secrecy**

- Migration `005`: table `audiences` (game, realm, member, turn, speaker, text), append-only, **with no visibility level and no access for `agent_reader`**, like lessons.
- The content is seen only by the sovereign (on the audience page) and by that member (in its briefing). Never in the other members' briefings nor in the chronicle.
- A public `audience` event records only the fact.

**Interface**

- On the turn page, a "Private audiences" section with one button per member.
- Dialogue page: sovereign's lines on the right, the member's on the left in its colour; text box; lines left; refresh every 2 seconds while the member answers.
- Matching JSON endpoints for `/docs`.

**Tests** (fake client): dialogue stored and shown; audience in the member's briefing at the next meeting and absent from the others', who see only the fact; audiences in the season-end review; line limit; missed answer; `agent_reader` with no access to the table; model text treated as text on the page.

**Trial** (game 6, turn 10, DeepSeek V4.1 Flash, 5 seconds, $0.0002): asked for an opinion on the Treasurer, the Architect answered "in council I praise him, because quarrelling builds nothing, but I know his accounts slow us more than they protect us", with the real wood numbers, and announced what it will propose at the next meeting.

**Out, for now**: leaks and jealousy (they need variable trust and loyalty), audiences with other characters (Voice of the square, ambassadors).

### Sovereign view and Voice of the square

The sovereign knows the people through others: the square and the council. Approved decisions: **no number and no summary word for mood** in the sovereign's view; the Voice of the square **may be a little wrong**, because it reacts more to recent events than to the slow trend.

**What the sovereign sees**

| Stays exact | Disappears |
| --- | --- |
| food, gold, wood, stone, food consumption | mood (number) |
| inhabitants per age group, housing | consecutive turns below the threshold |
| buildings, sites, free tiles | birth, death and ageing accumulators |
| workers and jobs per sector | game seed |
| taxes, ration, unrest level (protests and strikes are public) | |

This applies to the Turn and Kingdom pages and to the `GET /realms/{id}/state` endpoint (`server/sovereign_view.py`). The full state moves to the admin view.

**The Voice of the square**

- **When**: at every council meeting, before the ministers (first round only, not after directives). 2–3 sentences; at the first meeting of each season a longer story of the season just closed (up to about 150 words).
- **What it knows**: only what is evident to the people. It reads events with **court** clearance, so palace accounts (upkeep, spoilage, rescaled workers) never reach it.
  - The exact mood: in a monthly story over the peasants' memory horizon (`PEASANT_MEMORY_MONTHS = 3`, the current month and the two before); in a season story the three months of the season plus the starting value, so the trend shows and the story covers exactly the season.
  - Unrest level and months of deep discontent.
  - **Why the people feel as they do**, heaviest first and in words ("the taxes (crushing); the short ration (heavy)"): the engine's own mood factors (`mood_factors` in `engine/turn.py`), limited to what the people feel directly (taxes, ration, hunger, crowded houses, mourning). The reserve bonus is left out because it would reveal the granaries. The prompt asks it to talk most about the heaviest burden and never to invent events. Added after game 1, where the square blamed hunger while the taxes weighed most, and the council believed it.
  - **Not the granaries**, not even in words: the people cannot know the stock or the treasury, they can only guess from the ration, hunger and feasts (and may guess wrong). Ration and taxes, which they feel directly.
  - The events of the months told (famine, unrest, construction, births and deaths, audiences as a fact) and the decisions of the crown carried out.
  - **What it said in the last two turns**, to keep the thread (the same people, events that move on) without repeating the same images or carrying an old complaint forward.
  - Prompt rules tightened after game 2: no numbers even in words ("cinque bare"), no invented events (sales, carts, envoys).
- **What it says**: pleas, market rumours, complaints, celebrations, in Italian, **never numbers**. The prompt asks it to weigh what just happened more: after a famine it may exaggerate the anger, and it may miss slowly growing discontent.
- **Who hears it**: the sovereign, on the turn page, and the council members, in their briefing ("## What they say in the square", the last three months, each with its month). Visibility: court.
- **Model**: cheap tier without reasoning (DeepSeek V4.1 Flash to start, like the others), about $0.0001–0.0002 per story, within the cap per game.
- **If it does not answer**: no story that month, the meeting goes on.
- **Data**: new message kind `voice` in `council_messages` (migration `006`); one `square_voice` actor per realm, created with new games and, for existing ones, at the first meeting. No lessons or audiences for the Voice, for now.

**Council members do not see the mood either** (decided on 2026-11-07, after game 7, where 19 of 51 reports quoted the exact number to the sovereign). The engine keeps the number because it drives the simulation, but only the Voice of the square reads it, to turn it into words. Counsellors know the people from what the square said in the last three months (the season review rereads the whole season) and from the unrest level, which is public. Their lessons about the people are therefore less precise and sometimes wrong, like a real court's.

**Trial** (game 7, January, 2 seconds, $0.00008): "In the square they say the grain is enough, and that winter is hard but people get by. Some grumble about the cold and the dear firewood, but nobody raises their voice. 'As long as there's bread, let the king do as he likes,' says the old woman at the well." No numbers. Both ministers then picked up "the dear firewood" in their reports: the square really influences the council, even when it exaggerates (wood was 150).

### Admin view

The admin sees everything, separate from the sovereign's view.

- **Access**: enabled only with `ADMIN_VIEW=1` in `.env`; when off, the `/admin` pages answer 404. Reachable only from devices on the Tailscale network. With accounts it will become a reserved role.
- **Link**: when enabled, the top bar shows "Amministrazione".

| Page | Content |
| --- | --- |
| `/admin` | all games: status, turn, spend in dollars |
| `/admin/games/{id}` | for each realm the full state (mood, accumulators, ongoing unrest); replay check with a button; spend per council member |
| `/admin/realms/{id}/turns/{n}` | the turn seen from inside: council messages with their data, every model call with the prompt sent, reply, tokens, cost, time, error |
| `/admin/realms/{id}/lessons` | each member's lessons with their history: confirmed, revised, dropped, with the reasons |
| `/admin/realms/{id}/audiences` | all private audiences |
| `/admin/realms/{id}/agents` | each agent: model, reasoning effort, calls and cost, traits with the words they become in the prompt, every system prompt it can receive (rendered now by the same functions the council uses) and its last briefing sent |

- **Stored prompts**: migration `006` adds the system prompt and the briefing of every call to `model_calls`, cut to 20,000 characters each: about 10 MB for a 120-turn game. They explain why a member answered the way it did.
- **Everything read-only**, except the replay check, which writes nothing.

**Decision for later**: in games with friends the admin view would show their private audiences and their ministers' lessons. Before the first real game with other players we must choose whether the admin does not play, or whether in running games the view hides the other players' secrets.

**Tests** (fake client): the sovereign's view contains no mood on any page nor in the state endpoint; the Voice speaks in the first round, not after a directive, and enters the members' briefings; long story at season start; absent Voice does not block the meeting; with `ADMIN_VIEW` off `/admin` answers 404; on, it shows full state, lessons, audiences and prompts; model text stays text on the admin pages too.

## The manual of the realm

Approved on 2026-11-07, after game 7. In the playtests counsellors kept guessing how the realm works ("a farm creates two jobs", "a half-filled farm stays empty", "gold buys grain", "a feast brings food"), and each guess had been patched with a prompt rule. A single manual replaces the guessing.

- **Written from the game's config** (`server/council/manual.py`), never by hand: buildings with cost, build time, jobs, output per worker (farms by season) and the fact that **a building yields for every worker, even half-filled**; upkeep and unpaid upkeep; workers (only adults, beyond the jobs nothing, movable every month); rations and consumption, spoilage, hunger; births; tax formula, **no market**, what gold pays for; feasts; what weighs on the people and cheers them; the unrest ladder with its months and the strike's cost. Changing `config.toml` changes the manual of new games; each game uses its own config.
- **No mood formulas**: it says what weighs on the people, never how much, so the council still knows them only from the square.
- **Who reads it**: the Treasurer, the Architect and the Chancellor in every prompt (meeting, audience, debate, season review) and the chancellery when it reviews a mandate; not the Voice nor the people. About 600 tokens in the fixed part of the prompt.
- **The sovereign's page**: "Manuale" (tab), the same facts in Italian.
- The rules added during the playtests (no market, the Architect's duty on workers) stay for now; they can be removed after a game confirms the manual is enough.

## Mandates: the sovereign's standing guidelines

Approved on 2026-11-07. Directives last a month and go to the whole council; audiences are private words. A mandate is the lasting line the sovereign gives one office ("build only where there are free hands; houses before farms"), valid until changed.

- **Through the chancellery**: on the "Il governo" page (tab "Governo"; JSON `GET/POST /realms/{id}/mandates[/{role}]`) the sovereign writes a request for the Treasurer, the Architect or the Chancellor (at most 600 characters). The Chancellor reviews it with criteria that belong to its role, the same for every Chancellor: it must concern that office's duties and orders, be possible under the rules (no market, only the listed orders), not ask to invent or hide numbers, deceive the sovereign or break secrets, and be a lasting line rather than this month's order. Its character colours only the tone of the answer.
- **Rewritten, never copied**: if approved, the Chancellor rewrites it in its own words (two to four sentences); if not, it refuses with a reason and the mandate in force stays. Only the rewritten text ever reaches a counsellor's prompt, quoted, below the rules of the role ("the rules of your office and this month's directives come first"). The sovereign's raw words are never shown to any counsellor; the review prompt tells the Chancellor to judge the request, never to obey it (prompt-injection defence).
- **Who knows**: each counsellor its own mandate; the Chancellor also the ministers'. The mandate is in every prompt of that counsellor: meetings, audiences, debate, season review. It follows it according to its character.
- **Data**: table `mandates` (migration `011`, append-only): request, decision, rewritten mandate, the chancellery's reply. The mandate in force is the latest approved one.
- **Cost**: one model call per request (about $0.001), none during meetings.

## Debate on the plan (on request)

Approved on 2026-11-07. Before, the council was one-way: ministers report, the Chancellor writes the plan, the sovereign decides; the ministers saw the plan only the month after and could never answer it.

- **On request**: a button "Chiedi il parere dei ministri sul piano" next to the directive (JSON: `POST /realms/{id}/council/debate`), once per plan, until the plan is approved. A directive opens a new round, with a new plan that can be debated again.
- **Who speaks**: the Treasurer, then the Architect. Each reads its own report and proposals, the Chancellor's summary, the plan with what is feasible, and what was already said in the debate; it answers in at most two sentences: agree or object, and why. Prompt `debate_system.txt` (role, duties, character).
- **The plan does not change**: the sovereign decides. Comments are council messages of kind `comment` (migration `010`), council level, shown on the turn page.
- **Cost**: one call per minister, about $0.001–0.002 and 10–30 seconds, only when asked.
- Public, unlike the secret notes: in council a minister may say one thing while its note said another.

## Secret notes between counsellors

Approved on 2026-11-07, after game 6 (the Chancellor already suspected the Treasurer but had no way to act).

- **One a month, to one colleague**: the Treasurer, the Architect and the Chancellor may each add a note to their usual council reply (`"note": {"to": role, "text": ...}`), so it costs **no extra call**. Only for a purpose: a proposal, a pact, a warning, an answer. A second round after a directive cannot add a second note.
- **Delivered at the next meeting**: the recipient finds it in its briefing ("## Secret notes", the last three turns, received and sent), and also in its private audiences and its season review, where it can learn whom to trust.
- **The Chancellor stands above the parties**: its role text says it may hear every counsellor, also in notes, but weighs their words for the good of the realm, not to repay a favour; how faithfully depends on its character (loyalty, honesty). A role duty, not a personality trait.
- **Entirely secret**: not even the fact that a note was sent is recorded anywhere else: no event, no chronicle, no square. Table `counsel_notes` (migration `009`), append-only, no grant to `agent_reader`.
- **The sovereign can only ask**: in a private audience the counsellor sees its notes and the rule that the sovereign does not know whether any note exists; it may tell, deny or keep silent, according to its character (honesty trait).
- **Admin**: the turn page lists the notes written that turn.
- A bad note (to oneself, to someone outside the council, empty, not an object) is dropped; the rest of the reply stays valid.

## The people decide

Approved on 2026-11-07, after game 4: the square's opinion must turn into what the people do, otherwise the sovereign governs a people that never acts. First use of the decision service planned for Jev (state + typed questions → a bounded choice).

**Each month**, at the meeting, right after the Voice of the square and before the council:

1. A cheap model (`people` in `council.toml`, DeepSeek V4.1 Flash without reasoning, about $0.0002) plays the peasants as a whole. It reads how they feel (the mood band and the exact mood, never to be written), what weighs on them (the same felt factors as the square), the unrest, ration and taxes, what the square said, the crown's decisions of last month and its own last two decisions.
2. It chooses, inside the limits of the mood band (`[people]` in `engine/config.toml`, checked by `engine/people.py`):

| Behaviour | Effect in the engine | Content (mood > 550) | Neutral | Discontented (< 400) |
| --- | --- | --- | --- | --- |
| Effort | percent added to the yield of fields, sawmill and quarry | 0 to +15 | −8 to +8 | −25 to 0 |
| Births | percent of this month's births | 100 to 125 | 95 to 110 | 60 to 100 |
| Petition (optional, rare) | a request to the crown: one `set_tax`, `set_ration` or `hold_feast` that changes something, with the people's words | granted: the order decides its law for the turn (it runs first, the plan's orders on the same law are not sent) and the mood rises at once by the petition's weight; refused or unanswered: it falls by the same | | |

**Weight of a petition** (after game 5): half the relief the asked order brings to the people's burdens, between 10 and 30, computed when the people decide (`petition_weight` in `engine/people.py`) and stored with the decision. Taxes 10 → 7 % is worth 15, a ration back from reduced to normal 30, a request that relieves nothing only 10. A fixed +30 made trivial requests worth far more than their own effect, a "mood pump". Ranges widened at the same time: effort moved little and births stayed below 100 % almost every month.

3. The choice is stored in `people_decisions` (migrations `007` and `008`, append-only), the sovereign's answer in `petition_answers`. The resolution and the replay read them like orders, so **the engine stays deterministic**. Values outside the limits are clamped; an impossible petition (no change, not the people's to ask, more gold than the treasury holds, no words) is dropped. If the model is silent, fixed rules take the middle of each range.

**Who sees what**

- **Sovereign**: on the turn page, the behaviour in words ("I contadini lavorano svogliati; le famiglie rimandano i figli"), the numbers in a "I conti" box, and the petition with "Esaudisci" and "Respingi". JSON: `GET /realms/{id}/people?turn=N`, `POST /realms/{id}/people/petition`.
- **Council**: "## The people this month" in every briefing (behaviour in words, the petition and what granting it would do); the harvest estimate includes the people's effort.
- **Square**: the next month it is told what the people did and how the crown answered, and tells it.
- **Admin**: everything, including the model's reason and whether the model or the rules decided (turn page, agents page).

**Games saved before** have no `[people]` section in their config: the people decide nothing and their results do not change.

**Next behaviours** (after a played test): tax evasion (part of the taxes not collected), emigration (families leave after long, deep discontent), voluntary work (a site finishes a month early when the mood is high). The strike stays as the fixed extreme of the unrest ladder.

## Territory: map, town plan, expansion (phase 4, step 1)

Approved on 2026-11-08. The first step of the map, with a single realm: the city lives on tiles, buildings take several tiles, the Architect plans the town and the realm grows onto the tiles around it, paying gold and labour. Other states, trade and war come in the next steps. Phase 3 (accounts) is set aside until the game dynamics are richer.

**Feasibility** (`lab/urban_probe.py`, 2026-11-08): GLM 5.3 Flash "high" drew zones and placed three buildings on a 16 × 16 text map. 7 of 11 replies fully valid, 2 more failed only on a rule too strict (houses around the square in the "center" zone), 1 off by one on a 3-wide farm, 2 confused (overlapping zones, buildings on buildings). The plans made sense: square in the middle, fields next to the fields, sawmills along the forest, reserves for later. Hence: the engine checks every placement, one retry, and the model never counts tiles itself.

**Map**

- **World**: 64 × 64 tiles (`engine/maps/world.txt`; 40 × 40 left too little room between 8 cores), the same for every game, drawn with the help of `lab/draw_world.py`; the file is the source of truth. Terrains: plain, river, forest, hill. Later it may be generated from the seed.
- **8 starting sites**, ready for the automatic states. Every site has the **same 12 × 12 core**, rotated or mirrored (symmetric starts). The seed picks the site of the realm.
- **The core** is owned and cleared at the start: river, forest, hill, the square and the 12 starting buildings already placed, and a starting zone plan. The starting buildings take about 60 tiles, so the need to grow comes within the first year or two (12 × 12 to be confirmed by the lab).
- **Footprints**: house 1 × 1, sawmill 2 × 1 (must touch a forest tile), quarry 2 × 2 (on hill), farm 3 × 3 (on plain), square 2 × 2 (fixed). No roads: buildings stand side by side.
- **In the engine** (`engine/territory.py`): the world rows and the ownership rows are part of the realm state, every building has an id and a position, the zones and the square are in the state; free space comes from the map. The snapshot holds the map (about 10 KB a turn instead of 1 KB), so replay stays exact. Games saved before have no `[map]` in their config: they keep counting `free_tiles` and replay unchanged, so `ENGINE_VERSION` did not need to go up (snapshot format 2 loads format 1).

**Town plan (the Architect)**

- **`set_zones`**: the full list of zones, each a rectangle with a name and a purpose (`fields`, `center`, `houses`, `workshops`, `reserve`), at most 12. It replaces the plan in force.
- **Checks**: inside the map, no overlaps, every existing building (and the square) wholly in one zone of its purpose; houses are allowed in the center too. A zone may reach beyond the realm's land, to plan ahead for tiles to claim; buildings still stand only on owned, cleared tiles. `set_zones` and `demolish` run before the other orders of the same priority, so a build uses the new plan and the freed tiles. An invalid plan is refused with the reason and the Architect retries once in the same meeting; then the plan in force stays.
- **When**: the prompt asks for a new plan only when the territory grew or the plan has no room for what is needed, not every month. It goes through the Chancellor's plan and the sovereign's approval like any order.

**Building inside the zones**

- **`build`** becomes `{building, zone}`, with optional `x`, `y`. Without coordinates the engine takes the valid place nearest the square, preferring places aligned on the zone's grid (tidy rows, no farm half-way that wastes the zone); fixed tie-break, deterministic. Without a zone, any zone of the building's purpose. With coordinates it checks footprint, terrain, overlap and zone; a building sticking out by one tile is moved by one tile, otherwise the order is refused.
- **The Architect's briefing**: the map of the territory plus a ring of two tiles as a text grid (as in the probe), the zones with **how many buildings of each kind still fit** ("campi sud: posto per 1 fattoria"), the buildings with their id and position.

**Demolition**

- **`demolish`** `{building_id}`: costs gold (about half the building's cost) and gives back a quarter of its wood and stone (values in `config.toml`); takes one month. The workers lose their jobs and are rescaled as today; upkeep stops; the tiles are free again in their zone.
- Demolishing a house evicts nobody, but without housing births stop, as today when houses are full.
- **Why**: a sawmill whose forest is gone produces nothing; the briefing says so ("segheria 1: non tocca più il bosco, non produce") and the Architect may pull it down and build one elsewhere.

**Expansion: claiming tiles (gold)**

- **`claim_tiles`** `{direction: north/south/east/west, terrain, count}`, at most 4 tiles an order: the engine picks bordering tiles of that terrain in that direction, nearest the centre (deterministic).
- **Price** per tile grows with the territory: `20 + 1 gold every 8 tiles owned beyond the core` (20 since the lab; at 10 gold was no brake).
- **The land fund**: the gold paid goes into a fund at game level, the first data shared by all realms. In December the fund is split **equally among the other states** (the payer gets no share of its own payments); the remainder stays in the fund. It is public: everyone sees what they received, so they can guess how much the others grew. With a single realm the fund only grows, shown in the briefing and in the admin. **Built so far (step 1)**: each realm keeps the gold it paid (`land_paid_total` in its state), so the fund is the sum over the realms and replay stays exact. The December split is left to step 2: it moves gold between realms, so the replay must read it as an input of each realm (like the people's decisions), and with one realm there is nobody to pay.
- **Who**: the Architect proposes; the Treasurer sees price and fund in its briefing; the Chancellor's cost check adds the gold.

**Expansion: clearing tiles (labour)**

- A claimed plain or hill tile arrives **wild**: nothing is built on it until it is cleared. A claimed **forest stands** and belongs to the realm at once: a sawmill works only while it touches a forest **of the realm**.
- **`assign_workers`** gets a `clearing` sector. Work needed in worker-months (in `config.toml`): plain 3 (6 before the lab: no farm on new land in two years), hill 10, forest 12; felling gives 10 wood a worker-month (5 paid less than a sawmill worker). The tiles are cleared in the order they were claimed.
- **Felling the forest** is its own order, `fell_forest {count, direction?}`: it queues the realm's forest tiles nearest the square. A felled tile becomes plain and gives wood for every worker-month spent on it. Clearing has no strike or effort modifier (plain labour, kept simple); hands with nothing in the queue are idle. A standing forest is wood for ever (a sawmill touching it works), a felled one is wood once. The engine does not forbid felling the last forest tile next to a sawmill, but the briefing warns ("ultimo bosco della segheria 1"), like the idle-adults warning. No regrowth for now; a replanting order later if games show the need. The lab measures how many years a greedy realm takes to run out of nearby forest, to tune the wood of felling and the months of work.

**Balance lab** (`lab/territory_balance.py`, 2026-11-08, scripted sovereigns on the real engine, 36 months; they manage the ration but build few houses, so every run ends in revolt within three years, read up to that month):

| Policy | Today's values (claim 10, plain 6, felling 5) | What changes it |
| --- | --- | --- |
| Still (no claims) | the core's two free farm places are the only growth | — |
| Grower (4 plain tiles south when gold allows, 6 hands clearing outside winter) | 24 tiles claimed in two years, **no farm on the new land**: clearing is the bottleneck (a farm is 9 tiles = 54 worker-months); gold is not (250 left) | plain 3: the first farm on new land; claim 20: 16 tiles instead of 24, gold still left |
| Feller (10 hands felling the core's forest) | the sawmill stops in month 9; felling gives 5 wood a worker-month, less than a sawmill worker (6): no temptation | felling 10: +650 wood in 14 months |

**Applied (2026-11-08)**: clearing plain 3, felling 10, claim 20. With them the grower claims 28 tiles in three years, pays 596 gold into the fund and keeps the kingdom calm; the feller gets +650 wood in 14 months and loses its sawmill in month 9.

The first lab run also moved the world's forests and hills from straight below the cores to the corners between them: they left one or two rows of plain, never room for a 3 × 3 farm.
- Clearing takes hands from the fields: in winter it is a real decision.

**Council, manual, prompts**

- Manual: new lines from the config (footprints, terrains, price, fund, clearing, demolition).
- The Architect's craft gets town planning (keep the quarters in order, leave reserves, grow towards the terrain that is needed). The Treasurer and the Chancellor get one summary line on the territory (tiles, price, fund), not the map. Cost: about 600–1000 more input tokens per Architect call, under $0.0002.

**Built (2026-11-08)**: the Architect's briefing has "## The town and its land" (`server/council/map_text.py`): the text grid of the land and a ring of 2 tiles (tiles outside the realm in other characters), the zones with the room left per kind (counted by placing copies as the engine would), the buildings with id and place (a sawmill without forest marked NOT WORKING), the price and the land fund, the bordering tiles per side and terrain, the clearing queue, a warning when the last forest of a sawmill is queued. The Chancellor gets one summary line, the Treasurer the price line. The map orders and their formats (`prompts/order_formats_map.txt`), the town-planning craft (`prompts/expertise_architect_map.txt`), the territory rules in the manual and the Architect's wider duty appear only in games with a map. A town plan the engine would refuse is asked again once with the reason; refused twice, only the plan is dropped. The cost check warns of clearing hands with nothing queued.

**First test (game 19, GLM 5.3 Flash "high", 6 months)**: the Architect built the fifth farm in the "Campi" zone, in March claimed 2 plain tiles to the south "because the Campi zone is nearly full", in April put an idle adult to clearing and drew a new fields zone over the claimed land (valid at the first try). Weak: the new zone was 2 rows deep, too narrow for a 3 × 3 farm (craft line added); once it spoke of taxes and a feast, not its orders (5 replays of the same call: all on topic).

**Phone and admin**

- New page **"Mappa": the territory and its ring in SVG, colours by terrain, buildings as shapes with a letter or a simple icon, zones as coloured outlines, tiles being cleared hatched; tapping a building or a zone shows its details. A mockup comes before the code.
- Admin: the whole world and the fund.

**Built (2026-11-08)**: `/ui/realms/{id}/map` (tab "Mappa"), after a mockup on a Design canvas. The land and a ring of 2 tiles as a CSS grid of illustrated tiles, top-down like a storybook map: 17 small original SVGs in `server/ui/static/map/` (about 1 KB each: two grasses, forest, hill, wild land, six river pieces that join their river neighbours, farm, two houses, sawmill, quarry, square with its fountain). Land outside the realm is the same drawing faded; the realm's border is a gold line. No JavaScript: choosing a building (`b`), lighting a zone (`zone`), drawing every zone (`zones=1`) and bigger tiles (`zoom=1`, 22 → 34 px, scrolling in its frame) are links. Below: the chosen building, the land (tiles, price, fund, clearing), the town plan with the room per zone in Italian, a legend. The sovereign sees no coordinates. The world view comes with the other states.

**Order of work** (one commit each, with tests)

1. Engine: map, footprints, zones, placement, demolition, migration (no models).
2. Claiming, clearing and the fund, with the balance lab for prices, work and forest.
3. Council: orders, briefings, manual, prompts; the Architect probe again on the real map.
4. The map page on the phone.
5. A 12-month test game.

## Web UI

Server-rendered pages (FastAPI with Jinja2 templates), phone first, in the style of the mockups: dark ground, gold, Cormorant Garamond titles, one colour per council member. Every action is a plain form followed by a redirect, so it works without JavaScript and reloading the page does not repeat the action; HTMX (vendored, not from a CDN) is used only to refresh the council and audience panels. Approved instead of TypeScript for the prototype: the map will come as a separate component or with the move to TypeScript, without changing the APIs. All text shown to players is in Italian.

| Page | Content |
| --- | --- |
| `/ui` | games and new game |
| `/ui/realms/{id}` | the turn: numbers at a glance, last month, what they say in the square, the council (reports, summary, plan with the orders to keep ticked, directives), private audiences, closing the month |
| `/ui/realms/{id}/kingdom` | resources, people, work, buildings and laws (sovereign view: no mood) |
| `/ui/realms/{id}/chronicle` | events of all past months |
| `/ui/realms/{id}/audience/{role}` | private dialogue with one council member |

- **Background jobs**: the button answers at once, the panel refreshes every 2 seconds and shows the reports as they arrive; closing and reopening the page finds the meeting again. One job per realm at a time (meeting, directive or audience), also between UI and API; errors are kept per realm and kind of job.
- **The lock holds for a single server process**: with several processes it must move to the database. A server restart interrupts running meetings; messages already written stay.
- **Model text is always treated as text**: a model that answers with HTML cannot inject code into the page (there is a test).
- Reachable from the phone through Tailscale; no accounts yet.
