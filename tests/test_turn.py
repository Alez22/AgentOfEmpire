import pytest

from engine import parse_order, resolve_turn
from engine.state import Workers


def _order(raw):
    order, code, _ = parse_order(raw)
    assert code is None
    return order


def test_input_state_is_not_modified(start_state, config):
    resolve_turn(start_state, [_order({"action": "set_tax", "rate": 20})], config)
    assert start_state.turn == 1
    assert start_state.tax_rate == 10


def test_same_input_gives_identical_result(start_state, config):
    orders = [_order({"action": "build", "building": "farm"})]
    first = resolve_turn(start_state, orders, config)
    second = resolve_turn(start_state, orders, config)
    assert first.state == second.state
    assert first.events == second.events


def test_building_completes_after_its_build_turns(start_state, config):
    state = resolve_turn(start_state, [_order({"action": "build", "building": "farm"})], config).state
    assert state.buildings[-1].turns_left == 1
    result = resolve_turn(state, [], config)
    assert result.state.buildings[-1].turns_left == 0
    assert any(e.kind == "building_completed" for e in result.events)


def test_high_taxes_lead_to_revolt_in_about_ten_turns(start_state, config):
    state = resolve_turn(start_state, [_order({"action": "set_tax", "rate": 30})], config).state
    turns_played = 1
    while state.game_over is None and turns_played < 20:
        state = resolve_turn(state, [], config).state
        turns_played += 1
    assert state.game_over == "revolt"
    assert 9 <= turns_played <= 11


def test_empty_granary_causes_famine(start_state, config):
    start_state.food = 0
    result = resolve_turn(start_state, [], config)
    famine = [e for e in result.events if e.kind == "famine"]
    assert famine and famine[0].data["missing_pct"] > 0
    assert result.state.food == 0


def test_unpaid_upkeep_halves_production(start_state, config):
    start_state.gold = 0
    start_state.tax_rate = 0
    result = resolve_turn(start_state, [], config)
    assert any(e.kind == "upkeep_unpaid" for e in result.events)
    # Wood: 4 workers * 6 = 24, halved = 12
    assert result.state.wood == start_state.wood + 12


def test_workers_shrink_when_adults_die(start_state, config):
    start_state.adults = 10
    start_state.workers = Workers(6, 3, 1)
    start_state.food = 0  # famine kills some adults
    state = resolve_turn(start_state, [], config).state
    assert state.workers.total() <= state.adults


def test_finished_game_cannot_be_resolved(start_state, config):
    start_state.game_over = "revolt"
    with pytest.raises(ValueError):
        resolve_turn(start_state, [], config)


def test_stored_food_spoils_after_consumption(start_state, config):
    start_state.food = 10_000
    result = resolve_turn(start_state, [], config)
    spoiled = [e for e in result.events if e.kind == "food_spoiled"]
    assert spoiled
    # Winter: 54 * 15 / 2 = 405 produced, 860 eaten, then the spoilage share of the rest rots.
    stock_after_eating = 10_000 + 405 - 860
    assert spoiled[0].data["amount"] == stock_after_eating * config.economy.food_spoilage_pct // 100
    assert result.state.food == stock_after_eating - spoiled[0].data["amount"]
