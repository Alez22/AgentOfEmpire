# AgentOfEmpire – Work plan

Updated 2026-11-07.

The prototype is complete and playable from a phone. The next phase is **playing it for real for 12–24 turns** and tuning values, prompts and UI.

This file is the starting point of every work session: read it at the start and update it at the end. The full design lives in [`docs/DESIGN.md`](docs/DESIGN.md), the UI mockups in [`docs/mockups/`](docs/mockups/).

## Where we are

| Part | What it does | Where |
| --- | --- | --- |
| Engine | deterministic monthly simulation: economy, seasons, food spoilage, demography, mood, unrest | `engine/`, values in `engine/config.toml` |
| Database | PostgreSQL 18.6 in Docker, 11 migrations, row-level security, append-only logs, replay | `db/migrations/`, `server/db/` |
| LLM council | Treasurer, Architect, Chancellor and Voice of the square on OpenRouter (DeepSeek V4.1 Flash for all); secret lessons revised at season end; private audiences | `server/council/`, settings in `server/council.toml` |
| UI | phone pages: games, turn, kingdom, chronicle, audiences; meetings run in the background | `server/ui/` |
| Admin | everything visible: full state, prompts, calls, costs, lessons, audiences, replay; per-agent page with system prompts, traits and last briefing | `server/admin/`, enabled with `ADMIN_VIEW=1` |
| Tests | 185 tests: engine, database, council with fake models, UI | `tests/` |

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
- [ ] Play a game with mandates, notes, debate and audiences together
- [x] Counsellor prompts: quote only briefing numbers, never count idle adults or jobs yourself, never present a suggestion as a rule in force; the Chancellor's assignments within adults and jobs (game 6)
- [x] Petitions weighted by the relief they bring (10–30), wider ranges for effort and births (after game 5)
- [x] A granted petition decides its law: the plan's orders on the same policy are not sent, and a grant after approval links the identical order
- [ ] Play again to check the fixes: no mood numbers in reports, no calls over ~90 s, lesson reviews applied, the square keeps a thread, rations cut only when the harvest does not cover
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
- [ ] Roles as data (`roles.toml`: title, duties, obligations, orders) separate from persons (traits, résumé, name), before hiring and dismissing counsellors
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
