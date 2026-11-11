"""@brief Tools: farms, sawmills and quarries improved in steps (after game 38,
2026-11-12). How much do they give, what do they cost, how many hands do
they free?

Usage: docker compose run --rm -T tests python lab/village_tools.py [careful | staff | invest <hands> | trace <variant> <site>]
       (no argument: every variant under game 38's conditions; "careful":
       under the careful policy alone; "staff": game 38's conditions with 12
       adults off the work instead of 8; "invest": game 38's conditions with
       <hands> saving hands from April to September, whatever the granary;
       "trace": month by month of one site)

Why: in 38 games only 4 realms built a second sawmill or quarry, and none
filled it. A building only offers jobs; the output is the hands times the
land's yield, and 80-88 % of the adults stand on the fields (100 people eat
about 860 food a month, a fair farmer grows 16). More buildings add places,
not output. An improvement raises the yield of the hands already there: it
frees hands (for guards, merchants, a future temple, growth) and gives wood
and stone a use, so a second sawmill or quarry can pay.

The engine has no improvements yet. The lab adds them around it:
- an improvement is bought for one active building, takes BUILD_MONTHS and
  then raises the yield of the workers in it by the level's percent; the
  workers fill the best-equipped buildings first;
- each improved level adds stone upkeep (taken from the stock before the
  month; the careful policy adds quarry hands for it);
- the policy buys one improvement at a time: farms first, up to the
  variant's top level, then sawmills, then quarries (T7-T8: the quarry
  first); it buys when the stock
  keeps BUILDING_STOCK wood and stone and two months of gold costs after the
  price, and the wood also keeps the firewood to the end of the next
  winter; every building of a kind reaches a level before the first goes
  to the next; while it waits for wood or stone it moves SAVING_HANDS from the
  fields to that work, only from April to September and with 2 months of
  food in the granary.

The rest is lab/second_winter.py: the careful policy of lab/village_years.py
and game 37-38's conditions (the people's rule, tax 7, the R2 ration rule,
three raids in year 1, 8 adults off the work from April).

Printed per site: the end (or the month of the fall), people at month 36,
months on the reduced ration in years 2-3, the improvements bought (farm /
sawmill / quarry levels, the month of the first), the wood and stone spent
on them, and the spare hands at month 36: adults - militia - sawmill and
quarry hands - the farmers needed to feed everyone on the normal ration at
the yearly average yield. Spare hands are what an improvement frees.

Limits: no market (rich stone cannot be sold for the farms' tools), no
council, no petitions, no doors; the levels are bought in a fixed order.
"""

import copy
import dataclasses
import math
import sys

from engine import load_config, new_game, resolve_turn
from engine import turn as engine_turn
from engine.people import PeopleChoice, rule_choice
from engine.turn import monthly_upkeep
from lab.second_winter import ALL, RAID_FOOD, RAID_MONTHS, STAFF_FROM, Conditions
from lab.second_winter import _orders as winter_orders
from lab.village_years import (BUILDING_STOCK, SALARY, SEED, UNREST_ORDER, _firewood_ahead, _normal_need,
                               _output)

MONTHS = 36
BUILD_MONTHS = 2
SAVING_HANDS = 2
SAVING_FOOD_MONTHS = 2  # the saving hands leave the fields only with this much food in the granary
SECTORS = {"farm": "food", "sawmill": "wood", "quarry": "stone"}
ORDER = ("farm", "sawmill", "quarry")  # the columns of the printed levels


@dataclasses.dataclass(frozen=True)
class Step:
    """@brief One improvement level of one building kind."""
    bonus_pct: int  # yield of its workers, over the land's (cumulative: level 2 replaces level 1)
    wood: int
    stone: int
    gold: int


@dataclasses.dataclass(frozen=True)
class Tools:
    """@brief A candidate tech tree: the steps of each kind, the upkeep."""
    steps: dict  # kind -> tuple of Step, level 1 first
    stone_per_level: int = 1  # monthly stone upkeep of each improved level
    order: tuple = ("farm", "sawmill", "quarry")  # which kind the policy improves first


# ------------------------------------------------------------ the lab's own state of a run

LEVELS: dict[int, int] = {}  # building id -> level reached
PENDING: list = []  # [building id, level, months left] while one is being made
TOOLS: Tools | None = None


def _bonus(kind: str, level: int) -> int:
    return TOOLS.steps[kind][level - 1].bonus_pct if level else 0


def _ranked(state, config, sector):
    """@brief (jobs, bonus %) of the active buildings of a sector, the best-equipped first."""
    places = [(config.buildings[b.kind].jobs, _bonus(b.kind, LEVELS.get(b.id, 0)))
              for b in state.buildings if b.turns_left == 0 and config.buildings[b.kind].sector == sector]
    return sorted(places, key=lambda place: -place[1])


def _sector_output_with_tools(state, config, sector, building_kind, upkeep_paid, effort_pct=0, worn_pct=0):
    """@brief The engine's output, raised by the workers standing in improved buildings."""
    output = ENGINE_SECTOR_OUTPUT(state, config, sector, building_kind, upkeep_paid, effort_pct, worn_pct)
    employed = min(getattr(state.workers, sector), engine_turn.jobs_in_sector(state, config, sector))
    if TOOLS is None or employed == 0:
        return output
    bonus, left = 0, employed
    for jobs, pct in _ranked(state, config, sector):
        taken = min(left, jobs)
        bonus += taken * pct
        left -= taken
    return output * (employed * 100 + bonus) // (employed * 100)


ENGINE_SECTOR_OUTPUT = engine_turn._sector_output
engine_turn._sector_output = _sector_output_with_tools  # _produce looks it up by name


# ------------------------------------------------------------ the policy

def _levels_total() -> int:
    return sum(LEVELS.values())


def _next_target(state):
    """@brief (building, its next Step) of the next improvement, or None at the top."""
    for kind in TOOLS.order:
        steps = TOOLS.steps.get(kind, ())
        for level in range(len(steps)):  # every farm to level 1 before the first to level 2
            for building in state.buildings:
                if building.kind == kind and not building.turns_left and LEVELS.get(building.id, 0) == level:
                    return building, level + 1, steps[level]
    return None


def _reserve_gold(state, config):
    return 2 * (monthly_upkeep(state, config) + state.council_salary)


def _buy(state, config, run, month):
    """@brief Start the next improvement if the stock allows. @return The short good, or None."""
    if PENDING:
        return None
    target = _next_target(state)
    if target is None:
        return None
    building, level, step = target
    # Why the firewood: in the first run the poor-wood site bought tools in
    # January with its start wood and fell to the cold.
    if state.wood < step.wood + BUILDING_STOCK + _firewood_ahead(state, config):
        return "wood"
    if state.stone < step.stone + BUILDING_STOCK:
        return "stone"
    if state.gold < step.gold + _reserve_gold(state, config):
        return None
    state.wood -= step.wood
    state.stone -= step.stone
    state.gold -= step.gold
    run.wood_spent += step.wood
    run.stone_spent += step.stone
    run.first = run.first or month
    PENDING.append([building.id, level, BUILD_MONTHS])
    return None


def _advance_pending():
    if PENDING:
        PENDING[0][2] -= 1
        if PENDING[0][2] <= 0:
            building_id, level, _ = PENDING.pop()
            LEVELS[building_id] = level


def _move_hands(orders, state, config, short):
    """@brief Extra quarry hands for the tools' upkeep; SAVING_HANDS to the short good in summer."""
    extra_stone = math.ceil(_levels_total() * TOOLS.stone_per_level / _output(state, config, "stone", "quarry"))
    month = (state.turn - 1) % 12 + 1
    saving = short and 4 <= month <= 9 and state.food >= SAVING_FOOD_MONTHS * _normal_need(state, config)
    fixed = []
    for order in orders:
        if order.action == "assign_workers":
            add = {"wood": 0, "stone": extra_stone}
            if saving:
                add[short] += SAVING_HANDS
            jobs = {s: engine_turn.jobs_in_sector(state, config, s) for s in ("wood", "stone")}
            wood = min(order.wood + add["wood"], jobs["wood"])
            stone = min(order.stone + add["stone"], jobs["stone"])
            moved = (wood - order.wood) + (stone - order.stone)
            order = order.model_copy(update={"wood": wood, "stone": stone, "food": max(0, order.food - moved)})
        fixed.append(order)
    return fixed


def _farmers_needed(state, config):
    """@brief Farmers feeding everyone on the normal ration at the yearly average yield."""
    need, grown, farmers = _normal_need(state, config), 0, 0
    per_farmer = _output(state, config, "food", "farm")
    for jobs, pct in _ranked(state, config, "food") + [(10 ** 6, 0)]:  # beyond the farms: no tools
        for _ in range(jobs):
            if grown >= need:
                return farmers
            grown += per_farmer * (100 + pct) / 100
            farmers += 1
    return farmers


# ------------------------------------------------------------ a run

@dataclasses.dataclass
class Run:
    reduced: int = 0
    first: int = 0
    wood_spent: int = 0
    stone_spent: int = 0
    stone_short: int = 0
    unrest: str = "calm"
    end: str = ""
    people: int = 0
    spare: int = 0
    levels: str = ""


def play(config, site, cond, tools, trace=False):
    global TOOLS
    TOOLS = tools
    LEVELS.clear()
    PENDING.clear()
    state = new_game(config, SEED, site)
    state.council_salary = SALARY
    run = Run()
    for index in range(MONTHS):
        month = index + 1
        if cond.staff and month >= STAFF_FROM:
            state.militia = cond.staff_count
        if cond.raids and month in RAID_MONTHS:
            state.food = max(0, state.food - RAID_FOOD)
        orders = winter_orders(state, config, cond)
        if tools is not None:
            _advance_pending()
            state.stone = max(0, state.stone - _levels_total() * tools.stone_per_level)
            short = _buy(state, config, run, month)
            orders = _move_hands(orders, state, config, short)
        people = None
        if cond.people:
            effort, births = rule_choice(state, config)
            people = PeopleChoice(effort_pct=effort, birth_pct=births)
        result = resolve_turn(state, orders, config, people)
        state = result.state
        run.stone_short += any(e.kind == "stone_upkeep_short" for e in result.events)
        if month > 12:
            run.reduced += state.ration == "reduced"
        if UNREST_ORDER.index(state.unrest) > UNREST_ORDER.index(run.unrest):
            run.unrest = state.unrest
        spare = (state.adults - state.militia - state.workers.wood - state.workers.stone
                 - _farmers_needed(state, config))
        if trace:
            print(f"  {month:2} food {state.food:5} {state.ration:8} wood {state.wood:4} stone {state.stone:4}"
                  f" gold {state.gold:4} F/W/S {state.workers.food:2}/{state.workers.wood:2}/{state.workers.stone:2}"
                  f" adults {state.adults:3} spare {spare:3} levels {_level_text(state)} mood {state.mood:3} {state.unrest}")
        if state.game_over:
            run.end = f"{state.game_over} at {month}"
            break
    run.people = state.population()
    run.spare = spare
    run.levels = _level_text(state)
    run.end = run.end or "standing"
    return run


def _level_text(state):
    return "/".join(str(sum(LEVELS.get(b.id, 0) for b in state.buildings if b.kind == kind)) for kind in ORDER)


def run_all(label, config, cond, tools):
    print(f"\n== {label}")
    print("site | end | people m36 | reduced y2-3 | levels F/W/S (first month) | wood, stone spent | stone short | spare hands m36")
    standing, spare_total, people_total = 0, 0, 0
    for site, levels in enumerate(config.map.site_levels):
        r = play(copy.deepcopy(config), site, cond, tools)
        standing += r.end == "standing"
        spare_total += r.spare
        people_total += r.people
        tag = "/".join(level[0].upper() for level in levels)
        print(f"{site} {tag} | {r.end:<16} | {r.people:3} | {r.reduced:2} | {r.levels:7} ({r.first:2})"
              f" | {r.wood_spent:4} {r.stone_spent:4} | {r.stone_short:2} | {r.spare:3}")
    count = len(config.map.site_levels)
    print(f"-> standing at month {MONTHS}: {standing} of {count}; mean people {people_total / count:.0f},"
          f" mean spare hands {spare_total / count:.1f}")


# ------------------------------------------------------------ the candidate trees

def _scaled(steps, cost_pct):
    return tuple(Step(s.bonus_pct, s.wood * cost_pct // 100, s.stone * cost_pct // 100, s.gold * cost_pct // 100)
                 for s in steps)


FARM_1 = (Step(25, 60, 40, 20),)  # heavy plough
FARM_2 = FARM_1 + (Step(50, 100, 100, 40),)  # and the mill
SAWMILL_2 = (Step(50, 40, 40, 10), Step(100, 80, 80, 30))  # iron axes, then the water saw
QUARRY_2 = (Step(50, 60, 20, 10), Step(100, 100, 60, 30))  # iron tools, then the winch


def variants():
    full = {"farm": FARM_2, "sawmill": SAWMILL_2, "quarry": QUARRY_2}
    return {
        "T0 no tools (today)": None,
        "T1 farm level 1 (+25 %, 60 wood 40 stone 20 gold)": Tools({"farm": FARM_1}),
        "T2 farm levels 1-2 (+25 %, then +50 %: 100 wood 100 stone 40 gold)": Tools({"farm": FARM_2}),
        "T3 all three, two levels each": Tools(full),
        "T4 = T3 at half the price": Tools({k: _scaled(v, 50) for k, v in full.items()}),
        "T5 = T3 at double the price": Tools({k: _scaled(v, 200) for k, v in full.items()}),
        "T6 = T3 with no stone upkeep": Tools(full, stone_per_level=0),
        "T7 = T3, the quarry first": Tools(full, order=("quarry", "farm", "sawmill")),
        "T8 = T3 at half the price, the quarry first": Tools({k: _scaled(v, 50) for k, v in full.items()},
                                                           order=("quarry", "farm", "sawmill")),
    }


def main():
    base = load_config()
    trees = variants()
    if sys.argv[1:2] == ["trace"]:
        label = next(k for k in trees if k.startswith(sys.argv[2]))
        print(label)
        play(base, int(sys.argv[3]), Conditions(**ALL), trees[label], trace=True)
        return
    if sys.argv[1:2] == ["invest"]:  # a bolder player: more hands saving, whatever the granary
        global SAVING_HANDS, SAVING_FOOD_MONTHS
        SAVING_HANDS, SAVING_FOOD_MONTHS = int(sys.argv[2]), 0
        cond, title = Conditions(**ALL), f"game 38's conditions, {SAVING_HANDS} hands saving from April to September"
    elif sys.argv[1:] == ["careful"]:
        cond, title = Conditions(), "careful policy alone"
    elif sys.argv[1:] == ["staff"]:
        cond, title = Conditions(**ALL, staff_count=12), "game 38's conditions, 12 off the work"
    else:
        cond, title = Conditions(**ALL), "game 38's conditions"
    for label, tools in trees.items():
        run_all(f"{label} | {title}", base, cond, tools)


if __name__ == "__main__":
    main()
