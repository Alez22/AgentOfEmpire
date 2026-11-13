"""@brief Roads of the world, phase 2: the trades walk to the fair as caravans
(docs/DESIGN.md, "Phase 2: caravans and the fair"; values from
lab/caravans_map.py).

With [caravans] (and [bands], [market]) the market's warehouse stands at the
fair, the free hex nearest the middle of the map, and the market has a month
of latency both ways (engine/market.py):
- a sale's goods leave the realm's store the month they are ordered and join
  the warehouse marked `arriving`: nobody can buy them this month;
- a purchase is filled and paid at the fair at the start of the month, but
  its goods are not added to the realm's store.

Then, in the weeks of the bands' world step (engine/bands.py), every realm
with trades this month sends two legs: out (its sales, from its doorstep to
the fair) and back (its purchases, from the fair to its doorstep). Each
week a leg walks `speed` road units along the cheapest road and marks every
hex it crossed; it is met when one of them lies within `radius` hexes of a
band (any band with adults, where it stands at the week's end). Only the
first meeting counts:
- the leg loses its whole load: a sale's consignments leave the warehouse
  (nobody pays for them), a purchase never reaches the store (its gold was
  paid at the fair);
- the band keeps what it carries, adults x carry, food first (to its food),
  then wood (burned); the rest is scattered, stone is left on the road;
- the realm sees the band (`band_seen`, if not already this month).
A leg not met arrives when its road ends, or at the month's end if the road
is longer than the month: the sale's consignments lose `arriving`, the
purchase's goods enter the realm's new state. So nothing is on the road
across months: no caravan state is stored.

Pure in the sense of the world step: it changes the realms' new states, the
bands of the pool's copy and the market that resolve_month returned (the
caller's next month), never the inputs of the month. No randomness.
"""

from dataclasses import dataclass, field

from engine.config import Config
from engine.state import Event
from engine.territory import hex_distance, neighbours

GOODS = ("food", "wood", "stone")  # as engine/market.py (not imported: market imports this module)


def caravans_on(config: Config) -> bool:
    """@brief True when trades walk as caravans: [caravans] with the [bands],
    [market] and map it needs (a lab or a test may drop one of them and keep
    the file's [caravans]: then the market is instant, as before)."""
    return (config.caravans is not None and config.bands is not None and config.market is not None
            and config.map is not None)  # a game without a map has no roads: instant, as before


def fair_hex(roads) -> tuple[int, int]:
    """@brief The fair: the free hex nearest the middle of the map, ties by
    (y, x). Found again each month: it moves only if a realm grows over it.
    @param roads An engine.bands.RoadMap (its size and the realms' land)."""
    middle = roads.size // 2
    free = ((x, y) for y in range(roads.size) for x in range(roads.size) if (x, y) not in roads.owner)
    return min(free, key=lambda tile: (hex_distance(*tile, middle, middle), tile[1], tile[0]))


@dataclass
class Leg:
    """@brief One caravan of one month: a realm's sales out or its purchases back."""
    realm: str
    side: str  # "out" (to the fair) or "back" (home)
    load: dict[str, int]  # good -> units
    path: list[tuple[int, int]]  # the road, first hex where it starts; empty: no road, it just arrives
    index: int = 0  # the hex of the path it stands on
    done: bool = False


def _road(roads, start: tuple[int, int], goals: set[tuple[int, int]]) -> list[tuple[int, int]]:
    """@brief The cheapest road from start to the nearest goal, start first;
    empty when no goal can be reached (the land closes every way)."""
    cost, reached = roads.roads(start, goals)
    if reached is None:
        return []
    path = [reached]  # back from the goal, each step to a cheaper neighbour (as the bands walk)
    while path[-1] != start:
        path.append(min((t for t in neighbours(roads.config, *path[-1]) if t in cost), key=lambda t: cost[t]))
    path.reverse()
    return path


def _sales_on_the_road(market, key: str) -> dict[str, int]:
    """@brief The realm's consignments that joined the warehouse this month."""
    load = {good: sum(c.units for c in market.goods[good].queue if c.arriving and c.seller == key)
            for good in GOODS}
    return {good: units for good, units in load.items() if units}


def _purchases_on_the_road(events: list[Event], lot: int) -> dict[str, int]:
    """@brief The realm's purchases of this month, from its trade_bought events."""
    load: dict[str, int] = {}
    for event in events:
        if event.kind == "trade_bought" and event.data.get("road"):
            units = event.data.get("units", event.data["lots"] * lot)  # "units" only for a short lot
            load[event.data["good"]] = load.get(event.data["good"], 0) + units
    return load


def send_legs(market, results: dict, roads, config: Config) -> list[Leg]:
    """@brief Week 1: the out and back legs of every realm that traded this month.
    @param market The market resolve_month returned (None: a caller without one).
    @param results {realm key: TurnResult} of resolve_month (fallen realms' trades walk too).
    @throws ValueError if the market is missing while purchases are on the road
            (they would be lost: the caller must pass it)."""
    lot = config.market.lot_units
    if market is None:
        if any(_purchases_on_the_road(r.events, lot) for r in results.values()):
            raise ValueError("caravans need the market: pass it to resolve_world")
        return []
    fair = roads.fair
    legs = []
    for key, result in results.items():
        sales = _sales_on_the_road(market, key)
        purchases = _purchases_on_the_road(result.events, lot)
        if not sales and not purchases:
            continue
        home_to_fair = _road(roads, fair, roads.doorstep(key))[::-1]  # searched from the fair: one search
        if sales:
            legs.append(Leg(key, "out", sales, home_to_fair))
        if purchases:
            legs.append(Leg(key, "back", purchases, home_to_fair[::-1]))
    return legs


def _step(leg: Leg, roads, speed: int) -> list[tuple[int, int]]:
    """@brief One week along the leg's road, up to speed units.
    @return The hexes crossed this week, the one it starts from included."""
    if not leg.path:
        return []
    crossed, spent = [leg.path[leg.index]], 0
    while leg.index + 1 < len(leg.path):
        tile = leg.path[leg.index + 1]
        spent += roads.cost[roads.terrain[tile[1]][tile[0]]]
        if spent > speed:
            break
        leg.index += 1
        crossed.append(tile)
    return crossed


def _band_met(crossed: list[tuple[int, int]], bands: list, radius: int):
    """@brief The band nearest the hexes crossed, within radius; ties by the bands' order; None if none."""
    best = None
    for band in bands:
        if band.adults <= 0:
            continue
        distance = min(hex_distance(band.x, band.y, x, y) for x, y in crossed)
        if distance <= radius and (best is None or distance < best[0]):
            best = (distance, band)
    return best[1] if best else None


def _arrive(leg: Leg, market, results: dict, week: int) -> None:
    leg.done = True
    if leg.side == "out":
        for book in market.goods.values():
            for consignment in book.queue:
                if consignment.arriving and consignment.seller == leg.realm:
                    consignment.arriving = False
    else:
        state = results[leg.realm].state
        for good, units in leg.load.items():
            setattr(state, good, getattr(state, good) + units)
    results[leg.realm].events.append(Event("caravan_arrived", {"leg": leg.side, "goods": dict(leg.load),
                                                               "week": week}))


def _rob(leg: Leg, band, tile: tuple[int, int], market, results: dict, config: Config, week: int,
         seen: set[tuple[str, int]]) -> None:
    """@brief The band takes the load: it keeps what it carries, the rest is lost."""
    leg.done = True
    if leg.side == "out":
        for book in market.goods.values():  # never reached the warehouse: nobody pays for them
            book.queue = [c for c in book.queue if not (c.arriving and c.seller == leg.realm)]
    carried = band.adults * config.bandits.carry
    food = min(carried, leg.load.get("food", 0))
    band.food += food  # the wood they take they burn: it feeds nobody (as in a raid)
    events = results[leg.realm].events
    events.append(Event("caravan_robbed", {"leg": leg.side, "goods": dict(leg.load), "band": band.id,
                                           "adults": band.adults, "week": week, "x": tile[0], "y": tile[1]}))
    if (leg.realm, band.id) not in seen:
        seen.add((leg.realm, band.id))
        events.append(Event("band_seen", {"band": band.id, "adults": band.adults, "week": week,
                                          "x": band.x, "y": band.y, "tower": False, "road": True}))


def walk_caravans(legs: list[Leg], pool, roads, market, results: dict, config: Config, week: int,
                  seen: set[tuple[str, int]]) -> None:
    """@brief One week of every leg still on the road, after the bands walked.
    @param seen (realm, band id) pairs already seen this month (engine/bands.py _sightings)."""
    rules = config.caravans
    for leg in legs:
        if leg.done:
            continue
        crossed = _step(leg, roads, rules.speed)
        band = _band_met(crossed, pool.bands, rules.radius) if crossed else None
        if band is not None:
            tile = min(crossed, key=lambda t: hex_distance(band.x, band.y, *t))  # where they met
            _rob(leg, band, tile, market, results, config, week, seen)
        elif leg.index == len(leg.path) - 1 or not leg.path:
            _arrive(leg, market, results, week)


def finish_caravans(legs: list[Leg], market, results: dict, config: Config) -> None:
    """@brief The month's end: a leg whose road is longer than the month arrives anyway."""
    for leg in legs:
        if not leg.done:
            _arrive(leg, market, results, config.bands.weeks)
