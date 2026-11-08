"""The market as a building and the merchants (docs/DESIGN.md, "The market as
a building, merchants and their mood", village block A, step 2)."""

from dataclasses import replace

from engine import load_config, new_game, parse_order
from engine.market import (RealmMonth, check_trades, has_active_market, merchant_tax, new_market,
                           resolve_month, trade_capacity)
from engine.state import Building, Workers
from engine.territory import find_place
from engine.turn import monthly_tax_income
from engine.validator import apply_orders


def _order(raw):
    order, code, message = parse_order(raw)
    assert order is not None, message
    return order


def _trade(good, side, lots):
    return _order({"action": "trade", "good": good, "side": side, "lots": lots})


def _open_market(state, merchants):
    """@brief Give the realm a finished market and merchants in it."""
    place = find_place(state, load_config(), "market")
    state.buildings.append(Building("market", 0, state.next_building_id, *place))
    state.next_building_id += 1
    state.workers.food -= merchants
    state.workers.trade = merchants


def test_a_new_realm_has_no_market_and_cannot_trade(start_state, config):
    assert not has_active_market(start_state)
    _, results = check_trades(start_state, [_trade("food", "buy", 1)], new_market(config, 1), config, "1")
    assert results[0].code == "NO_MARKET_BUILDING"


def test_the_market_is_built_with_wood_only_in_its_reserved_place(start_state, config):
    wood_before, stone_before = start_state.wood, start_state.stone
    results = apply_orders(start_state, [_order({"action": "build", "building": "market"})], config)
    assert results[0].accepted, results[0].message
    market = start_state.buildings[-1]
    assert market.kind == "market" and market.turns_left == config.buildings["market"].build_turns
    assert (start_state.wood, start_state.stone) == (wood_before - 80, stone_before)
    zones = {z.name for z in start_state.zones if z.x1 <= market.x <= z.x2 and z.y1 <= market.y <= z.y2}
    assert zones == {"Mercato"}


def test_a_realm_has_one_market(start_state, config):
    build = _order({"action": "build", "building": "market"})
    start_state.wood = 500
    results = apply_orders(start_state, [build, build], config)
    assert [r.code for r in results] == [None, "ONE_PER_REALM"]


def test_a_site_under_construction_does_not_trade(start_state, config):
    apply_orders(start_state, [_order({"action": "build", "building": "market"})], config)
    _, results = check_trades(start_state, [_trade("food", "buy", 1)], new_market(config, 1), config, "1")
    assert results[0].code == "NO_MARKET_BUILDING"


def test_the_merchants_cap_the_lots_of_a_month(start_state, config):
    _open_market(start_state, merchants=2)  # 2 x 3 = 6 lots
    start_state.gold = 500
    orders = [_trade("food", "buy", 4), _trade("wood", "buy", 3), _trade("wood", "buy", 2)]
    requests, results = check_trades(start_state, orders, new_market(config, 1), config, "1")
    assert trade_capacity(start_state, config) == 6
    assert [r.code for r in results] == [None, "TRADE_CAPACITY", None]
    assert requests == {"food": 4, "wood": 2}


def test_merchants_beyond_the_jobs_handle_nothing(start_state, config):
    _open_market(start_state, merchants=6)
    start_state.workers.food -= 4
    start_state.workers.trade = 10
    assert trade_capacity(start_state, config) == 6 * config.market.lots_per_merchant


def test_the_merchants_pay_their_own_tax_not_the_ordinary_one(start_state, config):
    _open_market(start_state, merchants=6)
    ordinary = start_state.adults * start_state.tax_rate // config.economy.tax_divisor
    assert monthly_tax_income(start_state, config) == (start_state.adults - 6) * start_state.tax_rate // 20 < ordinary
    market = new_market(config, 1)
    # 2 lots of food bought at 10 and 1 lot of wood put on sale at 15: 35 gold of trade, 10 % = 3.
    assert merchant_tax(start_state, {"food": 2, "wood": -1}, market) == 3


def test_a_month_of_trade_brings_the_merchants_tax(start_state, config):
    _open_market(start_state, merchants=6)
    start_state.gold = 200
    market = new_market(config, 1)
    _, results = resolve_month(market, {"1": RealmMonth(start_state, [_trade("food", "buy", 2)])}, config)
    taxes = [e.data["gold"] for e in results["1"].events if e.kind == "merchant_tax"]
    assert taxes == [2]  # 2 lots at 10: 20 gold of trade


def test_the_treasurer_sets_the_merchants_tax(start_state, config):
    assert start_state.merchant_tax_rate == config.market.merchant_tax_start
    results = apply_orders(start_state, [_order({"action": "set_merchant_tax", "rate": 20}),
                                         _order({"action": "set_merchant_tax", "rate": 25})], config)
    assert [r.code for r in results] == [None, "DUPLICATE_POLICY"]
    assert start_state.merchant_tax_rate == 20
    too_high = apply_orders(start_state, [_order({"action": "set_merchant_tax", "rate": 31})], config)
    assert too_high[0].code == "INVALID_PARAM"


def test_games_before_block_a_keep_the_market_open_and_untaxed():
    base = load_config()
    old = replace(base, market=replace(base.market, needs_building=False, lots_per_merchant=0,
                                       merchant_tax_start=0, max_merchant_tax=0))
    state = new_game(old, seed=42)
    assert state.merchant_tax_rate == 0 and trade_capacity(state, old) is None
    state.gold = 500
    _, results = check_trades(state, [_trade("food", "buy", 9)], new_market(old, 1), old, "1")
    assert results[0].accepted
    refused = apply_orders(state, [_order({"action": "set_merchant_tax", "rate": 5})], old)
    assert refused[0].code == "NO_MARKET"


def test_rescaling_keeps_the_merchants_in_proportion(start_state, config):
    from engine.turn import _rescale_workers
    start_state.workers = Workers(40, 10, 5, 0, 5)  # 60 assigned
    start_state.adults = 30
    _rescale_workers(start_state, [])
    assert start_state.workers.total() == 30 and start_state.workers.trade in (2, 3)


# ---- Step 3: the merchants' mood and unrest (one engine for every class) ----

from engine.state import ClassState  # noqa: E402
from engine.turn import class_factors, resolve_turn, trade_factor  # noqa: E402


def _with_merchants(state, config, mood=500, records=()):
    _open_market(state, merchants=6)
    state.classes["merchants"] = ClassState(mood=mood, recent_trade=[list(r) for r in records])
    return config.classes["merchants"]


def test_finishing_the_market_brings_the_merchants(start_state, config):
    apply_orders(start_state, [_order({"action": "build", "building": "market"})], config)
    state = start_state
    for _ in range(config.buildings["market"].build_turns):
        assert "merchants" not in state.classes
        state = resolve_turn(state, [], config).state
    assert state.classes["merchants"].mood == config.mood.base  # a fresh start, as in the lab


def test_the_trade_factor_blames_the_crown_more_than_an_empty_warehouse(start_state, config):
    rules = _with_merchants(start_state, config)
    cls = start_state.classes["merchants"]
    cls.recent_trade = [[0, 18, 1], [0, 18, 1], [0, 18, 0]]
    assert trade_factor(cls, rules) == rules.idle_malus  # goods were on sale
    cls.recent_trade = [[0, 18, 0]] * 3
    assert trade_factor(cls, rules) == rules.empty_malus
    cls.recent_trade = [[10, 18, 1], [10, 18, 1], [2, 18, 1]]
    assert trade_factor(cls, rules) == rules.busy_bonus  # 22 of 54 lots: 40 %
    cls.recent_trade = [[4, 18, 1], [4, 18, 1], [0, 18, 1]]
    assert trade_factor(cls, rules) == 0  # some trade, under 40 % of the lots


def test_strike_months_do_not_count_for_the_trade_factor(start_state, config):
    rules = _with_merchants(start_state, config)
    cls = start_state.classes["merchants"]
    cls.recent_trade = [[-1, 0, 0]] * 3
    assert trade_factor(cls, rules) == 0


def test_the_merchants_pay_no_heed_to_the_granaries_and_feel_their_own_tax(start_state, config):
    _with_merchants(start_state, config)
    start_state.merchant_tax_rate = 15
    factors = class_factors(start_state, config, "merchants", 900, 0, 0)
    assert "reserve" not in factors
    assert factors["taxes"] == (15 - 10) * -10
    start_state.merchant_tax_rate = 10
    assert class_factors(start_state, config, "merchants", 900, 0, 0)["taxes"] == 0


def test_the_merchants_take_half_the_cold(start_state, config):
    _with_merchants(start_state, config, mood=500)
    start_state.turn = 1  # January: firewood
    start_state.wood = 0
    after = resolve_turn(start_state, [], config).state
    # Cold shock 100 % missing x 2 = 200 for the peasants; the merchants take 100
    # (plus their slow approach towards a target near 500).
    assert after.classes["merchants"].mood > after.mood
    assert 380 <= after.classes["merchants"].mood <= 420


def test_merchants_kept_idle_by_the_crown_end_on_strike_not_in_revolt(start_state, config):
    _with_merchants(start_state, config, mood=360, records=[[0, 18, 1]] * 3)
    state = start_state
    levels = []
    for _ in range(12):
        state.gold = 500
        state.food = 5000
        cls = state.classes["merchants"]
        if cls.unrest != "strike":
            cls.recent_trade = (cls.recent_trade + [[0, 18, 1]])[-3:]  # goods on sale, nothing traded
        state = resolve_turn(state, [], config).state
        levels.append(state.classes["merchants"].unrest)
    assert "protests" in levels and "strike" in levels and "revolt" not in levels
    assert state.game_over is None


def test_a_strike_stops_the_market_and_discontent_halves_the_lots(start_state, config):
    _with_merchants(start_state, config, mood=500)
    full = trade_capacity(start_state, config)
    start_state.classes["merchants"].mood = 300
    assert trade_capacity(start_state, config) == full // 2
    start_state.classes["merchants"].unrest = "strike"
    assert trade_capacity(start_state, config) == 0
    start_state.gold = 500
    _, results = check_trades(start_state, [_trade("food", "buy", 1)], new_market(config, 1), config, "1")
    assert results[0].code == "TRADE_CAPACITY"


def test_the_month_at_the_market_is_remembered(start_state, config):
    _with_merchants(start_state, config)
    start_state.gold = 200
    _, results = resolve_month(new_market(config, 1), {"1": RealmMonth(start_state, [_trade("food", "buy", 2)])},
                               config)
    assert results["1"].state.classes["merchants"].recent_trade == [[2, 18, 1]]


def test_the_peasants_mood_is_the_same_as_before_the_classes(start_state, config):
    """The peasants go through the shared step: a month with feast, petition,
    famine and cold gives the numbers of the old formula."""
    from engine.people import PeopleChoice
    start_state.turn = 1
    start_state.wood = 10
    start_state.food = 300
    feast = _order({"action": "hold_feast", "gold": 40})
    after = resolve_turn(start_state, [feast], config, PeopleChoice(0, 100, "granted", 20)).state
    assert after.mood == 224  # the engine before step 3 (commit 203f951) gives 224 for the same month
