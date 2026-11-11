"""@brief The second winter: why do sensible realms fall between January and
April of year 2? (after game 37, 2026-11-11).

Usage: docker compose run --rm -T tests python lab/second_winter.py [levers | trace <site>]
       (no argument: the careful policy and game 37's conditions one at a
       time; "levers": also the levers tried on all of game 37's conditions;
       "trace": month by month of one site under all the conditions)

Why: games 27, 28, 34 and 37 lost most realms the same way. The reduced
ration from October fills the granary, the mood sinks under the threshold
(350) by January, protests, a strike in March that cuts the spring harvest,
famine, revolt. Yet lab/village_years.py (a careful fixed policy) keeps every
site standing for 36 months. This lab looks for the difference.

Each of the 8 sites plays 24 months alone on the real engine, with the
careful policy of lab/village_years.py (ration reduced under 1 month of food,
normal above 1.5; the lowest tax covering the costs, never under the free
rate). Then game 37's conditions are added one at a time:
- people: the people's effort and births from the mood band (engine/people.py
  rule_choice, the fallback of the model); village_years leaves them at 0;
- tax 7 / tax 10: the council's usual rates instead of the lowest;
- R2 rule: the ration is normal while the food lasts with it, reduced
  otherwise (the automatic sovereign's check, food_lasts: October to March
  to the end of March, other months this month and one more), as the
  Treasurers and the automatic sovereign did in game 37 (normal all
  summer with 200-400 food, reduced from October);
- raids: three raids of 225 food in year 1 (months 1, 4, 7), as before the
  towers stood;
- staff: from April, 8 adults off the work (5 guards, 3 traders or clearers),
  as game 37's realms had from months 4-7 (4-6 guards, 2-6 traders, 4-8
  clearers); in the lab they stand as a militia of 8;
- all: everything together, the closest to game 37.

Printed per site: food at September and December of year 1, months on the
reduced ration in the second winter (October to March), months under the
threshold, the lowest mood, the worst unrest and the end (or the month of
the fall).

Limits: no market (game 37's realms could not buy anyway: the warehouse had
no grain from October), no council, no petitions, no doors.
"""

import copy
import dataclasses
import sys

from engine import load_config, new_game, resolve_turn
from engine.people import PeopleChoice, rule_choice
from engine.turn import monthly_upkeep
from lab.village_years import SALARY, SEED, UNREST_ORDER, _order
from lab.village_years import _orders as careful_orders
from server.sovereign.rules import Month, food_lasts, month_of

MONTHS = 24
RAID_FOOD = 225
RAID_MONTHS = (1, 4, 7)
STAFF_FROM = 4
STAFF = 8


@dataclasses.dataclass
class Conditions:
    """@brief Game 37's conditions switched on for a run, and the policy levers."""
    people: bool = False
    tax: int | None = None  # None: the careful policy's lowest rate
    winter_rule: bool = False
    raids: bool = False
    staff: bool = False
    staff_count: int = STAFF
    relief_tax: bool = False  # lever: the free tax rate while the ration is reduced
    feast: bool = False  # lever: a feast with the spare gold while the ration is reduced
    spread: bool = False  # lever: a normal month at the protests, if the food still reaches March


ALL = dict(people=True, tax=7, winter_rule=True, raids=True, staff=True)


def _ration_ok(state, config, ration, others):
    """@brief R2's check: does the food last (to the end of March in winter) with this ration?"""
    month = Month(state=state, config=config, market=None, realm_key="lab")
    return food_lasts(month, [_order({"action": "set_ration", "ration": ration})] + others)


def _lasts_spread(state, config, others):
    """@brief This month at the normal ration and the rest of the winter at the
    reduced one: is there food to the end of March?"""
    result = resolve_turn(state, [_order({"action": "set_ration", "ration": "normal"})] + others, config)
    later = result.state
    reduced = [_order({"action": "set_ration", "ration": "reduced"})]
    for _ in range((3 - month_of(state.turn)) % 12):
        if later.game_over or any(e.kind == "famine" for e in result.events):
            return False
        result = resolve_turn(later, reduced, config)
        later = result.state
    return not later.game_over and not any(e.kind == "famine" for e in result.events)


def _off_work(orders, state):
    """@brief The careful policy counts every adult; with a militia fewer are free: fewer farmers."""
    fixed = []
    for order in orders:
        if order.action == "assign_workers" and state.militia:
            room = max(0, state.free_adults() - order.wood - order.stone)
            order = order.model_copy(update={"food": min(order.food, room)})
        fixed.append(order)
    return fixed


def _orders(state, config, cond):
    orders = _off_work(careful_orders(state, config), state)
    if cond.winter_rule:
        others = [o for o in orders if o.action != "set_ration"]
        wanted = "normal" if _ration_ok(state, config, "normal", others) else "reduced"
        if wanted == "reduced" and cond.spread and state.unrest != "calm" and state.ration == "reduced":
            wanted = "normal" if _lasts_spread(state, config, others) else "reduced"
        orders = others + ([_order({"action": "set_ration", "ration": wanted})] if wanted != state.ration else [])
    reduced_next = any(o.action == "set_ration" and o.ration == "reduced" for o in orders) or (
        state.ration == "reduced" and not any(o.action == "set_ration" for o in orders))
    tax = cond.tax
    if cond.relief_tax and reduced_next:
        tax = config.mood.tax_free_rate
    if tax is not None:
        orders = [o for o in orders if o.action != "set_tax"]
        if tax != state.tax_rate:
            orders.append(_order({"action": "set_tax", "rate": tax}))
    if cond.feast and reduced_next:
        spare = state.gold - 2 * (monthly_upkeep(state, config) + state.council_salary)
        if spare >= 10:
            orders.append(_order({"action": "hold_feast", "gold": spare}))
    return orders


@dataclasses.dataclass
class Run:
    food_sep: int = 0
    food_dec: int = 0
    reduced_w2: int = 0
    under: int = 0
    mood_low: int = 1000
    unrest: str = "calm"
    end: str = ""


def play(config, site, cond, trace=False):
    state = new_game(config, SEED, site)
    state.council_salary = SALARY
    run = Run()
    for index in range(MONTHS):
        if cond.staff and index + 1 >= STAFF_FROM:
            state.militia = cond.staff_count
        if cond.raids and index + 1 in RAID_MONTHS:
            state.food = max(0, state.food - RAID_FOOD)
        people = None
        if cond.people:
            effort, births = rule_choice(state, config)
            people = PeopleChoice(effort_pct=effort, birth_pct=births)
        result = resolve_turn(state, _orders(state, config, cond), config, people)
        state = result.state
        month = index + 1
        if trace:
            print(f"  {month:2} food {state.food:5} {state.ration:8} tax {state.tax_rate:2} farmers {state.workers.food:2}"
                  f" people {state.population():3} mood {state.mood:3} low {state.low_mood_turns} {state.unrest}")
        if month == 9:
            run.food_sep = state.food
        if month == 12:
            run.food_dec = state.food
        if 10 <= month <= 15:
            run.reduced_w2 += state.ration == "reduced"
        run.under += state.mood < config.unrest.threshold
        run.mood_low = min(run.mood_low, state.mood)
        if UNREST_ORDER.index(state.unrest) > UNREST_ORDER.index(run.unrest):
            run.unrest = state.unrest
        if state.game_over:
            run.end = f"{state.game_over} at month {month}"
            return run
    run.end = f"{state.population()} people, food {state.food}"
    return run


def run_all(label, config, cond):
    print(f"\n== {label}")
    print("site | food Sep Dec | reduced Oct-Mar y2 | months <350 | lowest mood | worst unrest | end")
    standing = 0
    for site, levels in enumerate(config.map.site_levels):
        r = play(copy.deepcopy(config), site, cond)
        standing += "at month" not in r.end
        tag = "/".join(level[0].upper() for level in levels)
        print(f"{site} {tag} | {r.food_sep:5} {r.food_dec:5} | {r.reduced_w2} | {r.under:2} | {r.mood_low:3}"
              f" | {r.unrest:<8} | {r.end}")
    print(f"-> standing at month {MONTHS}: {standing} of {len(config.map.site_levels)}")


def _replace(config, part, **changes):
    return dataclasses.replace(config, **{part: dataclasses.replace(getattr(config, part), **changes)})


def main():
    base = load_config()
    if sys.argv[1:2] == ["trace"]:
        play(base, int(sys.argv[2]), Conditions(**ALL), trace=True)
        return
    run_all("careful (lab/village_years.py)", base, Conditions())
    run_all("+ people", base, Conditions(people=True))
    run_all("+ tax 7", base, Conditions(tax=7))
    run_all("+ tax 10", base, Conditions(tax=10))
    run_all("+ R2 rule (normal while the food lasts; from October, to March)", base, Conditions(winter_rule=True))
    run_all("+ raids (3 x 225 food in year 1)", base, Conditions(raids=True))
    run_all("+ staff (8 adults off the work from April)", base, Conditions(staff=True))
    run_all("all: people, tax 7, R2 rule, raids, staff", base, Conditions(**ALL))
    if sys.argv[1:] != ["levers"]:
        return
    run_all("all + L1 reduced ration -100 (was -150)",
            _replace(base, "mood", ration_reduced=-100), Conditions(**ALL))
    run_all("all + L2 the free tax rate while the ration is reduced", base, Conditions(**ALL, relief_tax=True))
    run_all("all + L3 a feast with the spare gold while the ration is reduced", base, Conditions(**ALL, feast=True))
    run_all("all + L4 strike output 85 % (was 70)",
            _replace(base, "unrest", strike_output_pct=85), Conditions(**ALL))
    run_all("all + L5 winter farm output 60 % (was 50)",
            _replace(base, "economy", farm_winter_pct=60), Conditions(**ALL))
    run_all("all + L6 a normal month at the protests, if the food still reaches March", base,
            Conditions(**ALL, spread=True))
    run_all("all + L7 reduced ration -120 (was -150)",
            _replace(base, "mood", ration_reduced=-120), Conditions(**ALL))
    run_all("all + L8 revolt after 8 months under the threshold (was 6)",
            _replace(base, "unrest", revolt_turns=8), Conditions(**ALL))
    food_plus_one = {level: value + 1 for level, value in base.levels.food.items()}
    run_all("all + L9 food yields +1 (" + ", ".join(f"{k} {v}" for k, v in food_plus_one.items()) + ")",
            _replace(base, "levels", food=food_plus_one), Conditions(**ALL))
    run_all("all + L10 4 adults off the work (was 8): a policy, fewer guards and traders", base,
            Conditions(**ALL, staff_count=4))
    no_winter_rule = dict(ALL, winter_rule=False)
    run_all("all but the R2 rule (the careful 1 / 1.5 months)", base, Conditions(**no_winter_rule))


if __name__ == "__main__":
    main()
