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
| Tests | 123 tests: engine, database, council with fake models, UI | `tests/` |

### How to use it

- **From the phone** (with Tailscale on): `http://<tailscale-ip>:8000/ui`, where the address is the one in `compose.override.yaml` (copy it from `compose.override.example.yaml`; it is not committed). Admin is at `/admin`, the API at `/docs`.
- **Start or restart the server:** `docker compose up -d server`. After changing `server/council.toml` or `.env`, use `docker compose up -d --force-recreate server`.
- **Tests:** `docker compose run --rm tests`.
- **Replay a game:** `docker compose run --rm tests python lab/replay.py <id>`.
- **Compare balance variants:** `docker compose run --rm tests python lab/compare_variants.py`.
- **Current cost:** about $0.01 per turn, meeting and Voice of the square included. The cap is $1 per game, in `server/council.toml`.

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

### 2. Field test – next

- [ ] Play 12–24 turns from the phone and note what does not work
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

- [ ] More classes: artisans and merchants, clergy, soldiers
- [ ] Marshal and Ambassador
- [ ] Tile map and more states, automatic ones too
- [ ] Market, trade and diplomacy (they give gold a use)
- [ ] Espionage, war, revolts and coups
- [ ] Eras, variable trust and loyalty, leaks
- [ ] Jev instead of the fixed rules

## Open decisions

| Decision | Needed by | Notes |
| --- | --- | --- |
| Models per tier and spending cap for a long game | end of phase 2 | today all roles use DeepSeek V4.1 Flash with reasoning `low` (the Voice `none`). At about $0.01 per turn, $1 lasts about 100 turns: 120 turns need about $1.50 |
| What the admin sees in games with others | phase 3, before the first game with friends | either the admin does not play, or in running games the view hides the other players' secrets |
| Use of gold | phase 4 | deferred. Options considered: simple market with fixed prices and a margin (preferred), concessions during unrest, higher recurring costs, expensive goals |
| Idle adults | phase 2 | extend the fixed rule to wood and stone, or leave them to the Architect |
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
- **Sovereign view:** no number and no summary word for mood. The sovereign learns about the people only from the Voice of the square and the council.
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
