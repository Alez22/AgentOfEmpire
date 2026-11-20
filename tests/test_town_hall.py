"""The town hall site: the passage from the village to the town (engine/eras.py)."""

from dataclasses import replace

from engine import eras, new_game, parse_order, resolve_turn
from engine.snapshot import state_from_dict, state_to_dict
from engine.state import Building
from engine.territory import find_place

TOWN_HALL = {"action": "build", "building": "town_hall"}


def _ready(config):
    """@brief A realm that meets every condition: April of year 2, 120 people,
    a finished market, no famine ever, calm, and the cost in store."""
    state = new_game(config, seed=42)
    state.turn = 16
    state.adults += 120 - state.population()
    state.buildings.append(Building("market", 0, state.next_building_id, *find_place(state, config, "market")))
    state.next_building_id += 1
    state.wood, state.stone, state.gold, state.food = 1000, 1000, 1000, 50_000
    return state


def _verdict(state, config, raw=TOWN_HALL):
    result = resolve_turn(state, [parse_order(raw)[0]], config)
    return result.order_results[0], result.state


def test_the_site_opens_when_the_realm_is_ready(config):
    state = _ready(config)
    assert eras.town_hall_missing(state, config) == []
    verdict, after = _verdict(state, config)
    assert verdict.accepted
    spec = config.town_hall
    assert after.town_hall_site == spec.build_turns - 1  # the first month of works is this one
    assert after.builders == spec.builders
    assert after.workers.total() <= after.adults - after.guards() - spec.builders  # hands off the work


def test_the_cost_is_paid_at_once(config):
    """Against the same month without the order (firewood and upkeep move wood and stone too)."""
    state = _ready(config)
    verdict, after = _verdict(state, config)
    assert verdict.accepted
    without = resolve_turn(_ready(config), [], config).state
    assert without.gold - after.gold == config.town_hall.gold
    assert without.stone - after.stone == config.town_hall.stone


def test_each_condition_blocks_the_site(config):
    cases = {
        "population": lambda s: setattr(s, "adults", s.adults - 1),
        "market": lambda s: setattr(s, "buildings", [b for b in s.buildings if b.kind != "market"]),
        "hunger": lambda s: setattr(s, "last_famine_turn", 11),  # November of year 1: inside the last winter
        "strike": lambda s: setattr(s, "unrest", "strike"),
    }
    for name, spoil in cases.items():
        state = _ready(config)
        spoil(state)
        verdict, _ = _verdict(state, config)
        assert not verdict.accepted and verdict.code == "NOT_READY", name


def test_a_famine_before_the_last_winter_does_not_count(config):
    state = _ready(config)  # April of year 2: the last winter began in October of year 1 (turn 10)
    state.last_famine_turn = 9
    assert eras.no_hunger_since_last_winter(state)
    state.last_famine_turn = 10
    assert not eras.no_hunger_since_last_winter(state)
    assert eras.last_winter_start(16) == 10
    assert eras.last_winter_start(15) == -2  # March of year 2: the last finished winter is year 1's first


def test_cost_and_builders_are_checked(config):
    state = _ready(config)
    state.stone = config.town_hall.stone - 1
    verdict, _ = _verdict(state, config)
    assert verdict.code == "INSUFFICIENT_RESOURCES"
    state = _ready(config)
    state.town_hall_site = 3
    verdict, _ = _verdict(state, config)
    assert verdict.code == "ONE_PER_REALM"


def test_a_strike_stops_the_works_and_the_end_makes_a_town(config):
    state = _ready(config)
    state.town_hall_site, state.builders = 1, config.town_hall.builders
    state.unrest = "strike"
    after = resolve_turn(state, [], config).state
    assert after.town_hall_site == 1 and after.era == "village"
    state.unrest = "calm"
    result = resolve_turn(state, [], config)
    assert result.state.era == "town" and result.state.builders == 0 and result.state.town_hall_site == 0
    assert [e.data for e in result.events if e.kind == "era_reached"] == [{"era": "town"}]


def test_a_famine_is_remembered_only_in_games_with_the_town_hall(config):
    state = new_game(config, seed=42)
    state.food = 0
    assert resolve_turn(state, [], config).state.last_famine_turn == 1
    old = replace(config, town_hall=None)
    assert resolve_turn(state, [], old).state.last_famine_turn == 0  # old snapshots replay unchanged
    verdict, _ = _verdict(_ready(old), old)
    assert verdict.code == "UNKNOWN_BUILDING"


def test_an_old_snapshot_loads_as_a_village(config):
    data = state_to_dict(new_game(config, seed=42))
    for key in ("era", "town_hall_site", "builders", "last_famine_turn"):
        del data[key]
    state = state_from_dict(data)
    assert (state.era, state.town_hall_site, state.builders, state.last_famine_turn) == ("village", 0, 0, 0)
