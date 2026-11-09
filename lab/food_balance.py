"""@brief Food balance lab of the village: does a realm rich in food have a
surplus to sell, and how short is a poor one? (after game 27, 2026-11-09).

Usage: docker compose run --rm -T tests python lab/food_balance.py

Why: in game 27 no realm ever held a month of eating in summer (Aurelia,
rich in food, 500-700 against 900 a month), so the automatic sovereign's
food check never let anyone sell food, and Brenna, poor in food, fell.

Each of the 8 sites plays 24 months alone on the real engine (resolve_turn,
no market, no claims) with one sensible fixed policy:
- ration: reduced below 1 month of food at the normal ration, normal
  again above 1.5 (the steward of lab/territory_balance.py);
- workers: 4 on wood, 3 on stone, every other adult on the fields up to
  the farm jobs;
- building: a farm when the fields have no room for the adults and wood
  and stone allow it, else a house when housing runs short;
- tax 8 %, salaries 6 (a council of three).

Printed per site and year: food produced, eaten, spoiled, the balance at the
normal ration, months on the reduced ration, famine months, the lowest and
highest stock, and "sellable": lots of food that leave a month of eating
after the sale at the end of a month from April to September (what the
sovereign's food check lets through outside winter).

Variants change one lever at a time: the farms' output by land level, the
food an adult eats, the autumn harvest.

Limits: a fixed policy is not a council; no market, so a poor realm cannot
buy and a rich one cannot sell (the lab measures what there would be to
trade). Production is the stock change plus what was eaten and spoiled.
"""

import copy
import dataclasses

from engine import load_config, new_game, parse_order, resolve_turn
from engine.territory import find_place
from engine.turn import food_needed, housing_capacity, jobs_in_sector

MONTHS = 24
SEED = 7
SALARY = 6
TAX = 8
HANDS = {"wood": 4, "stone": 3}
SELL_MONTHS = (4, 5, 6, 7, 8, 9)  # April to September: outside the sovereign's winter watch
LOT = 50


def _order(raw):
    order, code, message = parse_order(raw)
    assert order is not None, (raw, code, message)
    return order


def _normal_need(state, config):
    normal = copy.deepcopy(state)
    normal.ration = "normal"
    return food_needed(normal, config)


def _orders(state, config):
    orders = []
    months = state.food / max(1, _normal_need(state, config))
    if state.ration == "normal" and months < 1:
        orders.append(_order({"action": "set_ration", "ration": "reduced"}))
    elif state.ration == "reduced" and months > 1.5:
        orders.append(_order({"action": "set_ration", "ration": "normal"}))
    hands_free = state.adults - HANDS["wood"] - HANDS["stone"]
    farmers = max(0, min(jobs_in_sector(state, config, "food"), hands_free))
    orders.append(_order({"action": "assign_workers", "food": farmers, **HANDS}))
    farm, house = config.buildings["farm"], config.buildings["house"]
    if hands_free > jobs_in_sector(state, config, "food") and find_place(state, config, "farm") \
            and state.wood >= farm.wood + 50 and state.stone >= farm.stone + 20:
        orders.append(_order({"action": "build", "building": "farm"}))
    elif housing_capacity(state, config) - state.population() < 10 and state.wood >= house.wood + 50 \
            and state.stone >= house.stone + 20 and state.gold >= house.gold + 40:
        orders.append(_order({"action": "build", "building": "house"}))
    return orders


@dataclasses.dataclass
class Year:
    produced: int = 0
    eaten: int = 0
    spoiled: int = 0
    normal_need: int = 0
    reduced_months: int = 0
    famine_months: int = 0
    lowest: int = 10 ** 9
    highest: int = 0
    sellable: int = 0


def _eaten(need, events):
    famine = next((e for e in events if e.kind == "famine"), None)
    return need if famine is None else need * (100 - famine.data["missing_pct"]) // 100


def play(config, site):
    """@brief 24 months of one site; returns ([year 1, year 2], end note)."""
    state = new_game(config, SEED, site)
    state.council_salary = SALARY
    state.tax_rate = TAX
    years = [Year(), Year()]
    for month_index in range(MONTHS):
        year = years[month_index // 12]
        need = food_needed(state, config)
        year.normal_need += _normal_need(state, config)
        result = resolve_turn(state, _orders(state, config), config)
        after = result.state
        eaten = _eaten(need, result.events)
        spoiled = sum(e.data["amount"] for e in result.events if e.kind == "food_spoiled")
        year.produced += after.food - state.food + eaten + spoiled
        year.eaten += eaten
        year.spoiled += spoiled
        year.reduced_months += after.ration == "reduced"
        year.famine_months += any(e.kind == "famine" for e in result.events)
        year.lowest, year.highest = min(year.lowest, after.food), max(year.highest, after.food)
        if month_index % 12 + 1 in SELL_MONTHS and not after.game_over:
            year.sellable = max(year.sellable, (after.food - _normal_need(after, config)) // LOT)
        state = after
        if state.game_over:
            return years, f"{state.game_over} at month {month_index + 1}"
    return years, f"adults {state.adults}, farms {sum(b.kind == 'farm' for b in state.buildings)}"


def _levels(config, food):
    return dataclasses.replace(config, levels=dataclasses.replace(config.levels, food=food))


def _economy(config, **changes):
    return dataclasses.replace(config, economy=dataclasses.replace(config.economy, **changes))


def main():
    base = load_config()
    variants = {
        "today (food poor 14, fair 15, rich 18)": base,
        "fair +1 (15, 16, 19)": _levels(base, {"poor": 15, "fair": 16, "rich": 19}),
        "fair +2 (16, 17, 20)": _levels(base, {"poor": 16, "fair": 17, "rich": 20}),
        "rich only (14, 15, 20)": _levels(base, {"poor": 14, "fair": 15, "rich": 20}),
        "adults eat 9 (was 10)": _economy(base, food_per_adult=9),
        "autumn 150 % (was 130)": _economy(base, farm_autumn_pct=150),
    }
    for label, config in variants.items():
        print(f"\n== {label}")
        print("site level | year: produced eaten spoiled balance@normal | reduced famine | low high | sellable lots | end")
        for site, levels in enumerate(config.map.site_levels):
            years, end = play(copy.deepcopy(config), site)
            cells = []
            for number, year in enumerate(years, 1):
                if year.normal_need == 0:
                    continue
                cells.append(f"y{number}: {year.produced:5} {year.eaten:5} {year.spoiled:3} {year.produced - year.spoiled - year.normal_need:+5}"
                             f" | {year.reduced_months:2} {year.famine_months:2} | {year.lowest:4} {year.highest:4} | {year.sellable:2}")
            print(f"{site} {levels[0]:<4} | " + " || ".join(cells) + f" | {end}")


if __name__ == "__main__":
    main()
