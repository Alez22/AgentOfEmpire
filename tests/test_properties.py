"""Property tests: thousands of random order sequences must never break
the basic invariants of the engine."""

from hypothesis import given, settings
from hypothesis import strategies as st

from engine import load_config, new_game, parse_order, resolve_turn

CONFIG = load_config()

raw_order = st.one_of(
    st.fixed_dictionaries(
        {"action": st.just("build"), "building": st.sampled_from(["farm", "sawmill", "quarry", "house"])}
    ),
    st.fixed_dictionaries(
        {
            "action": st.just("assign_workers"),
            "food": st.integers(0, 80),
            "wood": st.integers(0, 30),
            "stone": st.integers(0, 30),
        }
    ),
    st.fixed_dictionaries({"action": st.just("set_tax"), "rate": st.integers(0, 40)}),
    st.fixed_dictionaries(
        {"action": st.just("set_ration"), "ration": st.sampled_from(["reduced", "normal", "abundant"])}
    ),
    st.fixed_dictionaries({"action": st.just("hold_feast"), "gold": st.integers(1, 300)}),
)

turn_orders = st.lists(raw_order, max_size=5)


def _parse_all(raw_orders):
    return [order for order, code, _ in map(parse_order, raw_orders) if code is None]


def _assert_invariants(state):
    for name in ("food", "wood", "stone", "gold", "children", "adults", "elders", "free_tiles"):
        assert getattr(state, name) >= 0, name
    assert 0 <= state.mood <= 1000
    assert state.workers.total() <= state.adults
    assert all(0 <= acc < 1000 for acc in [state.birth_acc, *state.death_acc, *state.aging_acc])


@settings(max_examples=300, deadline=None)
@given(st.lists(turn_orders, min_size=1, max_size=24))
def test_invariants_hold_for_random_games(orders_per_turn):
    state = new_game(CONFIG, seed=1)
    for raw_orders in orders_per_turn:
        if state.game_over:
            break
        state = resolve_turn(state, _parse_all(raw_orders), CONFIG).state
        _assert_invariants(state)


@settings(max_examples=50, deadline=None)
@given(st.lists(turn_orders, min_size=1, max_size=12))
def test_replay_is_identical(orders_per_turn):
    def play():
        state = new_game(CONFIG, seed=7)
        for raw_orders in orders_per_turn:
            if state.game_over:
                break
            state = resolve_turn(state, _parse_all(raw_orders), CONFIG).state
        return state

    assert play() == play()
