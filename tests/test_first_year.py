"""Hand check of docs/DESIGN.md ("Hand check of the first year"):
twelve turns with no orders from the sovereign.

The ranges are wider than the hand numbers because the hand check ignored
population growth and the fixed rule that moves new adults to the farms.
"""

from engine import resolve_turn


def _play(state, config, turns):
    history = []
    for _ in range(turns):
        state = resolve_turn(state, [], config).state
        history.append(state)
    return history


def test_winter_drains_the_food_reserve(start_state, config):
    end_of_winter = _play(start_state, config, 3)[-1]
    # Hand check: 1600 - 3 * (860 - 405) = 235, minus 2 % spoilage per month = about 195
    assert 150 <= end_of_winter.food <= 260


def test_first_year_about_breaks_even(start_state, config):
    end_of_year = _play(start_state, config, 12)[-1]
    # Fair land breaks even since 2026-11-09 (lab/food_balance.py, farms 16 per
    # worker): about 1620 with 2 % spoilage. Was about 1150 at 15 per worker.
    assert 1300 <= end_of_year.food <= 1900


def test_population_grows_slowly(start_state, config):
    end_of_year = _play(start_state, config, 12)[-1]
    # Hand check: about +6 people per year
    assert 103 <= end_of_year.population() <= 110


def test_mood_drifts_down_without_reaching_unrest(start_state, config):
    history = _play(start_state, config, 12)
    assert all(state.mood >= config.unrest.threshold for state in history)
    assert history[-1].mood < config.start.mood
    assert history[-1].unrest == "calm"
    assert history[-1].game_over is None


def test_gold_grows_by_18_per_month(start_state, config):
    after_one_turn = _play(start_state, config, 1)[-1]
    # Taxes 60 adults * 10 / 20 = 30, upkeep 12 buildings * 1 = 12
    assert after_one_turn.gold == start_state.gold + 30 - 12
