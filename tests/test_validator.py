from engine import check_plans, parse_order
from engine.validator import apply_orders


def _orders(*raw_orders):
    parsed = []
    for raw in raw_orders:
        order, code, _ = parse_order(raw)
        assert code is None, raw
        parsed.append(order)
    return parsed


def test_unknown_action_is_rejected_at_parse_time():
    order, code, _ = parse_order({"action": "summon_dragon"})
    assert order is None
    assert code == "UNKNOWN_ACTION"


def test_missing_action_is_unknown_action():
    _, code, _ = parse_order({"rate": 10})
    assert code == "UNKNOWN_ACTION"


def test_bad_parameter_is_invalid_param():
    _, code, _ = parse_order({"action": "set_tax", "rate": "high"})
    assert code == "INVALID_PARAM"


def test_two_builds_beyond_the_wood_give_one_accept_and_one_reject(start_state, config):
    # 150 wood: three farms (40 each) fit, the fourth does not.
    orders = _orders(*[{"action": "build", "building": "farm"} for _ in range(4)])
    results = apply_orders(start_state, orders, config)
    assert [r.accepted for r in results] == [True, True, True, False]
    assert results[3].code == "INSUFFICIENT_RESOURCES"
    assert start_state.wood == 150 - 3 * 40


def test_priority_decides_who_gets_the_resources(start_state, config):
    orders = _orders(
        {"action": "hold_feast", "gold": 100, "priority": 1},
        {"action": "build", "building": "house", "priority": 0},
    )
    results = apply_orders(start_state, orders, config)
    assert results[0].order.action == "build" and results[0].accepted
    assert results[1].code == "INSUFFICIENT_RESOURCES"


def test_second_tax_order_is_duplicate_policy(start_state, config):
    orders = _orders({"action": "set_tax", "rate": 5}, {"action": "set_tax", "rate": 20})
    results = apply_orders(start_state, orders, config)
    assert results[1].code == "DUPLICATE_POLICY"
    assert start_state.tax_rate == 5


def test_tax_above_maximum_is_invalid_param(start_state, config):
    results = apply_orders(start_state, _orders({"action": "set_tax", "rate": 31}), config)
    assert results[0].code == "INVALID_PARAM"


def test_more_workers_than_adults_is_rejected(start_state, config):
    orders = _orders({"action": "assign_workers", "food": 50, "wood": 10, "stone": 1})
    results = apply_orders(start_state, orders, config)
    assert results[0].code == "NOT_ENOUGH_WORKERS"


def test_no_free_tile(start_state, config):
    start_state.free_tiles = 0
    start_state.wood = 1000
    results = apply_orders(start_state, _orders({"action": "build", "building": "farm"}), config)
    assert results[0].code == "NO_FREE_TILE"


def test_check_plans_does_not_modify_the_state(start_state, config):
    orders = _orders({"action": "build", "building": "house"})
    report = check_plans(start_state, orders, config)
    assert report.results[0].accepted
    assert report.spent == {"food": 0, "wood": 30, "stone": 30, "gold": 20}
    assert report.remaining["wood"] == 120
    assert start_state.wood == 150
    assert len(start_state.buildings) == 12
