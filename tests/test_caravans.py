"""Roads of the world, phase 2: caravans and the fair (docs/DESIGN.md,
"Phase 2: caravans and the fair"; engine/caravans.py)."""

from dataclasses import replace

import pytest

from engine import new_game, parse_order
from engine.bandits import Band, BanditPool, new_pool, resolve_world
from engine.bands import RoadMap
from engine.caravans import _road, caravans_on
from engine.market import RealmMonth, check_month_plan, market_to_dict, new_market, resolve_month
from engine.territory import hex_distance

LOT = 50


@pytest.fixture
def config(config):
    """The market open from the first month (no building, no lot cap), with caravans."""
    return replace(config, market=replace(config.market, needs_building=False))


@pytest.fixture
def states(config):
    return {"1": new_game(config, seed=7, site_index=0), "2": new_game(config, seed=7, site_index=1)}


def _trade(good, side, lots):
    order, _, message = parse_order({"action": "trade", "good": good, "side": side, "lots": lots})
    assert order is not None, message
    return order


def _empty_pool():
    return BanditPool(seed=1, adults=0)


def _month(config, market, states, orders, pool=None, turn=5):
    """resolve_month then the world step, as the server runs them."""
    months = {key: RealmMonth(state, orders.get(key, [])) for key, state in states.items()}
    market, results = resolve_month(market, months, config)
    after_month = {key: {good: getattr(r.state, good) for good in ("food", "wood", "stone", "gold")}
                   for key, r in results.items()}
    pool = resolve_world(pool or _empty_pool(), results, config, turn, market)
    return market, results, pool, after_month


def _events(result, kind):
    return [e.data for e in result.events if e.kind == kind]


def _band_on_the_road(config, states, key):
    """A band of 2 (too small to raid: it stays) on the middle of the realm's road to the fair."""
    roads = RoadMap(config, states)
    path = _road(roads, roads.fair, roads.doorstep(key))
    x, y = path[len(path) // 2]
    pool = _empty_pool()
    pool.bands.append(Band(pool.next_band_id, x, y, x, y, 2))
    pool.next_band_id += 1
    return pool


def test_the_file_turns_caravans_on(config):
    assert caravans_on(config)
    assert not caravans_on(replace(config, bands=None))  # a lab without bands: instant, as before


def test_a_sale_reaches_the_warehouse_for_the_next_month(config, states):
    market = new_market(config, 0)
    for book in market.goods.values():
        book.queue = []  # only the realms' goods
    market, results, _, _ = _month(config, market, states, {"1": [_trade("food", "sell", 2)],
                                                          "2": [_trade("food", "buy", 2)]})
    assert _events(results["2"], "trade_bought") == []  # nothing to buy: Nord's food was on the road
    assert _events(results["1"], "trade_on_sale")[0]["road"]
    arrived = _events(results["1"], "caravan_arrived")
    assert arrived == [{"leg": "out", "goods": {"food": 2 * LOT}, "week": arrived[0]["week"]}]
    queue = market.goods["food"].queue
    assert [(c.seller, c.units, c.arriving) for c in queue] == [("1", 2 * LOT, False)]
    market, results, _, _ = _month(config, market, states, {"2": [_trade("food", "buy", 2)]}, turn=6)
    assert _events(results["2"], "trade_bought")[0]["lots"] == 2


def test_a_purchase_is_paid_at_once_and_reaches_the_store_at_the_month_s_end(config, states):
    market, results, _, after_month = _month(config, new_market(config, 2), states,
                                             {"2": [_trade("wood", "buy", 1)]})
    bought = _events(results["2"], "trade_bought")[0]
    assert bought["road"] and bought["gold"] > 0  # paid in the month (with the month's tax in the gold)
    assert results["2"].state.gold == after_month["2"]["gold"]  # nothing more to pay on arrival
    assert results["2"].state.wood == after_month["2"]["wood"] + LOT  # added by the world step, not the month
    assert _events(results["2"], "caravan_arrived")[0]["leg"] == "back"


def test_the_plan_check_does_not_count_goods_still_on_the_road(config, states):
    state = states["1"]
    report = check_month_plan(state, [_trade("wood", "buy", 1)], new_market(config, 2), config, "1")
    assert report.remaining["wood"] == state.wood and report.remaining["gold"] < state.gold
    instant = replace(config, caravans=None)
    report = check_month_plan(state, [_trade("wood", "buy", 1)], new_market(instant, 2), instant, "1")
    assert report.remaining["wood"] == state.wood + LOT


def test_a_sale_met_by_a_band_never_reaches_the_warehouse(config, states):
    pool = _band_on_the_road(config, states, "1")
    market, results, pool, _ = _month(config, new_market(config, 2), states,
                                      {"1": [_trade("food", "sell", 2)]}, pool)
    robbed = _events(results["1"], "caravan_robbed")
    assert len(robbed) == 1 and robbed[0]["leg"] == "out" and robbed[0]["goods"] == {"food": 2 * LOT}
    assert not _events(results["1"], "caravan_arrived")
    assert all(c.seller != "1" for c in market.goods["food"].queue)  # nobody will pay for it
    # It keeps what two men carry (then eats in its month); the other 50 are lost.
    assert 0 < pool.bands[0].food <= 2 * config.bandits.carry
    assert _events(results["1"], "band_seen")  # the realm learns of the band


def test_a_purchase_met_by_a_band_is_lost_with_its_gold(config, states):
    pool = _band_on_the_road(config, states, "2")
    gold = states["2"].gold
    _, results, _, after_month = _month(config, new_market(config, 2), states,
                                        {"2": [_trade("stone", "buy", 1)]}, pool)
    assert _events(results["2"], "caravan_robbed")[0]["leg"] == "back"
    assert results["2"].state.stone == after_month["2"]["stone"]  # never reached the store
    assert results["2"].state.gold < gold  # paid at the fair all the same


def test_the_market_needs_to_be_passed_when_goods_are_on_the_road(config, states):
    months = {"2": RealmMonth(states["2"], [_trade("wood", "buy", 1)])}
    _, results = resolve_month(new_market(config, 2), months, config)
    with pytest.raises(ValueError):
        resolve_world(_empty_pool(), results, config, 5)


def test_no_band_camps_near_the_fair(config):
    starts = [new_game(config, 7, site_index=i) for i in range(8)]
    roads = RoadMap(config, {str(i): s for i, s in enumerate(starts)})
    for seed in range(5):
        for band in new_pool(config, seed, 8, starts).bands:
            assert hex_distance(band.camp_x, band.camp_y, *roads.fair) > config.caravans.fair_peace


def test_the_stored_form_leaves_out_the_arriving_mark(config, states):
    market, _, _, _ = _month(config, new_market(config, 2), states, {"1": [_trade("food", "sell", 1)]})
    queue = market_to_dict(market)["goods"]["food"]["queue"]
    assert all("arriving" not in c for c in queue) and any(c["seller"] == "1" for c in queue)
