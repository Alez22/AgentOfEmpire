"""The common market (engine/market.py; docs/DESIGN.md, "Market, needs and
land levels", step 2)."""

import copy
from dataclasses import replace

from engine import check_plans, new_game, parse_order, resolve_turn
from engine.market import (MERCHANT, Consignment, RealmMonth, buy_price, check_month_plan, check_trades, market_from_dict,
                           market_to_dict, new_market, resolve_market, resolve_month, sell_price, stock)


def _trade(good, side, lots, priority=0):
    order, code, message = parse_order({"action": "trade", "good": good, "side": side, "lots": lots,
                                        "priority": priority})
    assert order is not None, message
    return order


def _empty_market(config):
    """@brief A market without the start stock, to follow the realms' goods alone."""
    market = new_market(config, 0)
    for book in market.goods.values():
        book.queue = []
    return market


def test_the_start_stock_grows_with_the_realms(config):
    market = new_market(config, 3)
    for good, book in market.goods.items():
        assert book.price == config.market.start_price[good]
        assert stock(book) == 3 * config.market.start_stock_per_realm[good]
        assert stock(book, include_start_stock=False) == 0


def test_the_margin_is_never_rounded_away(config):
    market = new_market(config, 1)
    assert (buy_price(market, config, "food"), sell_price(market, config, "food")) == (11, 9)
    market.goods["food"].price = 5
    assert (buy_price(market, config, "food"), sell_price(market, config, "food")) == (6, 4)


def test_a_realm_cannot_sell_what_it_has_not_or_buy_beyond_its_gold(start_state, config):
    market = new_market(config, 1)
    start_state.gold = 30
    orders = [_trade("wood", "sell", 3), _trade("wood", "sell", 1), _trade("food", "buy", 2), _trade("food", "buy", 1)]
    requests, results = check_trades(start_state, orders, market, config, "1")
    # 150 wood: three lots of 50, not a fourth; 30 gold: two lots at 11, not a third.
    assert [r.accepted for r in results] == [True, False, True, False]
    assert requests == {"wood": -3, "food": 2}


def test_a_realm_trades_a_good_one_way_a_month(start_state, config):
    _, results = check_trades(start_state, [_trade("food", "sell", 1), _trade("food", "buy", 1)],
                              new_market(config, 1), config, "1")
    assert results[1].code == "BOTH_SIDES"


def test_the_seller_is_paid_when_a_buyer_takes_the_goods(config):
    market = _empty_market(config)
    after_sale, _, paid, _ = resolve_market(market, {"1": {"wood": -2}}, config)
    assert paid == {} and stock(after_sale.goods["wood"]) == 100
    after_purchase, fills, paid, _ = resolve_market(after_sale, {"2": {"wood": 1}}, config)
    assert fills["2"] == {"wood": 1}
    assert paid == {"1": sell_price(after_sale, config, "wood")}
    assert stock(after_purchase.goods["wood"]) == 50
    assert stock(market.goods["wood"]) == 0  # the input market is not modified


def test_the_oldest_goods_sell_first_and_the_start_stock_pays_nobody(config):
    market = new_market(config, 1)  # 50 wood of the start stock
    market.goods["wood"].queue.append(Consignment("1", 50))
    _, _, paid, _ = resolve_market(market, {"2": {"wood": 1}}, config)
    assert paid == {}  # the start stock went first
    _, _, paid, _ = resolve_market(market, {"2": {"wood": 2}}, config)
    assert paid == {"1": sell_price(market, config, "wood")}


def test_a_short_warehouse_is_split_in_proportion(config):
    market = _empty_market(config)
    market.goods["food"].queue = [Consignment("9", 150)]  # 3 lots
    _, fills, _, _ = resolve_market(market, {"1": {"food": 4}, "2": {"food": 2}}, config)
    assert (fills["1"]["food"], fills["2"]["food"]) == (2, 1)  # 3 * 4 // 6 and 3 * 2 // 6


def test_the_price_rises_when_demand_is_not_met(config):
    market = _empty_market(config)
    after, _, _, _ = resolve_market(market, {"1": {"stone": 1}}, config)
    assert after.goods["stone"].price == config.market.start_price["stone"] * 110 // 100


def test_the_price_falls_only_when_the_realms_goods_do_not_move(config):
    market = new_market(config, 8)  # a large start stock and no demand
    after, _, _, _ = resolve_market(market, {}, config)
    assert after.goods["wood"].price == config.market.start_price["wood"]  # the start stock does not count
    after, _, _, _ = resolve_market(market, {"1": {"wood": -2}}, config)
    assert after.goods["wood"].price < config.market.start_price["wood"]  # unsold, and nobody asked


def test_the_price_stays_within_its_bounds(config):
    market = _empty_market(config)
    market.goods["food"].price = config.market.start_price["food"] * config.market.max_price_pct // 100
    after, _, _, _ = resolve_market(market, {"1": {"food": 1}}, config)
    assert after.goods["food"].price == market.goods["food"].price


def test_food_on_sale_spoils(config):
    market = _empty_market(config)
    after, _, _, _ = resolve_market(market, {"1": {"food": -2}}, config)
    assert stock(after.goods["food"]) == 100 - 100 * config.economy.food_spoilage_pct // 100


def test_the_market_state_survives_a_round_trip(config):
    market, _, _, _ = resolve_market(new_market(config, 2), {"1": {"food": -1}, "2": {"wood": 1}}, config)
    assert market_from_dict(market_to_dict(market)) == market


def test_a_month_trades_first_so_bought_wood_can_build(config):
    seller, buyer = new_game(config, 0, site_index=0), new_game(config, 0, site_index=1)
    buyer.wood = 0
    build = parse_order({"action": "build", "building": "house"})[0]
    market, results = resolve_month(new_market(config, 2), {
        "1": RealmMonth(seller, [_trade("wood", "sell", 2)]),
        "2": RealmMonth(buyer, [_trade("wood", "buy", 1), _trade("stone", "buy", 1), build]),
    }, config)
    bought = results["2"]
    assert [r.accepted for r in bought.order_results] == [True, True, True]
    assert [e.kind for e in bought.events if e.kind.startswith("trade")] == ["trade_bought", "trade_bought"]
    # The same month by hand: the lots arrive and are paid, then the turn runs with the build.
    start = new_market(config, 2)
    by_hand = copy.deepcopy(buyer)
    by_hand.wood += 50
    by_hand.stone += 50
    by_hand.gold -= buy_price(start, config, "wood") + buy_price(start, config, "stone")
    assert bought.state == resolve_turn(by_hand, [build], config).state
    assert any(e.kind == "trade_on_sale" for e in results["1"].events)
    assert results["1"].state.wood < seller.wood  # the sold wood left at once


def test_the_plan_check_runs_trades_first_and_keeps_the_input_order(start_state, config):
    start_state.wood = 0
    build = parse_order({"action": "build", "building": "house"})[0]
    assert not check_plans(start_state, [build], config).results[0].accepted  # no wood without the market
    report = check_month_plan(start_state, [build, _trade("wood", "buy", 1)], new_market(config, 1), config, "1")
    assert [r.order.action for r in report.results] == ["build", "trade"]
    assert all(r.accepted for r in report.results)
    assert report.remaining["wood"] == 50 - config.buildings["house"].wood
    assert start_state.wood == 0  # a dry run


def test_a_game_without_a_market_refuses_trades(start_state, config):
    no_market = replace(config, market=None)
    _, results = resolve_month(None, {"1": RealmMonth(start_state, [_trade("food", "sell", 1)])}, no_market)
    assert results["1"].order_results[0].code == "NO_MARKET"


def test_a_month_is_deterministic(config):
    def month():
        realms = {str(i): RealmMonth(new_game(config, 3, site_index=i), [_trade("food", "sell", 2)])
                  for i in range(3)}
        realms["1"].orders = [_trade("food", "buy", 5)]
        return resolve_month(new_market(config, 3), realms, config)
    first, second = month(), month()
    assert first[0] == second[0]
    assert {k: r.state for k, r in first[1].items()} == {k: r.state for k, r in second[1].items()}


def test_a_partial_fill_is_told_in_the_result(config):
    realm = new_game(config, 0)
    market = _empty_market(config)
    market.goods["stone"].queue = [Consignment(MERCHANT, 50)]
    _, results = resolve_month(market, {"1": RealmMonth(realm, [_trade("stone", "buy", 2)])}, config)
    assert results["1"].order_results[0].message == "filled 1 of 2 lots of stone asked this month"


def test_the_sovereign_reads_trades_in_italian():
    from server.ui.labels import event_label, order_label, rejection_label
    assert order_label({"action": "trade", "good": "wood", "side": "sell", "lots": 2}) == "Vendere al mercato 2 lotti di legno"
    assert event_label("trade_paid", {"gold": 27}) == "Il mercato ha pagato 27 oro per la merce venduta."
    assert rejection_label("NO_MARKET") == "in questo mondo non c'è mercato"


def test_the_lots_left_by_rounding_still_go_to_a_buyer(config):
    """Game 24: one lot asked by two realms for two each stayed unsold (0 + 0)."""
    market = _empty_market(config)
    market.goods["food"].queue = [Consignment("9", 50)]
    _, fills, _, _ = resolve_market(market, {"1": {"food": 2}, "2": {"food": 2}}, config)
    assert (fills["1"]["food"], fills["2"]["food"]) == (1, 0)  # equal remainders: the fixed order decides
    market.goods["food"].queue = [Consignment("9", 250)]  # 5 lots for 3 + 3 + 1 asked
    _, fills, _, _ = resolve_market(market, {"1": {"food": 3}, "2": {"food": 3}, "3": {"food": 1}}, config)
    assert sum(f["food"] for f in fills.values()) == 5
    assert (fills["1"]["food"], fills["2"]["food"], fills["3"]["food"]) == (2, 2, 1)


def test_a_realm_cannot_buy_back_its_own_goods(start_state, config):
    """Game 24: Corvara asked to buy the food it had on sale (margin paid twice)."""
    market = new_market(config, 1)
    market.goods["food"].queue.append(Consignment("1", 50))
    _, results = check_trades(start_state, [_trade("food", "buy", 1), _trade("wood", "buy", 1)], market, config, "1")
    assert [r.code for r in results] == ["OWN_GOODS_ON_SALE", None]
    _, results = check_trades(start_state, [_trade("food", "buy", 1)], market, config, "2")
    assert results[0].accepted  # another realm may buy it
    older_rules = replace(config, market=replace(config.market, no_buying_own_goods=False))
    _, results = check_trades(start_state, [_trade("food", "buy", 1)], market, older_rules, "1")
    assert results[0].accepted  # older games replay as played


def test_units_under_a_lot_sell_as_one_short_lot(config):
    """Game 24: 48 food rotted in the warehouse, nobody could buy less than a lot."""
    market = _empty_market(config)
    market.goods["food"].queue = [Consignment("9", 98)]  # one whole lot and 48
    after, fills, paid, short = resolve_market(market, {"1": {"food": 1}, "2": {"food": 2}}, config)
    assert (fills["1"]["food"], fills["2"]["food"]) == (1, 1)
    assert short == {"1": {}, "2": {"food": 2}}  # the last buyer in the fixed order takes the short lot
    assert stock(after.goods["food"]) == 0 and after.goods["food"].last_bought == 98
    assert paid == {"9": 98 * sell_price(market, config, "food") // 50}  # paid by the unit


def test_a_short_lot_is_paid_by_the_unit(config):
    realm = new_game(config, 0)
    market = _empty_market(config)
    market.goods["food"].queue = [Consignment("9", 48)]
    _, results = resolve_month(market, {"1": RealmMonth(realm, [_trade("food", "buy", 1)])}, config)
    gold = -(-48 * buy_price(market, config, "food") // 50)
    bought = next(e for e in results["1"].events if e.kind == "trade_bought")
    assert bought.data == {"good": "food", "lots": 1, "gold": gold, "units": 48}
    from server.ui.labels import event_label
    assert event_label("trade_bought", bought.data) == (
        f"Comprati al mercato 48 di cibo (l'ultimo lotto era incompleto) per {gold} oro.")


def test_whole_lots_are_not_cut_when_the_warehouse_has_more(config):
    market = _empty_market(config)
    market.goods["food"].queue = [Consignment("9", 98)]
    _, fills, _, short = resolve_market(market, {"1": {"food": 1}}, config)
    assert fills["1"]["food"] == 1 and short == {"1": {}}  # the 48 stay for later
    older_rules = replace(config, market=replace(config.market, short_last_lot=False))
    market.goods["food"].queue = [Consignment("9", 48)]
    _, fills, _, _ = resolve_market(market, {"1": {"food": 1}}, older_rules)
    assert fills["1"]["food"] == 0
