"""The fixed rules of the automatic sovereign (server/sovereign/rules.py)."""

from engine import parse_order
from engine.market import new_market
from engine.turn import monthly_upkeep
from server.sovereign import rules


def _month(state, config):
    return rules.Month(state, config, new_market(config, 1), "1")


def _items(*raw_orders):
    return [rules.Item(index, parse_order(raw)[0], raw, True) for index, raw in enumerate(raw_orders)]


def _excluded(state, config, *raw_orders, granted=None):
    return [index for index, _ in rules.exclusions(_month(state, config), _items(*raw_orders), granted)]


def test_no_farmers_leave_the_fields_in_winter(start_state, config):
    workers = start_state.workers
    fewer = {"action": "assign_workers", "food": workers.food - 5, "wood": workers.wood + 5, "stone": workers.stone}
    same = {"action": "assign_workers", "food": workers.food, "wood": workers.wood, "stone": workers.stone}
    assert _excluded(start_state, config, fewer) == [0]  # January
    assert _excluded(start_state, config, same) == []
    start_state.turn = 5  # May
    start_state.food = 5000
    assert _excluded(start_state, config, fewer) == []


def test_no_claims_in_winter(start_state, config):
    claim = {"action": "claim_tiles", "count": 1, "direction": "north", "terrain": "plain"}
    assert _excluded(start_state, config, claim) == [0]


def test_a_tax_cut_must_leave_the_costs_covered(start_state, config):
    start_state.council_salary = 0
    divisor = config.economy.tax_divisor
    costs = monthly_upkeep(start_state, config)
    lowest_covering = -(-costs * divisor // start_state.adults)
    assert lowest_covering < start_state.tax_rate - 1  # room for both cases
    assert _excluded(start_state, config, {"action": "set_tax", "rate": lowest_covering}) == []
    assert _excluded(start_state, config, {"action": "set_tax", "rate": lowest_covering - 1}) == [0]


def test_no_new_building_while_its_jobs_are_empty(start_state, config):
    farm = {"action": "build", "building": "farm"}
    start_state.wood, start_state.stone, start_state.gold = 5000, 5000, 5000
    start_state.workers.food -= config.buildings["farm"].jobs
    assert _excluded(start_state, config, farm) == [0]


def test_a_feast_must_leave_a_month_of_costs(start_state, config):
    start_state.council_salary = 20
    feast = {"action": "hold_feast", "gold": 10}
    start_state.gold = rules.costs(start_state, config) + 5
    assert _excluded(start_state, config, feast) == [0]
    start_state.gold = rules.costs(start_state, config) + 10
    assert _excluded(start_state, config, feast) == []


def test_no_buying_wood_that_is_already_enough(start_state, config):
    start_state.wood = 5000
    assert _excluded(start_state, config, {"action": "trade", "good": "wood", "side": "buy", "lots": 1}) == [0]


def test_the_winter_check(start_state, config):
    start_state.food = 50_000
    assert rules.food_lasts(_month(start_state, config), [])
    start_state.food = 0
    assert not rules.food_lasts(_month(start_state, config), [])


def test_petitions_on_taxes_and_rations(start_state, config):
    start_state.council_salary = 0
    month = _month(start_state, config)
    assert rules.petition_answer(month, {"action": "set_tax", "rate": start_state.tax_rate}, [])[0] == "granted"
    assert rules.petition_answer(month, {"action": "set_tax", "rate": 0}, [])[0] == "refused"
    start_state.ration = "reduced"
    start_state.food = 50_000
    assert rules.petition_answer(month, {"action": "set_ration", "ration": "normal"}, [])[0] == "granted"
    start_state.food = 100
    answer, reason = rules.petition_answer(month, {"action": "set_ration", "ration": "normal"}, [])
    assert answer == "refused" and "primavera" in reason


def test_a_directive_buys_the_stone_that_runs_short(start_state, config):
    start_state.stone, start_state.gold = 0, 500
    text, reason = rules.directive(_month(start_state, config), [])
    assert "compra" in text and "pietra" in text and "(R7)" in reason


def test_a_directive_sells_a_surplus_when_gold_is_short(start_state, config):
    start_state.gold, start_state.wood, start_state.stone = 0, 2000, 1000
    text, reason = rules.directive(_month(start_state, config), [])
    assert text == "Tesoriere, vendi al mercato 4 lotti di pietra." and "(R5)" in reason  # stone pays most
    # Stone just at what it keeps (6 months of upkeep + 2 lots): the wood goes.
    start_state.stone = rules.need_ahead(start_state, config, "stone", 6) + 100
    text, _ = rules.directive(_month(start_state, config), [])
    assert text == "Tesoriere, vendi al mercato 4 lotti di legno."


def test_no_directive_without_a_market(start_state, config):
    start_state.stone = 0
    assert rules.directive(rules.Month(start_state, config, None, "1"), []) is None


def test_wood_bought_in_spring_counts_the_coming_winter(start_state, config):
    """Game 25: in April every wood purchase was "useless" (no firewood in the next 4 months)."""
    start_state.turn = 4  # April
    start_state.wood = 12
    assert _excluded(start_state, config, {"action": "trade", "good": "wood", "side": "buy", "lots": 2}) == []
    start_state.wood = 5000
    assert _excluded(start_state, config, {"action": "trade", "good": "wood", "side": "buy", "lots": 2}) == [0]


def test_a_good_the_plan_buys_is_not_sold(start_state, config):
    """Game 25: Brenna was told to sell the wood its plan was buying."""
    start_state.gold, start_state.wood, start_state.stone = 40, 40, 1000
    start_state.turn = 5
    buy = _items({"action": "trade", "good": "wood", "side": "buy", "lots": 2})
    found = rules.directive(_month(start_state, config), buy)
    assert found is None or "legno" not in found[0]
