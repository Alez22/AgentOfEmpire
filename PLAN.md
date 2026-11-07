# AgentOfEmpire – Work plan

Updated 2026-11-07.

The prototype is complete and playable from a phone. The next phase is **playing it for real for 12–24 turns** and tuning values, prompts and UI.

This file is the starting point of every work session: read it at the start and update it at the end. The full design lives in [`docs/DESIGN.md`](docs/DESIGN.md), the UI mockups in [`docs/mockups/`](docs/mockups/).

## Where we are

| Part | What it does | Where |
| --- | --- | --- |
| Engine | deterministic monthly simulation: economy, seasons, food spoilage, demography, mood, unrest | `engine/`, values in `engine/config.toml` |
| Database | PostgreSQL 18.6 in Docker, 6 migrations, row-level security, append-only logs, replay | `db/migrations/`, `server/db/` |
| LLM council | Treasurer, Architect, Chancellor and Voice of the square on OpenRouter (DeepSeek V4.1 Flash for all); secret lessons revised at season end; private audiences | `server/council/`, settings in `server/council.toml` |
| UI | phone pages: games, turn, kingdom, chronicle, audiences; meetings run in the background | `server/ui/` |
| Admin | everything visible: full state, prompts, calls, costs, lessons, audiences, replay; per-agent page with system prompts, traits and last briefing | `server/admin/`, enabled with `ADMIN_VIEW=1` |
| Tests | 136 tests: engine, database, council with fake models, UI | `tests/` |

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

### 2. Field test – in progress

- [x] Play 12–24 turns from the phone and note what does not work (game 7, 12 months; see "Field test notes")
- [x] Fix the bugs found in the test: mood only to the Voice (the council hears the square), 90 s deadline on the whole call, 8000 output tokens cap, bad lesson actions discarded one by one
- [x] Voice of the square: only evident facts (court clearance, no granaries: the people only guess them), its own words of the last two turns, month windows aligned with the story; audience fact public, births and deaths court level
- [ ] Play again to check the fixes: no mood numbers in reports, no calls over ~90 s, lesson reviews applied, the square keeps a thread
- [ ] Decide on tiles and workers (overbuilding, housing dead end, idle adults)
- [ ] Tune engine values (food, taxes, mood)
- [ ] Review the council and square prompts
- [ ] Polish the UI after the test
- [ ] Choose models and spending cap for a 120-turn game

### 3. Before friends

- [ ] Invite-only accounts, login, admin role reserved
- [ ] Decide what the admin sees in games with other players
- [ ] Daily turn with deadline and confirmation from every player
- [ ] Absences, vacation mode, global pause, automatic sovereign
- [ ] Automatic database backups; database role without superuser privileges
- [ ] Meeting lock in the database, so the server can run as several processes

### 4. Full game

- [ ] More classes: artisans and merchants, clergy, soldiers; each with its own memory horizon in the square (peasants 2–3 months, merchants and clergy a year or more)
- [ ] Marshal and Ambassador
- [ ] Tile map and more states, automatic ones too
- [ ] Market, trade and diplomacy (they give gold a use)
- [ ] Espionage, war, revolts and coups; revolt as odds instead of automatic game over, weighed against soldiers, guards and propaganda (a militarised regime as a real choice with its own risks: cost, army mood, coups)
- [ ] Eras, variable trust and loyalty, leaks
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

## Open decisions

| Decision | Needed by | Notes |
| --- | --- | --- |
| Models per tier and spending cap for a long game | end of phase 2 | today all roles use DeepSeek V4.1 Flash with reasoning `low` (the Voice `none`). Game 7 measured about $0.02 per turn: $1 lasts about 50 turns, 120 turns need about $2.40 |
| What the admin sees in games with others | phase 3, before the first game with friends | either the admin does not play, or in running games the view hides the other players' secrets |
| Use of gold | phase 4 | deferred. Options considered: simple market with fixed prices and a margin (preferred), concessions during unrest, higher recurring costs, expensive goals |
| Tiles and workers | phase 2 | game 7: overbuilding with no staff and a housing dead end once tiles run out. Options: show the Architect unstaffed jobs, allow demolition, a way to gain tiles; also idle adults (extend the fixed rule to wood and stone, or leave them to the Architect) |
| Automatic sovereigns | phase 3 | personality, models, budget |
| Jev | phase 4 | technical details, policy schema, waiting-list sign-up |
| Lost vision sections | before phase 4 | rewrite the parts marked [Lost] in `docs/DESIGN.md` (map, war, victory, diplomacy, espionage, progress) |

## Decisions made (the main ones)

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
