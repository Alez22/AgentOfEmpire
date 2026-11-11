"""@brief The village in three years: does a sensible realm survive the second
winter, and how far can it grow? (after game 34, 2026-11-11).

Usage: docker compose run --rm -T tests python lab/village_years.py [all]
       (no argument: today's values only; "all": also the variants)

Why: in game 34 every realm fell, two of them in the second winter, and no
realm grew past 112 people while the gate of the town asks about 200. Births
are 15 a month per 1000 adults: about +6-7 people a year, so the gate is
about 12 years away even for a perfect player.

Each of the 8 sites plays 36 months alone on the real engine (resolve_turn:
no market, no bandits, no arrivals, no council; the people's decisions are
left at the middle). One sensible fixed policy, a careful player, not a
perfect one:
- ration: reduced below 1 month of food at the normal ration, normal again
  above 1.5 (as lab/food_balance.py);
- tax: the lowest rate that covers upkeep and salaries, never below the
  free rate (no mood cost up to it);
- stone: enough quarry hands for the upkeep, 2 more while the stock is under
  6 months of upkeep plus a building;
- wood: enough sawmill hands for a year of firewood and building, 2 more
  while the stock is under the firewood of the months left to the end of the
  next winter plus a building;
- every other adult on the fields up to the farm jobs;
- a farm when the fields are full and there is room, else a house when fewer
  than 10 beds are free.

Printed per site and year: people at the year's end, births and deaths,
months on the reduced ration, famine months, months short of stone and of
firewood, the lowest food of the year's winter (January-March), the worst
unrest, and the end (or the month of the fall).

Limits: a fixed policy does not trade, so poor sites are more fragile than
in a game with a market; no claims, so growth stops when the core's room
for farms and houses runs out.
"""

import copy
import dataclasses
import math
import sys

from engine import load_config, new_game, parse_order, resolve_turn
from engine.territory import find_place
from engine.turn import (firewood_needed, food_needed, housing_capacity, jobs_in_sector, monthly_upkeep,
                         stone_upkeep)

MONTHS = 36
SEED = 7
SALARY = 6  # a council of three
STONE_KEEP_MONTHS = 6
BUILDING_STOCK = 30  # wood and stone kept for the next building
FREE_BEDS = 10
UNREST_ORDER = ("calm", "protests", "strike", "revolt")


def _order(raw):
    order, code, message = parse_order(raw)
    assert order is not None, (raw, code, message)
    return order


def _normal_need(state, config):
    normal = copy.deepcopy(state)
    normal.ration = "normal"
    return food_needed(normal, config)


def _output(state, config, sector, building_kind):
    """@brief Output of one worker: the land level's, or the building's."""
    level = state.land_levels.get(sector)
    if level is None or config.levels is None:
        return config.buildings[building_kind].output_per_worker
    return getattr(config.levels, sector)[level]


def _firewood_ahead(state, config):
    """@brief Firewood from this month to the end of the next winter (March)."""
    month = (state.turn - 1) % 12 + 1
    months_left = (15 - month) % 12 + 1  # this month up to the next March
    later = copy.copy(state)
    total = 0
    for step in range(months_left):
        later.turn = state.turn + step
        total += firewood_needed(later, config)
    return total


def _stone_hands(state, config):
    upkeep = stone_upkeep(state, config)
    hands = math.ceil(upkeep / _output(state, config, "stone", "quarry"))
    if state.stone < upkeep * STONE_KEEP_MONTHS + BUILDING_STOCK:
        hands += 2
    return min(hands, jobs_in_sector(state, config, "stone"))


def _wood_hands(state, config):
    later = copy.copy(state)
    yearly = 0
    for step in range(12):
        later.turn = state.turn + step
        yearly += firewood_needed(later, config)
    hands = math.ceil((yearly + BUILDING_STOCK) / 12 / _output(state, config, "wood", "sawmill"))
    if state.wood < _firewood_ahead(state, config) + BUILDING_STOCK:
        hands += 2
    return min(hands, jobs_in_sector(state, config, "wood"))


def _tax(state, config):
    """@brief The lowest rate covering upkeep and salaries (gold = adults * rate / divisor)."""
    costs = monthly_upkeep(state, config) + state.council_salary
    rate = math.ceil(costs * config.economy.tax_divisor / max(1, state.adults))
    return max(config.mood.tax_free_rate, min(rate, config.economy.max_tax_rate))


def _can_build(state, config, kind):
    building = config.buildings[kind]
    return (find_place(state, config, kind) is not None and state.wood >= building.wood + BUILDING_STOCK
            and state.stone >= building.stone + BUILDING_STOCK and state.gold >= building.gold)


def _orders(state, config):
    orders = []
    months = state.food / max(1, _normal_need(state, config))
    if state.ration == "normal" and months < 1:
        orders.append(_order({"action": "set_ration", "ration": "reduced"}))
    elif state.ration == "reduced" and months > 1.5:
        orders.append(_order({"action": "set_ration", "ration": "normal"}))
    rate = _tax(state, config)
    if rate != state.tax_rate:
        orders.append(_order({"action": "set_tax", "rate": rate}))
    stone, wood = _stone_hands(state, config), _wood_hands(state, config)
    hands_free = max(0, state.adults - stone - wood)
    farmers = min(jobs_in_sector(state, config, "food"), hands_free)
    orders.append(_order({"action": "assign_workers", "food": farmers, "wood": wood, "stone": stone}))
    if hands_free > jobs_in_sector(state, config, "food") and _can_build(state, config, "farm"):
        orders.append(_order({"action": "build", "building": "farm"}))
    elif housing_capacity(state, config) - state.population() < FREE_BEDS and _can_build(state, config, "house"):
        orders.append(_order({"action": "build", "building": "house"}))
    return orders


@dataclasses.dataclass
class Year:
    people: int = 0
    births: int = 0
    deaths: int = 0
    reduced: int = 0
    famine: int = 0
    stone_short: int = 0
    cold: int = 0
    winter_low: int = 10 ** 9
    unrest: str = "calm"
    mood_low: int = 1000


def play(config, site):
    """@brief 36 months of one site. @return ([year 1, 2, 3], end note, people at month 30)."""
    state = new_game(config, SEED, site)
    state.council_salary = SALARY
    years = [Year() for _ in range(MONTHS // 12)]
    people_30 = None
    for index in range(MONTHS):
        year = years[index // 12]
        result = resolve_turn(state, _orders(state, config), config)
        state = result.state
        kinds = {e.kind: e.data for e in result.events}
        demography = kinds.get("demography", {})
        year.births += demography.get("births", 0)
        year.deaths += demography.get("deaths", 0)
        year.reduced += state.ration == "reduced"
        year.famine += "famine" in kinds
        year.stone_short += "stone_upkeep_short" in kinds
        year.cold += "firewood_short" in kinds
        if index % 12 < 3:
            year.winter_low = min(year.winter_low, state.food)
        if UNREST_ORDER.index(state.unrest) > UNREST_ORDER.index(year.unrest):
            year.unrest = state.unrest
        year.mood_low = min(year.mood_low, state.mood)
        year.people = state.population()
        if index + 1 == 30:
            people_30 = state.population()
        if state.game_over:
            return years[:index // 12 + 1], f"{state.game_over} at month {index + 1}", people_30
    houses = sum(b.kind == "house" for b in state.buildings)
    farms = sum(b.kind == "farm" for b in state.buildings)
    return years, f"farms {farms} houses {houses} mood {state.mood}", people_30


def run(label, config):
    print(f"\n== {label}")
    print("site F/W/S | per year: people (births-deaths) reduced famine stone-short cold | winter low | worst unrest, lowest mood | end")
    standing, best_30 = 0, 0
    for site, levels in enumerate(config.map.site_levels):
        years, end, people_30 = play(copy.deepcopy(config), site)
        cells = [f"y{n}: {y.people:3} (+{y.births}-{y.deaths}) {y.reduced:2} {y.famine:2} {y.stone_short:2} {y.cold:2}"
                 f" | {y.winter_low:5} | {y.unrest:<8} {y.mood_low:3}" for n, y in enumerate(years, 1)]
        standing += "at month" not in end
        best_30 = max(best_30, people_30 or 0)
        tag = "/".join(level[0].upper() for level in levels)
        print(f"{site} {tag} | " + " || ".join(cells) + f" | {end}")
    print(f"-> standing at month {MONTHS}: {standing} of {len(config.map.site_levels)};"
          f" most people at month 30: {best_30}")


def _replace(config, part, **changes):
    return dataclasses.replace(config, **{part: dataclasses.replace(getattr(config, part), **changes)})


def variants(base):
    food_plus_one = {level: value + 1 for level, value in base.levels.food.items()}
    return {
        "A: births +50 % (15 -> 22 per 1000 adults a month)":
            _replace(base, "demography", birth_permille_per_adult=22),
        "B: the birth bonus from mood 550 (was 700)":
            _replace(base, "demography", high_mood_births_above=550),
        "C: stone upkeep halved (1 per 2 buildings)":
            _replace(base, "needs", stone_upkeep_buildings=2 * base.needs.stone_upkeep_buildings),
        "D: food yields +1 (" + ", ".join(f"{k} {v}" for k, v in food_plus_one.items()) + ")":
            _replace(base, "levels", food=food_plus_one),
        "E: start food +1000 (1600 -> 2600)":
            _replace(base, "start", food=base.start.food + 1000),
    }


def main():
    base = load_config()
    run("today", base)
    if sys.argv[1:] == ["all"]:
        for label, config in variants(base).items():
            run(label, config)


if __name__ == "__main__":
    main()
