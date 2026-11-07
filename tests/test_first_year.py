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
    # Hand check: 2000 - 3 * (405 - 860) = 635, minus 2 % spoilage per month = about 570
    assert 550 <= end_of_winter.food <= 720


def test_first_year_ends_with_less_food_than_it_started(start_state, config):
    end_of_year = _play(start_state, config, 12)[-1]
    # Engine: about 1460 with 2 % spoilage (the fixed rule adds farmers in spring)
    assert 1300 <= end_of_year.food < 2000


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
