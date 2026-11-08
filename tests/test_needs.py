"""Firewood, stone upkeep and land levels (docs/DESIGN.md, "Market, needs and
land levels", step 1)."""

from dataclasses import replace

from engine import new_game, resolve_turn
from engine.snapshot import state_from_dict, state_to_dict
from engine.turn import expected_output, firewood_needed, stone_upkeep

JUNE = 6


def _in_month(state, month):
    state.turn = month  # turn 1 is January
    return state


def test_firewood_burns_only_in_the_cold_months(start_state, config):
    january = resolve_turn(start_state, [], config)
    assert firewood_needed(start_state, config) == start_state.population() // config.needs.firewood_people
    june_state = _in_month(new_game(config, seed=42), JUNE)
    assert firewood_needed(june_state, config) == 0
    assert not any(e.kind == "firewood_short" for e in january.events)


def test_missing_firewood_hits_the_mood_at_once(start_state, config):
    warm = resolve_turn(start_state, [], config).state
    start_state.wood = 0
    cold = resolve_turn(start_state, [], config)
    short = [e for e in cold.events if e.kind == "firewood_short"]
    assert short and short[0].data["missing"] == firewood_needed(start_state, config)
    # All the firewood missing: 100 % x the shock per percent.
    assert warm.mood - cold.state.mood == 100 * config.needs.cold_shock_per_pct


def test_stone_upkeep_is_paid_every_month(start_state, config):
    active = sum(1 for b in start_state.buildings if b.turns_left == 0)
    assert stone_upkeep(start_state, config) == active // config.needs.stone_upkeep_buildings
    june_state = _in_month(new_game(config, seed=42), JUNE)
    produced = expected_output(june_state, config)["stone"]
    after = resolve_turn(june_state, [], config).state
    assert after.stone == june_state.stone + produced - stone_upkeep(june_state, config)


def test_missing_stone_wears_the_output(start_state, config):
    june_state = _in_month(start_state, JUNE)
    full = expected_output(june_state, config)
    june_state.stone = 0
    worn = resolve_turn(june_state, [], config)
    assert any(e.kind == "stone_upkeep_short" for e in worn.events)
    # All the stone missing: the output falls by worn_output_loss_pct (50 %).
    assert expected_output(june_state, config)["wood"] == full["wood"] * (100 - config.needs.worn_output_loss_pct) // 100


def test_every_site_has_zero_sum_levels(config):
    assert len(config.map.site_levels) == len(config.map.sites)
    for levels in config.map.site_levels:
        assert sorted(levels) in (["fair", "poor", "rich"], ["fair", "fair", "fair"])


def test_the_land_level_sets_the_yield(config):
    rich_food = new_game(config, seed=0)  # site 0: food rich, wood fair, stone poor
    assert rich_food.land_levels == {"food": "rich", "wood": "fair", "stone": "poor"}
    june_state = _in_month(rich_food, JUNE)
    output = expected_output(june_state, config)
    farmers = min(june_state.workers.food, 4 * config.buildings["farm"].jobs)
    assert output["food"] == farmers * config.levels.food["rich"]  # spring: farms at 100 %
    assert output["stone"] == june_state.workers.stone * config.levels.stone["poor"]


def test_the_fair_level_is_the_building_value(config):
    for sector, kind in (("food", "farm"), ("wood", "sawmill"), ("stone", "quarry")):
        assert getattr(config.levels, sector)["fair"] == config.buildings[kind].output_per_worker


def test_a_site_index_gives_each_realm_its_own_land(config):
    first, second = new_game(config, seed=7, site_index=7), new_game(config, seed=7, site_index=8)
    assert first.square != second.square  # 8 wraps to site 0
    assert second.land_levels == new_game(config, seed=0).land_levels
    assert new_game(config, seed=7).square == first.square  # without an index the seed picks, as before


def test_games_saved_before_have_no_needs_and_no_levels(start_state, config):
    old_config = replace(config, needs=None, levels=None)
    start_state.land_levels = {}
    result = resolve_turn(start_state, [], old_config)
    assert firewood_needed(start_state, old_config) == 0 and stone_upkeep(start_state, old_config) == 0
    assert result.state.wood == start_state.wood + start_state.workers.wood * config.buildings["sawmill"].output_per_worker


def test_land_levels_survive_a_snapshot_and_old_snapshots_load(start_state):
    data = state_to_dict(start_state)
    assert state_from_dict(data).land_levels == start_state.land_levels
    del data["land_levels"]  # a snapshot of format 2
    assert state_from_dict(data).land_levels == {}
