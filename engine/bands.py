"""@brief Roads of the world, phase 1: the bandits as bands on the map
(docs/DESIGN.md, "Roads of the world"; values from lab/bands_map.py).

Replaces the pool's raids when the config has [bands]: the world step of
engine/bandits.py resolve_world calls resolve_bands. Pure and integer-only;
the only randomness is a generator seeded from the pool's seed and the turn
(`"{seed}:bands:{turn}"`), drawn in the bands' fixed order: a replay is exact.

The month of the world, after every realm's resolve_month, in this order:
1. Flight: a realm's fugitives join the band camped nearest its land within
   join_range hexes, or found one on the nearest free wood or hill
   (engine/bandits.py _flee runs on the band unchanged).
2. Targets: each band with at least merge_under adults picks the realm with
   the highest score, food and wood in view x the raid's odds / road units,
   among those within range; with `rest`, never the realm it raided last month.
3. Weeks: each band walks up to `speed` road units a week toward its target
   (plain 1, forest and hill 2, river 3; the realms' land is closed); next
   to the target's land it raids once and goes back to its camp. The raid
   succeeds with raiders / (raiders + guard_worth x guards): the full loot,
   `carry` a raider, food first, then wood; or nothing, and each raider
   stays as a citizen with stay_pct, beds permitting (the doors do not
   count: they are for who looks for a home). Each week every realm sees
   the bands within `see` hexes of its land or tower_see of its watchtower:
   a court event `band_seen`, once a band a month.
4. Each band's month (engine/bandits.py _pool_month: eating, decline, hunger,
   children growing up), then bands too big split, bands too small merge.
5. Stage 2 (with [migration]): the seekers come from the bands merged into
   one pool, taken back from the bands nearest each realm that drew them;
   the raiders who stayed join the month's `arrival` event.
6. A realm that fell this month founds a band on its land with the fallen
   shares of [bandits].

Cost: one Dijkstra over the 64 x 64 hexes per band to pick a target and
one per band per week to walk; a breadth-first map of the steps to the
realms' land once a month. Bands stay few (split and merge): well under a
second a month.

The number of bandits is never shown: players see bands near them, never
the world's total (court event, words in the UI).
"""

import heapq
import random

from engine.bandits import Band, BanditPool, _flee, _pool_month, pool_from_dict, pool_to_dict
from engine.config import BandsConfig, BanditsConfig, Config
from engine.migration import free_beds, resolve_arrivals
from engine.state import Event, GameState
from engine.territory import NOT_OWNED, TERRAIN_CHARS, hex_distance, neighbours
from engine.turn import TurnResult

FAR = 10 ** 9
WOODS = (TERRAIN_CHARS["forest"], TERRAIN_CHARS["hill"])


class RoadMap:
    """@brief The world's terrain and the realms' land for one month: roads,
    doorsteps, distances to the land, free camps."""

    def __init__(self, config: Config, states: dict[str, GameState]):
        self.config = config
        self.terrain = next(iter(states.values())).terrain
        self.size = len(self.terrain)
        self.cost = {TERRAIN_CHARS[name]: units for name, units in config.bands.road_cost.items()}
        self.land = {key: [(x, y) for y, row in enumerate(state.owned) for x, char in enumerate(row)
                           if char != NOT_OWNED] for key, state in states.items()}
        self.owner = {tile: key for key, tiles in self.land.items() for tile in tiles}
        self.steps_to_land = self._steps_to_land()
        self._doorsteps: dict[str, set[tuple[int, int]]] = {}

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size

    def _steps_to_land(self) -> dict[tuple[int, int], int]:
        """@brief Hex steps from every hex to the nearest realm's land (breadth-first)."""
        steps = {tile: 0 for tile in self.owner}
        frontier = list(self.owner)
        while frontier:
            next_frontier = []
            for here in frontier:
                for tile in neighbours(self.config, *here):
                    if self.inside(*tile) and tile not in steps:
                        steps[tile] = steps[here] + 1
                        next_frontier.append(tile)
            frontier = next_frontier
        return steps

    def doorstep(self, key: str) -> set[tuple[int, int]]:
        """@brief Free hexes next to a realm's land: where a band raids from."""
        if key not in self._doorsteps:
            self._doorsteps[key] = {tile for own in self.land[key] for tile in neighbours(self.config, *own)
                                    if self.inside(*tile) and tile not in self.owner}
        return self._doorsteps[key]

    def roads(self, start: tuple[int, int], goals: set[tuple[int, int]]) -> tuple[dict, tuple[int, int] | None]:
        """@brief Dijkstra over the free hexes from start, stopping at the
        first goal reached. Ties broken by (cost, hex): deterministic.
        @return ({hex: road units}, the goal reached or None)."""
        cost = {start: 0}
        queue = [(0, start)]
        while queue:
            here_cost, here = heapq.heappop(queue)
            if here_cost > cost[here]:
                continue
            if here in goals:
                return cost, here
            for tile in neighbours(self.config, *here):
                if not self.inside(*tile) or tile in self.owner:
                    continue
                step = here_cost + self.cost[self.terrain[tile[1]][tile[0]]]
                if step < cost.get(tile, FAR):
                    cost[tile] = step
                    heapq.heappush(queue, (step, tile))
        return cost, None

    def free_camp(self, near: tuple[int, int], gap: int, taken: set[tuple[int, int]]) -> tuple[int, int] | None:
        """@brief The wood or hill hex nearest `near`, more than gap hexes from
        any realm's land and not another band's camp; None if there is none."""
        best = None
        for y, row in enumerate(self.terrain):
            for x, char in enumerate(row):
                if char not in WOODS or (x, y) in taken or self.steps_to_land.get((x, y), FAR) <= gap:
                    continue
                distance = hex_distance(x, y, *near)
                if best is None or distance < best[0]:
                    best = (distance, (x, y))
        return best[1] if best else None

    def distance_to_land(self, key: str, x: int, y: int) -> int:
        return min((hex_distance(x, y, lx, ly) for lx, ly in self.land[key]), default=FAR)


# ---- bands -------------------------------------------------------------------------

def _found_band(pool: BanditPool, camp: tuple[int, int], adults: int = 0, children: int = 0,
                food: int = 0) -> Band:
    band = Band(pool.next_band_id, camp[0], camp[1], camp[0], camp[1], adults, children, food)
    pool.next_band_id += 1
    return band


def start_bands(pool: BanditPool, config: Config, wanderers: int, states: list[GameState]) -> None:
    """@brief The start wanderers in bands of party_size, camped by the seed on
    woods and hills more than start_gap hexes from every realm's land."""
    roads = RoadMap(config, {str(index): state for index, state in enumerate(states)})
    rng = random.Random(f"{pool.seed}:bands:start")
    woods = [(x, y) for y, row in enumerate(roads.terrain) for x, char in enumerate(row)
             if char in WOODS and roads.steps_to_land.get((x, y), FAR) > config.bands.start_gap]
    left = wanderers
    while left > 0 and woods:
        adults = min(left, config.bandits.party_size)
        pool.bands.append(_found_band(pool, rng.choice(woods), adults))
        left -= adults


def _flight(pool: BanditPool, states: dict[str, GameState], events: dict[str, list[Event]],
            roads: RoadMap, bandits: BanditsConfig, rules: BandsConfig) -> None:
    """@brief Step 1: each realm's fugitives join or found a band near its land."""
    for key, state in states.items():
        square = tuple(state.square)
        near = [band for band in pool.bands
                if roads.distance_to_land(key, band.camp_x, band.camp_y) <= rules.join_range]
        if near:
            band = min(near, key=lambda b: hex_distance(b.camp_x, b.camp_y, *square))
            _flee(state, bandits, band, events[key])
            continue
        camp = roads.free_camp(square, rules.camp_gap, {(b.camp_x, b.camp_y) for b in pool.bands})
        if camp is None:
            continue  # no free wood in the world: nobody can take to the woods
        band = Band(pool.next_band_id, *camp, *camp, 0)
        _flee(state, bandits, band, events[key])
        if band.adults + band.children:
            pool.next_band_id += 1
            pool.bands.append(band)


def _odds_weight(state: GameState, raiders: int, rules: BandsConfig) -> tuple[int, int]:
    """@brief (raiders, raiders + guard_worth x guards): the raid's odds as a fraction."""
    return raiders, raiders + rules.guard_worth * state.guards()


def _pick_targets(pool: BanditPool, states: dict[str, GameState], roads: RoadMap, rules: BandsConfig) -> None:
    """@brief Step 2: each band's target this month, or None."""
    for band in pool.bands:
        band.last_target = band.target if band.raided else None
        band.target, band.raided = None, False
        if band.adults < rules.merge_under:
            continue
        cost, _ = roads.roads((band.x, band.y), set())
        best = None
        for key, state in states.items():
            if rules.rest and key == band.last_target:
                continue
            reach = min((cost[tile] for tile in roads.doorstep(key) if tile in cost), default=None)
            if reach is None or reach > rules.range:
                continue
            wins, tries = _odds_weight(state, band.adults, rules)
            score = (state.food + state.wood) * wins * 100 // (tries * max(1, reach))
            if best is None or score > best[0]:
                best = (score, key)
        band.target = best[1] if best else None


def _walk(band: Band, roads: RoadMap, rules: BandsConfig) -> None:
    """@brief One week toward the target, along the cheapest road, up to speed units."""
    cost, reached = roads.roads((band.x, band.y), roads.doorstep(band.target))
    if reached is None:
        band.target = None  # the road is closed (the realm grew around it)
        return
    path = [reached]  # back from the goal, each step to a cheaper neighbour
    while path[-1] != (band.x, band.y):
        path.append(min((t for t in neighbours(roads.config, *path[-1]) if t in cost), key=lambda t: cost[t]))
    path.reverse()
    spent = 0
    for tile in path[1:]:
        spent += roads.cost[roads.terrain[tile[1]][tile[0]]]
        if spent > rules.speed:
            break
        band.x, band.y = tile


def _raid(state: GameState, band: Band, config: Config, rng: random.Random, events: list[Event]) -> int:
    """@brief The raid's odds, the loot or the raiders who stay.
    @return Raiders who stayed as citizens (already moved into the realm)."""
    rules = config.bands
    guards = state.guards()
    wins, tries = _odds_weight(state, band.adults, rules)
    if rng.randrange(tries) < wins:
        loot = band.adults * config.bandits.carry
        food = min(loot, state.food)
        wood = min(loot - food, state.wood)
        state.food -= food
        state.wood -= wood
        band.food += food  # the wood they burn: it feeds nobody
        events.append(Event("raid", {"raiders": band.adults, "guards": guards, "repelled": False,
                                     "food": food, "wood": wood}))
        return 0
    raiders = band.adults
    stayed = sum(1 for _ in range(raiders) if rng.randrange(100) < rules.stay_pct)
    stayed = min(stayed, free_beds(state, config))
    band.adults -= stayed
    state.adults += stayed
    events.append(Event("raid", {"raiders": raiders, "guards": guards, "repelled": True,
                                 "food": 0, "wood": 0, "stayed": stayed}))
    return stayed


def _sightings(pool: BanditPool, states: dict[str, GameState], events: dict[str, list[Event]],
               roads: RoadMap, rules: BandsConfig, week: int, seen: set[tuple[str, int]]) -> None:
    """@brief The bands each realm sees this week; one `band_seen` a band a month."""
    for key, state in states.items():
        tower = next(((b.x, b.y) for b in state.buildings if b.kind == "watchtower" and b.turns_left == 0), None)
        for band in pool.bands:
            if (key, band.id) in seen or band.adults + band.children == 0:
                continue
            near = roads.distance_to_land(key, band.x, band.y) <= rules.see
            from_tower = tower is not None and hex_distance(band.x, band.y, *tower) <= rules.tower_see
            if near or from_tower:
                seen.add((key, band.id))
                events[key].append(Event("band_seen", {"band": band.id, "adults": band.adults, "week": week,
                                                       "x": band.x, "y": band.y, "tower": from_tower and not near}))


def _weeks(pool: BanditPool, states: dict[str, GameState], events: dict[str, list[Event]], roads: RoadMap,
           config: Config, rng: random.Random) -> dict[str, int]:
    """@brief Step 3: walking, raiding and sightings, week by week.
    @return {realm key: raiders who stayed as citizens}."""
    rules = config.bands
    stayed: dict[str, int] = {}
    seen: set[tuple[str, int]] = set()
    for week in range(1, rules.weeks + 1):
        for band in pool.bands:
            if band.target is None or band.raided:
                continue
            if (band.x, band.y) not in roads.doorstep(band.target):
                _walk(band, roads, rules)
            if band.target is None or (band.x, band.y) not in roads.doorstep(band.target):
                continue
            key = band.target
            stayed[key] = stayed.get(key, 0) + _raid(states[key], band, config, rng, events[key])
            band.raided = True
            band.x, band.y = band.camp_x, band.camp_y
        _sightings(pool, states, events, roads, rules, week, seen)
    return stayed


def _split_and_merge(pool: BanditPool, roads: RoadMap, rules: BandsConfig) -> None:
    """@brief Step 4: a band too big splits onto the next free wood; a band too
    small joins the nearest within merge_range; empty bands are gone."""
    for band in list(pool.bands):
        if band.adults <= rules.split_over:
            continue
        camp = roads.free_camp((band.camp_x, band.camp_y), rules.camp_gap,
                               {(b.camp_x, b.camp_y) for b in pool.bands})
        if camp is None:
            continue
        half = _found_band(pool, camp, band.adults // 2, band.children // 2, band.food // 2)
        band.adults -= half.adults
        band.children -= half.children
        band.food -= half.food
        pool.bands.append(half)
    for band in sorted(pool.bands, key=lambda b: (b.adults, b.id)):
        if band.adults >= rules.merge_under or not any(b is band for b in pool.bands):
            continue
        others = [b for b in pool.bands if b is not band
                  and hex_distance(b.camp_x, b.camp_y, band.camp_x, band.camp_y) <= rules.merge_range]
        if not others:
            continue
        into = min(others, key=lambda b: (hex_distance(b.camp_x, b.camp_y, band.camp_x, band.camp_y), b.id))
        into.adults += band.adults
        into.children += band.children
        into.food += band.food
        pool.bands = [b for b in pool.bands if b is not band]
    pool.bands = [b for b in pool.bands if b.adults + b.children > 0]


def _take_back(pool: BanditPool, state: GameState, adults: int, children: int) -> None:
    """@brief Remove settled seekers from the bands nearest the realm's square."""
    square = tuple(state.square)
    for band in sorted(pool.bands, key=lambda b: (hex_distance(b.camp_x, b.camp_y, *square), b.id)):
        a, c = min(band.adults, adults), min(band.children, children)
        band.adults -= a
        band.children -= c
        adults -= a
        children -= c


def _arrivals(pool: BanditPool, states: dict[str, GameState], events: dict[str, list[Event]], config: Config,
              stayed: dict[str, int]) -> None:
    """@brief Step 5: stage 2 on the bands merged into one pool; the people a
    realm took in leave the bands nearest it."""
    merged = BanditPool(pool.seed, sum(b.adults for b in pool.bands), sum(b.children for b in pool.bands),
                        seek_acc=pool.seek_acc)
    resolve_arrivals(merged, states, events, config, raiders_stayed=stayed)
    pool.seek_acc = merged.seek_acc
    for key, state in states.items():
        for event in events[key]:
            if event.kind == "arrival":
                _take_back(pool, state, event.data["adults"] - event.data["from_raids"], event.data["children"])
    pool.bands = [b for b in pool.bands if b.adults + b.children > 0]


def _fallen_found_bands(pool: BanditPool, results: dict[str, TurnResult], rules: BanditsConfig) -> None:
    """@brief Step 6: the realms that fell this month send part of their people
    to the woods, as one band on their own land; they act from the next month."""
    for result in results.values():
        state = result.state
        if not any(event.kind == "game_over" for event in result.events):
            continue
        adults = state.adults * rules.fallen_adult_pct // 100
        children = state.children * rules.fallen_child_pct // 100
        food = state.food * rules.fallen_food_pct // 100
        if not adults + children + food:
            continue
        state.adults -= adults
        state.children -= children
        state.food -= food
        pool.bands.append(_found_band(pool, tuple(state.square), adults, children, food))
        result.events.append(Event("flight", {"adults": adults, "children": children, "merchants": 0}))


def resolve_bands(pool: BanditPool, results: dict[str, TurnResult], config: Config, turn: int) -> BanditPool:
    """@brief The world step of a month with [bands] (the module's steps 1-6).
    Changes the realms' new states and appends their events.
    @param pool The bandits at the start of the month (not changed: pure).
    @param results {realm key: TurnResult} of resolve_month, in the realms' fixed order.
    @param turn The month just resolved (1 = January of the first year).
    @return The bandits at the start of the next month.
    """
    pool = pool_from_dict(pool_to_dict(pool))  # pure: a deep copy through the stored form
    if not results:
        return pool
    rules = config.bands
    playing = {key: result.state for key, result in results.items() if not result.state.game_over}
    events = {key: results[key].events for key in playing}
    roads = RoadMap(config, {key: result.state for key, result in results.items()})
    rng = random.Random(f"{pool.seed}:bands:{turn}")
    _flight(pool, playing, events, roads, config.bandits, rules)
    _pick_targets(pool, playing, roads, rules)
    stayed = _weeks(pool, playing, events, roads, config, rng)
    for band in pool.bands:
        _pool_month(band, config, (turn - 1) % 12 + 1)
    _split_and_merge(pool, roads, rules)
    if config.migration is not None:
        _arrivals(pool, playing, events, config, stayed)
    _fallen_found_bands(pool, results, config.bandits)
    return pool
