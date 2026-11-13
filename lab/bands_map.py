"""@brief Roads of the world, phase 1: the bandits as bands on the map
(docs/DESIGN.md, "Roads of the world"). Finds the bracketed values and
compares raids by distance with today's pool, which raids any realm.

Usage: docker compose run --rm -T tests python lab/bands_map.py [label words...]

Built on the real engine with stages 1 and 2 and the fixed policy of
lab/village_migration.py, on the worlds of lab/village_fallen.py: 8 realms
on the 8 sites, realms 1-2 in crisis (tax 25 %). Two world steps are run:
- "pool": the engine's resolve_world, as today;
- "bands": this script's step. A band is the engine's BanditPool with a
  place (so the engine's flight, raid and pool-month functions run on it
  unchanged), in this order:
  1. flight: a realm's fugitives join the band camped nearest its land
     within JOIN_RANGE hexes, or found one on the nearest free wood or hill;
  2. targets: each band picks the realm with the highest weight (the
     engine's: food and wood in view, less for guards) per hex of road,
     among those within RANGE; none: it stays;
  3. WEEKS steps: each band walks up to SPEED road units (plain 1, forest
     and hill 2, river 3; realms' land closed) toward its target; standing
     next to the target's land it raids once (the engine's _raid with all
     its adults) and goes back to its camp; sightings are counted per realm
     each week (bands within SEE hexes of its land, TOWER_SEE of its tower);
  4. each band's month (the engine's _pool_month), then split and merge;
  5. acceptance (stage 2) on the bands merged into one pool, the people
     taken back from the bands, largest first (lab simplification: the
     spec takes them from the nearest bands);
  6. a realm that fell this month founds a band on its land with the
     engine's shares (fallen_*_pct).

Printed per world, step and seed: falls, raids on each realm, the share of
raids on the crisis realms' neighbours (realms 3 and 4, next to 2 and 1 on
the ring), raids seen coming, raids seen coming (a sighting of
the raiding band in the weeks before), bands and their adults at the peak.

Variants (RUNS): the brakes "rest" and "floor", deterrence, and the
owner's odds (a raid succeeds with raiders / (raiders + k x guards); chosen
2026-11-13 with k 3 and 10 % of a failed raid's raiders staying; PLAN.md,
"Lab: bands on the map").

Limits, on purpose: no caravans (phase 2), bands walk through each other,
the camp is a hex not a territory, acceptance ignores distance.
"""

import dataclasses
import heapq
import random
import sys

from engine import load_config
from engine.bandits import BanditPool, _flee, _pool_month, _raid, _weight, new_pool, resolve_world
from engine.market import RealmMonth, new_market, resolve_month
from engine.migration import resolve_arrivals
from engine.state import Event
from engine.turn import housing_capacity
from engine.territory import NOT_OWNED, TERRAIN_CHARS, hex_distance, neighbours
from lab.village_bandits import REALMS
from lab.village_fallen import WORLDS, _doors_orders
from lab.village_migration import Realm, orders_of

MONTHS = 24
SEEDS = (0, 1, 2)
WEEKS = 4
COST = {".": 1, "T": 2, "^": 2, "~": 3}
WOODS = (TERRAIN_CHARS["forest"], TERRAIN_CHARS["hill"])


@dataclasses.dataclass(frozen=True)
class Values:
    """@brief The bracketed values of the spec under test."""
    speed: int = 8  # road units a week
    range: int = 24  # road units from the band to a realm it may target
    join_range: int = 6  # hexes: fugitives join a band camped this near
    camp_gap: int = 2  # hexes between a new camp and any realm's land
    split_over: int = 16  # adults
    merge_under: int = 3  # adults
    merge_range: int = 10  # hexes
    see: int = 4  # hexes from the realm's land
    tower_see: int = 12  # hexes from the watchtower
    rest_months: int = 0  # 1: a band does not raid the realm it raided last month
    reach_floor: int = 0  # score = weight / (reach + reach_floor): higher, distance counts less
    # Deterrence: a band skips a realm whose guards it cannot beat.
    # 0 off; 1 it needs more adults than guards (the owner's idea, 2026-11-13);
    # 2 it needs more adults than the guards stop (repel_per_guard each).
    deter: int = 0
    # The owner's odds (2026-11-13): a raid succeeds with raiders / (raiders +
    # guards); a failed raid takes nothing and each raider stays as a citizen
    # with stay_pct (beds permitting, doors ignored). Targets weigh exposure
    # by the same odds. -1: off (the engine's repel_per_guard).
    stay_pct: int = -1
    guard_worth: int = 1  # in the odds a guard counts as this many raiders (walls, arms, training)


@dataclasses.dataclass(eq=False)
class Band(BanditPool):
    x: int = 0
    y: int = 0
    camp: tuple[int, int] = (0, 0)
    target: str | None = None
    raided: bool = False
    last_target: str | None = None

    # Two bands of the same size are still two bands: compare by identity,
    # not by the fields that BanditPool's dataclass would compare.
    __eq__ = object.__eq__
    __hash__ = object.__hash__


# ---- the map ------------------------------------------------------------------

class World:
    """@brief Terrain, the realms' land and the free woods, rebuilt each month."""

    def __init__(self, config, states):
        self.config = config
        self.terrain = next(iter(states.values())).terrain
        self.size = len(self.terrain)
        self.land = {key: {(x, y) for y, row in enumerate(s.owned) for x, c in enumerate(row) if c != NOT_OWNED}
                     for key, s in states.items()}
        self.owner = {tile: key for key, tiles in self.land.items() for tile in tiles}
        self.gap = self._steps_to_land()
        self._doorsteps = {}

    def _steps_to_land(self):
        """@brief Hex steps from every hex to the nearest realm's land (breadth-first, once)."""
        steps = {tile: 0 for tile in self.owner}
        frontier = list(self.owner)
        while frontier:
            nxt_frontier = []
            for here in frontier:
                for nxt in neighbours(self.config, *here):
                    if self.inside(*nxt) and nxt not in steps:
                        steps[nxt] = steps[here] + 1
                        nxt_frontier.append(nxt)
            frontier = nxt_frontier
        return steps

    def inside(self, x, y):
        return 0 <= x < self.size and 0 <= y < self.size

    def near_land(self, x, y, gap):
        return self.gap.get((x, y), 10 ** 9) <= gap

    def road(self, start, goals):
        """@brief Dijkstra over free hexes from start; returns {hex: cost}, stopping at the goals' cheapest."""
        cost = {start: 0}
        queue = [(0, start)]
        while queue:
            here_cost, here = heapq.heappop(queue)
            if here_cost > cost[here]:
                continue
            if here in goals:
                return cost, here
            for nxt in neighbours(self.config, *here):
                if not self.inside(*nxt) or nxt in self.owner:
                    continue
                step = here_cost + COST[self.terrain[nxt[1]][nxt[0]]]
                if step < cost.get(nxt, 10 ** 9):
                    cost[nxt] = step
                    heapq.heappush(queue, (step, nxt))
        return cost, None

    def doorstep(self, key):
        """@brief Free hexes next to a realm's land: where a band raids from."""
        if key not in self._doorsteps:
            self._doorsteps[key] = {n for tile in self.land[key] for n in neighbours(self.config, *tile)
                                    if self.inside(*n) and n not in self.owner}
        return self._doorsteps[key]

    def free_camp(self, near, gap, taken):
        """@brief The nearest wood or hill hex at least gap+1 from any realm's land."""
        best = None
        for y, row in enumerate(self.terrain):
            for x, char in enumerate(row):
                if char not in WOODS or (x, y) in taken or self.near_land(x, y, gap):
                    continue
                d = hex_distance(x, y, *near)
                if best is None or d < best[0]:
                    best = (d, (x, y))
        return best[1]


# ---- the bands' step ---------------------------------------------------------------

def _new_band(seed, camp, adults=0, children=0, food=0):
    return Band(seed, adults, children, food, x=camp[0], y=camp[1], camp=camp)


def start_bands(config, world, seed, values):
    """@brief The engine's start pool, in bands of party_size camped by the seed far from the sites."""
    pool = new_pool(config, seed, REALMS)
    rng = random.Random(f"{seed}:bands:start")
    woods = [(x, y) for y, row in enumerate(world.terrain) for x, c in enumerate(row)
             if c in WOODS and not world.near_land(x, y, 6)]
    bands, left = [], pool.adults
    while left > 0:
        adults = min(left, config.bandits.party_size)
        bands.append(_new_band(seed, rng.choice(woods), adults))
        left -= adults
    return bands


def _flight(states, events, world, bands, rules, values, seed):
    camps = {b.camp for b in bands}
    for key, state in states.items():
        sx, sy = state.square
        near = [b for b in bands if min(hex_distance(b.camp[0], b.camp[1], x, y) for x, y in world.land[key])
                <= values.join_range]
        band = min(near, key=lambda b: hex_distance(*b.camp, sx, sy)) if near else None
        if band is None:
            band = _new_band(seed, world.free_camp((sx, sy), values.camp_gap, camps))
        before = (band.adults, band.children)
        _flee(state, rules, band, events[key])
        if (band.adults, band.children) != before and not any(b is band for b in bands):
            bands.append(band)
            camps.add(band.camp)


def _pick_targets(states, world, bands, rules, values):
    for band in bands:
        band.last_target = band.target if band.raided else None
        band.target, band.raided = None, False
        if band.adults < values.merge_under:
            continue
        cost, _ = world.road((band.x, band.y), set())
        best = None
        for key, state in states.items():
            reach = min((cost[h] for h in world.doorstep(key) if h in cost), default=None)
            if reach is None or reach > values.range:
                continue
            if values.rest_months and key == band.last_target:
                continue
            if values.deter and band.adults <= state.guards() * (rules.repel_per_guard if values.deter == 2 else 1):
                continue
            if values.stay_pct >= 0:
                guards = state.guards() * values.guard_worth
                exposed = (state.food + state.wood) * band.adults // (band.adults + guards)
            else:
                exposed = _weight(state, rules)
            score = exposed * 100 // max(1, reach + values.reach_floor)
            if best is None or score > best[0]:
                best = (score, key)
        band.target = best[1] if best else None


def _walk(band, world, values):
    """@brief One week toward the target: follow the cheapest road, up to speed units."""
    goals = world.doorstep(band.target)
    cost, reached = world.road((band.x, band.y), goals)
    if reached is None:
        band.target = None
        return
    path = [reached]  # walk back from the goal along decreasing cost
    while path[-1] != (band.x, band.y):
        here = path[-1]
        path.append(min((n for n in neighbours(world.config, *here) if n in cost), key=lambda n: cost[n]))
    path.reverse()
    spent = 0
    for here, nxt in zip(path, path[1:]):
        spent += COST[world.terrain[nxt[1]][nxt[0]]]
        if spent > values.speed:
            break
        band.x, band.y = nxt


def _sightings(states, world, bands, values, seen):
    for key, state in states.items():
        tower = next(((b.x, b.y) for b in state.buildings if b.kind == "watchtower" and b.turns_left == 0), None)
        for band in bands:
            near = min(hex_distance(band.x, band.y, x, y) for x, y in world.land[key]) <= values.see
            far = tower is not None and hex_distance(band.x, band.y, *tower) <= values.tower_see
            if near or far:
                seen.add((key, id(band)))


def _odds_raid(state, band, rules, values, events, stats, rng):
    """@brief The owner's raid: success with raiders / (raiders + guards); a
    failure takes nothing and some raiders stay. The event says guards 0 so the
    engine's stopped-raiders rule (migration) does not run on it too."""
    raiders, guards = band.adults, state.guards() * values.guard_worth
    if rng.randrange(raiders + guards) < raiders:
        loot = raiders * rules.carry
        food = min(loot, state.food)
        wood = min(loot - food, state.wood)
        state.food -= food
        state.wood -= wood
        band.food += food
        events.append(Event("raid", {"raiders": raiders, "guards": 0, "repelled": False, "food": food, "wood": wood}))
        return
    stay = sum(1 for _ in range(raiders) if rng.randrange(100) < values.stay_pct)
    stay = min(stay, max(0, housing_capacity(state, CONFIG[0]) - state.population()))
    band.adults -= stay
    state.adults += stay
    stats["stayed"] += stay
    events.append(Event("raid", {"raiders": raiders, "guards": 0, "repelled": True, "food": 0, "wood": 0}))


def _weeks(states, events, world, bands, rules, values, stats, rng):
    seen = set()
    for _ in range(WEEKS):
        for band in bands:
            if band.target is None or band.raided:
                continue
            if (band.x, band.y) not in world.doorstep(band.target):
                _walk(band, world, values)
            if band.target is not None and (band.x, band.y) in world.doorstep(band.target):
                warned = (band.target, id(band)) in seen
                food_before = band.food
                if values.stay_pct >= 0:
                    _odds_raid(states[band.target], band, rules, values, events[band.target], stats, rng)
                else:
                    _raid(states[band.target], band.adults, rules, band, events[band.target])
                stats["food"][band.target] = stats["food"].get(band.target, 0) + band.food - food_before
                stats["raids"][band.target] = stats["raids"].get(band.target, 0) + 1
                stats["warned"] += warned
                band.raided = True
                band.x, band.y = band.camp
        _sightings(states, world, bands, values, seen)


def _split_and_merge(bands, world, values, seed):
    for band in list(bands):
        if band.adults > values.split_over:
            camp = world.free_camp(band.camp, values.camp_gap, {b.camp for b in bands})
            half = _new_band(seed, camp, band.adults // 2, band.children // 2, band.food // 2)
            band.adults -= half.adults
            band.children -= half.children
            band.food -= half.food
            bands.append(half)
    for band in sorted(bands, key=lambda b: b.adults):
        if band.adults >= values.merge_under or band not in bands:
            continue
        others = [b for b in bands if b is not band and hex_distance(*b.camp, *band.camp) <= values.merge_range]
        if not others:
            continue
        into = min(others, key=lambda b: hex_distance(*b.camp, *band.camp))
        into.adults += band.adults
        into.children += band.children
        into.food += band.food
        bands.remove(band)
    bands[:] = [b for b in bands if b.adults + b.children > 0]


def _acceptance(states, events, bands, config):
    merged = BanditPool(0, sum(b.adults for b in bands), sum(b.children for b in bands))
    adults, children = merged.adults, merged.children
    resolve_arrivals(merged, states, events, config)
    taken = [adults - merged.adults, children - merged.children]
    for band in sorted(bands, key=lambda b: -b.adults):
        a, c = min(band.adults, taken[0]), min(band.children, taken[1])
        band.adults -= a
        band.children -= c
        taken[0] -= a
        taken[1] -= c


def _fallen(results, world, bands, rules, seed):
    for key, result in results.items():
        state = result.state
        if not any(e.kind == "game_over" for e in result.events):
            continue
        adults = state.adults * rules.fallen_adult_pct // 100
        children = state.children * rules.fallen_child_pct // 100
        food = state.food * rules.fallen_food_pct // 100
        state.adults -= adults
        state.children -= children
        state.food -= food
        bands.append(_new_band(seed, tuple(state.square), adults, children, food))


def bands_world(bands, results, config, values, turn, seed, stats):
    """@brief The bands' world step of one month (the module's steps 1-6)."""
    rules = config.bandits
    playing = {k: r.state for k, r in results.items() if not r.state.game_over}
    events = {k: results[k].events for k in playing}
    world = World(config, {k: r.state for k, r in results.items()})
    _flight(playing, events, world, bands, rules, values, seed)
    _pick_targets(playing, world, bands, rules, values)
    _weeks(playing, events, world, bands, rules, values, stats, random.Random(f"{seed}:bands:{turn}"))
    for band in bands:
        _pool_month(band, config, (turn - 1) % 12 + 1)
    _split_and_merge(bands, world, values, seed)
    if config.migration is not None:
        _acceptance(playing, events, bands, config)
    _fallen(results, world, bands, rules, seed)


# ---- the runs ---------------------------------------------------------------------

def play(config, plans, mode, seed, values):
    realms = [Realm(str(i + 1), config, i, i, plans[i]) for i in range(REALMS)]
    market = new_market(config, REALMS)
    stats = {"raids": {}, "food": {}, "warned": 0, "bands_peak": 0, "adults_peak": 0,
             "arrived": 0, "from_raids": 0, "repelled": 0, "stayed": 0}
    pool = new_pool(config, seed, REALMS)
    bands = start_bands(config, World(config, {r.key: r.state for r in realms}), seed, values)
    for month in range(1, MONTHS + 1):
        live = [r for r in realms if not r.state.game_over]
        if not live:
            break
        months = {r.key: RealmMonth(r.state, orders_of(r, config, market) + _doors_orders(r)) for r in live}
        market, results = resolve_month(market, months, config)
        if mode == "pool":
            pool = resolve_world(pool, results, config, month)
            for key, result in results.items():
                raids = sum(1 for e in result.events if e.kind == "raid")
                stats["raids"][key] = stats["raids"].get(key, 0) + raids
                food = sum(e.data["food"] for e in result.events if e.kind == "raid")
                stats["food"][key] = stats["food"].get(key, 0) + food
            adults, count = pool.adults, 1
        else:
            bands_world(bands, results, config, values, month, seed, stats)
            adults, count = sum(b.adults for b in bands), len(bands)
        for r in live:
            r.state = results[r.key].state
            for e in results[r.key].events:
                if e.kind == "arrival":
                    stats["arrived"] += e.data["adults"]
                    stats["from_raids"] += e.data["from_raids"]
                elif e.kind == "raid" and e.data["repelled"]:
                    stats["repelled"] += 1
        stats["bands_peak"] = max(stats["bands_peak"], count)
        stats["adults_peak"] = max(stats["adults_peak"], adults)
    return realms, stats


def report(realms, stats, mode):
    raids = stats["raids"]
    per_realm = " ".join(f"{r.key}:{raids.get(r.key, 0):>2}" for r in realms)
    total = sum(raids.values()) or 1
    near = raids.get("3", 0) + raids.get("4", 0)  # sites next to the crisis realms 1 and 2
    falls = " ".join(f"{r.key}@{r.state.turn - 1}" for r in realms if r.state.game_over) or "-"
    warned = f" warned {stats['warned']:>2}" if mode == "bands" else ""
    worst = max(stats["food"].items(), key=lambda item: item[1], default=("-", 0))
    warned += f" | worst food lost {worst[0]}:{worst[1]:>5}"
    return (f"falls {falls:<14} | raids {per_realm} | total {total:>3} next-to-crisis {near * 100 // total:>3} %"
            f"{warned} | repelled {stats['repelled']:>2} arrived {stats['arrived']:>3} (raiders {stats['from_raids'] + stats['stayed']:>2})"
            f" | bands peak {stats['bands_peak']:>2} adults peak {stats['adults_peak']:>3}")


RUNS = {
    "pool (today)": ("pool", Values()),
    "bands": ("bands", Values()),
    "bands, range 16": ("bands", Values(range=16)),
    "bands, range 40": ("bands", Values(range=40)),
    "bands, speed 4": ("bands", Values(speed=4)),
    "bands, rest": ("bands", Values(rest_months=1)),
    "bands, floor 24": ("bands", Values(reach_floor=24)),
    "bands, rest+floor": ("bands", Values(rest_months=1, reach_floor=24)),
    "bands, odds stay 5": ("bands", Values(rest_months=1, stay_pct=5)),
    "bands, odds stay 10": ("bands", Values(rest_months=1, stay_pct=10)),
    "bands, odds stay 20": ("bands", Values(rest_months=1, stay_pct=20)),
    "bands, odds stay 10 no rest": ("bands", Values(stay_pct=10)),
    "bands, odds worth 2": ("bands", Values(rest_months=1, stay_pct=10, guard_worth=2)),
    "bands, odds worth 3": ("bands", Values(rest_months=1, stay_pct=10, guard_worth=3)),
    "bands, deter 1": ("bands", Values(deter=1)),
    "bands, deter 2": ("bands", Values(deter=2)),
    "bands, rest+deter 1": ("bands", Values(rest_months=1, deter=1)),
    "bands, rest+deter 2": ("bands", Values(rest_months=1, deter=2)),
}


CONFIG = []  # the run's config, for the lab's own raid (set by main)


def main():
    config = load_config()
    CONFIG.append(config)
    chosen = sys.argv[1:]
    for world, plans in WORLDS.items():
        print(f"\n== {world} (realms 1-2 in crisis, tax 25 %)")
        for label, (mode, values) in RUNS.items():
            if chosen and not any(word in label for word in chosen):
                continue
            for seed in SEEDS:
                realms, stats = play(config, plans, mode, seed, values)
                print(f"  {label:<16} seed {seed} | " + report(realms, stats, mode))


if __name__ == "__main__":
    main()
