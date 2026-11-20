"""@brief The passage to the town: do careful realms reach the town hall, and
do they survive its site? (2026-11-20, after game 46; docs/DESIGN.md "The
town hall site").

Usage: docker compose run --rm -T tests python lab/town_hall_passage.py [all]
       (no argument: the careful policy alone; "all": also with game 46's
       conditions: the people, tax 7, raids, 8 adults off the work)

Each of the 8 sites plays 48 months alone on the real engine with the
careful policy of lab/second_winter.py and the winter rule (the ration
follows the automatic sovereign's winter check, as R2d now asks). The market
is given finished at month 6 (no merchants: only the condition is in play).
The town hall is ordered the first month R14's test passes
(server/sovereign/rules.town_hall_ready: conditions, cost, food, firewood and
stone upkeep); the policy's farmers then fit the adults left.

Printed per site: people at month 30, the month the site opened (and what
was missing at month 30), the month the town was reached, the lowest food
during the site, the end.

Limits: no council, no petitions, no market trade, no doors; the merchants'
hands are not taken.
"""

import copy
import sys

from engine import eras, load_config, new_game, resolve_turn
from engine.people import PeopleChoice, rule_choice
from engine.state import Building
from engine.territory import find_place
from engine.turn import jobs_in_sector
from lab.second_winter import ALL, RAID_FOOD, RAID_MONTHS, STAFF_FROM, Conditions, _orders
from lab.village_years import SALARY, SEED, _order
from server.sovereign import rules

MONTHS = 48
MARKET_MONTH = 6


def _give_market(state, config):
    place = find_place(state, config, "market")
    state.buildings.append(Building("market", 0, state.next_building_id, *place))
    state.next_building_id += 1


def _fit_farmers(orders, state):
    """@brief The policy counts every adult; the builders and guards are not free."""
    fitted = []
    for order in orders:
        if order.action == "assign_workers":
            room = max(0, state.free_adults() - order.wood - order.stone)
            order = order.model_copy(update={"food": min(order.food, room)})
        fitted.append(order)
    return fitted


SAVE_FROM = 24  # the saving lever: from month 24, hands moved from the fields to quarry and woods
SAVE_STONE, SAVE_WOOD = 3, 2


def _save_for_the_site(orders, state, config):
    """@brief A council that plans the town hall: a few more quarrymen and
    woodcutters, taken from the farmers, while the site is not open yet."""
    saved = []
    for order in orders:
        if order.action == "assign_workers":
            stone = min(order.stone + SAVE_STONE, jobs_in_sector(state, config, "stone"))
            wood = min(order.wood + SAVE_WOOD, jobs_in_sector(state, config, "wood"))
            moved = (stone - order.stone) + (wood - order.wood)
            order = order.model_copy(update={"stone": stone, "wood": wood, "food": max(0, order.food - moved)})
        saved.append(order)
    return saved


def _cost_in_store(state, config):
    spec = config.town_hall
    return state.wood >= spec.wood and state.stone >= spec.stone and state.gold >= spec.gold


def play(config, site, cond, save=False):
    state = new_game(config, SEED, site)
    state.council_salary = SALARY
    opened = reached = None
    people_30, missing_30 = None, ""
    site_low = None
    for month in range(1, MONTHS + 1):
        if month == MARKET_MONTH:
            _give_market(state, config)
        if cond.staff and month >= STAFF_FROM:
            state.militia = cond.staff_count
        if cond.raids and month in RAID_MONTHS:
            state.food = max(0, state.food - RAID_FOOD)
        people = None
        if cond.people:
            effort, births = rule_choice(state, config)
            people = PeopleChoice(effort_pct=effort, birth_pct=births)
        orders = _orders(state, config, cond)
        if save and month >= SAVE_FROM and opened is None:
            orders = _save_for_the_site(orders, state, config)
        if opened is None and rules.town_hall_ready(rules.Month(state, config, None, "lab"), orders):
            orders.append(_order({"action": "build", "building": "town_hall"}))
        if state.builders or any(o.action == "build" and o.building == "town_hall" for o in orders):
            orders = _fit_farmers(orders, state)
        result = resolve_turn(state, orders, config, people)
        state = result.state
        if opened is None and state.town_hall_site:
            opened = month
        if state.town_hall_site:
            site_low = state.food if site_low is None else min(site_low, state.food)
        if reached is None and state.era == "town":
            reached = month
        if month == 30:
            people_30 = state.population()
            missing_30 = "; ".join(eras.town_hall_missing(state, config)) or (
                "" if _cost_in_store(state, config)
                else f"the cost (wood {state.wood}, stone {state.stone}, gold {state.gold})")
        if state.game_over:
            return people_30, missing_30, opened, reached, site_low, f"{state.game_over} at month {month}"
    return people_30, missing_30, opened, reached, site_low, f"{state.population()} people, food {state.food}"


def run_all(label, config, cond, save=False):
    print(f"\n== {label}")
    print("site | people m30 | site opened | town reached | lowest food in the site | end | missing at m30")
    towns = 0
    for site, levels in enumerate(config.map.site_levels):
        people_30, missing, opened, reached, low, end = play(copy.deepcopy(config), site, cond, save)
        towns += reached is not None
        tag = "/".join(level[0].upper() for level in levels)
        print(f"{site} {tag} | {people_30} | {opened or '-'} | {reached or '-'} | {low if low is not None else '-'}"
              f" | {end} | {missing or '-'}")
    print(f"-> towns by month {MONTHS}: {towns} of {len(config.map.site_levels)}")


def main():
    base = load_config()
    run_all("careful + winter rule", base, Conditions(winter_rule=True))
    # The careful policy keeps the lowest tax and never sells: it saves no gold.
    run_all("careful + winter rule + tax 7 (saving for the site)", base, Conditions(winter_rule=True, tax=7))
    run_all(f"careful + winter rule + tax 7 + saving from month {SAVE_FROM} (+{SAVE_STONE} quarry, +{SAVE_WOOD} woods)",
            base, Conditions(winter_rule=True, tax=7), save=True)
    if sys.argv[1:] == ["all"]:
        run_all("game 46's conditions: people, tax 7, winter rule, raids, staff", base, Conditions(**ALL))
        run_all("game 46's conditions + saving", base, Conditions(**ALL), save=True)


if __name__ == "__main__":
    main()
