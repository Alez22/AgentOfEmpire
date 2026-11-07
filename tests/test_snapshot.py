from engine import parse_order, resolve_turn
from engine.snapshot import state_from_json, state_to_json


def _order(raw):
    order, code, _ = parse_order(raw)
    assert code is None
    return order


def test_round_trip_gives_the_same_state(start_state, config):
    state = resolve_turn(start_state, [_order({"action": "build", "building": "house"})], config).state
    assert state_from_json(state_to_json(state)) == state


def test_json_is_canonical(start_state):
    assert state_to_json(start_state) == state_to_json(state_from_json(state_to_json(start_state)))


def test_replay_from_a_reloaded_snapshot_matches_continued_play(start_state, config):
    orders_per_turn = [
        [_order({"action": "set_tax", "rate": 15})],
        [_order({"action": "build", "building": "farm"})],
        [],
        [_order({"action": "hold_feast", "gold": 40})],
        [],
    ]
    state = start_state
    for orders in orders_per_turn[:2]:
        state = resolve_turn(state, orders, config).state
    saved_text = state_to_json(state)

    continued = state
    for orders in orders_per_turn[2:]:
        continued = resolve_turn(continued, orders, config).state

    replayed = state_from_json(saved_text)
    for orders in orders_per_turn[2:]:
        replayed = resolve_turn(replayed, orders, config).state

    assert state_to_json(replayed) == state_to_json(continued)
