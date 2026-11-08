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
