"""@brief Balance lab of the territory: scripted sovereigns, no models.

Usage: docker compose run --rm -T tests python lab/territory_balance.py

Three fixed policies play 36 months on the real engine under a few
variants of the [map] values:
- still: no claim, no felling (the old game on the new map);
- grower: claims plain to the south outside winter while it keeps a gold
  reserve, clears with 6 hands, builds a farm when one fits and a house
  when housing runs short;
- feller: puts 10 hands on felling the core's forest from the first month.
Printed per run: tiles owned, farms, lowest food, gold and wood at the
end, the month the fields first had no room, the month the sawmill stopped.

Limit: a fixed policy is not a council; it shows the pace and the edges,
not what a sensible Architect would do. The policies manage the ration
but build few houses, so they all end in revolt within three years (full
houses, as in the game without a map): read the numbers up to that month.
"""

import copy
import dataclasses

from engine import load_config, new_game, parse_order, resolve_turn
from engine.territory import claim_price, find_place, owned_count
from engine.turn import food_needed, housing_capacity, jobs_in_sector

MONTHS = 36
WINTER = (0, 1, 2, 11)  # month index (0 = January)
SEED = 42
GOLD_RESERVE = 40


def _variant(config, **changes):
    return dataclasses.replace(config, map=dataclasses.replace(config.map, **changes))


def _order(raw):
    order, code, message = parse_order(raw)
    assert order is not None, (raw, code, message)
    return order


def _southern_fields(state):
    """@brief A fields zone just south of the core, on land still to claim."""
    sx, sy = state.square[0] - 5, state.square[1] - 3
    zones = [dataclasses.asdict(zone) for zone in state.zones]
    zones.append({"name": "Campi del sud", "purpose": "fields", "x1": sx, "y1": sy + 12, "x2": sx + 8, "y2": sy + 17})
    return _order({"action": "set_zones", "zones": zones})


def _workers(state, config, clearing, wood=4, stone=2):
    food = min(jobs_in_sector(state, config, "food"), state.adults - wood - stone - clearing)
    return _order({"action": "assign_workers", "food": max(0, food), "wood": wood, "stone": stone,
                   "clearing": clearing})


def steward(state, config):
    """@brief The ration rule every policy shares, on the consumption at the
    normal ration: reduced below 1 month of food, normal again above 1.5."""
    normal = copy.deepcopy(state)
    normal.ration = "normal"
    months = state.food / max(1, food_needed(normal, config))
    if state.ration == "normal" and months < 1:
        return [_order({"action": "set_ration", "ration": "reduced"})]
    if state.ration == "reduced" and months > 1.5:
        return [_order({"action": "set_ration", "ration": "normal"})]
    return []


def grower_orders(state, config):
    month = (state.turn - 1) % 12
    orders = ([_southern_fields(state)] if state.turn == 1 else []) + steward(state, config)
    winter = month in WINTER
    clearing = 0 if winter or not state.clearing_queue else 6
    orders.append(_workers(state, config, clearing))
    if not winter and len(state.clearing_queue) < 8 and state.gold >= 4 * claim_price(state, config) + GOLD_RESERVE:
        orders.append(_order({"action": "claim_tiles", "direction": "south", "terrain": "plain", "count": 4}))
    if find_place(state, config, "farm") and state.wood >= 40 and state.stone >= 10:
        orders.append(_order({"action": "build", "building": "farm"}))
    elif housing_capacity(state, config) - state.population() < 10 and state.wood >= 30 and state.stone >= 30 \
            and state.gold >= 20 + GOLD_RESERVE:
        orders.append(_order({"action": "build", "building": "house"}))
    return orders


def feller_orders(state, config):
    orders = steward(state, config)
    if state.turn == 1:
        orders.append(_order({"action": "fell_forest", "count": 16}))
    orders.append(_workers(state, config, 10 if state.clearing_queue else 0))
    return orders


def still_orders(state, config):
    return steward(state, config)


def play(policy, config):
    state = new_game(config, SEED)
    lowest_food, no_room, sawmill_stopped = state.food, None, None
    for _ in range(MONTHS):
        result = resolve_turn(state, policy(state, config), config)
        state = result.state
        lowest_food = min(lowest_food, state.food)
        if no_room is None and find_place(state, config, "farm") is None:
            no_room = state.turn - 1
        if sawmill_stopped is None and jobs_in_sector(state, config, "wood") == 0:
            sawmill_stopped = state.turn - 1
        if state.game_over:
            break
    farms = sum(1 for b in state.buildings if b.kind == "farm")
    return (f"tiles {owned_count(state):>3} | farms {farms} | lowest food {lowest_food:>5} | gold {state.gold:>4}"
            f" | wood {state.wood:>4} | adults {state.adults:>3} | fields full at month {no_room}"
            f" | sawmill stopped at month {sawmill_stopped} | paid {state.land_paid_total}"
            f"{f' | {state.game_over} at month {state.turn - 1}' if state.game_over else ''}")


def main():
    base = load_config()
    variants = {
        "today (claim 20, plain 3, fell 10)": base,
        "older values (claim 10, plain 6, fell 5)": _variant(base, claim_base_gold=10, clear_work_plain=6,
                                                             fell_wood_per_work=5),
        "cheap land (claim 10)": _variant(base, claim_base_gold=10),
        "slow clearing (plain 6)": _variant(base, clear_work_plain=6),
    }
    for name, policy in (("still", still_orders), ("grower", grower_orders), ("feller", feller_orders)):
        print(f"\n== {name}")
        for label, config in variants.items():
            print(f"{label:<36} {play(policy, copy.deepcopy(config))}")


if __name__ == "__main__":
    main()
