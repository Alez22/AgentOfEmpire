# AgentOfEmpire – Work plan

Updated 2026-11-11 (game 38, the first seasonal game: 4 of 6 realms stand at month 24, against 1 of 6 in game 37; the seasonal sovereign is built and the reduced ration costs 100 mood instead of 150).

The prototype is complete and playable from a phone, and the field test is closed. Phase 3 (accounts) is set aside: the game first needs richer dynamics. **Now: phase 4, the market**: the labs are done (`lab/market_sim.py`, `lab/market_closed.py`) and the spec "Market, needs and land levels" is approved (`docs/DESIGN.md`); next, the engine (step 1 built: needs, land levels, a site per realm; steps 2 and 3 built: the market, the `trade` order, market states in the database, game-level resolution and replay; step 4 built: the council trades through the Treasurer, the "Mercato" page; next step 5, a 12-month game with three realms), then a game with three realms. The territory step 1 is done (spec in `docs/DESIGN.md`, "Territory").

This file is the starting point of every work session: read it at the start and update it at the end. The full design lives in [`docs/DESIGN.md`](docs/DESIGN.md), the UI mockups in [`docs/mockups/`](docs/mockups/).

## Where we are

| Part | What it does | Where |
| --- | --- | --- |
| Engine | deterministic monthly simulation: economy, seasons, food spoilage, demography, mood, unrest | `engine/`, values in `engine/config.toml` |
| Database | PostgreSQL 18.6 in Docker, 12 migrations, row-level security, append-only logs, replay | `db/migrations/`, `server/db/` |
| LLM council | Treasurer, Architect, Chancellor and Voice of the square on OpenRouter (GLM 5.3 Flash "high"; the Voice on DeepSeek V4.1 Flash); secret lessons revised at season end; private audiences | `server/council/`, settings in `server/council.toml` |
| UI | phone pages: games, turn, kingdom, map, market, chronicle, audiences; meetings run in the background | `server/ui/` |
| Admin | everything visible: full state, prompts, calls, costs, lessons, audiences, replay; per-agent page with system prompts, traits and last briefing | `server/admin/`, enabled with `ADMIN_VIEW=1` |
| Tests | 316 tests: engine, database, council with fake models, UI | `tests/` |

### How to use it

- **From the phone** (with Tailscale on): `http://<tailscale-ip>:8000/ui`, where the address is the one in `compose.override.yaml` (copy it from `compose.override.example.yaml`; it is not committed). Admin is at `/admin`, the API at `/docs`.
- **Start or restart the server:** `docker compose up -d server`. After changing `server/council.toml` or `.env`, use `docker compose up -d --force-recreate server`.
- **Tests:** `docker compose run --rm tests`.
- **Replay a game:** `docker compose run --rm tests python lab/replay.py <id>`.
- **Compare balance variants:** `docker compose run --rm tests python lab/compare_variants.py`.
- **Current cost:** about $0.02 per turn (measured on game 7), meeting and Voice of the square included. The cap is $1 per game, in `server/council.toml`.

### Known limits

- **No accounts.** Anyone on the Tailscale network reaches the admin pages and every realm: **do not add other people** to Tailscale before phase 3.
- **Server restart:** interrupts a running meeting. This also happens on auto-reload when a Python file changes.
- **Meeting lock:** works only while the server runs as a single process.
- **Gold:** piles up because it has few uses (decision deferred to phase 4).
- **Idle adults:** the fixed rule sends them only to the farms, not to wood and stone.

## Phases

Move to the next phase when the previous one is closed. Phase 3 is mandatory before any game with other players.

### 1. Prototype – done

- [x] Engine, starting values, seasons and food spoilage
- [x] Database, migrations, row-level security, replay
- [x] HTTP server and phone access via Tailscale
- [x] LLM council: Treasurer, Architect, Chancellor, directives, plan approval
- [x] Memory of consequences and secret lessons revised at season end
- [x] Private audiences
- [x] Voice of the square and filtered sovereign view (no mood)
- [x] Phone UI and admin view

### 2. Field test – closed (2026-11-08)

The open items below carry over: they are checked and tuned while playing the next steps.

- [x] Play 12–24 turns from the phone and note what does not work (game 7, 12 months; see "Field test notes")
- [x] Fix the bugs found in the test: mood only to the Voice (the council hears the square), 90 s deadline on the whole call, 8000 output tokens cap, bad lesson actions discarded one by one
- [x] Voice of the square: only evident facts (court clearance, no granaries: the people only guess them), its own words of the last two turns, month windows aligned with the story; audience fact public, births and deaths court level
- [x] Fixes from game 2: expected harvest and vacant jobs in the briefings, no-change orders dropped from plans, "no market / a feast brings no food" in every counsellor prompt, months to winter, own role only, refused measures may come back, reports with numbers, Voice without numbers in words or invented events
- [x] Famine balance: variant D applied (immediate shock −4 per missing point, −10 per death; `engine/config.toml`)
- [x] Workers beyond the jobs: the Chancellor's cost check warns (`jobs_at_harvest` in the engine)
- [x] Tension: start food 1600 and start mood 500 (lab above); without orders the realm now revolts in the second winter
- [x] Game 4 fixes: the Voice hears the direction of tax and ration changes; the Treasurer sees the farm yield of the coming seasons
- [x] The people decide (effort, births, petitions) with a cheap model, inside limits by mood band; stored per turn, replays exact (see "The people decide" in `docs/DESIGN.md`)
- [x] Play a game to see the people's decisions (game 5): readable and consistent
- [x] Secret notes between counsellors: one a month to one colleague, inside the usual reply, delivered at the next meeting, unknown to everyone else (see `docs/DESIGN.md`)
- [x] Mandates: standing guidelines per counsellor, requested by the sovereign, reviewed and rewritten by the Chancellor (page "Il governo")
- [x] Debate on request: the ministers comment on the plan before approval (see `docs/DESIGN.md`)
- [x] The Chancellor's role stands above the parties (role duty in its prompt)
- [x] Play a game with mandates, notes, debate and audiences together (game 7, 20 turns)
- [x] The manual of the realm: how every element works, written from the config, in every counsellor prompt and on the sovereign's "Manuale" page
- [x] The craft of each role (good practice, not laws) and the Treasurer's registry and ration consumption; the Architect's duty is a duty again
- [ ] Model tiers: cheap models compared (games 9–17 and the bench); since 2026-11-08 every tier and every counsellor is GLM 5.3 Flash with reasoning "high" for development; still to decide the real tiers (and whether a tier also sets the reasoning effort); later a settings page for them
- [x] Persons: a small catalog (12), the council drawn from the moderates at game start; name, gender, traits, story, model and salary come with the person; salaries paid by the engine; persons carry a tier (low, medium, high), never a model
- [ ] Play a game to check manual and craft together, then remove the prompt rules they make redundant
- [x] Game 7 fixes: the Architect may fill a new building with workers moved from a sector that needs them less (the growth trap); jobs per building in the briefing; a reply that ran up to the token cap is retried without reasoning
- [x] Counsellor prompts: quote only briefing numbers, never count idle adults or jobs yourself, never present a suggestion as a rule in force; the Chancellor's assignments within adults and jobs (game 6)
- [x] Petitions weighted by the relief they bring (10–30), wider ranges for effort and births (after game 5)
- [x] A granted petition decides its law: the plan's orders on the same policy are not sent, and a grant after approval links the identical order
- [ ] Play again to check the fixes: no mood numbers in reports, no calls over ~90 s, lesson reviews applied, the square keeps a thread, rations cut only when the harvest does not cover
- [ ] Decide on tiles and workers (overbuilding, housing dead end, idle adults)
- [ ] Tune engine values (food, taxes, mood)
- [ ] Review the council and square prompts
- [ ] Polish the UI after the test
- [ ] Choose models and spending cap for a 120-turn game

### 3. Before friends – set aside (2026-11-08)

Still mandatory before any game with other players: until then, nobody else on Tailscale.

- [ ] Invite-only accounts, login, admin role reserved
- [ ] Decide what the admin sees in games with other players
- [ ] Daily turn with deadline and confirmation from every player
- [ ] Absences, vacation mode, global pause, automatic sovereign
- [ ] Automatic database backups; database role without superuser privileges
- [ ] Meeting lock in the database, so the server can run as several processes

### 4. Full game – in progress

- [ ] More classes: artisans and merchants, clergy, soldiers; each with its own memory horizon in the square (peasants 2–3 months, merchants and clergy a year or more)
- [ ] Marshal and Ambassador
- [ ] Roles as data (`roles.toml`: title, duties, obligations, orders) separate from persons (traits, résumé, name), before hiring and dismissing counsellors
- [ ] Hiring and dismissal: extreme persons for hire, persons moving between realms with their lessons and memories (person separate from post), unpaid salaries hurting loyalty, the full catalog (12 + 8 + 8 per role)
- [ ] Tile map and more states, automatic ones too. **Step 1, the territory** (one realm; spec approved 2026-11-08):
  - [x] Feasibility: the Architect plans zones on a text map (`lab/urban_probe.py`: 7 of 11 fully valid, plans sensible)
  - [x] Draw the world (64 × 64, 8 sites) and the 12 × 12 core (`engine/maps/`)
  - [x] Engine: map, footprints, zones, placement, demolition (`engine/territory.py`; no migration needed: the map lives in the snapshot)
  - [x] Claiming (gold into the land fund), clearing and felling (labour), sawmills need the realm's forest; balance lab (`lab/territory_balance.py`)
  - [x] Values from the lab: clearing plain 3, felling 10 wood, claim 20 gold
  - Step 2: the land fund split in December among the other states (needs them, and a cross-realm input for the replay)
  - [x] Council: orders, briefings, manual, prompts; first test with real models (game 19, 6 months)
  - [x] The map page on the phone (mockup first: illustrated tiles, the river joined, the realm's border in gold)
  - [x] A 12-month test game (game 20): the Architect plans the land unprompted; gold stops the growth; 3 runaway replies
  - Step 2: automatic states and contested borders; then trade, diplomacy, war
- [ ] Market, trade and diplomacy (they give gold a use)
  - [x] Lab of the market: 3 scripted realms and one outside merchant, price from its stock, margin, restock (`lab/market_sim.py`; see "Lab: the market")
  - [x] Closed market (decided 2026-11-08: nothing from outside, no restock): warehouse on consignment, price moved by unmet demand or unsold goods, realms with different yields (`lab/market_closed.py`; see "Lab: the closed market")
  - [x] A steady demand for wood and stone, in the lab: A firewood in winter, B upkeep in stone (see "Lab: firewood and stone upkeep")
  - [x] Decided 2026-11-08: A and B go into the game (firewood 1 per 2 people in winter, stone upkeep; values tuned below), a small start stock in the warehouse (the only goods from outside, once)
  - [x] Price rule "cover": down only when the stock is more than 3 months of the recent demand (see "Lab: price rule and start stock")
  - [x] Three levels per resource and site (poor, fair, rich), in the world map, unknown at the start; the expert of the land in a later era (`docs/DESIGN.md`, "Land levels")
  - [x] Lab with 8 realms and zero-sum profiles (see "Lab: eight realms")
  - [x] First tuning from the 8-realm lab: start stock out of the price rule, poorer levels, firewood November to March (see "Lab: eight realms, tuning")
  - [x] Decided 2026-11-08: the market shows only prices, stock and totals, never who sold or bought
  - [x] Second tuning: stone upkeep 1 per building, food levels 14 / 15 / 16 (see "Lab: eight realms, second tuning")
  - [x] Third tuning: stone upkeep 2 per 3 buildings, or 1 per building with 3 hands on stone at the start (see "Lab: eight realms, third tuning")
  - [x] Stone upkeep chosen 2026-11-08: 1 per building, 3 workers on stone at the start; food levels 14 / 15 / 16
  - [x] Spec approved 2026-11-08: "Market, needs and land levels" in `docs/DESIGN.md` (Part 2); yields hidden from the manual, trades by the Treasurer
  - [x] 1. Engine: needs A and B, land levels, a site per realm (`tests/test_needs.py`; the manual still shows the yields until step 4)
  - [x] 2. Engine: the market and the `trade` order (`engine/market.py`, `tests/test_market.py`)
  - [x] 3. Database: market states, game-level resolution and replay (migration 012)
  - [x] 4a. Council: briefing, manual, prompts, craft, cost check, the Voice, Italian labels
  - [x] 4b. The market page on the phone, after a mockup (`server/ui/market_view.py`)
  - [x] 5. Game 24, 12 months, three realms played by Claude (notes and draft sovereign rules: `docs/game24_notes.md`). No realm fell. Findings: nobody has food to sell (levels 14/15/16 too narrow, winter halves every harvest); wood is short in the whole world; Treasurers rarely think of selling their surplus without a directive; a realm may buy back its own goods (margin paid twice); remnants under a lot cannot be sold; a pro-rata rounding defect fixed (dbdaca4)
  - [x] Food levels 14 / 15 / 18 (decided 2026-11-08, see "Lab: food levels")
  - [x] No buying a good one has on sale (`OWN_GOODS_ON_SALE`); units under a lot sell as one short lot, paid by the unit (decided and built 2026-11-08; flags in `[market]`, game 24 replays unchanged)
  - [x] Automatic sovereign, first version (spec approved 2026-11-08, `docs/DESIGN.md`): fixed rules R1–R9 from game 24, no model for the sovereign (`server/sovereign/`), `POST /realms/{id}/sovereign/auto`, reasons in a council message `sovereign` (migration 013), `lab/auto_game.py`
  - [x] Game 25: three automatic realms, 12 months, real models, $0.21 (see "Game 25")
  - [x] R5b: the sovereign sells a surplus also when gold is not short (decided and built 2026-11-08)
  - [x] A game with R5b (game 26): **no**, R5b never fired: it kept 4 months of gross eating (~3,600 food), Aurelia peaked at 2,626. **Now 2 months** (checked on game 26's states: Aurelia would sell 2 lots in November and 4 in December, the poor realms never; 1 month sold in January in the poor realms too)
- [ ] **The village, implementation** (decided 2026-11-08): block **A** the market as a building, merchants as a class with their own mood (needed: every class flees by its own discontent), no prices without the market until the travellers exist; then block **B+C** together: bandits (stage 1), watchtower, Gastaldo, militia. Values from a lab before each block.
  - [x] A: spec approved 2026-11-08 in `docs/DESIGN.md`, "The market as a building, merchants and their mood" (unrest ladder per class, trade tax as a share of the margin)
  - [x] A1. Lab `lab/village_market.py` (see "Lab: the village market, block A"): market 80 wood, no stone, 2 months; 6 merchants x 3 lots; merchants' own tax on the trades' value (10 %); a reserved market zone; shocks at half; idle malus only for the crown's fault
  - [x] A2. Engine: the building, its zone and the core, the `trade` sector, capacity, the merchants' tax (`tests/test_village_market.py`; games 20-26 replay unchanged)
  - [x] A3. Engine: mood and unrest per class (`[classes.*]`), the merchants' effort and strike (one mood step and ladder for every class; strike months neutral for the trade factor; games 20-26 replay unchanged)
  - [x] A4. Council: briefings, manual, prompts, craft, the Voice, R10 (per-realm market status; merchants start at the mood base)
  - [x] A6. Game 27, 12 months, three automatic realms (see "Game 27"); two defects of the automatic sovereign fixed
  - [x] A5. UI after a mockup ("Pagina Mercato" canvas): the market page without a market (no prices), "I mercanti", the market on the map (icon "shop"), the kingdom page; two leaks closed in the sovereign's state (merchants' mood, land levels)
  - [x] After game 27 (decided 2026-11-09): R2b (no richer ration when the food does not last); the Treasurer's craft on the merchants' tax (free up to a tenth) and on selling food; food yields 15/16/19, farms 16 (lab `lab/food_balance.py`, see "Lab: the village's food balance")
  - [x] Game 28: check R2b, the craft lines and the new yields (see "Game 28")
  - [x] After game 28 (decided 2026-11-09): R5/R5b sell food down to what reaches the next March on the normal ration (the engine's months, in any season; in March the next one). On game 28's states: Aurelia sells 3 lots a month from October (its one merchant's lots), Brenna and Corvara nothing
  - [x] Game 29 (see "Game 29"): Aurelia sold food, Brenna stood; a defect of the food sale fixed (a reduced ration in the plan made room for a sale)
  - [x] After game 29 (decided 2026-11-09): Corvara's fall from the cold stays as it is, no new aid: a bad choice the player could see coming (the briefing gives the firewood a month, the craft says to build the market once the winter's firewood is safe, the cold is reported). No briefing line that does the sum for the council, no R4c
  - [x] B+C: spec approved 2026-11-09 in `docs/DESIGN.md`, "Bandits, the watchtower, the Gastaldo and the militia" (stage 1: flight, pool, raids, watchtower from the first month, Gastaldo with the militia only; the loot feeds the pool)
  - [x] B1. Lab (8 realms, 24 months): values and spirals (see "Lab: bandits, block B+C")
  - [x] B2. Engine: flight, pool, raids, watchtower, militia (`engine/bandits.py`, table `bandit_pools`; games 20-29 replay unchanged)
  - [x] B3. Council: the Gastaldo, briefings, manual, Voice, automatic sovereign R11 (mandates and debate still for three offices)
  - [x] B4. UI after a mockup ("Blocco B+C" row on the "Pagina Mercato" canvas): the watchtower on the map, raids and flights in the chronicle, the Gastaldo's card in the government page, the Gastaldo's mandate
  - [x] B5. Game with three automatic realms
  - [x] After B4 (decided 2026-11-10): the Gastaldo speaks in the debate on the plan, after the Architect
- [ ] Village block B+C, stage 2: the doors and acceptance (`docs/DESIGN.md`, "The doors and acceptance", spec approved 2026-11-10)
  - [x] S1. Lab (8 realms, 24 months): values and spirals (`lab/village_migration.py`); values tuned, no inflow from outside (decided 2026-11-10)
  - [x] S2. Engine (2026-11-10): `[migration]`, `engine/migration.py` run by `resolve_world` after the pool's month, `set_doors` (needs a finished watchtower; demolition resets to normal), `GameState.doors` (snapshot format 6), public `arrival` event with an Italian chronicle line; same states as the lab's tuned acceptance, also with a lab inflow of 6; replays 27, 29, 31 unchanged; the two village labs run without `[migration]`
  - [x] S3. Council (2026-11-10): `set_doors` to the Gastaldo (only in games with `[migration]`, a no-change order dropped), its duty and craft (`expertise_gastaldo_doors.txt`), `order_formats_doors.txt`; the gate section adds the doors in force, free beds, empty jobs and the arrivals of the last 6 months; the manual's "Bandits and arrivals" / "Briganti e arrivi"; the Voice and the memory hear `arrival`; the `arrival` event says only whether the people grumbled (no mood points: the council never sees the mood)
  - [x] S4. UI after a mockup (2026-11-10, mockup "Stadio 2" on the Pagina Mercato canvas): the doors box on the Gastaldo's card (yellow when closed doors lack guards), free beds, empty jobs and the arrivals of 6 months; the "Arrivi" box in the chronicle; on the kingdom page "Nuovi venuti in 12 mesi" (only if somebody came) and "Porte" among the laws (normal before the watchtower too); games before stage 2 unchanged
  - [x] S5. Game with three automatic realms (game 32: nobody arrived; seekers and stopped raiders round down to 0 in a small pool, see "Game 32")
    - [x] Game 30 (see "Game 30"): void, R8 crashed on the watchtower in 8 realm-months; fixed, to be played again
    - [x] Game 31 (see "Game 31"): no errors; two towers, two Gastaldi, guards kept all year in an empty world
- [ ] Travellers, bandits and migration (designed 2026-11-08, `docs/DESIGN.md` Part 1): travellers carry public news late and distorted (in the village a public fact of another realm arrives only through them); families flee long discontent into a world pool of bandits (adults and some children, elders stay) that raids exposed stores; flight by class (clergy never), class lost in the pool, arrivals enter as peasants; a small pool from the start so rare raids teach the need for a militia; the **Gastaldo** (first council expansion, in the village, brought by the watchtower): doors (closed / normal / open), militia (none before it), news from outside, counter-espionage in the town; with open doors a raid becomes immigration; stages: 1 flight, raids, Gastaldo and militia, 2 doors and acceptance (needs a multi-realm lab for spirals), 3 spies among migrants, offended origin, remembered trade, funded bandits
- [ ] Espionage, war, revolts and coups; revolt as odds instead of automatic game over, weighed against soldiers, guards and propaganda (a militarised regime as a real choice with its own risks: cost, army mood, coups)
- [ ] Eras, variable trust and loyalty, leaks. **Eras designed 2026-11-08** (`docs/DESIGN.md`, "Progress" → "The eras"): village short (tutorial), town the long era, kingdom the risky finale; passage = the palace's building site, public, an era never lost; four rare resources, one per site, recipes by kinds present (2 kinds village → town, 3 town → kingdom), games with fewer than 8 realms allowed; every class born from a building (market → merchants in the village, the realm starts without a market; workshop, barracks, temple in the town); the temple brings the Prior, not a minister, not required for the kingdom; war from the town, annexation only as a kingdom. Still to decide: names of the rare resources, values (costs, months, population thresholds), the militia in the village
- [ ] Press by era: rumours only, then government communiqués (propaganda, also to other states), then independent journalism (see Progress in `docs/DESIGN.md`)
- [ ] Jev instead of the fixed rules

## Field test notes

### Game 7 "Prova" (2026-11-07, 12 months resolved, $0.24, 86 calls, no order rejected)

| | Jan (t1) | Apr (t4) | Jul (t7) | Oct (t10) | Jan (t13) |
| --- | --- | --- | --- | --- | --- |
| Food | 2000 | 1382 | 2102 | 2428 | 3139 |
| Wood / stone | 150 / 100 | 146 / 102 | 96 / 94 | 74 / 60 | 154 / 66 |
| Gold | 100 | 94 | 107 | 106 | 101 |
| Mood | 600 | 446 | 404 | 447 | 460 |
| Population | 100 | 102 | 105 | 106 | 108 |
| Free tiles | 7 | 6 | 4 | 1 | 0 |

**Bugs**

1. **Mood numbers reach the sovereign through the council**: 19 of 51 reports and summaries quote the exact mood ("Il morale è 478", "446/1000", "sotto 350 è rivolta"), audiences too. The briefing gives the number and the threshold; no prompt forbids repeating them. The Voice never did, because its prompt forbids it.
2. **The 60 s timeout is not enforced**: one Architect call took 221 s, the Chancellor up to 92 s. httpx's timeout applies to each network wait, not to the whole call, and OpenRouter keeps the connection alive while the model reasons.
3. **Lesson reviews fail**: turn 7 Architect failed twice ("revise of lesson 2 needs a reason"), so that season taught it nothing; turn 13 the Chancellor wrote the key `"reason "` (trailing space) and needed the retry. The Architect's first refusal at turn 7 had no reason at all, the second put the reason inside the text.
4. **Runaway generation, no output cap**: at turn 13 the Architect looped on "(turno 11)" up to 131,072 output tokens (221 s, $0.074, 31 % of the whole game). No call sets a maximum number of output tokens.

**Balance**

- No crisis at all: the first winter only went down to 1382 food (reduced ration, 3 new farms), then food rose every month to 3139 (5+ months). Mood never went below 404: unrest always calm. The reduced ration, kept for half the year with plenty of food, was the main cause of low mood.
- Overbuilding: the Architect used all 7 tiles (3 farms, 2 sawmills, 2 quarries); 165 jobs for 67 adults, the new sawmills and quarries stay almost empty. Its own lessons say to staff them; it did not.
- Gold is tight, not piling up: 19 buildings = 19 gold upkeep vs 26 tax at 8 %, plus a feast almost every month.
- Dead end ahead: 108 people for 120 places, no free tile, so no house can be built. In about a year housing is full (no births, −100 mood) with nothing to do about it.

**Council**

- Works: directives followed; the Voice of the square is very good (no numbers, remembers events, credible doubts); the Chancellor learned the sovereign's preferences.
- Wrong lessons: the Architect believes "normal ration and feasts raise food" (false) and that "the Treasurer can trim the proposals" (it was the sovereign).
- In audience the Chancellor promised "taxes at 20 %" but can only recombine the ministers' proposals, and the Treasurer never knew.
- Useless orders: `set_tax 8` proposed again at turns 9 and 10 with taxes already at 8 %.
- The Voice's season stories start one month early ("A settembre" for October–December): it receives two earlier months of mood.

**Cost**

- About $0.02 per turn, twice the estimate (about $0.014 without the runaway call): the $1 cap stops a game around turn 50; 120 turns need about $2.40.
- The Architect alone spends half ($0.129) and averages 27 s per call; Treasurer 11 s, Voice 2 s.

**Proposed order of work**: (1) fix the four bugs; (2) decide on tiles and workers; (3) more tension (harder winters or smaller stocks, tried with `lab/compare_variants.py`); (4) small fixes: drop no-op orders, Chancellor aware in audiences that it can only recombine (Voice months: done).

### Game 1 "Valdoro" (2026-11-07, played by Claude as a greedy sovereign; new database)

Goal: stress the people (taxes 20 % then 30 %, reduced ration, every feast refused) with the fixes of game 7 in place. Revolt at the end of turn 8. $0.080 in 50 calls, about $0.010 per turn.

| Turn | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Mood (hidden) | 600 | 500 | 400 | 325 | 268 | 226 | 207 | 216 | 249 |
| Unrest | calm | calm | calm | calm | protests | protests | strike | strike | revolt |
| Tax / ration | 10 / normal | 20 / reduced | 30 / reduced | | | | | 30 / normal | 30 / abundant |
| Food | 2000 | 1738 | 1481 | 1259 | 1483 | 1711 | 1988 | 1855 | 1457 |

**Fixes confirmed**: no mood number in 33 reports and summaries, nor in audiences; slowest call 34 s; both lesson reviews applied with nothing discarded; the output cap fired once (an Architect reply spent all 8000 tokens reasoning and came back empty, then the retry worked).

**What worked**: from the square alone the sovereign felt the mood fall month by month ("più cupa", "la piazza non siede più", "hanno posato gli attrezzi"), before protests and strike. The Voice keeps a thread (the widow Marchi in every month). Lessons are now qualitative and learned from the square ("il silenzio in piazza con la razione calata è avviso, non consenso"). The Chancellor learned the sovereign's line and stopped offering tax cuts and feasts, and it vetoed useless farms.

**Problems**

1. **The square names the wrong cause.** *(Fixed: the Voice now receives the felt mood factors in words, heaviest first, and must not invent events.)* The engine's mood was driven by taxes (−250 at 30 %) more than by the ration (−150), but the Voice spoke only of hunger while the granaries kept filling, and invented a fact ("i carri sono partiti per la città del signore"). The ministers took it as true; the Treasurer said in audience "lo sciopero è fame, non calcolo" and advised against cutting taxes. Following the council, the sovereign raised the ration and the kingdom revolted anyway. Idea: give the Voice what weighs on the people (heavy taxes, short ration, deaths, full houses), in words, so it complains about the real causes; and forbid inventing events that are not in its facts.
2. **Council courtesy turns into a death spiral**: the Chancellor's lesson "non offrire abbassamenti senza ordine esplicito" is realistic, but nobody warned that taxes were the main cause. Maybe a counsellor of low loyalty or high honesty should still say it.
3. **Overbuilding again**: 9 farms, 135 farm jobs for 65 adults; the Architect proposed a farm almost every month and invented a "mulino ad acqua" that is not in the catalogue. The Chancellor stopped some of them.
4. **Time sense**: "l'inverno è vicino" in June, "alle porte" in August, although the briefing says how many months are left.
5. **Small slips**: the Architect speaks as if it set taxes; the Treasurer asks to "buy grain" (no market yet); a no-op `set_tax 30` in a plan; a wrong sum by the Chancellor ("restano 476 oro"); the Voice said the tax changed three times (it was twice).

### Game 2 "Grananera" (2026-11-07, played by Claude; stress: a real famine)

Normal ration kept, half the farmers moved to wood and stone in winter, every ration cut refused. Granary empty at turn 5, famine at turns 5–6 (25 % then 11 % of the food missing), 8 deaths (103 → 95 people). 10 turns, $0.094 in 52 calls (about $0.009 per turn), no refused reply, slowest call 34 s, no mood number in 33 reports.

| Turn | 1 | 3 | 5 | 6 | 7 | 8 | 10 | 11 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Food | 2000 | 835 | 17 | 0 | 0 | 232 | 705 | 1028 |
| Mood (hidden) | 600 | 534 | 497 | 454 | 460 | 470 | 467 | 462 |
| Unrest | calm | calm | calm | calm | calm | calm | calm | calm |

**What worked**: the square did not know the granaries and said nothing of hunger until bread ran short ("la fame non morde ancora"), then told the famine with force ("cinque bare han lasciato il borgo", "si è mangiato mentre si seppelliva"). The new felt causes work: with taxes at 10 % the square spoke of the tax collector. The Architect noticed that sawmill and quarry have only 10 jobs each. Lessons are rich and practical ("le fattorie nuove non producono grano nell'immediato: vanno avviate prima"). The Chancellor learned the sovereign's refusals.

**Problems**

1. **The briefing has no production**: the Treasurer sees stock, consumption and "reserve 0.8 months", never what the fields will yield. So the council predicts empty granaries while they fill (summer), and proposes cutting rations almost every month (games 7, 1 and 2).
2. **A famine barely touches the mood**: 8 % of the people died and the unrest stayed calm (mood 497 → 454), while taxes at 30 % caused a revolt in game 1. Hunger (−6 per missing point, at most −400, but a 25 % shortage is only −150) and deaths (−5 each) weigh too little against taxes (−10 per point).
3. **The council believes gold buys food**: the Treasurer and the Chancellor proposed a feast "per comprare cibo" and higher taxes "per acquistare grano". There is no market; a feast only lifts the mood.
4. **The Voice still invents and sometimes counts**: "il grano nuovo è già mezzo venduto" (no market) was repeated by the Treasurer as a fact; "cinque bare a maggio, tre a giugno" breaks the no-numbers rule. Keeping the thread also kept a stale complaint (the tax collector, with taxes at 5 %).
5. **Overbuilding again**: 9 farms (135 jobs) for 61 adults, all tiles used by turn 7; later "non posso costruire".
6. **No-op orders in most plans**: `set_tax 10` with taxes at 10 %, `set_ration normal` with the ration normal.
7. **Refusals become taboos**: once the sovereign refused the reduced ration, nobody proposed it again, not even with the granary empty and people dying ("non è una via praticabile").
8. Sometimes a report is vague, with no numbers at all (Architect turn 2, Treasurer turn 9).

### Game 3 "Altavalle" (2026-11-07, played by Claude as an attentive but ordinary sovereign)

Listened to the council, kept the normal ration, lowered taxes to 8 % then 5 % when the square blamed them, two sober feasts, one farm for growth. 10 turns, $0.082 in 55 calls, no refused reply, slowest call 40 s, no mood number in 36 reports, no digit in the square's 10 stories.

| Turn | 1 | 2 | 4 | 5 | 7 | 8 | 9 | 10 | 11 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Food | 2000 | 1559 | 693 | 699 | 684 | 839 | 989 | 1144 | 1369 |
| Mood (hidden) | 600 | 567 | 535 | 526 | 514 | 499 | 511 | 497 | 507 |
| Unrest | calm | calm | calm | calm | calm | calm | calm | calm | calm |

**Fixes confirmed**: the council reasons with the expected harvest ("per la prima volta il grano cresce invece di calare") and cut the ration only once, with a reason, after it had been refused ("già rifiutata a gennaio, ma oggi il granaio è più magro"); the Chancellor weighed it against the April harvest. Nobody believes gold buys food any more. The Architect stopped building empty farms ("aggiungerebbe soltanto posti che nessuno può riempire") and warned honestly when the sovereign ordered one anyway. It also keeps to its role ("materia del Tesoriere, non mia"). The square explained the people's mood: taxes, then relief, then the feast ("il fabbro ha ripreso a battere il ferro cantando").

**Problems**

1. **No tension for a sensible player**: the unrest stayed calm all year, the lowest food was 684 and the mood only drifted from 600 towards the base 500. The first winter is not a crisis unless the sovereign makes mistakes (games 1 and 2). Balance question for later: smaller starting stock, harsher winter, or start mood at the base.
2. **The square invents a cause when nothing weighs**: the mood drifts down from 600 to the base 500 by itself, and with no burden in its facts the square spoke of "un lutto che non ha nome" and "una stanchezza". Partly a consequence of the start mood being above the base.
3. **Nothing to do after a few months**: all adults employed, 6 free tiles unused, wood (200) and gold piling up. Growth depends only on births; one class and no use for gold leave the sovereign with few choices (known: gold use, more classes).
4. **The Voice answered once in English** (fixed in `voice_system.txt`: "Write ONLY in {language}"). It inverted a decision once ("il sovrano ha messo la tassa" after a cut) and overstated a slight burden ("ci mangia vivi" at 8 %).
5. **Workers beyond the jobs**: the Chancellor proposed 63 adults in the fields with 60 jobs, computing its own (wrong) yield; the engine check does not flag workers beyond the jobs.
6. The Treasurer over-corrected once: "un banchetto non dà pane" became a reason to refuse feasts, which do lift the mood.

### Game 4 "Pietrasanta" (2026-11-07, Claude as a sensible sovereign, start food 1600 and mood 500)

Check of the new start values and of the fixes from games 2–3. 10 turns, $0.079 in 52 calls, no refused reply, slowest call 47 s, no mood number in 33 reports, no no-change order in the plans.

| Turn | 1 | 2 | 3 | 4 | 5 | 7 | 9 | 11 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Food | 1600 | 1420 | 1243 | 807 | 811 | 791 | 1163 | 1588 |
| Mood (hidden) | 500 | 455 | 416 | 424 | 438 | 456 | 467 | 473 |
| Ration | normal | reduced | reduced | normal | normal | normal | normal | normal |

**The first winter is now a real decision**: at turn 1 the council asked for the reduced ration and a small feast to get through to spring; the square resented the feast during the thin soup ("ci hanno fatto ballare mentre il grano spariva"); the mood fell to 416 (threshold 350), then recovered once the ration was normal again. A sensible player is never in danger but has to think. The Architect planned growth (a farm in June, the workers moved there in August as promised) and still never built for nobody.

**Problems**

1. **The Voice inverts tax cuts**: twice it spoke of "la tassa nuova che nessuno aveva chiesto" after the sovereign lowered taxes (10 → 7 %, 7 → 5 %). It receives "set_tax 7 (April)" without the previous rate.
2. **The Treasurer sees only this month's harvest**: in May and June it asked to cut the ration "per accumulare per l'inverno" while summer (120 %) and autumn (130 %) were about to fill the granary. The briefing shows the season yield of this month only.
3. The square keeps a vague rumour about grain going "per strade che noi non vediamo" (allowed as gossip, but recurring).
4. The Architect's sums are sometimes wrong ("togliere cinque contadini per darne quattro al legno e tre alla pietra"); the Chancellor corrected it.

### Game 5 "Borgoverde" (2026-11-07, Claude as sovereign; first game where the people decide)

Granted, refused and granted again tax petitions, imposed a reduced ration in June, granted the ration petition. 10 turns, $0.080 in 62 calls (the people: $0.0017), no refused reply, slowest call 37 s, no mood number in 33 reports, replay exact.

| Turn | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Mood (hidden) | 500 | 525 | 518 | 478 | 513 | 509 | 469 | 495 | 501 | 489 |
| Effort % | 0 | +3 | −2 | −3 | +3 | +4 | +1 | +2 | +3 | +1 |
| Births % | 100 | 90 | 92 | 92 | 103 | 108 | 96 | 95 | 96 | 93 |
| Petition | taxes 10→7, granted | | taxes 7→5, refused | again, granted | | | ration back to normal, granted | | | |

**What worked**: the people's choices are readable and consistent with their reasons ("the crown refused us in March, so we work less"). After a refusal effort fell and the square said "il Sovrano ci ascolta quando vuole lui"; after a grant effort rose and births recovered. The council advised on every petition and the Chancellor once left out of the plan the order the petition would carry out. The square told the petitions and the answers the next month. Every decision came from the model (never the fallback).

**Problems**

1. **A granted petition duplicates the plan's order**: the petition's `set_tax 7` ran first and the plan's identical one was rejected as `DUPLICATE_POLICY` (harmless noise). Granting should drop the plan's orders on the same policy.
2. **Petitions as a mood pump**: every grant is +30 at once, also for a small burden (taxes 10 → 7 % at turn 1, with the mood neutral). The real cost is the policy itself, and once taxes reach 5 % there is nothing left to ask; to watch in a longer game.
3. **Births stay below 100 %** in almost every month (90–96 %), even when the people were content with the crown: the model leans to caution, so growth is slower than before.
4. Effort moves little (−3 to +4 %): visible in the numbers, subtle in play.

### Game 6 "Torrealta" (2026-11-07, Claude as sovereign; focus: private audiences)

8 audience lines with all three counsellors (Architect 3, Chancellor 3, Treasurer 2), the rest played sensibly. 10 turns, $0.073 in 70 calls, no refused reply, slowest call 39 s, replay exact. The people and the square as in game 5; no crisis (mood 484–510).

**Audiences work as designed**

- **More candid in private**: in council the Architect said of the reduced ration "non è mia competenza"; in private "il Tesoriere guarda il conto, io guardo la piazza", and it took a stand.
- **Promises are kept**: the Architect promised to move the woodcutters to the fields and did it at the next meeting ("come promesso"); the Chancellor promised a plan without feasts and twice left them out ("niente feste, come volete").
- **Secrecy holds**: asked what the sovereign told the Treasurer, the Chancellor knew only that the audience took place. The fact is public (the month's events).
- **Characters differ**: the Chancellor insinuated against the Treasurer ("ama il proprio registro più del regno") and fished for more ("se ha parlato d'altro con lui, me lo dica"); the Treasurer refused to judge the Chancellor "senza fondamento".
- **Audiences shape the lessons**: "La razione non si tocca: il sovrano non la ridurrà mai" (Treasurer, from a private word); "Il sovrano non vuole feste" (Chancellor), later revised with the reason "il sovrano ha detto di aver cambiato idea"; the Chancellor even learned "il sovrano mi saggia su ciò che si dice in privato al Tesoriere: devo farmi aprire il suo registro".
- **Private orders can collide**: "no feasts" to the Chancellor, then "propose a feast" to the Treasurer: the Treasurer proposed it "come Vostra Maestà ha ordinato", the Chancellor removed it holding to the first word. A public directive settled it at once. A credible court dynamic.

**Problems**

1. **The Chancellor invents facts and numbers**: "dieci lavoratori inattivi" (there were none) leading to a plan with 68 workers for 63 adults and an empty quarry; "tre operai liberi" in an audience; it called its own suggestion a rule in force ("da allora il bilancio passa in consiglio").
2. **The people petition on the very first turn** again (taxes 10 → 7 %), when the tax is their only, slight burden.
3. **An odd sentence of the square became a lesson** for two counsellors ("dar da mangiare a chi lavora non sfama chi non lavora").

### Game 7 "Montebello", turns 1–10 (2026-11-07, Claude as sovereign; mandates, notes, debate, audiences)

Three mandates, one changed at turn 6; one debate; three audiences about notes; two petitions granted. $0.085 in 69 calls, replay exact.

| Turn | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Food | 1600 | 1110 | 907 | 456 | 441 | 415 | 390 | 516 | 655 | 799 | 1011 |
| Mood (hidden) | 500 | 502 | 461 | 493 | 487 | 482 | 479 | 465 | 466 | 455 | 473 |

**Mandates**: the chancellery approved all four requests and rewrote them sensibly. It kept the valid part of a mixed request and explained the cut ("ho escluso l'acquisto di grano dai mercanti, perché il regno non ha mercato"), and twice refused "build in advance" as against the role ("non ho accolto il preparare fattorie vuote in anticipo"). Counsellors quote their mandate in council ("come vuole il mio mandato"). A loosely worded mandate is read literally: "cut the ration only if the harvest is not enough" made the Treasurer ask for the reduced ration in January with 1600 in store.

**Notes**: 10 in 10 turns, all used to coordinate: the Chancellor pre-negotiated with the ministers ("non proporre la festa", "tieni pronta la razione ridotta per l'autunno: allora la sosterrò"), and they confirmed. No intrigue with these moderate characters. In audiences all three told the truth about their notes, and their stories matched the table.

**Chancellor**: a good arbiter. It overruled the Treasurer's ration cut with the seasonal outlook ("d'estate e d'autunno i campi rendono più del consumo, 1046 e 1133 contro 890").

**Problems**

1. **Runaway reply again**: at turn 4 the Treasurer's first try was empty, the second hit the 8000-token cap; the Treasurer was absent that month. Second runaway in the playtests (also game 1).
2. **Mandates contain the orders' code names** ("set_tax", "set_ration"), which the sovereign reads on the government page.
3. **No growth in sight**: all adults employed, the chancellery forbids building before free hands exist, a farm takes two months, births stay at 96–100 %. Ten turns: no building, population 100 → 106, mood slowly down. Projection: the second winter starts with about 1200 food against a deficit of about 470 a month, so a famine is likely by March if nothing changes.
4. **The debate adds little when the plan has no conflict**: both ministers agreed.
5. **Notes make the council consensual**: disagreements are settled in private before the meeting, so the sovereign sees fewer conflicts.

### Game 7 "Montebello", turns 11–20

Minimal intervention: approved the plans, granted two petitions, refused one, one audience, one directive (build a farm). $0.116 in 67 calls, replay exact.

| Turn | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Food | 1011 | 1251 | 1522 | 1310 | 1057 | 456 | 422 | 373 | 324 | 469 | 524 |
| Mood (hidden) | 473 | 494 | 484 | 439 | 386 | 444 | 446 | 459 | 469 | 465 | 473 |
| Ration | normal | normal | normal | reduced | reduced | normal | normal | normal | normal | normal | normal |
| Effort / births % | +2 / 97 | +6 / 101 | +5 / 105 | −5 / 96 | **−20 / 65** | +4 / 104 | +2 / 103 | +3 / 102 | +5 / 106 | −3 / 97 | |

**What worked**: the council foresaw the second winter ("terrò pronta la razione ridotta per gennaio") and cut the ration in January. The people reacted strongly when their ration petition was refused (effort −20 %, births 65 %, mood into the discontented band); granting it brought effort back at once, and the square told it ("abbiamo pianto forte e ci hanno ascoltato"). The notes became political: the Treasurer and the Chancellor negotiated the ration month by month, and in turns 19–20 the Treasurer wrote privately to the Architect that new farms were needed before winter. A public directive got the farm built.

**Bug found and fixed during the game** (commit `c9a8409`): the first mood below 400 crashed the meeting (`effort_discontented` instead of `effort_discontent`), and the crash after the Voice left the turn stuck. Rounds now count only once the summary exists; a meeting held again does not repeat the square, the people or the season reviews.

**Problems**

1. **The growth trap**: fields full (60/60), each new adult sent to the sawmill, and the Architect's duty "build only where free adults can fill the jobs" (also in its mandate) means free adults never appear, so no farm is ever built: wood piled up to 717 while the granary fell to 324. Asked why, the Architect did not consider moving woodcutters. The duty should allow workers moved from a sector that needs them less.
2. **Invented building facts**: "una fattoria crea due posti" (it has 15): the briefing lists building costs but not their jobs. Other wrong sums: "le scorte crescono di +360 al mese" (Architect note), "il raccolto primaverile di circa 720 copre il consumo" (Chancellor; consumption was about 950).
3. **Runaway replies are frequent**: five calls hit the 8000-token cap in turns 13–18 (empty content after reasoning, or a looping string); all were retried, but each wastes about $0.0045. Cost of these ten turns $0.116 vs $0.085 for the first ten. A reasoning budget (OpenRouter `reasoning.max_tokens`) would cut the waste.
4. **A refused ration petition is very costly** (effort −20 %): to watch, it may make refusing almost never worth it.

### Game 7 "Montebello", turns 21–30 (after the growth-trap fix)

New Architect mandate at turn 21, then only approvals. $0.099 in 62 calls; the whole game, 30 turns: $0.30 (about $0.010 per turn, so a 120-turn game would cost about $1.20). One call hit the output cap and was retried without reasoning; replay exact.

| Turn | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Food | 524 | 803 | 1238 | 1638 | 2018 | 1541 | 1078 | 622 | 739 | 844 | 915 |
| Mood (hidden) | 473 | 479 | 484 | 465 | 483 | 476 | 482 | 486 | 489 | 491 | 470 |
| People | 113 | 114 | 115 | 114 | 115 | 116 | 117 | 118 | 119 | 120 | 120 |

**What worked**: with the fix the Architect moved the ten woodcutters to the fields at once (70, then 75 farmers): October's harvest reached 1439 and the third winter started with 2018 food, so no ration cut was needed and the council said so ("ridurre il pane in inverno accenderebbe il malumore senza salvare il granaio"). The Chancellor saw housing at 117/120 and proposed a house. The notes became a private debate between the Treasurer ("servono altre fattorie") and the Architect ("una fattoria da 15 posti resterebbe quasi vuota"), month after month.

**Problems**

1. **A milder growth trap**: with every worker already in the fields and one new adult a month, the Architect waits for 15 free adults before building a farm, so none is built. It ignores that a half-filled farm already pays (15 food per worker against 1 gold of upkeep) and that building takes two months. The duty should say so.
2. **Little to do in a stable realm**: in ten turns the sovereign only approved; no petitions, no crisis, mood flat around 480. Mid-game needs more choices (known: more classes, a use for gold, the map).

### Game 8 "Valfiorita" (2026-11-07, check of the manual; no mandates, almost no intervention)

10 turns, $0.122 in 62 calls (three runaway replies at the cap, each retried without reasoning: about $0.017), replay not needed.

| Turn | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Food | 1600 | 1158 | 746 | 344 | 164 | 261 | 357 | 623 | 888 | 1156 | 1524 |
| Mood (hidden) | 500 | 502 | 504 | 500 | 517 | 505 | 496 | 478 | 486 | 470 | 477 |

**The manual changed the Architect, too much**: it built a farm at turn 1 on its own ("pronta a primavera") and moved the woodcutters to the fields, as hoped; but at turn 3 it started a second farm while the first was still empty, ending with 6 farms (90 farm jobs for 65 adults) and nobody at the sawmill or the quarry for nine months (wood stuck at 70, stone at 80). From "never build without free adults" to "a half-filled farm pays, so build".

**Problems**

1. **Overbuilding and abandoned sectors**: the manual needs the other half of the rule: build a new building of a sector when its jobs are nearly full, and keep some workers at the sawmill and the quarry so wood and stone do not stop.
2. **The abundant ration with an empty granary**: in April, with 344 food, the Treasurer proposed the abundant ration and the Chancellor kept it (it was approved by a mistake of mine as the test player). The next month the council itself went back to normal. The briefing gives the consumption at the current ration only; it should give it at every ration.
3. **Runaway replies are still about one call in twenty** (three in this game), now cheap to recover; a repetition penalty could be tried.

### Game 9 "Pianalta" (2026-11-07, weaker-model test: Mistral Small 3.2 for the three counsellors)

Counsellors (Brunilde Masi, Bertoldo Sassi, Matteo Alberi) on `mistralai/mistral-small-3.2-24b-instruct`; the Voice and the people stayed on DeepSeek Flash. 10 turns, **$0.0166 in 62 calls** (the three counsellors: $0.0134, against roughly $0.10 for the same work on Flash in game 8), no refused reply, no runaway, slowest call 9.3 s (usually 2–6 s). The kingdom ended calm, food 830, gold 41 (falling slowly all game).

**What gets worse with the weaker model**

1. **Shallow reports**: two or three sentences, often only a description of the situation with no number and no proposal ("il popolo è stanco").
2. **Craft and role ignored**: the Treasurer flip-flops on the ration (reduced in July with the granary growing, abundant in August, again in October) and proposes a feast nearly every month with gold at 40–60; the Architect talks about taxes and morale and proposes a house every month, even against the sovereign's directive "niente nuove case" and with 34 free places.
3. **Invented or stale facts**: food figures that are not in the briefing; once the Chancellor summarised a feast and an abundant ration the Treasurer had not proposed that month (carried over from the month before).
4. **The Chancellor rubber-stamps**: the plans keep everything the ministers asked for; it did catch once an impossible worker plan (68 workers for 65 adults).
5. The sovereign had to reject most of the plans to keep the gold; a less careful player would have emptied the treasury with feasts.

**Verdict**: usable as the `low` tier (cheap, fast, valid JSON), not as a default counsellor. A low-tier person should be a cheap hire with visibly weaker advice, which is what this model gives.

### Game 10 "Collerosso" (2026-11-07, weaker-model test: gpt-oss-120b for the three counsellors)

Same set-up as game 9 (Brunilde Masi, Gisella da Valle, Matteo Alberi on `openai/gpt-oss-120b`, reasoning low; Voice and people on Flash). 10 turns, **$0.0174 in 62 calls** (counsellors $0.0136, the same as Mistral), no refused reply, no runaway (longest reply 1192 tokens), slowest call 8.7 s. The kingdom ended calm, food 760, gold 65 (rising after the tax went to 8%).

**Better than Mistral**

1. **Right numbers**: the Treasurer gives the consumption at the current ration, the harvest, taxes in and upkeep plus salaries out, and the projection is close to what happens.
2. **The Chancellor filters**: it postponed the Architect's quarry, refused to take farmers off the fields while food was falling, and dropped a feast after the sovereign's directive.
3. **The directive was obeyed** in the round after it (no quarry, no move from the fields).

**Still weak**

1. **The Architect chases empty jobs**: almost every month "move farmers to the sawmill and the quarry" and "build a quarry" while wood and stone pile up (420 and 208 at the end) and food was the scarce good; also off its role (feast, ration, tax). The manual's half of the rule is missing here too (game 8, problem 1): fill jobs only where the product is needed.
2. **The Treasurer flip-flops on taxes**: 8% in August, back to 6% for a petition in September, 10% in October "without burdening the people", against the manual (heavy taxes weigh on the people).
3. **Italian slips**: "granario", "cibarie", "nei segheri", a contradictory sentence (lighten the tax burden... raise the tax to 8%).
4. The Chancellor once read the directive as "save gold for the winter food" (gold buys no food).

**Verdict**: a clear step above Mistral at the same price; a good candidate for `low`, perhaps for `medium`. To compare with Flash on the same seed before choosing.

### Games 11–13 "Roccafonda" (2026-11-07, Ling 3.1 Flash: not usable)

Same seed as game 10. Game 11: HTTP 400, OpenRouter routed to Novita, which rejects `response_format`. With `provider.require_parameters` (now sent on every call) there was no provider left (game 12, 404): DeepInfra, the other one, is dropped by the account's "regional surcharge" filter. Game 13, without the schema for this model (`models_without_json_schema` in council.toml): the model thinks aloud in English inside the reply, before any JSON, up to the 8000-token cap even with reasoning "none"; 6 calls out of 6 refused, 38–88 s each, $0.0055 for a turn with no council. The analysis that could be read was sound; the format and the length are the problem. Dropped.

### Game 14 "Roccafonda" (2026-11-07, GLM 5.3 Flash for the three counsellors)

Same seed and persons as game 10. 10 turns, **$0.033 in 62 calls** (counsellors $0.028, about twice gpt-oss: 857 output tokens a call against 569, longest 2143), no refused reply, no runaway, calls 3–18 s (mean 6.9). The kingdom ended calm, food 1208 (760 in game 10), gold 39 (taxes at 5% for a petition), one month of protests in May (reduced ration kept four months on the Treasurer's advice).

**Better than gpt-oss**

1. **The Treasurer plans over the seasons**: harvest by season, the winter gap of about 450 a month, "il pane tornerà con più campi, non con un decreto"; she kept a prudent line and said why. Some sums are still wrong (in September "above 1000 the normal ration holds all winter", with a gap of about 1340).
2. **The Chancellor weighs and remembers**: it refused the abundant-looking plans when the numbers did not hold, and at turn 10 dropped the house because "the sovereign has already removed it in July, August and September" with nothing changed.
3. **Livelier Italian**, in the voice of the time (staia, casale, gabelliere), with the Architect keeping to its office ("non posso giudicare la gabella: è parte della Tesoriera").
4. The directive (a farm, nobody leaves the fields) was followed at once.

**Still weak**

1. **The Architect** still proposes moving farmers to wood and stone in winter, a sawmill instead of a farm, then moves one worker to the sawmill and back the next month; it read the manual backwards once ("un fabbricato mezzo vuoto non rende").
2. **Slips**: "renditione", "segherio", "sesterzi d'oro"; the Chancellor once left the 20 gold out of the cost of a house and got the gold balance at 5% wrong.

**Verdict**: the best of the three cheap models tried, at about a quarter of the cost of Flash with reasoning (0.67 against 2.8 thousandths of a dollar a call). Candidate for `medium`, with gpt-oss-120b for `low`. Still to compare: Flash with reasoning "none" on the same seed.

### Game 15 "Roccafonda" (2026-11-07, DeepSeek Flash with reasoning "none" for the three counsellors)

Same seed and persons as games 10 and 14; reasoning set to "none" for the counsellors for this game only. 10 turns, **$0.030 in 59 calls** (counsellors $0.026, 0.66 thousandths a call: the same as GLM 5.3 Flash, a quarter of Flash with reasoning "low"), 371 output tokens a call on average but one reply of 3509 (the Architect wrote on and on even without reasoning), calls 2.5 s on average. The kingdom ended calm all game, food 1372, gold 47.

| Counsellors, per call | Flash, low (game 8) | gpt-oss-120b (10) | GLM 5.3 Flash (14) | Flash, none (15) |
| --- | --- | --- | --- | --- |
| Output tokens (max) | 3200 (8000) | 569 (1192) | 857 (2143) | 371 (3509) |
| Thousandths of $ | 2.81 | 0.32 | 0.67 | 0.66 |
| Seconds | 17.8 | 3.8 | 6.9 | 2.5 |

**Good**: the numbers of the briefing are read right (harvest, consumption, gold in and out); the Architect proposed a farm on its own in May; the Chancellor put food first ("nessuna casa ora, tutti gli uomini liberi nei campi").

**Weak**

1. **Plans that empty a sector**: three times the worker plan put 0 at the sawmill or the quarry (once the Chancellor's own).
2. **The Treasurer flip-flops**: reduced ration in January, normal in February with the same numbers ("il granaio tiene" with spring below consumption); taxes 8% in April, 6% in June.
3. **The Architect** asks for a second sawmill ("mulino") month after month while the first has 8–9 empty jobs.
4. **Contradictions**: "19 in, 23 out... l'oro cresce piano ma sicuro"; the Chancellor once recommended a sawmill the Architect had not proposed in its report.
5. **The counsellors repeat the Voice**: "le braccia ci sono, la terra no" came from the square and went into both ministers' reports.

**Verdict**: at the same price GLM 5.3 Flash reasons better (seasonal planning, the Chancellor's memory of refused proposals, fewer impossible plans); Flash without reasoning is the fastest. Proposed tiers: `low` gpt-oss-120b, `medium` GLM 5.3 Flash, `high` Flash with reasoning (or Pro, still to test). A tier is a model only today; Flash "low" vs "none" shows that a tier may need its reasoning effort too.

### Game 16 "Roccafonda" (2026-11-07, GLM 5.3 Flash with reasoning "high")

Same seed and persons as games 10, 14 and 15; the counsellors' reasoning set to "high" for this game only. 10 turns, **$0.042 in 59 calls** (counsellors $0.038: 0.97 thousandths a call against 0.67 with "low" in game 14, +45%), 1424 output tokens a call on average (857 with "low"), longest 2810, no runaway, no refused reply, calls 9.3 s on average (19 s at most). The kingdom stayed calm all game (game 14 had a month of protests), food 1353, gold 29 (taxes down to 5% for two petitions).

**Better than "low"**

1. **The Architect stopped asking for sawmills and quarries**: in April it proposed the fifth farm on its own (the Treasurer too), then for six months "nessun cantiere nuovo col podere mezzo vuoto", sending each new adult to the fields first, then to the quarry. No farmer moved to wood or stone in winter. The other half of the manual's rule (game 8) was found by reasoning.
2. **The Treasurer uses the manual**: a feast repeated the month after "raccoglierà metà dell'effetto"; "l'oro non compra grano"; the gold lost at each tax cut is given in numbers; the winter is reckoned over its three months.

**Worse than "low"**

1. **The Italian breaks more often**: "dioro", an Arabic letter inside a word ("quest'مese"), "store", "manodopore", "Conflietti", "Maestra sono prudente", "Il Tesoriere Brunilde Masi"; once the Treasurer named an invented courtier ("Colza Colmaro consigliere di corte").
2. **The Chancellor overbuilt once**: in July it added a sixth farm that the Architect had just declined (dropped by the sovereign).
3. Still one plan with 0 at the sawmill and the quarry (February, all hands to the fields).

**Verdict**: more reasoning buys better judgement for about half again the cost, and costs Italian; still a third of Flash with reasoning "low". A candidate for `high` (GLM "high"), with `medium` GLM "low": the tier would then set the reasoning effort as well as the model.

### Game 17 "Roccafonda" (2026-11-07, GLM 5.3 Flash with reasoning "medium")

Same seed and persons as games 10 and 14–16. 10 turns, **$0.027 in 62 calls** (counsellors $0.024, 0.58 thousandths a call), 608 output tokens a call on average: **fewer than with "low"** (857), so the effort levels of this model are not a ladder (or the provider changed between games). Longest call 31 s. The kingdom stayed calm, food 1008, gold 59; the sovereign had to order the farm (game 16 found it on its own).

| GLM 5.3 Flash, counsellors | low (game 14) | medium (17) | high (16) |
| --- | --- | --- | --- |
| Output tokens a call (max) | 857 (2143) | 608 (1866) | 1424 (2810) |
| Thousandths of $ a call | 0.67 | 0.58 | 0.97 |
| Farm proposed unasked | no | no | yes |

**The weakest of the three GLM games**

1. **The Treasurer lost her voice in four months out of ten**: generic reports with no numbers ("la situazione sociale è critica", "prioritizzo l'ottimizzazione della produzione agricola"), English words ("ration normal", "petition"), twice the abundant ration with 350 food, once a sawmill (not her office).
2. **Counsellors believe refused proposals were carried out**: in September the Architect said "il segherio rende" and the Chancellor "il segherio del turno 8 ha già aperto la via" (the sovereign had refused it); in October "la cava avviata a settembre sarà pronta" (refused too). The briefing's history says what followed each proposal, but it was not read.
3. **The Architect** asked for a second sawmill or a quarry four times while the first ones had 8–9 empty jobs.
4. **The Chancellor** let the abundant ration through twice (in October with harvest 1187 against consumption 1193, "il granaio resta crescente").

**What this says about the tests so far**: one game per setting is a small sample; the spread between games 14, 16 and 17 is as large as the spread between models. Before fixing the tiers: two or three games per candidate, or a shorter fixed test (the same few briefings sent to every model and scored).

### Lab: bench of the council models (2026-11-07, `lab/bench.py`)

8 stored briefings with a known trap (`lab/bench_scenarios.toml`: 3 Treasurer, 3 Architect, 2 Chancellor), each sent 3 times to each candidate; the ministers' memory section is rebuilt with the current code (with the new "Not approved by the sovereign" line). Nothing is written to the database. About $0.20 for the whole run (120 + 30 calls).

| Candidate | Clean / 24 | Fell in the trap | Invalid | Output tokens | Seconds |
| --- | --- | --- | --- | --- | --- |
| Flash, none | 16 | 8 | 0 | 263 | 2.5 |
| GLM 5.3 Flash, high | 15 | 9 | 0 | 1282 | 9.2 |
| Flash, low | 15 | 5 | 4 (8000-token cap) | 4879 | 24.2 |
| GLM 5.3 Flash, low | 14 | 10 | 0 | 864 | 6.3 |
| gpt-oss-120b, low | 11 | 13 | 0 | 582 | 3.8 |

**What it says**

1. **The candidates are close**: with 3 repeats a difference of two or three runs is noise. Only gpt-oss is clearly behind, and Flash "low" falls least in the traps but runs away to the cap one call in six (without the meeting's retry) at 20 times the tokens.
2. **The Architect fails with every model**: in winter (scenario 5) 13 runs out of 15 took farmers from the fields, often for a quarry or a sawmill; with the granary falling (scenario 6) a farm came 3 times out of 15 (Flash "low" twice, GLM "high" once), a house or a second quarry/sawmill instead. With an empty sawmill (scenario 4), 8 out of 15 asked for another one. This is the prompt (craft and manual: "a half-filled building already pays" is read as "build", the other half of the rule is missing; game 8, problem 1), not the model.
3. **The Treasurer passes**: 43 runs out of 45 clean on winter, low granary and repeated feast (gpt-oss proposed the feast again twice).
4. **The Chancellor** let the abundant ration through 5 times out of 15 and proposed the refused house again 3 times out of 15.

Mistake of the first run: scenarios 7 and 8 pointed at the Chancellor's end-of-season reflection (lessons), the first call of those turns; corrected to the meeting calls and run again.

**Next**: fix the Architect's craft and the manual (when to build: a sector's jobs nearly full and its product needed; keep the farmers in winter), then run the bench again on the same scenarios; the tiers after that.

**Second run, after the new Architect craft** (food first, empty jobs are no problem, build only where jobs are nearly full and the product short, no second sawmill/quarry while the first has empty jobs) and the manual without "a half-filled building already pays": the Architect's scenarios 4–6 clean in **25 runs out of 45 (11 before)**; GLM "high" 8 out of 9 (2 before), GLM "low" 5 (1), Flash "none" 5 (3), Flash "low" 5 (4), gpt-oss 2 (1). Treasurer and Chancellor about the same (noise). Two new faults:

1. **Winter plans that empty the sawmill and the quarry** ("food 60 wood 0 stone 0", 6 runs in scenario 5): "no hand leaves the fields" is read as "every hand to the fields".
2. **gpt-oss reads assign_workers as a change**: "food 0 wood 1 stone 0" to send one idle adult to the sawmill (3 runs), which would empty the fields. The order format says "adults per sector" but not that the numbers are totals after the order.

**Flash "high"** on the same second run: **13 replies out of 24 hit the 8000-token cap** (invalid; the meeting would retry them without reasoning), 7122 output tokens and 31 s a call on average, $0.118 for 24 calls (0.005 a call, 7 times GLM "low"). The 11 that finished fell in no trap. Not usable with the present cap; a higher cap means more cost and calls near the 90 s deadline.

Clean replies of the second run, out of 24: GLM "high" **21** (Treasurer 9/9, Architect 8/9, Chancellor 4/6), Flash "none" 18, GLM "low" 17, Flash "low" 16 (5 invalid), Flash "high" 11 (13 invalid), gpt-oss 10 (Chancellor 0/6).


### Game 18 "Roccafonda" (2026-11-08, every agent on GLM 5.3 Flash "high"; new Architect craft and the three fixes)

Same seed and persons as games 10 and 14–17. New since game 17: the Architect's craft (food first...), the manual without "already pays", "Not approved by the sovereign" in the ministers' memory, assign_workers as totals in the order format, the idle-adults warning. 10 turns, **$0.032 in 59 calls**, no refused reply, no runaway, calls up to 17 s. The kingdom stayed calm all game, food 1296, gold 48 (taxes 8% then 6% for a petition and the Treasurer).

**Better**

1. **The Architect** proposed the fifth farm on its own in April ("il bisogno è scritto nei posti pieni"), asked for no sawmill or quarry in ten months ("né seconde fabbriche mentre i primi posti son vuoti"), kept 2 and 1 hands at the sawmill and the quarry, sent every new adult to the fields, and proposed a house only in July with births running and 15 free places (approved).
2. **The memory fix works**: in February the Architect wrote "concordo con la Sua scelta di gennaio di non costruire, e non ripresento il progetto".
3. **The Chancellor** dropped the Treasurer's reduced ration in March with the numbers ("con razione normale il granaio arriva a primavera con circa 260 sacchi").
4. No assign_workers read as a change.

**Still weak**

1. **The February plan moved two farmers to the sawmill in winter** (55/4/1), while the Architect's own report said "nei mesi freddi nessuna mano lascia i campi" (refused).
2. **Garbled words, mostly in the Voice of the square**: "recatrimba", "badoreggia", "battisce", "favoredella", "targheggia", "l'incensière"; once three paragraphs long; a recurring invented villager ("Serena"). The counsellors too: "Ilconfigs", "would sour", "gonarsi", "in store".
3. The Treasurer called the gold "sufficient" while it fell from 104 to 48 (the house, upkeep and salaries above 19 a month of taxes).

**Voice and people on GLM "high"**: the same cost as Flash "none" (about 0.0002 a call: GLM reasons little there), a little slower (2.7–2.9 s against 1.3–1.8). The people's decisions looked sound (effort +1 to +6, births 102–105%, one petition). The Voice's Italian is worse than with Flash: the Voice went back to Flash "none", the people stay on GLM "high".

### Game 20 "Pianverde" (2026-11-08, first 12 months on the map; GLM 5.3 Flash "high", Voice on Flash "none")

Claude as a sensible sovereign: approved most plans, removed 5 orders (two claims and a tax raise against an empty treasury, two feasts, a town plan the Chancellor invented), answered 5 petitions (3 granted). **$0.066 in 71 calls** ($0.0055 a month: the Architect's calls cost the most, input 4,500 → 6,300 tokens). The realm ended calm with food 1,899 and gold 12; 6 farms, 146 tiles.

**On the map, good**

1. **The Architect foresaw the land**: in February, "the Campi will be full as soon as the farm opens", it claimed 2 plain tiles to the south; in April it put 2 hands to clearing "as promised"; both tiles were cleared by June. In October, with the Campi full, it redrew the plan stretching the fields zone to row 62, beyond the border, and waited for the gold to claim more. It built the sixth farm in the last free place.
2. **The Chancellor remembered** that the sovereign removed the claims ("la Vostra avversione alle acquisizioni") and kept the land for when the treasury allows.

**Weak**

1. **The Architect missed 2 meetings** (August, September): a reply ran up to the 8,000-token cap in 60 s and the retry at reasoning "none" got HTTP 400 from GLM (fixed: "low" for models that must reason); in September the call timed out at 90 s. In October one more runaway was saved by the fix. 3 runaways in 12 months, none in game 18: the longer briefing (map, zones, memory) may push GLM "high" into long reasoning.
2. **Gold, not labour, stopped the growth**: the people petitioned the tax down to 6% three times; at 6% income is 18-20 against 23-24 of upkeep and salaries, so a 20-gold tile was never affordable after March. Gold now has a use, but a realm that listens to its people cannot grow: to watch in the next games (price, salaries, taxes).
3. **The Chancellor**: put a "secret note" for the Treasurer inside the summary the sovereign reads (May); wrote in June "I add the farm to the plan" with no farm in the plan; in September, with the Architect absent, invented a town plan in the corner of the world (refused by the engine anyway); raised the tax to 10% two months after the petition for 6% was granted.
4. **The ministers' memory says "Not approved by the sovereign" also for what the Chancellor left out**: the Architect believed the sovereign had refused a house it never saw.
**Fixed after the game (2026-11-08)**: the ministers' memory tells "Left out of the plan by the Chancellor (the sovereign never saw them)", "Changed by the Chancellor: A → B" and "Removed from the plan by the sovereign" apart; the Chancellor's prompt: the summary tells only what is in the plan, secret notes only in their field, no town plan for an absent Architect; the Architect's map ring 1 tile instead of 2 (the map is only about a tenth of the prompt: the rest is the system prompt, notes, memory, lessons and the square); output cap 6,000 instead of 8,000 (longest good GLM reply 4,566).

5. Sawmill and quarry without hands from July on (stores were large); garbled words again ("tarned", "sta Thanks", "Ora di goodwill"); the Treasurer's report once only "Petition check"; the Architect's report twice generic and off its duty (January, May).

### Game 21 "Altopiano" (2026-11-08, 12 months on the map; the sovereign kept the taxes covering the costs)

Same models; after the game 20 fixes (memory, Chancellor rules, ring 1, cap 6,000). Claude as sovereign kept the tax at 8% (income 24-26 against 23-24 of upkeep and salaries): granted the petition from 10 to 8%, refused the one to 7%, removed two feasts, a claim and a farm with no room. **$0.053 in 72 calls, no failed call** (no runaway this time), longest call 70 s. The realm ended calm with food 1,928 and gold 34; 6 farms, 148 tiles (4 claimed, 80 gold into the fund, all cleared by September).

**Good**: the Architect claimed in March "before the Campi zone runs out", cleared with 1 to 3 hands outside winter, stretched the fields zone over the new land, kept no claims while gold was short ("la cassa è corta"); the new memory works ("riproporre il campo o la terra negati il mese scorso non è saggio"); the Chancellor's summaries matched the plans and no note leaked.

**After the game**: texts far over or under their length are asked again; the room per zone says where the next building stands; claims inside a zone (the land comes as a block); price 10 and salaries halved (lab: two farms on new land in three years instead of none).

**The economy of land (point E)**: with the tax covering the costs the treasury grows by 1-3 gold a month, so a 20-gold tile takes about ten months of surplus; a farm needs a 3 × 3 block, 9 tiles, about 180 gold and 27 worker-months. In a year the realm claimed 4 tiles and built **no farm on new land** (the sixth farm took the core's last place). Growth by land is out of reach at these prices, with or without petitions.

**Weak**

1. **Texts with no length check**: in April the Treasurer's report ran on for over a thousand words, repeated signatures and capitals ("FINE, GIURO"); in October the Chancellor answered "..." with an empty plan (13 output tokens). Both valid JSON, both accepted. A directive brought a second round, weaker than the first (the Architect's house was lost, a farm with no room and a pointless claim proposed).
2. **"Room for 1 farm" does not say where**: the Architect believed the sixth farm would stand on the cleared land; it went to the core's last place.
3. The Architect's report was generic and off its duty twice (round 2 of October; earlier games too); the Treasurer once proposed a house (not its order); "cinquantacinque" for 60 adults in a summary.

### Game 22 "Valchiara" (2026-11-08, 12 months; price 10, salaries halved, claims inside zones)

Claude as sovereign kept the tax at 8% (income 24-26 against 19-21 of upkeep and salaries: about +5 a month): granted the petitions to 8% and back to the normal ration, refused the one to 6%, removed two feasts, a tax raise to 10% and two claims the Chancellor invented in zones already owned. **$0.049 in 70 calls**, no missed meeting, longest call 23 s. The length check worked once (a one-word report asked again). The realm ended calm with food 1,779 and gold 27; 6 farms, 7 houses, 155 tiles (11 claimed, 113 gold into the fund; 5 still being cleared).

**Good**: the Architect claimed **inside the fields zone** every time ("so the block grows as a block"), cleared outside winter with 3 to 6 hands, waited for the surplus ("111 ducats are not enough for nine tiles and the wages"); the Treasurer read the new margin right ("25 of income against 14 of upkeep and 6 of wages"); the Chancellor held the house back so the treasury would not fall to 2 gold before winter. Gold is now a real but reachable brake.

**Weak**

1. **The new fields zone was 2 rows deep again** (rows 60-61): the Architect claimed 11 tiles into it while the briefing said "Campi: full", and never saw that no farm fits there. "Full" does not say that even the whole zone, claimed and cleared, holds no farm. No farm on new land in 12 months.
2. **The Chancellor invents territory orders**: in June two claims "inside" zones the realm already owned (refused by the engine anyway).
3. Generic reports without numbers again (Treasurer and Architect in December; the same output size as good ones, so not a short reasoning); the Treasurer proposed a tax raise twice in calm months.

### Lab: famine balance (2026-11-07)

The exact orders of games 1 and 2 replayed under mood variants (the base replay reproduces both games exactly). Mood month by month, from turn 2.

| Variant | Taxes 30 % (game 1) | Famine (game 2) |
| --- | --- | --- |
| Today | revolt at turn 8 | 497 454 460 470 …: always calm |
| A: hunger −12/point, max −500, death −15 | revolt at turn 8 | 497 404 398 423 …: calm |
| B: hunger −15/point, max −600, death −20 | revolt at turn 8 | 497 379 368 401 …: calm |
| **D: immediate shock −4 per missing point, −10 per death** | revolt at turn 8 | 497 **304 273 (protests)** 329 359 377 …: protests for 3 months, then recovery |
| E: immediate shock −6 / −15 | revolt at turn 8 | 229 180 260 307: strike for 3 months |

Making hunger weigh more in the target is not enough: the mood moves only 25 % of the way each month and a famine lasts one or two months. A famine has to be a shock, like a feast in reverse. **Applied: D.** Two new `[mood]` values; they default to 0, so games saved before keep their own rules and replay unchanged (no `ENGINE_VERSION` bump needed).

### Lab: tension for a sensible player (2026-11-07)

The accepted orders of games 1 (greedy), 2 (famine) and 3 (sensible) replayed under start and winter variants. The orders are fixed, so the replay does not show how a council would react (e.g. cutting the ration when the store runs low): it shows how close each player comes to the edge.

| Variant | Greedy (g1) | Famine (g2) | Sensible (g3) |
| --- | --- | --- | --- |
| Today | revolt at turn 8 | 2 famine months, 9 deaths, protests | lowest food 684, always calm |
| Start mood 500 | revolt at turn 7 | 9 deaths, strike | lowest food 684, mood 485–501 |
| Start food 1600 | revolt at turn 8 | 7 famine months, 33 deaths, revolt | **lowest food 316**, calm |
| Winter farms 40 % | revolt at turn 8 | 31 deaths, revolt | lowest food 433, calm |
| **Food 1600 + mood 500** | revolt at turn 7 | 33 deaths, revolt | **lowest food 316**, mood 485–501, calm |
| Food 1500 + winter 40 % + mood 500 | revolt at turn 7 | 36 deaths, revolt | 1 famine month, 3 deaths |

**Applied (2026-11-07): food 1600 and start mood 500.** The sensible player reaches the spring with about a third of a month of food: the first winter becomes a real decision (cut the ration or not) without forcing a famine. A start mood equal to the base removes the slow drift the square misread as "un lutto che non ha nome". To be confirmed by a played game, since the council adapts.

### Lab: the market (2026-11-08)

`lab/market_sim.py`: three realms of the same core, 24 months, fixed policies (farmer sells food above 2 months; builder buys wood, stone and food instead of cutting the ration; prudent, tax 12, buys food below 1.5 months and sells wood and stone). One merchant: lots of 50, start price food 10, wood 15, stone 20 gold, price = base × base stock / stock (50–300 %), restock 20 % a month. The market is applied by the script before each turn, not by the engine.

| Variant | Farmer gold (alone 422) | Builder gold / reduced months (alone 395 / 9) | Prudent gold / reduced months (alone 625 / 9) | Food price range |
| --- | --- | --- | --- | --- |
| Margin 10, food stock 600 | 937 | 26 / 0 | 86 / 0 | 9–33 |
| Margin 25 | 816 | 17 / 0 | 72 / 0 | 10–38 |
| Restock 5 % | 1192 | 24 / 0, **famine** | 56 / 0 | 33 (the cap) for most months |
| Small stocks (food 200) | 872 | 322 / 0, **famine**, 8 deaths | 168 / 0 | 19–33 |
| Large food stock (2000) | 730 | 36 / 0 | 180 / 0 | 10–18 |
| Cheap food (5 a lot) | 719 | 45 / 0 | 304 / 0 | 5–17 |

1. **Gold gets a use**: the buyers end with almost no gold (from 400–600 to 20–90). The market is a gold sink, and the winter becomes a choice between gold and the ration.
2. **Food is the only real trade**: nobody needs wood or stone (the cores are the same and cover their needs). The prudent sells 600 wood, and the wood price falls below the base. Trade in wood and stone needs realms that differ (terrain, rare resource).
3. **The merchant is a source of food**: about 2850 bought against 1500 sold, so about 1350 came from outside. With a large stock the winter tension we tuned disappears (prudent, lowest food 821, no month on the reduced ration).
4. **Depending on the market is a risk**: with small stocks or a slow restock the buyers split the short stock pro rata and the builder, which never cuts the ration, has a famine.
5. **The naive seller gets hungry**: the farmer sells in autumn above 2 months and spends 9 months on the reduced ration instead of 5. The Treasurer will need the seasonal outlook before selling.
6. **Seasonal swing, possible speculation**: the food price runs 9–33 in a year, low in autumn, high in late spring. Buying in autumn and selling in spring would pay far more than the margin and the 2 % spoilage. Not tested: a policy that only speculates.

### Lab: the closed market (2026-11-08)

`lab/market_closed.py`. The sovereign chose a market with nothing from outside (no Ambassador, no bilateral deals in this step), and realms that differ. A warehouse on consignment: the seller hands over the goods and is paid when a buyer takes them, first in first out. The warehouse owns no gold and no goods; stored food spoils 2 %. Price per lot of 50 (start 10, 15, 20): +10 % when the month asked more than there was, −10 % when goods stayed unsold, within 50–300 %. One policy for every realm; only the yields per worker differ (same map): granary food 18, wood 4, stone 3; forest food 14, wood 9, stone 3; quarry food 14, wood 4, stone 6 (base 15, 6, 4). A realm puts twice the hands on a sector its land is good at.

| Variant | Granary | Forest | Quarry |
| --- | --- | --- | --- |
| Alone, no market | gold 350, 3 reduced months | **revolt at month 20**, 14 reduced | **revolt at month 21**, 14 reduced |
| Same land for all | gold 332, sells 500 food | the same | the same |
| Mild lands, margin 10 | **gold 720**, sells 2950 food | gold 69, buys 1100 food, calm, 12 reduced | gold 145, buys 900 food, calm, 10 reduced |
| Margin 25 / price step 20 | about the same flows | about the same | about the same |
| Strong lands (farms 12) | sells 3350, 1758 food left unsold | **revolt at month 12** | **revolt at month 12** |

1. **Food works**: it flows from the granary to the others, the gold flows back, and the market saves the forest and the quarry from the revolt they reach alone.
2. **Nobody buys wood or stone**: the forest sells 1450 wood and earns 0. The stock piles up (1800 wood, 500 stone) and the price sits at the floor. Every realm builds only a few buildings in its core (6 farms, 9 houses) and has enough wood and stone of its own. The forest and the quarry pay for food only with taxes.
3. **Food arrives late**: in the first year the granary has a surplus only from the autumn. With strong lands the forest and the quarry revolt at month 12, while 1758 food later sits unsold.
4. **Margin and price step change little**: they move only the gold.
5. "Mild" is not mild: with 14 per farm worker and fewer hands on the fields, the forest and the quarry fall alone. The base game alone already spends 9 months on the reduced ration.

### Lab: firewood and stone upkeep (2026-11-08)

Same lab (`lab/market_closed.py`), with two needs applied by the script. **A, firewood**: 1 wood per 2 people per winter month (January to March); what is missing costs 2 mood per missing percent, at once. **B, stone upkeep**: 1 stone per 2 active buildings a month; what is missing lowers the month's output by half the missing share. The policy keeps 4 months of needs plus the next building, buys below that and sells above it. Light lands: granary food 17, wood 4, stone 3; forest food 15, wood 9, stone 3; quarry food 15, wood 4, stone 6.

| Variant | Granary | Forest | Quarry | Wood / stone at the end |
| --- | --- | --- | --- | --- |
| A+B, alone | gold 377, 2 cold months, 3 worn | **strike**, 13 reduced | **revolt at month 20** | – |
| No needs, market | sells 1850 food | sells 1500 wood, earns 17 | sells 400 stone, earns 31 | 1800 / 500 unsold, both at the floor |
| A+B, market | buys 150 wood, 100 stone | sells 1100 wood, earns 96 | sells 250 stone, earns 48 | 850 / 50 |
| A+B, market, margin 25 | the same flows | the same | the same | the same |
| A+B, market, **realms react to prices** | gold 430 | **6 reduced months** instead of 10, mood 426 | 5 reduced instead of 10, mood 426 | 400 / 0, stone price back up to 16 |
| Firewood 1 per person | **revolt at month 8** | revolt at month 21 | **revolt at month 8** | the warehouse is empty in winter |
| A+B, strong lands (farms 12) | sells 3350 food, 1722 unsold | revolt at month 12 | revolt at month 11 | – |

1. **A and B create trade in wood and stone**: the granary and the quarry buy wood, the granary and the forest buy stone. The wood price first rises (22 in June against a start of 15), then falls as the forest keeps selling.
2. **Supply must react to the price**: with fixed hands the forest makes far more wood than anyone burns. A realm that moves its extra hands to the fields when the price is below the start trades less wood but eats better (forest reduced months 10 → 6). A council will have to see prices and stocks.
3. **The price falls as long as anything stays unsold**: a few old lots kept the wood at the floor all the second year, even with buyers around. To decide: compare the stock with the recent demand instead of "any lot unsold", or let a seller take back its goods.
4. **The first winter has no market**: the warehouse starts empty, so in January every realm short of firewood is cold for a month.
5. **Firewood 1 per person is too much**: nobody sells wood in winter, and two realms revolt at month 8. 1 per 2 people works.
6. **Trade does not replace a self-sufficient land**: with farms 12 the forest and the quarry fall even with food in the warehouse (it arrives in the autumn). The asymmetry has to stay light for food.

### Lab: price rule and start stock (2026-11-08)

Same lab, with A+B and light lands. **New price rule**: the price falls only when the warehouse holds more than 3 months of the lots asked lately (with no demand, any stock is too much); before, it fell whenever a lot stayed unsold. **Start stock**: 300 food, 150 wood, 100 stone, nobody's goods (their gold leaves the game).

| Variant | Granary | Forest | Quarry | Price at month 24: food / wood / stone (start 10 / 15 / 20, mid price) |
| --- | --- | --- | --- | --- |
| Old rule, realms react | gold 430, 1 cold month | 6 reduced | 5 reduced, 1 cold | 10 / 7 / 14 |
| New rule, realms react | gold 476, 1 cold month | 6 reduced | 5 reduced, 1 cold | 16 / 7 / 14 |
| **New rule, start stock, react** | gold 371, **no cold month** | lowest food 410 (was 362) | lowest food 497 (was 406), **no cold month** | 11 / 7 / 14 |
| New rule, start stock, no reaction | gold 415 | 9 reduced, 950 wood unsold | 7 reduced | 12 / 7 / 10 |
| Margin 25 | about the same flows | the same | the same | – |

1. **The new rule keeps prices where demand is**: food and stone recover in the second year. Wood still falls to the floor, but now for a real reason: the forest makes more than anyone burns (300–450 unsold for about 1 lot asked a month).
2. **The start stock removes the cold first January** and raises the lowest food of the poorer realms.
3. Policy artefact, not a market rule: in January the granary sells about 2000 food at once, because its reserve rule drops from 3 to 2 months.

### Lab: eight realms (2026-11-08)

`lab/market_closed.py eight`: 8 realms with A+B, the new price rule and a start stock of 800 food, 400 wood, 250 stone. Levels: food 14 / 15 / 17, wood 4 / 6 / 9, stone 3 / 4 / 6 (poor / fair / rich); profiles one rich, one fair, one poor in every order, plus 2 realms all fair. The policy doubles the hands on a rich resource while its price is not below the start.

| Realm | Alone | Market | Gold at the end, market |
| --- | --- | --- | --- |
| 1 F+ W= S- | calm, 4 worn months | calm | 449 |
| 2 F+ W- S= | calm, 2 cold months | calm | 439 |
| 3 F= W+ S- | **strike**, 13 reduced | calm, 6 reduced | 268 |
| 4 F- W+ S= | **revolt at month 20** | calm, 9 reduced | 162 |
| 5 F= W- S+ | **revolt at month 20** | calm, 5 reduced | 236 |
| 6 F- W= S+ | **revolt at month 21** | calm, 9 reduced | 176 |
| 7, 8 F= W= S= | calm, 8 reduced | calm, 5 reduced | 244 |

1. **Nobody falls with the market**; alone, 4 of 8 do.
2. **Food is worth the most**: 6100 food bought against 800 wood and 100 stone. The realms rich in food end with about 440 gold, those rich in wood with 160–270.
3. **Wood is oversupplied**: two rich forests flood a small demand (firewood 3 months a year). The stock grows to 1300 and the price sits at the floor from month 15.
4. **Stone is barely traded**: a poor quarry (3 per worker, 2 hands) almost covers the upkeep. The start stock of 250 stayed unsold for 15 months.
5. **The start stock lowers the prices**: nobody asks for it at first, so the rule reads it as too much and the stone price falls from 20 to 10 without one sale. To decide: leave the start stock out of the price rule, or make it smaller.
6. Without the reaction to prices the flows are the same, with more unsold wood (2500) and more reduced months.
7. Policy artefacts: doubling the hands on a rich resource takes them from the fields (that is why realms 3 and 5, fair in food, fall alone); the realms all fair sell food in January and buy it back later (the reserve rule).

### Lab: eight realms, tuning (2026-11-08)

Same lab (`lab/market_closed.py eight`), every realm reacting to prices. Poorer levels: wood 3 / 6 / 9, stone 2 / 4 / 6 (were 4 / 6 / 9 and 3 / 4 / 6).

| Variant | Wood / stone bought | Wood in stock, months 12–24 | Stone price (mid, start 20) | Cold months | Gold sink |
| --- | --- | --- | --- | --- | --- |
| Before (start stock in the price rule) | 800 / 100 | 900–1300 | 10 before any sale | 0 | 584 |
| Start stock out of the price rule | 800 / 400 | 900–1300 | 20 until month 3, then falls with the realms' sales | 0 | 647 |
| + poorer levels | 1000 / 400 | 800–1200 | the same | 1 each for realms 2 and 5 (poor wood) | 676 |
| + rich wood 8 | 1000 / 400 | 700–1000 | the same | the same | 676 |
| **+ poorer levels, firewood November to March** | **1200** / 400 | **0–100** | the same | 1 each for realms 2 and 5 | 701 |

Nobody falls in any variant (alone, with the poorer levels, 4 of 8 still fall).

1. **Firewood from November to March balances wood**: the stock stays at 0–100 from month 12 and the price moves around 8–12 instead of sitting at the floor. Rich wood 8 helps much less.
2. **Leaving the start stock out of the price rule works**: stone keeps its price until the realms start selling, and 4 times more stone is bought.
3. **Stone demand is still weak**: about 400 bought in two years by 8 realms; the stock goes up to 450 when the rich quarries sell, and the price falls to about 10. The realms rich in stone end with 140–165 gold.
4. **Food sets the wealth**: the realms rich in food end with 415–496 gold, those poor in food with 138–149. Food is about 80 % of all trade.
5. The gold sink (margin and start stock) is about 700 in two years for 8 realms, about 3.6 gold a realm a month.

### Lab: eight realms, second tuning (2026-11-08)

Base: the best run before (wood 3 / 6 / 9, stone 2 / 4 / 6, firewood November to March, start stock out of the price rule), every realm reacting to prices.

| Variant | Fallen | Gold, realms rich in food / poor in food | Food bought | Stone price (mid) at month 24 | Gold sink |
| --- | --- | --- | --- | --- | --- |
| Best before (stone upkeep 1 per 2, food 14 / 15 / 17) | none | 415–485 / 142–149 | 6150 | 12 | 701 |
| Stone upkeep 1 per building | **2 revolts** (realms 3 and 4, month 23) | 425–443 / 86–120 | 6600 | **60, the cap** | 853 |
| Food 14 / 15 / 16 | none | 330–383 / 163–188 | 4350 | 12 | 742 |
| Both | none, 2 realms in protests | 400–423 / 147–230 | 4950 | 60, the cap | 939 |

1. **Stone upkeep 1 per building is too much**: the world makes less stone than it needs. Alone, all 8 realms revolt (output lost to wear, then famine). With the market the price runs to the cap, and two realms revolt. It shows that the price rule reacts to a real shortage.
2. **Food 14 / 15 / 16 narrows the gap**: realms rich in food against poor in food from about 3.3 : 1 to about 2 : 1 in gold. Less food changes hands (4350), the rich realms spend more months on the reduced ration (9 instead of 5), and food piles up at the end (about 1800, price 8).
3. The right stone upkeep lies between 1 per 2 and 1 per building, or the start needs more hands on stone (2 today). "Fair" must mean the start hands cover the upkeep.

### Lab: eight realms, third tuning (2026-11-08)

Food 14 / 15 / 16, wood 3 / 6 / 9, stone 2 / 4 / 6, firewood November to March, start stock out of the price rule, every realm reacting to prices. Only the stone upkeep and the start hands on stone change.

| Variant | Alone: fallen of 8 | Market: fallen | Stone bought | Stone price (mid) months 15–24 | Worn months, realms poor in stone | Gold: richest / poorest |
| --- | --- | --- | --- | --- | --- | --- |
| Upkeep 1 per 2 buildings, 2 hands | not measured | none | 400 | 10–12, stock up to 450 | 0 | 383 / 163 |
| Upkeep 2 per 3 buildings, 2 hands | 6 (only the all-fair realms hold) | none | 200 | 10–15, stock 150–250 | 1 | 404 / 151 |
| **Upkeep 1 per building, 3 hands** | 6 | none | 400 | 10–16, stock 50–200, rising at the end | **6** | 443 / 137 |

1. **1 per building with 3 hands makes stone a real need**: the poor quarries are short (6 worn months), the stock runs low and the price rises again in the second year. Nobody falls, but the realms poor in stone are less content (mood about 365 against 400).
2. **2 per 3 buildings is gentler**: stone keeps a fair price, but little changes hands (200).
3. **Alone, both are harsh**: 6 of 8 realms fall. The market becomes what keeps most realms standing.
4. **Gold follows food**, not stone: the realms rich in stone are also fair or poor in food, and end with 137–199 gold.
5. A third hand on stone comes from the fields: food is a little scarcer (food bought 3850, price 20 at the end).

### Lab: food levels (2026-11-08, after game 24)

`python lab/market_closed.py food`. Game 24 had no food on sale: with 14 / 15 / 16, a farmer of the rich land makes about 848 a month against about 900 eaten. Same lab as the third tuning (upkeep 1 per building, 3 hands on stone); the lab now drops the engine's own `[needs]` and `[levels]` so they are not counted twice. 8 realms, 24 months, at one market.

| Food levels | Fallen | Food bought | Food sold by the 2 rich realms | Food price (buy) months 15–24 | Gold: rich food / poor food |
| --- | --- | --- | --- | --- | --- |
| 14 / 15 / 16 (before) | none | 3850 | 1150 + 1150 | 16–20 | 443, 425 / 180, 137 |
| **14 / 15 / 18** | none | 6500 | 2150 + 2700 | 11–17 | 582, 593 / 149, 142 |
| 13 / 15 / 18 | 2 (both poor in food, month 21) | 6700 | 2150 + 2700 | 11–20 | 445, 710 / 88, 73 |
| 13 / 16 / 19 | 2 (both poor in food, month 21) | 8050 | 2900 + 4000 | 11 falling to 6, stock up to 6716 | 607, 546 / 52, 32 |

1. **14 / 15 / 18 is the only wider variant where no realm falls.** Food changes hands 70 % more, the price stays near its start, and a rich land pays (590 gold against 430).
2. **A poor level of 13 is too harsh**: the two realms poor in food spend 14 months on the reduced ration and revolt.
3. **19 floods the market**: the price falls towards the floor and food is worth little.
4. Limit: the lab's policy sells everything above 2 months of food. Game 24's Treasurers kept their surplus unless the sovereign asked (draft rule 5).

### Lab: the village market, block A (2026-11-08)

`lab/village_market.py [base|why|cost|gold|timing|capacity|tax|mood]`: 8 realms on the 8 sites, 24 months, on the real engine (market, needs, levels of `engine/config.toml`); the lab adds the market building (center or houses zone), merchants off the fields, the lot cap, the trade tax and the merchants' mood with their ladder stopped at the strike. Fixed policy (trade up to 2 months of food, wood and stone for 4 months of needs and the next building, taxes to 5 % above 150 gold, a feast a season above 200, the market first). Results are near the edge: one realm more or less fallen is partly noise.

| Run | Fallen of 8 | Market open at month | Lots traded / cut by the cap | Trade tax, all realms |
| --- | --- | --- | --- | --- |
| No market | 4 | - | - | - |
| Old rule (open from month 1, no cap) | 0 | 1 | 917 / 0 | - |
| 60 wood 40 stone, 2 months | 6 | 5-7 | 540 / 68 | 73 |
| 100 wood 60 stone, 2 or 3 months | 6-7 | 5-12 | 470-500 / 75-105 | 45-50 |
| **80 wood, no stone, 2 months** (6 jobs x 2 lots, tax 50 %) | **1** | 5-9 | 562 / 63 | 70 |
| 120 wood, no stone, 3 months | 4 | 7-8, two never by month 24 | 397 / 28 | 49 |
| 50 wood 50 gold / 40 wood 80 gold | 4 / 2 | 2 for all | 570-585 | 92-95 |

1. **Stone in the cost kills**: with 40-60 stone 5-7 realms fall. Diagnosis (`why`): the building alone, with no farmer lost and no cap, already makes 5 fall; a free market of one month none; 80 wood and no stone 1. The world is short of stone (price at the cap, 66) and the market takes the stone of the houses.
2. **80 wood, 2 months** opens between month 5 and 9, before the second winter. The realm poor in wood (F= W- S+) opens last (month 9), is cold 5 months and falls at month 17; with the old rule it held.
3. **Gold in the cost** makes everyone open at month 2 (they start with 100 gold): no longer a goal, and it does not save the realm poor in wood.
4. **Capacity**: 6 jobs x 1 lot cuts 25 % of the lots wanted, x 2 about 10 % (mostly the rich lands selling), x 3 7 %. 6 x 2 chosen.
5. **The trade tax is tiny**: at 50 % of the own margin about 70 gold in two years for 8 realms, 0.4 gold a realm a month. Symbolic, not "the first income that is not from the fields".
6. **Merchants' mood**: 7 months without trade (realms 1-4, months 12-18) bring one realm of four to the strike (3 months), the others to 317-380. In falling realms the merchants reach 0: they take the peasants' shocks (cold, famine) in full and recover 2.5 times slower.
7. **No room for the market**: with the market allowed only in the center, houses filled the center first and two realms never built it. The lab allows the houses zones too.

### Lab: the village market, second run (2026-11-08)

Same lab, with the decisions taken after the first run: the merchants' own tax on the gold value of the month's trades (no ordinary tax for them), famine and cold shocks at half for the merchants, idle malus -250, the market on a reserved place (the palace's reserve stands in for it), and the policy buys no more than the warehouse holds (the first run asked blindly and spent the merchants' lots on empty shelves). Lots are now counted as asked and as really filled.

| Run | Fallen | Lots filled (all realms, 24 months) | Value traded (gold) | Merchants' tax | Merchants' strike months |
| --- | --- | --- | --- | --- | --- |
| Old rule, open from month 1 | 0 | 185 | 1937 | - | - |
| Tax 0 % | 3 | 106 | 1237 | 0 | 13 |
| Tax 10 % | 3 | 104 | 1225 | 115 | 17 |
| Tax 20 % | 2 | 110 | 1258 | 247 | 60 |
| Tax 30 % | 3 | 102 | 1176 | 343 | 77 |
| Capacity 6 x 1 / x 2 / x 3 (tax 10 %) | 3 / 3 / 3 | 100 / 104 / 122 | 1123 / 1225 / 1419 | 96 / 115 / 133 | 9 / 17 / 21 |

1. **The world trades little**: even with the old rule about 1 lot a realm a month changes hands (about 10 gold of value), because the warehouse is empty most months (the world is short of food and stone). With the market as a building about 0.5 lot. Ordinary taxes bring about 30 gold a month.
2. **So any tax on trade is small in the village**: at 10 % about 0.6 gold a realm a month; at 20-30 % 1.3-1.8 gold, and the merchants strike 60-77 months out of 192.
3. **The merchants are angry mostly because the warehouse is empty** (the idle factor), not because of the crown: 13 strike months even with no tax.
4. **Capacity**: with sensible buying, 6 x 2 cuts about a quarter of the lots asked (mostly sales of the rich lands); 6 x 3 cuts a sixth and fills 17 % more.
5. Halving the shocks changed nothing in the idle test (the realms that fall are the same, poor in wood).
6. One realm more or less fallen moves with any small change: the falls (2-3 of 8, always poor in wood or food) are near the edge with this policy.

### Lab: the village market, third run (2026-11-08)

Values chosen: 80 wood, 2 months, 6 merchants x 3 lots, merchants' tax 10 % with no complaint up to 10 %, idle malus -250 only when goods were on sale and the realm traded nothing, -80 when the warehouse was empty for everyone, shocks at half.

- At 10 %: 3 of 8 fall (poor in wood or food, as in every run), 122 lots filled, 128 gold of merchants' tax in two years, 11 strike months: in the realms poor in food (the reduced ration weighs on everyone) and in one poor in wood.
- Realms 1-4 kept idle in months 12-18: two of them strike 6-9 months, one does not.
- 80 wood + 10 stone: 2 fall instead of 3 (inside the noise); kept at wood only.

### Game 25: three automatic sovereigns (2026-11-08, 12 months, $0.21)

`lab/auto_game.py new 0 12`, seed 0 as game 24: Aurelia F+ W= S-, Brenna F- W+ S=, Corvara F= W- S+. Every realm played by the rules R1–R9.

1. **Nobody fell, every realm calm all year.** The rules caught what Claude caught in game 24: Corvara's Chancellor taking 52 farmers off the fields in February (R2), claims in winter (R3), farms with 14–24 empty jobs (R8), tax cuts below the costs (R6).
2. **The market was hardly used**: 9 trade events in 12 months, one sale by a realm (Brenna's lot of food in November, bought by Corvara the same month). A short lot of 45 food was sold in June (the new rule works).
3. **Aurelia, rich in food, piled up 1858 food and never sold it**: R5 sells only when gold is short, and Aurelia's 67 gold covered 3 months of costs. Brenna, poor in food, ended on the reduced ration. Open: a rule to sell a surplus anyway.
4. **Two defects of the rules, fixed**: R4b counted the next 4 months of firewood, so from April to July every wood purchase was "useless" (wood now counts to the end of the next winter); R5 told Brenna to sell the wood its own plan was buying (a good the plan buys is no longer sold). Brenna's Treasurer refused that directive on its own, with the right reason.

### Game 26: three automatic sovereigns on the hex grid (2026-11-08, 12 months, $0.22)

`lab/auto_game.py new 0 12`, seed 0 as games 24 and 25, the first game on hexes (realms 32-34). 217 calls, $0.22 (game 25: $0.21).

1. **The hex briefing works in real meetings.** Architect: 48 calls, 1,970 output tokens on average, 4,394 at most (cap 10,000), 13.8 s on average, 40 s at most; one timeout (Corvara, month 5) out of 48. No reply cut by the cap. The other counsellors as before (Treasurer one invalid reply).
2. **The map was used little, but right**: 4 builds (a farm in every realm's Campi, Corvara a second sawmill in Botteghe del bosco), all accepted; Brenna felled 4 forest hexes and claimed 2 plain hexes to the north. No town plan redrawn (game 25 on squares: 3 builds, 2 claims). One refusal: Aurelia in May claimed 4 tiles "in Campi", a zone already all owned (`NO_LAND`): the briefing does not say a zone has nothing left to claim, and the craft's "first draw the zone beyond the border" was skipped.
3. **Nobody fell, all calm all year.** The map pages draw the SVG board for the three realms.
4. **R5b never fired**: Aurelia ended with 2,626 food and sold none. The rule keeps 4 months of *gross* eating (about 900 food a month, so 3,600) before selling; Aurelia never got there. Brenna and Corvara ended on the reduced ration. To decide: keep months of net need (eating minus expected harvest) or a lower number.

### Game 27: the village market, three automatic sovereigns (2026-11-09, 12 months, $0.27)

`lab/auto_game.py new 0 12`, seed 0 as games 24-26 (realms 35-37: Aurelia F+ W= S-, Brenna F- W+ S=, Corvara F= W- S+), with village block A (steps 2-4). 225 calls, $0.27 (game 26: $0.22), some of them a meeting of the fallen Brenna in month 12.

1. **The councils built the market on their own**: Brenna in January (open in March), Aurelia in May (July), Corvara in July (September); R10 never had to order it, it only staffed Aurelia's (month 7). All before the second winter.
2. **Merchants**: Aurelia 3, Brenna 1-2, Corvara 6 (all the places: 6 farmers less, for 2 lots in 3 months).
3. **Little trade, as in the lab**: Brenna bought the start stock's food (6 lots, months 5-6), then the warehouse had no food from month 9 to the end: nobody sold any. Aurelia, rich in food, opened only in July, kept the abundant ration from July and sold no food (R5b keeps 2 months of eating). Aurelia 5 lots in all, Corvara 2.
4. **Brenna fell (revolt, month 11)**, the first automatic realm to fall: poor in food, food 0 from June, buys refused for lack of food in the warehouse. Not only block A: its Treasurer set the abundant ration in July with no food (R2 excludes only from October to March), and in game 26 Brenna lived on the reduced ration. But with the market open from month 1 Aurelia would have had more months to sell.
5. **The merchants' tax went to 0 in all three realms by month 11** (two first to 5 %), though up to 10 % it costs no mood. It yielded almost nothing anyway.
6. **Merchants' mood**: Aurelia's and Corvara's 450-510, calm; Brenna's followed the famine down to the strike (month 11).
7. **Two defects, fixed**: the automatic sovereign played a fallen realm (meeting paid, then a 500 from the petition check): now it skips it. R7 told Brenna to buy wood the month its market opened, with no merchant yet (`TRADE_CAPACITY`): R7 and R5 now ask no more lots than the merchants can handle.
8. To decide: the food of the world (nobody sells food: R5b, or the Treasurer's craft, or a start stock of food that lasts longer), the abundant ration with no food outside winter (an R2 for every month?), the merchants' tax that Treasurers cut to 0 for no reason.

### Lab: bandits, block B+C (2026-11-09)

`lab/village_bandits.py`: 8 realms on the 8 sites, 24 months on the real engine with block A; flight, the pool, raids and the militia run on top after each month. Fixed policy of `lab/village_market.py` (ration, gold, trades), the market first, then the watchtower, 3 merchants.

1. **The baseline had to be fixed first**: with 4 woodcutters the realms poor or fair in wood froze in the second winter and 3 of 8 fell with no bandits at all. Now 6 woodcutters, twice the hands on a poor resource: no realm falls, no cold. Still a fragile world: realms spend 4-12 months of 24 on the reduced ration, mood 300-350 in the second spring, so a small push tips them.
2. **Flight below 300 came too late**: the ladder starts at 350 (protests after 2 months, revolt after 6), so a realm in crisis (25 % tax) revolted at month 8 with 2 adults gone. Now **below 350 for 3 months, 2 % of the adults and 1 % of the children a month**: 3 adults leave a crisis realm before its revolt, and calm realms lose a few in a bad spring.
3. **Spirals: at 3 % after 2 months the world spirals** (pool 10 -> 33, 5 realms of 8 fall); at 5 % pool 59, 7 fall. At 2 % after 3 months the pool stays 6-16.
4. **The start pool (5-15)**: about 1 raid a realm a year, about 200 food each (a quarter of a month's eating); the pool shrinks slowly to 2-7 in a serene world (seed 1: 7 -> 1). 10-25 felt heavy (41 raids, 8,300 food). The decline needed an accumulator (5 % of 10 rounds to 0).
5. **The militia works and costs**: 4 guards (repel 2 raiders each) repel half the raids or more, the loot falls from 7,250 to 2,100 food and the pool starves (13 -> 2-7); 2 guards repel nothing (parties of about 10) but cut the loot by 40 %. The guards' food (4 farmers, about 64 food a month) costs as much as the raids they stop in a quiet world: the tension the design wants.
6. **Bandits tip fragile realms**: with 2 realms in crisis and no guards, 4 realms fall instead of 2 (the others in the second spring, mood about 300, after 700-1,000 food lost); a rich realm with no guards is raided most (14 raids, 2,700 food).
7. Values for the engine: flight below 350 for 3 months, 2 % adults, 1 % children; start pool 5-15; decline 5 % a month, 10 % in winter, +30 % of the food missing; parties of 8, 25 units a raider, 2 raiders stopped by a guard, each guard 10 % less attractive (max 80 %); watchtower 40 wood 20 stone, 2 months.

### Lab: the doors and acceptance, block B+C stage 2 (2026-11-10)

`lab/village_migration.py`: 8 realms, 24 months, on the real engine with stage 1 (`engine/bandits.py`) and the bandits lab's fixed policy; acceptance, raids turned into immigration and the grumbling run on top. Realms 1-2 in crisis (tax 25 %) in most runs.

1. **The baseline needed a kinder tax**: with the bandits lab's gold policy (5-10 %) the realms sat at mood 310-370 and fell by chance, and almost nobody reached the unrest threshold to draw anyone. At tax 5 the 6 healthy realms stay calm (lowest 344-397); only the 2 crisis realms fall. The stage-1 lab gives the same numbers at its own commit (no regression).
2. **The world's pool is tiny, so is migration**: about 13 wanderers for 8 realms, shrinking; the crisis realms revolt in month 8 having lost 3 adults each (flight is slower than revolt). Arrivals over 24 months: 4-14 adults for all 8 realms (about 1 a realm a year), almost all from raids stopped by guards at open doors. Free beds are not the limit (houses keep 10-20 free).
3. **With a bigger stream (a lab inflow of 4-10 wanderers a month) the first values break**: open doors took 20-47 raiders a realm, the grumbling (10 mood a 1 % arrived) toppled 3 of 6 open realms; the search for a home never found a realm with 2 months of food (almost every arrival came from raids).
4. **Tuned values**: seek 10 % of the pool a month; a realm draws people with 1 month of food (not 2); stopped raiders kept 25 % at normal, 50 % at open (not 90); grumbling 4 mood a 1 % arrived, only in scarcity; closed doors need 2 guards. With them, no realm falls beyond the crisis ones at inflow 0 and 2; open realms grow 60 -> 80-95 adults against 74 closed, with 0-56 mood of grumbling; a fragile open realm (poor wood) protests.
5. **No spiral**: a rich realm does not absorb the others' people (the crisis realms fall by revolt long before their flight counts); closed doors with 4 guards are the safe choice, open doors a bet on growth.
6. **The stream decides whether stage 2 matters**: inflow 0 (today's world) 6-14 arrivals in 24 months; inflow 2 a month (for 8 realms) 29-52, raids 53 instead of 21 without watchtowers and no extra fall; inflow 4 without watchtowers 5 realms fall to raids.
7. **Decided 2026-11-10: no inflow**, the world stays as it is (start pool plus flight); stage 2 stays a small effect. The tuned values of point 4 go into the DESIGN brackets.

### Lab: the people of a fallen realm (2026-11-11, after game 34)

`lab/village_fallen.py`: 8 realms, 30 months, the real engine with stages 1 and 2 and the policy of `lab/village_migration.py`; realms 1-2 in crisis (tax 25 %) fall at month 8. On top, the month a realm falls, a share of its adults (half that share of its children, 25 % of its food) joins the pool; or, as "refugees", first looks for a home with the engine's room and only the homeless go to the woods. Three worlds (no watchtowers; watchtowers with 2 guards; 4 guards with realms 3-5 open, 6-8 closed), pool seeds 0-2. Today: the six other realms go from 360 to about 470 adults, 8-15 arrivals in all.

1. **25 % or more to the woods spirals**: 50 % and 75 % topple 6 of the 6 other realms in most runs without 4 guards each (pool peak 150-300, 100-260 raids); 25 % topples one more realm in 2 of 3 seeds without watchtowers.
2. **10-15 % to the woods holds** in the worlds without and with 2 guards (no extra fall in 6 of 6 runs each): raids +50 % (17-31 against 11-20), arrivals about double (15-29, half of them stopped raiders where there are guards), growth almost none (+4 to +10 adults for six realms).
3. **Refugees grow the neighbours but the lump topples the fragile one**: 30 of 37 settle at once (25 %), 67 of 77 (50 %); without watchtowers +25 to +55 adults for six realms with no extra fall at 25 %; with watchtowers realm 3 (fair food, poor wood) falls at month 19-20 in every run: the natives' grumbling for a mass arrival in scarcity (4 mood a 1 %) and the extra mouths.
4. **Realm 3 is the fragile one** in the open-doors world even today (falls in 1 of 3 seeds with nobody joining the pool).
5. **Reading**: the fallen realm's people make bandits matter at 10-15 %; as a growth engine they need to arrive slowly (or with a softer grumbling), not in one month.

### Lab: the village in three years (2026-11-11, after game 34)

`lab/village_years.py`: each of the 8 sites alone for 36 months on the real engine (no market, bandits, arrivals or council), a careful fixed policy: ration by the food's months, the lowest tax that covers the costs, quarry and sawmill hands sized to the upkeep and the next winter's firewood, every other adult on the fields, a farm when the fields are full, a house when fewer than 10 beds are free. Then one lever at a time.

1. **Today every site stands 36 months**: no famine, no stone short, no cold, all calm. The poor-food sites spend 3-6 months a year on the reduced ration with the lowest mood at 358-367, just above the threshold (350). So game 34's falls came from choices, the automatic rules and the outages, not from the economy.
2. **Growth is flat and the same everywhere**: 108, 116, 124 people at the end of each year (births +11, +13, +14; deaths 3-6); 120 at month 30. Births depend only on adults; the mood never goes below 300 or above 700, so it never changes them.
3. **A, births +50 % (22 per 1000 adults)**: 135 at month 30, 144 at month 36; the poor sites touch the protests once (mood 346).
4. **B, the birth bonus from mood 550**: no effect; the policy's mood never goes above about 506 (base 500, almost every factor negative; only the abundant ration, reserves and feasts lift it).
5. **C, stone upkeep halved, and D, food yields +1**: no growth; more comfort (fewer reduced months, mood up to 440-506, bigger stocks). D gives the poor sites a year 2 without the reduced ration.
6. **E, start food +1000**: changes only year 1 (no reduced ration); from year 2 as today.
7. **No lever reaches the gate of about 200 by month 30**: it would take about 3 times today's births. Population is also near the core's room (5-6 farms, 8-9 houses): growth beyond needs claims.
8. **Combinations** (`combos`): growth follows the births only (A+D, A+C, A+C+D: 135 at month 30). D removes A's fragility: with A+D no poor site touches the protests (lowest mood 353-364); A+C does not (346).

### Lab: the second winter (2026-11-11, after game 37)

`lab/second_winter.py`: each of the 8 sites alone for 24 months on the real engine with the careful policy of `lab/village_years.py`, then game 37's conditions one at a time (the people's effort and births from the mood band, tax 7 or 10, R2's ration rule, three raids of 225 food in year 1, 8 adults off the work from April standing for guards, traders and clearers), all together, then one lever at a time on all of them.

1. **No condition alone makes the spiral**: people, tax 7 or 10, R2's rule, raids: 8 of 8 stand. Hands off the work alone: 6 of 8 (two poor sites revolt at months 23-24).
2. **All together reproduce game 37**: September food 326-924 (game 37: 29-576), 2 of 8 stand (the two sites rich in food), the others revolt at month 14 (game 37: 16-19, later because they bought food in summer while the warehouse had some). Trace of a fair site: with 8 adults off the fields there is no surplus even in summer, R2 keeps the reduced ration from April, the mood goes under 350 in September, protests in October, strike in December, revolt in February.
3. **The arithmetic**: the reduced ration's target mood is 500 − 150 − 10 per tax point above 5, so 330 at tax 7, and it reaches the threshold (350) only at tax 5. Six months in a row on the reduced ration with any tax above 5 is a revolt, whatever the granary holds. `lab/village_years.py` survived on the edge (lowest mood 349-358) only because its tax never went above 5.
4. **Levers on all the conditions** (standing of 8):
   - L1 reduced ration −100 (was −150): **8**, lowest mood 340-396, all calm.
   - L7 reduced ration −120: 4. L10 4 adults off the work instead of 8 (a policy): 4.
   - L2 tax at 5 while the ration is reduced: 2 (the revolt moves to month 17: gold runs short, the upkeep goes unpaid and output halves).
   - L3 feasts with the spare gold, L4 strike output 85 %, L5 winter farms 60 %, L6 a normal month at the protests, L8 revolt after 8 months under the threshold, L9 food yields +1: 2, nothing changes (L8 and L9 only move the fall: the strike harvest brings famine).
   - Without R2's rule (the careful 1 / 1.5 months): 0.
5. **Reading**: the second winter is not a winter problem. It is a village of about 60 adults that carries guards, traders and clearers with no food margin, plus a reduced ration that cannot last 6 months. L1 is the only engine lever that saves the realms; it also makes the reduced ration a state a village can live in (discontented: effort −12 %). Open decision "The second winter".

### Game 38: the seasonal sovereign, built (2026-11-11, 24 months)

Seed 1 and the same six realms and styles as game 37, now with `rhythm = "seasonal"` and the reduced ration at −100. Driver: scratchpad `season2.py` (asks `GET /realms/{id}/rhythm`; automatic months through `POST /realms/{id}/sovereign/auto`, which locks the laws). 1014 calls, $1.27 (cap raised to $3 for the game, back to $1); 21 timeouts and 17 invalid replies. Replay matches. **4 of 6 stand at month 24**: Aurelia 113 people, Corvara 111, Dalmora 119, Elsina 116; Brenna fell in month 18, Fosca (hands-off) in month 22. Game 37: 1 of 6.

1. **The rhythm holds**: 5 played realms, 39 season months and only 9 alarms in 24 months (game 37: 14 alarms, nearly monthly in year 2). No alarm from month 4 to month 14; in year 2 alarms came only where a realm was really in trouble (Brenna 3, Aurelia 2, Corvara 1, Dalmora 1).
2. **R12 works and is needed**: 26 law items excluded in automatic months (ration, tax, doors, merchants' tax); the counsellors keep proposing laws every month, also against the season's choice.
3. **The second winter passed without the spiral**: in December of year 1 moods were 399-472 (game 37: 303-444, four realms under 320), all calm. The protests of year 2 came from other causes: Brenna's cold (firewood short in January) and Corvara's short famine.
4. **The season's ration is a real decision**: Corvara (normal to January) and Dalmora (normal all winter) had a 2 % famine in March and came back. One month of hunger, as the spec expected.
5. **Petition refusals pile up in realms short of food**: Aurelia (5 farms on a poor site) and Brenna (4 farms) could not pay the normal ration in any season of year 2, and the people asked for it at every sovereign month: each refusal −30. Brenna fell from that plus the cold, a strike in April (ministers absent that month) and famine. Brenna's Treasurer: "coi campi di oggi nessuna stagione regge il pane pieno". The realms grew to 108-114 people with the farms of month 1: R8 keeps excluding farms while farm jobs are empty, but the jobs are empty because the hands are on guard, at the market and in the forest.
6. **Fosca (hands-off) shows the lock's limit**: granting every petition gave it the abundant ration with no food, locked for a season; it fell in month 22.
7. No realm reached the gate's population (about 120): Dalmora 119.
8. Driver mistakes, not the game's: Fosca's April of year 1 resolved without orders (the hands-off branch skipped the meeting); Brenna's tax went to 15 % in month 18 (plan approved whole, the realm already lost).

### Game 37: six realms, a seasonal sovereign (2026-11-11, 24 months)

Seed 1 (realms 67-72). The seasonal sovereign simulated with a driver (scratchpad `season.py`): the council meets every month and the automatic sovereign (R1-R11) approves; Claude plays a realm only in the first month of a season (1, 4, 7, 10, ...) or after an alarm in its last month (famine, a raid not repelled, flight, strike or revolt). Styles: Aurelia careful (mandates on wood, stone, ration), Brenna open doors, Corvara firm tax (10 %), Dalmora the trader, Elsina strong militia, Fosca hands-off (plans approved as they are). Weekly engine steps were considered and rejected the same day (they make the simulation finer, not the game faster; the whole config is monthly). The persona catalog went to 8 moderates per role for this game. 868 calls, $1.17 (cap raised to $4, back to $1). Replay matches. **Five of six fell**: Elsina month 16, Aurelia and Corvara 17, Fosca 18, Brenna 19 (all revolt); Dalmora stands with 129 people at month 24.

1. **The seasonal rhythm holds in calm, not in crisis.** 39 season decisions and 14 alarm decisions over 144 realm-months, 8 directives. From April to December of year 1 almost no alarm (the early raids only); from January of year 2 flight and strike called the sovereign almost every month in every realm: the seasonal sovereign becomes monthly exactly when it matters.
2. **Petitions in the automatic months undo the season's laws.** R1 granted 13 petitions without the sovereign (tax 7 % four times, the normal ration six). Corvara's 10 % (a mandate, then a directive) was brought back to 7 % three times; the automatic sovereign does not read mandates. Brenna's normal ration granted in February of year 2 ("il cibo basta") led to famine in March.
3. **Without a sovereign the ministers set heavy laws.** Fosca's Treasurer raised the tax to 25 % in an automatic month and nothing excluded it (no rule bars raising a tax); Gastaldi proposed closing the doors month after month in spring of year 2.
4. **The spiral of the second winter, again** (games 27, 28, 34, 37): the reduced ration from October filled the granaries (Dalmora 1573, Brenna 1485 in January) but brought mood to 230-300 by March; strike halves the harvest (Aurelia 428 in April against about 800), famine, revolt. Refusing the normal ration was right on the numbers every time and fatal every time. From October of year 1 the world warehouse had no grain to sell: buying was never a way out.
5. **The survivor is the realm that never cut the ration for long**: Dalmora (the trader) entered winter with the most food, went back to the normal ration in January (petition granted), stayed calm all game, and grew to 129 people. It grew from the fallen: the fallen realms' people joined the pool, raided Dalmora twice a month, its 5 guards repelled them and stopped raiders settled (1-4 a month). The first realm past the gate's population (about 120). R5 sold its food every month the gold was under 3 months of costs (tax 5 %).
6. **Mandates work on the counsellors**: the market waited for spring (Aurelia), towers came first (Brenna, Elsina), Brenna's Gastaldo kept the doors normal under one month of food as its mandate said. The chancellery rejected a trade mandate for the Treasurer before the market existed (right: no trade order yet).
7. Raids: the pool stayed at 3-9 adults until the falls; with towers almost every raid from August on was repelled. Elsina's Treasurer was absent twice (invalid replies).

### Game 34: three years with studied choices (2026-11-10/11, ended at month 26)

Seed 0 (realms 56-58). Claude as sovereign through a driver (my choices first, then the automatic sovereign R1-R11 for the rest; some months approved by hand). Stimuli: Aurelia "open doors" (tower early, doors open, later a golden age: tax 5, abundant ration), Brenna "the merchant" (buy food, sell wood), Corvara "the repentant tyrant" (tax 25 %, petitions refused, then a feast). 453 calls, $0.53 (cap raised to $3 for the game, back to $1). Replay matches. **All three fell**: Brenna month 11, Corvara month 18, Aurelia month 26.

1. **Brenna fell (revolt, month 11)**, the third time in 8 games (27, 28, 34) for the same reason: the reduced ration from April, six petitions for the normal ration refused by R1/R2b ("the food would not reach spring"), effort -25 %, strike, revolt. In month 10 the people made no petition (exhausted), so my "grant" had nothing to grant, and R2b excluded the Treasurer's own normal ration; in month 11 the Chancellor raised the tax to 12 in the strike.
2. **The repentant tyrant works**: one month at 25 % (mood -30), then in month 10 the normal ration and a feast of 100 gold paid with the tyranny's gold: protests to calm in one month (274 -> 393). Corvara then fell in the second winter: reduced ration, stone at 0, strike, famine in May-June (20 dead), revolt in June. Its April meeting was void (network outage, below).
3. **Ministers undo the sovereign's directive the next month**: Aurelia's Gastaldo opened the doors in April and set them back to normal in May; Corvara's Treasurer brought the tax from 25 to 12 a month after "it stays there until I say otherwise"; Corvara's merchants' tax 30 % back to 10 the next month. Aurelia's Treasurer answered "obbedisco: la gabella scende al 5" with no `set_tax` in the plan. **Mandates held** (the doors stayed open from month 7 to the end). The sovereign sees none of this unless reading every order.
4. **Stone upkeep short halves every building, farms included**: the hidden killer of Corvara and Aurelia (stone 0-4 for months, fields at half). In October of year 2 Aurelia's Architect proposed the cure (8 hands to the quarry: "il raccolto torna intero") and **R2 excluded it** (no farmers off the fields in autumn and winter). R2 does not know the stone.
5. **My golden age was a blunder the game punished readably**: abundant ration in July with stone 13 against 15 of upkeep; the Architect warned in council; famine from August (9 %, 35 %, 16 %), mood 482 -> 185 in two months, while the square was happiest ("i bambini ridono al pozzo") the month the granary hit 0. The content band (mood above 550) was never reached in the whole game (max about 510).
6. **Network outages pass the month with an empty council**: "Temporary failure in name resolution" (Corvara month 16, 15 calls) and "Network is unreachable" (Aurelia months 20-21): ministers "absent", plan empty, the month resolved anyway. Two of the three falls had a void month near the end.
7. **Stage 2 seen for the first time**: a raid of 2 repelled at Aurelia's open doors in month 24, one raider stayed (grumbled). Arrivals in 26 months: 3 adults (Brenna 5, Corvara 12, Aurelia 24). Flights: about 10 adults in all. **A fallen realm sends nobody to the pool**: 103 people at Brenna's fall, 85 at Corvara's, vanish.
8. **The court is alive**: Corvara's Treasurer bargained 25 -> 15 ("vi consiglio misura"); its Chancellor in audience: "la corda è già tesa... meglio un granaio pieno e un popolo che lavora che uno scrigno con dentro una rivolta"; Brenna's Treasurer: "le parlo da mugnaia, non da cortigiana". Several reports with English words ("however", "autosufficient") and broken words.
9. **The second winter is the wall**: in March of year 2 Aurelia had 51 food and Corvara 12; nobody grew past 112 people (gate about 200). The start stock carries year 1; year 2 shows whether the realm feeds itself, and none did under these choices.

### Game 33: stage 2 with the accumulators (2026-11-10, 12 months)

`lab/auto_game.py new 0 12`, seed 0 (realms 53-55: Aurelia, Brenna, Corvara). 242 calls, $0.29; 4 timeouts and 1 invalid reply, no server error. Replay matches.

1. **Nobody arrived again, now for hunger, not rounding.** The accumulator worked: the pool (5 adults, then 3, 2, 1, empty from month 9 by its decline) produced one seeker in month 6. No realm drew him: a month of eating is about 900 food and in spring and summer all three held 100-700 (`min_food_months` 1). Aurelia had room from month 8 (1,030 food, 15 beds), when the pool was down to 1 wanderer.
2. Only one raid: 2 raiders on Brenna in March, no guards, 50 food. Brenna ordered the tower in April, finished in May, 4 guards from June (3 from October); Corvara's tower finished in December; Aurelia built none. No Gastaldo proposed any doors.
3. All three calm at year end; Brenna on the reduced ration (829 food).
4. **Reading**: in a 3-realm world the start pool (5) only shrinks (no inflow, decided) and in the warm months the realms eat what they grow, so stage 2 stays almost silent. **Decided (2026-11-10): accept it**: small worlds stay quiet; more realms, or flight from long discontent, fill the pool. No inflow of wanderers. To verify with a bigger game.

### Game 32: block B+C stage 2, the doors (2026-11-10, 12 months)

`lab/auto_game.py new 0 12`, seed 0 (realms 50-52: Aurelia, Brenna, Corvara). 251 calls, $0.31; 9 invalid replies and 4 timeouts, no server error. Replay matches.

1. **Nobody arrived all year, in any realm.** The pool started at 5 adults and was at 0-2 from month 2 (one raid of 2 on Aurelia in March, one of 2 repelled at Brenna in August, 2 adults fled from Brenna). The seekers are 10 % of the pool rounded down: with fewer than 10 wanderers nobody ever looks for a home. The stopped raiders who stay are 25 % rounded down: of a band of 2, none. In a 3-realm world stage 2 does not happen at all (the 8-realm lab had a pool of about 13: one seeker a month).
2. **Two towers, two Gastaldi, the doors understood**: Aurelia's tower finished in May (6 guards from July), Brenna's in June (4 guards); Corvara built none. Both Gastaldi proposed "set_doors normal" every month from August, dropped as no change; their reports weigh the doors well ("con la piazza in protesta nessuno viene a stabilirsi, e aprire ora non porterebbe che mormori"; "con 27 posti vuoti e 14 letti liberi chi viene può mettersi al lavoro"). Nobody tried open or closed. One Aurelia report has English words mixed in (the model, not the prompt).
3. Brenna ended in protests on the reduced ration (1,045 food), Aurelia and Corvara calm.
4. **Decided: accumulators** (2026-11-10) for the seekers (the pool's `seek_acc`) and the stopped raiders (the realm's `keep_acc`, snapshot format 7), as flight has: a pool of 5 sends one seeker every second month, a band of 2 leaves one every second raid. `[migration] accumulate`, false in games saved before: game 32 replays unchanged. The lab keeps rounding down (its values are unchanged: the accumulators only add the lost fractions). Next: a game to see the first arrivals.

### Game 31: block B+C (2026-11-09, 12 months)

`lab/auto_game.py new 0 12`, seed 0 (realms 47-49: Aurelia, Brenna, Corvara). 229 calls, $0.24. No errors.

1. **Two towers, two Gastaldi, all chosen by the councils**: Brenna (raided in March, 2 raiders, 50 food) ordered the tower in April (too little wood), again in May, finished in June; its Gastalda Ermengarda Valli sat from July. Aurelia, never raided, built it in September, finished in October, its Gastaldo from November. Corvara asked in April without the wood and never again. R11 never fired (the councils came first).
2. **The Gastaldi kept the guards all year, in a world without bandits**: Brenna 4 guards from July, 5 from October; Aurelia 4 from November. The pool started at 5 adults and was empty from month 9 (one raid in all); nobody fled, all three realms calm all year. The Gastaldi said so themselves ("la porta è quieta da sei mesi") and kept the guards for the full granaries before winter.
3. **The guards cost Brenna, the realm poor in food**: 4-5 farmers less from July (about 60-80 food a month); Brenna ended at 963 food on the reduced ration in December (Aurelia 1,790, Corvara 1,583, normal ration).
4. **The Gastaldi's reports are in character and use their briefing**: the stores in view, the raid of March, the guards against a party of 8, winter's months; Brenna's Gastalda backed the people's petition against the 12 % tax ("chi fugge nel bosco diventa poi la razzia").

### Game 30: block B+C, void (2026-11-09, 12 months)

`lab/auto_game.py new 0 12`, seed 0 (realms 44-46: Aurelia, Brenna, Corvara).

1. **Void: the automatic sovereign crashed (HTTP 500) in 8 realm-months** (Aurelia 6-9 and 12, Brenna 5, 6 and 8). R8 ("already N empty places") looked up the jobs of the watchtower's sector, which is empty (`AttributeError: 'Workers' object has no attribute ''`), whenever the Architect put the tower in the plan. Those months the realm gave no orders. Fixed: R8 skips a building with no jobs and no beds; a test.
2. **So no watchtower and no Gastaldo**: the Architects of Aurelia (from month 5) and Brenna (months 5-8) proposed the tower every month, both before any raid on them.
3. **Almost no bandits**: the pool started at 5 adults (5-15 scaled to 3 realms of 8), one raid of 2 raiders on Aurelia in month 3 (50 food), and it was empty from month 9. Nobody fled: all three realms stayed calm all year.
4. Stores at the end: Aurelia 2,242 food, Brenna 1,316, Corvara 1,276; Aurelia sold 3 lots of food (R5b).

### Game 29: the food sale down to the next spring (2026-11-09, 12 months)

`lab/auto_game.py new 0 12`, seed 0 (realms 41-43: Aurelia F+ W= S-, Brenna F- W+ S=, Corvara F= W- S+).

1. **Aurelia sold food**: 2 lots in August (its Treasurer), then 4 a month from September to November on R5 directives, 14 lots in all, and still ended at 2,459 food on the normal ration, calm.
2. **Brenna, poor in food, stood**: the normal ration from February to November, calm all year (mood 412-504); December on the reduced ration with 656 food.
3. **Corvara fell (revolt, month 8), from the cold, not the food**: its council built the market in February with poor wood (111 wood, 80 for the market), firewood short in February and March (19 and 38 of 50), mood 502 -> 289, protests in April, the people's effort -12 to -25 %, famine in June, strike, revolt in August. R10 checks the firewood before ordering the market; a market the council plans itself is not checked.
4. **A defect of the new food sale, fixed**: Brenna was told to sell 4 lots in November and December with 459-519 food. Its plan cut the ration to reduced, and the check ran on the plan, so the food "lasted". The sale is now weighed without a cut to the reduced ration. Its Treasurer had said so itself: "con la vendita una razione piena non ci porta alla primavera".
5. The merchants' tax stayed at 10 % in all three realms.

### Game 28: R2b, the Treasurer's craft, food yields 15/16/19 (2026-11-09, 12 months)

`lab/auto_game.py new 0 12`, seed 0 as games 24-27 (realms 38-40: Aurelia F+ W= S-, Brenna F- W+ S=, Corvara F= W- S+).

1. **The new yields work for the rich and the fair realm**: Aurelia ended at 2,020 food on the normal ration all year (game 27: 779 on the abundant ration), Corvara at 1,152 (game 27: 601), both calm.
2. **The merchants' tax stayed at 10 % in all three realms** (game 27: 0 everywhere); Corvara's Treasurer even set it to 10 again.
3. **R2b fired three times**, on Brenna's plan for the normal ration (food not lasting to spring).
4. **Nobody sold food again**: Brenna asked 9 lots and got 6 (the start stock), Corvara asked 15 and got none. Aurelia had the food (1,400-2,000 from August) but its Treasurer never sold, and the sovereign's R5 (gold short from October: 25-47 gold) keeps 3 months of gross eating (about 2,800) before selling food, R5b 2. At about 1,425 food to reach spring, Aurelia had 600 or more to spare from October.
5. **Brenna fell (revolt, month 12)** with 736 food: 8 months on the reduced ration (May-December), the people's petitions for the normal ration refused (R1, R2b: the food would not reach spring), mood 500 -> 208. Its 6 merchants (6 farmers less, about 90 food a month) traded about 1 lot a month.

### Lab: the village's food balance (2026-11-09)

`lab/food_balance.py`: each of the 8 sites alone for 24 months on the real engine, no market, a fixed sensible policy (reduced ration below 1 month of food, every free adult on the fields, a farm when the fields are full). Why: in game 27 no realm ever held a month of eating in summer, so nobody could sell food.

1. **Aurelia's missing surplus was the abundant ration, not the land.** Seasons: winter (January-March) at 50 %, spring about even for a rich realm (+50 a month), the surplus comes in summer (120 %) and autumn (130 %), about +300 a month. Aurelia set the abundant ration in July and ate it; the lab's site 0 at the normal ration reached 3,500 food in autumn. R2b would have blocked that ration (578 food against 898 a month).
2. **The world ate more than it grew.** At 14/15/18 a year: rich +1,100, fair -800 (5 months on the reduced ration), poor -1,450; the 8 sites together -3,900. A fair realm: 53 farmers x 15 = 795 a month against 860 eaten. Trade could cover a third of the gap at most.
3. **Levers, one at a time** (first-year balance, fair / poor / rich): yields +1 (15/16/19) -190 / -800 / +1,730, world +1,100; yields +2 -> +460 / -190 / +2,400; adults eating 9 -> -90 / -740 / +1,840; autumn at 150 % -> -290 / -975 / +1,730. **Chosen: +1** (a fair realm about breaks even, a poor one buys about 16 lots a year, a rich one sells 30+); farms 16 per worker so the fair land still equals the farm's value.
4. Limit: two fair sites with poor wood or poor stone revolt in year 2 with no market to buy firewood and stone: a limit of the lab, not a result.

### Presentation page and map graphics (2026-11-08)

- **Presentation page** of the finished game: `docs/index.html`, live at https://alez22.github.io/AgentOfEmpire/ (GitHub Pages from `main` → `/docs`). Eleven chapters in Italian, click-to-open deep dives, a "where we are" section. The vision decisions it needed are in `docs/DESIGN.md` (victory paths, reputation, espionage, eras' names, seasons, battles). The game's name is **AgentOfEmpire**.
- **Gallery of graphic proposals** at the bottom of the page (temporary, to be removed once chosen): game-icons, Fluent Emoji, Phosphor; public-domain art (Lorenzetti, Très Riches Heures, Bruegel…); Kenney tiles, Watabou, Azgaar. About 6 MB in `docs/assets/proposals/`.
- **Map graphics decided** (DESIGN, "Territory" → "Map graphics"): **hexes with game-icons**, **night theme** (`lab/hex_map_mockup.py`, SVG, icons in `lab/assets/game_icons` with `AUTHORS.txt`). The same icon set will serve the UI panels. Explored and set aside: Kenney Tiny Town recoloured with our own pixel buildings and terrain (`lab/tiny_town_mockup.py`, `lab/pixel_*.py`).
- **Real hex grid in the engine**: spec in DESIGN ("Hex grid"), **approved 2026-11-08**: farm a 7-hex flower, quarry and square 4-hex rhombi; the palace later (its rhombus left free in the new core); old square games kept for replay and reading only (briefing and map page hex only). Footprints as steps in `config.toml` (`hex_steps`), new world files `world_hex.txt` / `core_hex.toml`, text grid with 4-character cells.
  - [x] Step 1, engine (2026-11-08): `[map] grid` ("square" when missing; still "square" in `config.toml` until step 2), `neighbours()`, `hex_distance()`, footprints walked from the anchor, packing in `find_place`, nudge to the 6 neighbours, directions on the 7/4 scale (`engine/territory.py`, `tests/test_hex_grid.py`). Square games unchanged (all old tests pass).
  - [x] Step 2, world and core (2026-11-08): `engine/maps/core_hex.toml`, `engine/maps/world_hex.txt` (`lab/draw_world.py --hex`), the palace's rhombus left free; room for 2 farms, 1 sawmill, 1 quarry, 14 houses; lab: same growth pace as on squares (first farm on new land in month 10). `config.toml` still square: new games go hex at the end of step 4
  - [ ] `lab/territory_balance.py` predates the needs: with firewood and stone upkeep its grower revolts in month 8 on both grids; to update if the lab is needed again
  - [x] Step 3a, first probe (`lab/hex_probe.py`, $0.05): 1 of 10 clean both by anchor and by zone; 6-8 of 10 run out of the 6000 output tokens reasoning on hex geometry (square control: 5 of 5 answered, 2 clean). To decide: a probe that mirrors the real briefing (room per zone from the engine, no neighbour formulas, a smaller task) before touching the briefing
  - [x] Step 3b, probe with a 24000-token cap ($0.04): 8 of 10 clean; typical reply 9,000 output tokens. The reasoning shows the cost is reading the shifted grid (recounting cells per row), a task the 2-hex ring cannot satisfy, and overlap checks by hand; hex geometry itself is right. Next probe: rows as runs with columns, wider ring, room per zone
  - [x] Step 3c, probe with rows as runs, room per zone, ring 4 ($0.02): by zone 5 of 5 clean, by anchor 4 of 5; output 600–4,700 tokens (was ~9,000). Room per zone is the big saving, runs another third. Decided for the briefing: runs, ring 4, room per zone, build by zone
  - [x] Step 3, briefing (2026-11-08): runs and ring 4 in `map_text.py`, `neighbours()` for frontier and forest warning, shapes in words, manual on both grids, prompts in words true on both grids; Architect output cap 10,000 (`[max_output_tokens_by_role]`), others 6,000 (`tests/test_hex_briefing.py`) (`map_text.py` still has its own 4-neighbour loops at the frontier and the forest warning), manual, prompts
  - [x] Step 4, map page (2026-11-08): SVG board for hex games (`server/ui/hex_board.py`), night theme, icon sprite (`lab/build_icon_sprite.py` → `server/ui/static/icons/`), credits page `/ui/credits`; the square view stays for old games. **New games are hex** (`config.toml`: `grid = "hex"`, `world_hex.txt`, `core_hex.toml`); square-grid tests use `square_config`
  - [x] Game 26, 12 months on the hex grid, three automatic realms ($0.22): the Architect's hex briefing works (output ≤ 4,394 tokens, ≤ 40 s, 1 timeout in 48 calls); see "Game 26"
  - [x] The briefing says when a zone has no land left to claim ("all its land is the realm's: nothing to claim here"; Aurelia's `NO_LAND`, game 26)
  - [ ] Map page: the lit zone's colour (fields #F2D27A) is close to the realm's gold border; pick zone colours for the night board

## Review: playability and originality (2026-11-10)

A reading of `docs/DESIGN.md`, the notes of games 1–33 and the pages of game 33. No new game was played. The proposals are in "Open decisions" (rows marked "review 2026-11-10"); nothing here is decided yet.

**Verdict**: originality is high in the court and in the information, conventional in the economy. Playability stands on good ground, but today the sovereign mostly approves the plan and corrects the council's mistakes. The recent work went almost all into the economy, the least original part.

**What is really new**

- **The mood hidden from everyone**: neither the sovereign nor the council sees it; only the Voice of the square reads it, puts it into words and may be wrong. The filter is in the database, not in the prompt.
- **The court as persons**: secret lessons (wrong ones too), secret notes, audiences where a counsellor speaks differently than in council, mandates rewritten by the Chancellor. Games 6 and 7 are the liveliest notes of this file.
- **Eras change the regime of information**: rumours, then communiqués that may lie, then independent journalism. The strongest idea of the design still to build.
- **Bandits born from discontent**: a neighbour's misrule becomes your problem, and accepting people is a common good paid by one.

**What is conventional**: food, wood, stone and gold; taxes, rations and feasts; the unrest ladder; three eras; four victories. Fine, as long as the economy stays the ground the court moves on and not the centre of the game.

**Playability findings**

1. **The sovereign is a proof-reader.** In game 24 almost every intervention is "excluded" (66 workers of 60, farmers off the fields in winter). Eleven fixed rules (R1–R11) carry a year with no model. In game 7, turns 21–30, the sovereign "only approved".
2. **Mistakes come from the model, not from character.** With moderate persons only there is no intrigue, and the notes make the council consensual. Every fix (manual, craft, briefing lines) moves the council towards an autopilot: the same tension as "gameplay over optimization".
3. **The new systems do not bite.** Each choice is well argued on its own; the sum is the problem: the market about 1 lot a realm a month; the merchants' tax 1–2 gold a month; bandits one raid a year of 50 food, the pool empty from month 9; the doors no arrival (games 32, 33); the people's effort −3 to +4 % except after a refused petition; the debate adds little without a conflict.
4. **The village has no engine of growth.** Population 100 → 120 in 30 months (game 7) against a gate of about 200 by year 2½; the immigration meant to fill the gap is silent.
5. **Pace.** A turn is about a minute of waiting and about 540 words to read (Brenna, June, game 33), and many months say only "born 1, dead 0". With the Marshal, the Ambassador and the Prior the text doubles. At a turn a day the village lasts over a real month with almost no interaction between players.
6. **The counsellors' Italian**: "quest'empo", "dei guardie", "territorial" in one month's reports; the Voice is good. In a game made of text it weighs a lot.
7. **Few human tests.** The only game played by a person is game 7 "Prova", before the map, the market and the bandits. A model playing the sovereign never gets bored.

**Risks for the town and the kingdom**

- **Holes in the design**: war, diplomacy, espionage and victory are the [Lost] sections, the very ones that carry the two eras.
- **A horizon never tried**: no game beyond 30 months, none with the market beyond 12, so no realm ever came near an era passage.
- **Breadth**: Prior, journalist, spies, double agents, coups, exile, Jev; every block of the village took a lab and several games.

## Open decisions

| Decision | Needed by | Notes |
| --- | --- | --- |
| Models per tier and spending cap for a long game | before a long game | since 2026-11-08 every counsellor and the people use GLM 5.3 Flash "high", the Voice DeepSeek V4.1 Flash "none". Game 18 measured about $0.0032 per turn: 120 turns about $0.40 per realm, about $3 with 8 realms |
| What the admin sees in games with others | phase 3, before the first game with friends | either the admin does not play, or in running games the view hides the other players' secrets |
| Thin trade | before the town | lab 2026-11-08 (village market): about 1 lot a realm a month changes hands even with the market open from month 1, because the warehouse is empty most months (the world short of food and stone). Any income from trade stays small; to look at with the rare resources and the town |
| Use of gold | phase 4 | the market lab (2026-11-08) shows a merchant with a stock and a dynamic price absorbs the gold; rules still to decide (stock size, margin, seasons, speculation). Other options considered: concessions during unrest, higher recurring costs, expensive goals |
| Tiles and workers | decided 2026-11-08 | answered by the territory (claiming, clearing, demolition; see `docs/DESIGN.md`); idle adults still open. Was: game 7: overbuilding with no staff and a housing dead end once tiles run out. Options: show the Architect unstaffed jobs, allow demolition, a way to gain tiles; also idle adults (extend the fixed rule to wood and stone, or leave them to the Architect) |
| Automatic sovereigns | phase 3 | personality, models, budget |
| Jev | phase 4 | technical details, policy schema, waiting-list sign-up |
| Lost vision sections | before phase 4 | rewrite the parts marked [Lost] in `docs/DESIGN.md` (map, war, victory, diplomacy, espionage); progress rewritten 2026-11-08 ("The eras"), war by era decided |
| Palace in the engine | phase 4, after the hex grid | fixed building east of the square (approved in direction); a 4-hex rhombus, its place left free in the hex core |
| A long automatic game (review 2026-11-10) | before the town | 8 realms, 36–48 months, about $3 at game 33's cost ($0.008 a realm a month): does any realm reach the gate of the town (population about 120 and the other conditions), do the market, the bandits and the doors come alive with 8 realms |
| A lab on extreme traits (review 2026-11-10) | before hiring and dismissal | same seed, extreme persons instead of the moderates: if the behaviour does not change in a way the sovereign can read, hiring and dismissal do not hold |
| The court before more economy (review 2026-11-10) | next block of phase 4 | bring forward variable trust and loyalty, hiring and dismissal, ahead of further economic systems |
| Pace (review 2026-11-10) | before a game with friends | the engine stays monthly (weekly steps rejected 2026-11-11: finer, not faster); the council meets every month under the mandates, the sovereign plays at the start of each season and on alarms. Game 37: calm seasons run by themselves, but petitions in automatic months undid the season's laws, a minister raised the tax to 25 % unchecked, and in a crisis the alarms called the sovereign every month. **Decided 2026-11-11 by the user**: the season's laws stay locked until the next season, only the sovereign changes a law; the rest left to Claude. **Built 2026-11-11** ("Seasonal sovereign" in `docs/DESIGN.md`), a game setting. Game 38: 9 alarms in 24 months, R12 excluded 26 law items, 4 of 6 realms stand. Still open: food for realms short of farms (R8 and the hands, game 38 note 5); how to keep the text readable with 7–8 voices; the length of the village |
| The temple draws converts (idea of the user, 2026-11-11) | with the temple (town era) | once the temple is built, religion also draws people to the realm: the share of stopped raiders who settle (and of bandits accepted at the doors) rises. Game 37: stopped raiders settling were the only real growth seen in the village (Dalmora, 129 people). To weigh with the clergy's other effects ("The eras", classes) and the Prior's demands |
| Tools: farms, sawmills and quarries improved in steps (idea of the user, 2026-11-12) | spec, then a game | the tech progress of the eras: each building kind improved in levels, the village's first, the later ones unlocked by the town's other areas. Why: in 38 games 4 realms built a second sawmill or quarry and none filled it; a building only offers jobs, 80-88 % of the adults stand on the fields, so more buildings add places, not output. `lab/village_tools.py` (2026-11-12, 8 sites, 36 months, game 38's conditions): a farm level of +25 % frees about 4 hands for good and pays back in about 6 months of hand-work; today's realm is about 6.5 hands short of feeding itself on the normal ration (22-24 of 24 months reduced in years 2-3 on 6 sites); at 60 wood 40 stone 20 gold the realms buy 1-3 levels in 36 months (the first in months 11-15) and never reach level 2; at half that price 2-6 levels from month 3, spare hands -6.5 -> +3.9; at double nobody buys. The bottleneck is stone (wood piles to 300-400, stone stays 50-100, the quarry 3-7 of 10 hands). Quarry tools first, or more hands saving in summer, cost the winter (5-6 of 8 stand): a real trade-off. People do not grow (116-124): births cap growth, tools only free hands. Limits: no market, a fixed order |
| Order of the town (review 2026-11-10) | with the rewrite of the [Lost] sections | first the Ambassador, treaties and rare resources, then the Marshal and war: the talk between ambassadors is where a model adds most, war where it adds least |
| Archives opened at game end (review 2026-11-10) | phase 4 | the mood curve, the lessons and the secret notes shown to the sovereign when the game ends; the admin view already holds them |
| A 12-month game played by hand (review 2026-11-10) | before the town | by the user on the current build, noting the minutes per turn and when it gets boring |
| The counsellors' Italian (review 2026-11-10) | with "Models per tier" | a better model for the text the sovereign reads; today's cost leaves room |

## Decisions made (the main ones)

- **The reduced ration costs 100 mood (2026-11-11, built; was 150):** with any tax above 5 % its target fell under the unrest threshold, so six reduced months were a revolt whatever the granary held (lab "the second winter": 8 of 8 sites stand with −100, 2 with −150). A hungry village can now last on it, discontented (effort −12 %). Chosen by Claude on the user's delegation; making the cost readable to the council (option b) left aside unless the next game needs it.

- **Seasonal sovereign (2026-11-11, built):** a game setting (`rhythm`): the sovereign plays the first month of each season and after an alarm (famine, a raid not repelled, unrest one step up, the first flight of a stretch); the other months the automatic sovereign approves the plan, the four laws stay locked (R12) and the people's petition is dropped (`docs/DESIGN.md`, "Seasonal sovereign").

- **Orders reversed by a counsellor (2026-11-11, built):** the turn page says under a plan item when it changes a law the sovereign decided in the last 3 months (tax, merchants' tax, ration, doors); information only (`docs/DESIGN.md`, after "Mandates").

- **A fallen realm's people (2026-11-11, built):** the month a realm falls, 10 % of its adults and 5 % of its children take to the woods with 25 % of its food (lab "the people of a fallen realm": 25 % or more spiralled). Slow refugees as a growth engine left to stage 3.

- **The gate of the town (2026-11-11):** a low population minimum [about 120] and the other conditions (a winter without hunger, the market, no revolt, the rare resources): good government, not a headcount (`docs/DESIGN.md`, "The eras"; lab "the village in three years"). Arrivals from fallen realms as the growth engine on top (spec to approve); births +50 % with food yields +1 kept as an option.

- **After game 34 (2026-11-11), built:** a council that no model can reach (every minister failing for a network error or a timeout in the first round) is not a meeting: nothing is stored and it can be held again; `lab/auto_game.py` stops before resolving. R2 lets farmers go to the quarry in winter while the stone covers less than 3 months of upkeep.

- **Language:** code, comments, prompts and this plan are in English. Player-facing text (UI, council replies) is in Italian, because the players are Italian for now.
- **Stack:** Python with FastAPI, PostgreSQL in Docker, handwritten SQL. UI with Jinja2 templates and HTMX, vendored in the project; we move to TypeScript when the map arrives.
- **Engine:** deterministic, integer-only, replay from the same seed. Each game stores a copy of its own config.
- **Approved rules:** building upkeep, seasonal farm output, food spoilage at 2% per month.
- **Council:** the engine always computes the numbers. Orders always go through the council, never through audiences.
- **Lessons:** at most 10 per council member, reasoned revision every season, no automatic forgetting. Secret from everyone, sovereign included.
- **Private audiences:** only words count. The other council members know only that they took place; a member may stay silent or embellish, but never change the numbers.
- **Mood:** a number inside the engine, read only by the Voice of the square. Neither the sovereign nor the council sees it: both know the people from the square's words and the public unrest level.
- **Security:** no open port on the router, access via Tailscale. The OpenRouter key lives only in `.env` and reaches only the server.

## How we work

1. **Spec first:** for every new part, a short spec in `docs/DESIGN.md` or in chat, and code only after approval.
2. **Minimal changes:** change only what is needed. No rewrites or unrequested abstractions.
3. **Tests always in Docker** (`docker compose run --rm tests`), with the fake client. Runs with real models cost a few cents and are done only when needed.
4. **At session end:** update the statuses in this file and the touched sections of `docs/DESIGN.md`.
5. **`.env` is never read or shared:** it holds the database password and the OpenRouter key.
6. **Language:** code, comments and this plan in English; text shown to players in Italian.

## References

- [Design](docs/DESIGN.md): reconstructed on 2026-11-07 after the Claude Docs original was deleted; parts of the game vision are marked **[Lost]** and need rewriting
- [UI mockups](docs/mockups/): copied from the [Design canvas](https://claude.ai/artifact/NnWtw9hteq18CxdFv8tBuc)
- Test games in the database: 1–7. Game 6 reached turn 10, with lessons and an audience.
