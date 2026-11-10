"""@brief Bandits born from discontent: the world step after every realm's month
(village block B+C, stage 1; docs/DESIGN.md, "Bandits, the watchtower, the
Gastaldo and the militia"; values from lab/village_bandits.py).

Pure and integer-only, like the turn. The only randomness is a generator
seeded from the pool's seed and the turn, so a replay is exact.

The world step, after resolve_month (engine/market.py), in this order:
1. Flight: a class whose unrest counter (low_mood_turns: months under the
   unrest threshold, one back for a month above) reaches flee_turns loses
   a share of its adults every month, the peasants their children too;
   elders stay. Fugitives join the pool, their class is lost.
2. Raids: the pool's adults split into parties of party_size (the
   remainder raids too, by chance); each party picks one realm, weighted
   by what lies exposed (food and wood) and by how weak its militia is.
   Guards stop repel_per_guard raiders each: enough guards repel the
   party, fewer cut its loot. Raiders carry away food first, then wood.
3. The pool's month: the bandits eat the food they looted like the realms'
   people; the food they lack, a natural decline (more in winter) and an
   accumulator make the pool shrink; children grow up.

4. Stage 2, with a [migration] section: raids turned into immigration,
   acceptance and the natives' grumbling (engine/migration.py).
"""

import random
from dataclasses import asdict, dataclass, field

from engine.config import BanditsConfig, Config
from engine.migration import resolve_arrivals
from engine.state import Event, GameState
from engine.turn import TurnResult, _rescale_workers

WINTER_MONTHS = (12, 1, 2)


@dataclass
class BanditPool:
    """@brief The world's bandits: a game-level state, like the market's warehouse."""
    seed: int  # the generator's seed for raids, with the turn
    adults: int
    children: int = 0
    food: int = 0  # what they looted and have not eaten yet
    grow_acc: int = 0  # thousandths of a child growing up, as the realms' aging
    decline_acc: int = 0  # hundredths of a bandit leaving
    # Hundredths of a seeker, [adults, children] (stage 2, migration.accumulate);
    # [0, 0] for games saved before.
    seek_acc: list[int] = field(default_factory=lambda: [0, 0])


def new_pool(config: Config, seed: int, realm_count: int) -> BanditPool | None:
    """@brief The world's wanderers at game start, in proportion to the realms
    (the lab's 5-15 were for 8 realms: one realm alone drew every raid and
    starved); None for a game without bandits."""
    if config.bandits is None:
        return None
    rules = config.bandits
    rng = random.Random(f"{seed}:bandits:start")
    return BanditPool(seed, rng.randint(rules.start_min, rules.start_max) * realm_count // rules.start_realms)


def pool_to_dict(pool: BanditPool) -> dict:
    return asdict(pool)


def pool_from_dict(data: dict) -> BanditPool:
    return BanditPool(**data)


def _leave(acc: int, count: int, pct: int) -> tuple[int, int]:
    """@brief Integer share with an accumulator in hundredths: (gone, new acc)."""
    acc += count * pct
    return min(count, acc // 100), acc % 100


def _flee(state: GameState, rules: BanditsConfig, pool: BanditPool, events: list[Event]) -> None:
    """@brief One realm's flight, peasants then each class, by its own counter."""
    adults = children = merchants = 0
    if state.low_mood_turns >= rules.flee_turns:
        peasants = state.adults - state.workers.trade
        adults, state.flight_acc[0] = _leave(state.flight_acc[0], peasants, rules.flee_adult_pct)
        children, state.flight_acc[1] = _leave(state.flight_acc[1], state.children, rules.flee_child_pct)
    merchant_class = state.classes.get("merchants")
    if merchant_class is not None and merchant_class.low_mood_turns >= rules.flee_turns:
        merchants, merchant_class.flight_acc = _leave(merchant_class.flight_acc, state.workers.trade,
                                                     rules.flee_adult_pct)
        state.workers.trade -= merchants
    if not adults + children + merchants:
        return
    state.adults -= adults + merchants
    state.children -= children
    pool.adults += adults + merchants
    pool.children += children
    events.append(Event("flight", {"adults": adults, "children": children, "merchants": merchants}))
    _rescale_workers(state, events)


def _weight(state: GameState, rules: BanditsConfig) -> int:
    """@brief How much a realm draws the raiders: what lies exposed, less for its guards."""
    shield_pct = min(rules.max_guard_weight_pct, state.guards() * rules.guard_weight_pct)
    return max(1, (state.food + state.wood) * (100 - shield_pct) // 100)


def _raid(state: GameState, raiders: int, rules: BanditsConfig, pool: BanditPool, events: list[Event]) -> None:
    guards = state.guards()
    stopped = guards * rules.repel_per_guard
    if stopped >= raiders:
        events.append(Event("raid", {"raiders": raiders, "guards": guards, "repelled": True, "food": 0, "wood": 0}))
        return
    loot = (raiders - stopped) * rules.carry
    food = min(loot, state.food)
    wood = min(loot - food, state.wood)
    state.food -= food
    state.wood -= wood
    pool.food += food  # the wood they burn: it feeds nobody
    events.append(Event("raid", {"raiders": raiders, "guards": guards, "repelled": False, "food": food, "wood": wood}))


def _raids(states: dict[str, GameState], events: dict[str, list[Event]], rules: BanditsConfig,
           pool: BanditPool, turn: int) -> None:
    rng = random.Random(f"{pool.seed}:raids:{turn}")
    parties = pool.adults // rules.party_size
    if rng.randrange(rules.party_size) < pool.adults % rules.party_size:
        parties += 1  # the remainder raids too, by chance
    keys = list(states)
    if not parties or not keys:
        return
    raiders = max(1, pool.adults // parties)
    for _ in range(parties):
        weights = [_weight(states[key], rules) for key in keys]
        key = rng.choices(keys, weights)[0]
        _raid(states[key], raiders, rules, pool, events[key])


def _pool_month(pool: BanditPool, config: Config, month_of_year: int) -> None:
    rules, economy = config.bandits, config.economy
    need = pool.adults * economy.food_per_adult + pool.children * economy.food_per_child
    eaten = min(need, pool.food)
    pool.food -= eaten
    missing_pct = (need - eaten) * 100 // need if need else 0
    pct = rules.winter_decline_pct if month_of_year in WINTER_MONTHS else rules.decline_pct
    pct += missing_pct * rules.starve_pct // 100
    total = pool.adults + pool.children
    gone, pool.decline_acc = _leave(pool.decline_acc, total, pct)
    from_children = gone * pool.children // total if total else 0
    pool.children -= from_children
    pool.adults -= gone - from_children
    pool.grow_acc += pool.children * config.demography.child_to_adult_permille
    grown = min(pool.children, pool.grow_acc // 1000)
    pool.grow_acc %= 1000
    pool.children -= grown
    pool.adults += grown


def resolve_world(pool: BanditPool | None, results: dict[str, TurnResult], config: Config,
                  turn: int) -> BanditPool | None:
    """@brief The world step of a month, after resolve_month: flight, raids,
    the pool's month, then the arrivals (stage 2). Changes the realms' new states and appends their events.
    @param pool The pool at the start of the month (None: a game without bandits).
    @param results {realm key: TurnResult} of resolve_month, in the realms' fixed order.
    @param turn The month just resolved (1 = January of the first year).
    @return The pool at the start of the next month.
    """
    if pool is None or config.bandits is None:
        return pool
    rules = config.bandits
    pool = BanditPool(**asdict(pool))  # pure: the caller's pool is not changed
    playing = {key: result.state for key, result in results.items() if not result.state.game_over}
    events = {key: results[key].events for key in playing}
    for key, state in playing.items():
        _flee(state, rules, pool, events[key])
    _raids(playing, events, rules, pool, turn)
    _pool_month(pool, config, (turn - 1) % 12 + 1)
    if config.migration is not None:
        resolve_arrivals(pool, playing, events, config)
    return pool
