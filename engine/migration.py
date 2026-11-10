"""@brief The doors and acceptance: people of the bandits' pool become citizens
(village block B+C, stage 2; docs/DESIGN.md, "The doors and acceptance";
values from lab/village_migration.py).

Pure and integer-only, like the turn; no randomness (the shares are split
by largest remainder in the realms' fixed order), so a replay is exact.

Run by engine/bandits.py resolve_world, after the pool's month (the order
the lab tuned the values with), in this order:
1. Raids turned into immigration: the raiders a realm's guards stopped stay,
   by its doors (closed none, normal keep_normal_pct, open keep_open_pct),
   up to the free beds; they leave the pool.
2. Acceptance: seek_pct of the pool's adults and children look for a home.
   Only a realm with the mood at or above the unrest threshold, food for
   min_food_months and free beds draws them. Each takes, by its doors:
   closed none, normal the smaller of free beds and empty jobs, open the
   free beds (beyond the jobs too). Seekers are shared in proportion to
   that room.
3. The natives' grumbling: in scarcity (food under scarce_food_months or no
   empty job) the arrivals cost the peasants' mood grumble_per_pct points
   per 1 % of the population arrived, at once.
Newcomers enter as peasants, free adults for the Architect from the next
month; children as children. An `arrival` event tells each realm's month.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.config import Config, MigrationConfig
from engine.state import Event, GameState
from engine.turn import food_needed, housing_capacity, jobs_in_sector

if TYPE_CHECKING:  # engine/bandits.py imports this module: no import at run time
    from engine.bandits import BanditPool

JOB_SECTORS = ("food", "wood", "stone", "trade")


def free_beds(state: GameState, config: Config) -> int:
    """@brief Beds of the finished houses nobody sleeps in."""
    return max(0, housing_capacity(state, config) - state.population())


def empty_jobs(state: GameState, config: Config) -> int:
    """@brief Jobs of the working buildings beyond the adults free to take them."""
    jobs = sum(jobs_in_sector(state, config, sector) for sector in JOB_SECTORS)
    return max(0, jobs - state.free_adults())


def doors_in_force(state: GameState, rules: MigrationConfig) -> str:
    """@brief The realm's doors this month: closed doors need closed_min_guards
    guards, with fewer they count as normal. Doors other than normal exist
    only with a finished watchtower (engine/validator.py, demolition)."""
    if state.doors == "closed" and state.guards() < rules.closed_min_guards:
        return "normal"
    return state.doors


def _room(state: GameState, config: Config, rules: MigrationConfig) -> int:
    """@brief Adults the realm takes in from the seekers this month (0: it draws nobody)."""
    doors = doors_in_force(state, rules)
    if doors == "closed" or state.mood < config.unrest.threshold:
        return 0
    if state.food < rules.min_food_months * food_needed(state, config):
        return 0
    beds = free_beds(state, config)
    return beds if doors == "open" else min(beds, empty_jobs(state, config))


def _stopped_raiders_stay(state: GameState, events: list[Event], config: Config, rules: MigrationConfig,
                          pool: BanditPool) -> int:
    """@brief The raiders the guards stopped this month who stay, by the doors.
    @return Adults taken in (already moved from the pool to the realm)."""
    keep_pct = {"closed": 0, "normal": rules.keep_normal_pct, "open": rules.keep_open_pct}[doors_in_force(state, rules)]
    taken = 0
    for event in events:
        if event.kind != "raid" or not keep_pct:
            continue
        stopped = min(event.data["raiders"], event.data["guards"] * config.bandits.repel_per_guard)
        stay = min(stopped * keep_pct // 100, free_beds(state, config), pool.adults)
        pool.adults -= stay
        state.adults += stay
        taken += stay
    return taken


def _shares(total: int, rooms: dict[str, int]) -> dict[str, int]:
    """@brief total split in proportion to rooms, never beyond the whole room
    (largest remainder; ties in the realms' fixed order: the sort is stable)."""
    keys = [key for key, room in rooms.items() if room > 0]
    whole = sum(rooms[key] for key in keys)
    if not keys or not total:
        return {}
    total = min(total, whole)
    exact = {key: total * rooms[key] for key in keys}
    shares = {key: exact[key] // whole for key in keys}
    left = total - sum(shares.values())
    for key in sorted(keys, key=lambda key: -(exact[key] % whole))[:left]:
        shares[key] += 1
    return shares


def _seekers_settle(states: dict[str, GameState], config: Config, rules: MigrationConfig,
                    pool: BanditPool) -> dict[str, tuple[int, int]]:
    """@brief seek_pct of the pool looks for a home among the realms that draw it.
    @return {realm key: (adults, children)} taken in (already moved)."""
    seekers = pool.adults * rules.seek_pct // 100
    seeking_children = pool.children * rules.seek_pct // 100
    rooms = {key: _room(state, config, rules) for key, state in states.items()}
    settled = {}
    for key, adults in _shares(seekers, rooms).items():
        state = states[key]
        # Children follow the adults, as far as the beds left go.
        children = min(seeking_children * adults // seekers, max(0, free_beds(state, config) - adults))
        pool.adults -= adults
        pool.children -= children
        state.adults += adults
        state.children += children
        settled[key] = (adults, children)
    return settled


def _grumbling(state: GameState, config: Config, rules: MigrationConfig, arrived: int) -> int:
    """@brief The natives' mood malus for the month's arrivals: only in scarcity.
    @return Mood points lost (already applied)."""
    scarce = (state.food < rules.scarce_food_months * food_needed(state, config)
              or not empty_jobs(state, config))
    if not scarce:
        return 0
    malus = arrived * 100 // max(1, state.population()) * rules.grumble_per_pct
    state.mood = max(0, state.mood - malus)
    return malus


def resolve_arrivals(pool: BanditPool, states: dict[str, GameState], events: dict[str, list[Event]],
                     config: Config) -> None:
    """@brief The month's arrivals in every realm still playing; changes the
    states, the pool and appends one `arrival` event per realm that took anybody.
    @param pool The world's pool after its month (changed in place).
    @param states {realm key: state} of the realms still playing, in the fixed order.
    @param events {realm key: the realm's events of the month}, with its raids.
    """
    rules = config.migration
    from_raids = {key: _stopped_raiders_stay(state, events[key], config, rules, pool)
                  for key, state in states.items()}
    settled = _seekers_settle(states, config, rules, pool)
    for key, state in states.items():
        adults, children = settled.get(key, (0, 0))
        adults += from_raids[key]
        if not adults + children:
            continue
        grumble = _grumbling(state, config, rules, adults + children)
        events[key].append(Event("arrival", {"adults": adults, "children": children,
                                             "from_raids": from_raids[key], "grumble": grumble}))
