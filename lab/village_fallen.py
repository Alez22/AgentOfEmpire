"""@brief The people of a fallen realm (after game 34, 2026-11-11): part of
them flee to the bandits' pool. Does it make the neighbours grow, and does it
spiral? Finds the bracketed values before the engine gets them.

Usage: docker compose run --rm -T tests python lab/village_fallen.py [label words...]

Why: in game 34 Brenna and Corvara fell with 103 and 85 people, who simply
vanished; the pool stayed at 0-3 and raids, doors and arrivals hardly
happened. The proposal (spec approved 2026-11-11): the month a realm falls,
[50 %] of its adults and [25 %] of its children join the pool, elders stay,
and they carry [25 %] of the granary as the pool's food.

Built on the real engine with stage 1 and stage 2 (engine/bandits.py,
engine/migration.py: flight, raids, the doors, arrivals) and the fixed
policy of lab/village_migration.py: 8 realms on the 8 sites, realms 1-2 in
crisis (tax 25 %) so they fall around month 8. On top, after the world step,
this script moves the fallen realm's people into the pool (the engine does
not have it yet). They act from the next month.

Printed per world, fallen share and pool seed: falls (the crisis realms and
any other), the arrivals in the six other realms (and how many were stopped
raiders), raids, food lost to raids, the pool's peak, the six realms' adults
at the end against the start, and their lowest mood.
"""

import dataclasses
import sys

from engine import load_config
from engine.bandits import new_pool, resolve_world
from engine.market import RealmMonth, new_market, resolve_month
from engine.migration import _grumbling, _room, _shares, free_beds
from lab.village_bandits import REALMS, _order
from lab.village_migration import Plan, Realm, crisis, orders_of

MONTHS = 30
POOL_SEEDS = (0, 1, 2)


@dataclasses.dataclass(frozen=True)
class Fallen:
    """@brief The share of a fallen realm that joins the pool."""
    adult_pct: int = 0
    child_pct: int = 0
    food_pct: int = 0
    refugees: bool = False  # True: they first look for a home; the homeless go to the woods




SHARES = {
    "today (nobody)": Fallen(),
    "25 % adults": Fallen(25, 12, 25),
    "50 % adults": Fallen(50, 25, 25),
    "75 % adults": Fallen(75, 37, 25),
    "10 % adults": Fallen(10, 5, 25),
    "15 % adults": Fallen(15, 7, 25),
    "refugees 25 %": Fallen(25, 12, 25, refugees=True),
    "refugees 50 %": Fallen(50, 25, 25, refugees=True),
}


def _doors_orders(realm):
    """@brief The engine's doors (stage 2 is in the engine): set them once the tower stands."""
    state = realm.state
    tower = any(b.kind == "watchtower" and b.turns_left == 0 for b in state.buildings)
    if not tower or state.doors == realm.plan.doors:
        return []
    return [_order({"action": "set_doors", "doors": realm.plan.doors})]


def _settle_refugees(adults, children, live_states, config):
    """@brief The refugees look for a home at once, by the engine's room (doors,
    mood, food, beds, jobs); the natives grumble as for any arrival.
    @return (adults, children) who found none."""
    rooms = {key: _room(state, config, config.migration) for key, state in live_states.items()}
    taken = 0
    for key, settled in _shares(adults, rooms).items():
        state = live_states[key]
        kids = min(children * settled // adults, max(0, free_beds(state, config) - settled))
        state.adults += settled
        state.children += kids
        children -= kids
        taken += settled
        _grumbling(state, config, config.migration, settled + kids)
    return adults - taken, children


def _to_the_woods(state, fallen, pool, live_states, config):
    """@return (people who left the fallen realm, of them settled at once)."""
    adults = state.adults * fallen.adult_pct // 100
    children = state.children * fallen.child_pct // 100
    left = adults + children
    if fallen.refugees and adults:
        adults, children = _settle_refugees(adults, children, live_states, config)
    pool.adults += adults
    pool.children += children
    pool.food += state.food * fallen.food_pct // 100
    return left, left - adults - children


def play(config, plans, fallen, pool_seed):
    realms = [Realm(str(i + 1), config, i, i, plans[i]) for i in range(REALMS)]
    market = new_market(config, REALMS)
    pool = new_pool(config, pool_seed, REALMS)
    stats = {"arrived": 0, "from_raids": 0, "raids": 0, "food_lost": 0, "pool_peak": pool.adults,
             "to_woods": 0, "settled": 0, "low_mood": 1000}
    for month in range(1, MONTHS + 1):
        live = [r for r in realms if not r.state.game_over]
        if not live:
            break
        months = {r.key: RealmMonth(r.state, orders_of(r, config, market) + _doors_orders(r)) for r in live}
        market, results = resolve_month(market, months, config)
        pool = resolve_world(pool, results, config, month)
        for r in live:
            r.state = results[r.key].state
        standing = {r.key: r.state for r in live if not r.state.game_over}
        for r in live:
            if r.state.game_over:
                left, settled = _to_the_woods(r.state, fallen, pool, standing, config)
                stats["to_woods"] += left
                stats["settled"] += settled
                continue
            for event in results[r.key].events:
                if event.kind == "arrival":
                    stats["arrived"] += event.data["adults"] + event.data["children"]
                    stats["from_raids"] += event.data["from_raids"]
                elif event.kind == "raid":
                    stats["raids"] += 1
                    stats["food_lost"] += event.data["food"]
            if int(r.key) > 2:
                stats["low_mood"] = min(stats["low_mood"], r.state.mood)
        stats["pool_peak"] = max(stats["pool_peak"], pool.adults)
    others = realms[2:]
    falls = [f"{r.key}@{r.state.turn - 1}" for r in realms if r.state.game_over]
    start = sum(r.start_adults for r in others)
    end = sum(r.state.adults for r in others if not r.state.game_over)
    return (f"falls {' '.join(falls) or '-':<16} | left {stats['to_woods']:>3} settled {stats['settled']:>3} | pool peak {stats['pool_peak']:>3}"
            f" | raids {stats['raids']:>3} food lost {stats['food_lost']:>5} | arrived {stats['arrived']:>3}"
            f" (raiders {stats['from_raids']:>2}) | adults of 3-8 {start} -> {end:>3} | low mood {stats['low_mood']}")


WORLDS = {
    "no watchtowers, all doors normal, 10 spare beds": crisis(*[Plan(spare_beds=10)] * 6),
    "watchtowers, 2 guards, doors normal": crisis(*[Plan(tower=True, guards=2, spare_beds=10)] * 6),
    "watchtowers, 4 guards, realms 3-5 open, 6-8 closed":
        crisis(*[Plan(doors="open", tower=True, guards=4, spare_beds=10)] * 3,
               *[Plan(doors="closed", tower=True, guards=4, spare_beds=10)] * 3),
}


def main():
    config = load_config()  # stages 1 and 2 as in the engine
    chosen = sys.argv[1:]
    for world, plans in WORLDS.items():
        print(f"\n== {world} (realms 1-2 in crisis, tax 25 %)")
        for label, fallen in SHARES.items():
            if chosen and not any(word in label for word in chosen):
                continue
            for seed in POOL_SEEDS:
                print(f"  {label:<15} seed {seed} | " + play(config, plans, fallen, seed))


if __name__ == "__main__":
    main()
