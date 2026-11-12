"""The fixed rules of the automatic sovereign (server/sovereign/rules.py)."""

import re

from engine import parse_order
from engine.market import new_market
from engine.turn import monthly_upkeep
from server.sovereign import rules


def _month(state, config):
    return rules.Month(state, config, new_market(config, 1), "1")


def _items(*raw_orders):
    return [rules.Item(index, parse_order(raw)[0], raw, True) for index, raw in enumerate(raw_orders)]


def _open_market(state, config, merchants=3):
    """@brief A finished market with merchants: R7 and R5 apply only then (R10 before)."""
    from engine.state import Building
    from engine.territory import find_place
    state.buildings.append(Building("market", 0, state.next_building_id, *find_place(state, config, "market")))
    state.next_building_id += 1
    state.workers.food -= merchants
    state.workers.trade = merchants


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


def test_farmers_may_go_to_the_quarry_in_winter_when_stone_runs_short(start_state, config):
    """Game 34: short stone halves the farms, so the quarry is the cure for the food."""
    workers = start_state.workers
    to_quarry = {"action": "assign_workers", "food": workers.food - 5, "wood": workers.wood, "stone": workers.stone + 5}
    to_wood = {"action": "assign_workers", "food": workers.food - 5, "wood": workers.wood + 5, "stone": workers.stone}
    start_state.food = 50_000  # the winter check passes: only the flat rule is weighed
    start_state.stone = 0
    assert _excluded(start_state, config, to_quarry) == []  # January
    assert _excluded(start_state, config, to_wood) == [0]
    start_state.stone = 5_000
    assert _excluded(start_state, config, to_quarry) == [0]


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


def test_a_watchtower_in_the_plan_is_not_weighed_by_r8(start_state, config):
    """Game 30: the tower has no jobs nor beds, and R8 crashed on its empty sector."""
    start_state.wood, start_state.stone = 5000, 5000
    assert _excluded(start_state, config, {"action": "build", "building": "watchtower"}) == []


def test_a_feast_must_leave_a_month_of_costs(start_state, config):
    start_state.council_salary = 20
    feast = {"action": "hold_feast", "gold": 10}
    start_state.gold = rules.costs(start_state, config) + 5
    assert _excluded(start_state, config, feast) == [0]
    start_state.gold = rules.costs(start_state, config) + 10
    assert _excluded(start_state, config, feast) == []


def test_no_richer_ration_when_the_food_does_not_last(start_state, config):
    """R2b: with an empty granary R2 drops nothing (the famine comes anyway),
    so a richer ration is checked on its own (game 27, Brenna and Aurelia)."""
    abundant = {"action": "set_ration", "ration": "abundant"}
    reduced = {"action": "set_ration", "ration": "reduced"}
    start_state.turn = 7  # July
    start_state.food = 0
    assert _excluded(start_state, config, abundant) == [0]
    assert _excluded(start_state, config, reduced) == []  # a poorer ration is always allowed
    start_state.food = 50_000
    assert _excluded(start_state, config, abundant) == []


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
    _open_market(start_state, config)
    start_state.stone, start_state.gold = 0, 500
    text, reason = rules.directive(_month(start_state, config), [])
    assert "compra" in text and "pietra" in text and "(R7)" in reason


def test_a_directive_sells_a_surplus_when_gold_is_short(start_state, config):
    _open_market(start_state, config)
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


def test_a_large_surplus_is_sold_even_with_gold_enough(start_state, config):
    """R5b, game 25: Aurelia kept 1858 food with gold enough."""
    _open_market(start_state, config)
    start_state.turn, start_state.gold = 8, 1000  # August
    start_state.food, start_state.wood, start_state.stone = 50_000, 100, 1000
    month = _month(start_state, config)
    month.market.goods["stone"].price = 1  # stone is cheap: not sold off
    text, reason = rules.directive(month, [])
    assert text == "Tesoriere, vendi al mercato 4 lotti di cibo." and "(R5b)" in reason
    start_state.food = 0  # nothing that would still reach the spring
    assert rules.directive(month, []) is None


def test_food_sells_down_to_what_reaches_the_spring(start_state, config):
    """Game 28: Aurelia kept 1,400-2,000 food from August and never sold;
    the rule now sells what the realm does not need to reach the next March."""
    _open_market(start_state, config)
    start_state.turn, start_state.gold = 10, 1000  # October, gold enough (R5b)
    start_state.wood, start_state.stone = 1000, 1000
    month = _month(start_state, config)
    for good in ("wood", "stone"):
        month.market.goods[good].price = 1  # cheap: not sold off, only the food is in play
    lot = config.market.lot_units
    start_state.food = 0
    while not rules.food_lasts(month, [], to_spring=True):  # the least food that reaches March
        start_state.food += lot
    start_state.food += 2 * lot  # two lots more than the spring needs
    text, reason = rules.directive(month, [])
    assert text == "Tesoriere, vendi al mercato 2 lotti di cibo." and "(R5b)" in reason
    start_state.ration = "reduced"  # the sale is weighed on the normal ration
    assert rules.directive(month, []) == (text, reason)
    # A plan that cuts the ration does not make room for a sale (game 29, Brenna).
    start_state.ration = "normal"
    start_state.food -= 3 * lot  # one lot short of the spring at the normal ration
    assert rules.directive(month, []) is None
    assert rules.directive(month, _items({"action": "set_ration", "ration": "reduced"})) is None



def test_a_food_sale_in_march_looks_to_the_next_spring(start_state, config):
    """In March the end of March is this month: the check must reach the next one."""
    import dataclasses
    # Land too poor to feed the realm (a fair realm, 16 a farmer, reaches the next March).
    config = dataclasses.replace(config, levels=dataclasses.replace(config.levels, food={"poor": 12, "fair": 12, "rich": 12}))
    start_state.turn = 3
    start_state.food = rules.food_needed(start_state, config)  # enough for March only
    month = _month(start_state, config)
    assert rules.food_lasts(month, [])  # the winter check: March is covered
    assert not rules.food_lasts(month, [], to_spring=True)


def test_r10_builds_the_market_once_the_wood_covers_the_winter(start_state, config):
    month = _month(start_state, config)
    assert rules.directive(month, []) is None  # January: 150 wood is the firewood until March
    start_state.wood = 300
    text, reason = rules.directive(month, [])
    assert "costruisci il mercato" in text and "(R10)" in reason
    planned = _items({"action": "build", "building": "market"})
    assert rules.directive(month, planned) is None


def test_r10_staffs_a_market_without_merchants(start_state, config):
    _open_market(start_state, config, merchants=0)
    text, reason = rules.directive(_month(start_state, config), [])
    assert "adulti al mercato" in text and "(R10)" in reason
    staffed = _items({"action": "assign_workers", "food": 50, "wood": 4, "stone": 3, "trade": 3})
    assert "(R10)" not in (rules.directive(_month(start_state, config), staffed) or ("", ""))[1]


def test_no_trade_directive_beyond_the_merchants_lots(start_state, config):
    """Game 27: a directive to buy wood the month the market opened, with no merchant yet."""
    _open_market(start_state, config, merchants=1)  # 3 lots this month
    start_state.wood = 0
    start_state.gold = 500
    planned = _items({"action": "trade", "good": "food", "side": "buy", "lots": 3})
    assert rules.directive(_month(start_state, config), planned) is None
    text, _ = rules.directive(_month(start_state, config), [])
    lots = int(re.search(r"compra al mercato (\d+) lott", text).group(1))
    assert 1 <= lots <= 3


def test_r11_builds_the_watchtower_after_the_first_raid(start_state, config):
    """Village block B+C: the early raids are the lesson (no directive before one)."""
    _open_market(start_state, config)
    start_state.turn, start_state.wood, start_state.stone, start_state.gold = 5, 500, 200, 500  # May
    month = _month(start_state, config)
    found = rules.directive(month, [])
    assert found is None or "(R11)" not in found[1]  # no raid yet
    month.raided = True
    text, reason = rules.directive(month, [])
    assert "torre di guardia" in text and "(R11)" in reason
    planned = _items({"action": "build", "building": "watchtower"})
    found = rules.directive(month, planned)
    assert found is None or "(R11)" not in found[1]  # already in the plan
    start_state.wood = 30  # the firewood comes first
    found = rules.directive(month, [])
    assert found is None or "(R11)" not in found[1]


def _building(state, kind):
    return next(b for b in state.buildings if b.kind == kind)


def test_tools_only_where_the_workers_fill_them(start_state, config):
    """R13: the start's 53 farmers fill an improved farm, its 3 quarrymen do not fill a quarry."""
    start_state.turn = 5  # May: no firewood ahead to weigh
    start_state.wood, start_state.stone, start_state.food = 500, 500, 50_000
    farm, quarry = _building(start_state, "farm"), _building(start_state, "quarry")
    assert _excluded(start_state, config, {"action": "improve", "building_id": farm.id}) == []
    assert _excluded(start_state, config, {"action": "improve", "building_id": quarry.id}) == [0]
    # The plan's own assignment counts: 8 quarrymen fill more than half of its 10 jobs.
    workers = start_state.workers
    more = {"action": "assign_workers", "food": workers.food - 5, "wood": workers.wood, "stone": workers.stone + 5}
    assert _excluded(start_state, config, more, {"action": "improve", "building_id": quarry.id}) == []
    # Three farms with tools: 50 farmers do not reach a fourth's half (45 + 7).
    for other in [b for b in start_state.buildings if b.kind == "farm" and b is not farm][:3]:
        other.level = 1
    start_state.workers.food = 50
    assert _excluded(start_state, config, {"action": "improve", "building_id": farm.id}) == [0]


def test_no_tools_at_the_cost_of_the_firewood(start_state, config):
    """R13: in January a poor-wood realm's stock is the winter's firewood
    (the start: 150 wood, 24 cut before March's fire, 150 burnt; 120 wood leaves 36 short)."""
    farm = _building(start_state, "farm")
    start_state.food = 50_000
    start_state.stone = 500
    start_state.wood = 120
    reasons = rules.exclusions(_month(start_state, config), _items({"action": "improve", "building_id": farm.id}), None)
    assert reasons and "tagliato fino a primavera (114)" in reasons[0][1]


def test_tools_count_the_wood_still_to_be_cut(start_state, config):
    """R13, game 39: in July a full sawmill cuts the firewood before winter."""
    sawmill = _building(start_state, "sawmill")
    start_state.turn = 7
    start_state.food, start_state.stone, start_state.wood = 50_000, 500, 60
    jobs = config.buildings["sawmill"].jobs
    workers = start_state.workers
    full = {"action": "assign_workers", "food": workers.food + workers.wood - jobs, "wood": jobs,
            "stone": workers.stone}
    improve = {"action": "improve", "building_id": sawmill.id}
    assert _excluded(start_state, config, full, improve) == []
    # No woodcutters: the stock alone must cover the firewood, and it does not.
    none = {**full, "food": full["food"] + jobs, "wood": 0}
    assert _excluded(start_state, config, none, improve) == [1]


def test_no_build_at_the_cost_of_the_firewood(start_state, config):
    """R10b, game 40: in January the council's own market (80 wood) leaves the
    start realm short (150 wood, 24 cut before March's fire, 150 burnt)."""
    start_state.food, start_state.stone = 50_000, 500
    market = {"action": "build", "building": "market"}
    reasons = rules.exclusions(_month(start_state, config), _items(market), None)
    assert reasons and "(R10b)" in reasons[0][1] and "tagliato fino a primavera (94)" in reasons[0][1]
    # With wood for the winter and the site, the build stays.
    start_state.wood = 300
    assert _excluded(start_state, config, market) == []
