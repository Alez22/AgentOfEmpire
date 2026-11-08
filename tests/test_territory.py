"""Territory (docs/DESIGN.md, "Territory"): map start, placement, town plan, demolition."""

import pytest

from engine import new_game, parse_order
from engine.snapshot import state_from_dict, state_from_json, state_to_dict, state_to_json
from engine.territory import OWNED, find_place, place_error, zones_error
from engine.validator import apply_orders


def _orders(*raw_orders):
    return [parse_order(raw)[0] for raw in raw_orders]


def _site(state):
    """Top-left tile of the realm's core (the square is at core (5, 3))."""
    return state.square[0] - 5, state.square[1] - 3


def _local(state, building):
    sx, sy = _site(state)
    return building.x - sx, building.y - sy


def test_every_site_of_the_world_holds_the_core(config):
    squares = set()
    for seed in range(len(config.map.sites)):
        state = new_game(config, seed)  # raises if the world does not match the core
        squares.add(tuple(state.square))
    assert len(squares) == len(config.map.sites)


def test_a_new_realm_owns_its_core_and_its_starting_town(start_state, config):
    sx, sy = _site(start_state)
    owned = [(x, y) for y, row in enumerate(start_state.owned) for x, char in enumerate(row) if char == OWNED]
    assert len(owned) == 12 * 12 and min(owned) == (sx, sy)
    assert [b.id for b in start_state.buildings] == list(range(1, 13))
    assert [b.kind for b in start_state.buildings][:6] == ["farm"] * 4 + ["sawmill", "quarry"]
    assert start_state.free_tiles == 0
    assert zones_error(start_state, config, start_state.zones) is None  # the starting plan is valid


def test_farms_fill_the_fields_in_rows_then_there_is_no_room(start_state, config):
    start_state.wood = 1000
    orders = _orders(*[{"action": "build", "building": "farm"} for _ in range(3)])
    results = apply_orders(start_state, orders, config)
    assert [r.accepted for r in results] == [True, True, False]
    assert results[2].code == "NO_SPACE"
    new = start_state.buildings[-2:]
    assert sorted(_local(start_state, b) for b in new) == [(3, 9), (6, 9)]  # aligned with the old ones
    assert [b.id for b in new] == [13, 14]


def test_each_kind_goes_to_its_terrain(start_state, config):
    sx, sy = _site(start_state)
    assert find_place(start_state, config, "quarry") == (sx + 10, sy + 3)  # the free hill below the quarry
    sawmill = find_place(start_state, config, "sawmill")
    assert sawmill == (sx + 4, sy + 1)  # next to the forest
    assert find_place(start_state, config, "house", "Case di ponente") is not None


def test_given_coordinates_are_used_or_moved_by_one_tile(start_state, config):
    sx, sy = _site(start_state)
    start_state.wood = 1000
    orders = _orders({"action": "build", "building": "farm", "zone": "Campi", "x": sx + 3, "y": sy + 9},
                     {"action": "build", "building": "farm", "x": sx + 6, "y": sy + 10})  # one row too low
    results = apply_orders(start_state, orders, config)
    assert all(r.accepted for r in results)
    assert [_local(start_state, b) for b in start_state.buildings[-2:]] == [(3, 9), (6, 9)]


@pytest.mark.parametrize("raw, code", [
    ({"action": "build", "building": "house", "x": 2, "y": 2}, "NOT_OWNED"),
    ({"action": "build", "building": "house", "zone": "Nowhere"}, "UNKNOWN_ZONE"),
    ({"action": "build", "building": "house", "x": 10}, "INVALID_PARAM"),
])
def test_bad_places_are_refused(start_state, config, raw, code):
    assert apply_orders(start_state, _orders(raw), config)[0].code == code


def test_place_rules(start_state, config):
    sx, sy = _site(start_state)
    assert place_error(start_state, config, "house", sx + 9, sy + 2)[0] == "WRONG_TERRAIN"  # the river
    assert place_error(start_state, config, "sawmill", sx + 7, sy + 0)[0] == "NO_FOREST"
    assert place_error(start_state, config, "house", sx + 5, sy + 3)[0] == "OVERLAP"  # the square
    assert place_error(start_state, config, "house", sx + 9, sy + 7)[0] == "OUTSIDE_ZONE"  # a reserve
    assert place_error(start_state, config, "house", sx + 8, sy + 3) is None


def test_a_new_plan_replaces_the_old_one_before_the_builds(start_state, config):
    sx, sy = _site(start_state)
    zones = [{"name": z.name, "purpose": z.purpose, "x1": z.x1, "y1": z.y1, "x2": z.x2, "y2": z.y2}
             for z in start_state.zones if z.name != "Riserva di levante"]
    zones.append({"name": "Case di levante", "purpose": "houses", "x1": sx + 11, "y1": sy + 5,
                  "x2": sx + 11, "y2": sy + 11})
    # The build comes first in the list, but the plan runs first.
    orders = _orders({"action": "build", "building": "house", "zone": "Case di levante"},
                     {"action": "set_zones", "zones": zones})
    results = apply_orders(start_state, orders, config)
    assert [r.order.action for r in results] == ["set_zones", "build"]
    assert all(r.accepted for r in results)
    assert _local(start_state, start_state.buildings[-1]) == (11, 5)


def test_a_plan_that_leaves_a_building_outside_is_refused(start_state, config):
    zones = [{"name": z.name, "purpose": z.purpose, "x1": z.x1, "y1": z.y1, "x2": z.x2, "y2": z.y2}
             for z in start_state.zones if z.name != "Campi"]
    result = apply_orders(start_state, _orders({"action": "set_zones", "zones": zones}), config)[0]
    assert result.code == "BAD_ZONES" and "farm 1" in result.message
    assert len(start_state.zones) == 7  # the plan in force stays


def test_overlapping_zones_are_refused(start_state, config):
    zones = [{"name": z.name, "purpose": z.purpose, "x1": z.x1, "y1": z.y1, "x2": z.x2, "y2": z.y2}
             for z in start_state.zones]
    zones[1]["x2"] += 1  # the western houses now reach into the centre
    result = apply_orders(start_state, _orders({"action": "set_zones", "zones": zones}), config)[0]
    assert result.code == "BAD_ZONES" and "overlap" in result.message


def test_demolition_frees_the_tiles_and_gives_back_a_quarter(start_state, config):
    sawmill = start_state.buildings[4]
    wood, stone, gold = start_state.wood, start_state.stone, start_state.gold
    # The build is listed first, but the demolition runs first and frees the tiles.
    orders = _orders({"action": "build", "building": "sawmill", "x": sawmill.x, "y": sawmill.y},
                     {"action": "demolish", "building_id": sawmill.id})
    results = apply_orders(start_state, orders, config)
    assert all(r.accepted for r in results)
    assert sawmill.id not in [b.id for b in start_state.buildings]
    assert start_state.gold == gold - config.map.demolish_gold
    assert start_state.wood == wood + 30 * 25 // 100 - 30
    assert start_state.stone == stone + 20 * 25 // 100 - 20


def test_demolition_of_an_unknown_building_or_without_a_map(start_state, config):
    assert apply_orders(start_state, _orders({"action": "demolish", "building_id": 99}), config)[0].code \
        == "UNKNOWN_BUILDING"
    start_state.terrain = []
    assert apply_orders(start_state, _orders({"action": "demolish", "building_id": 1}), config)[0].code == "NO_MAP"


def test_the_map_survives_a_snapshot(start_state, config):
    apply_orders(start_state, _orders({"action": "build", "building": "house"}), config)
    assert state_to_json(state_from_json(state_to_json(start_state))) == state_to_json(start_state)


def test_a_snapshot_saved_before_the_map_still_loads(start_state):
    old = state_to_dict(start_state)
    for key in ("terrain", "owned", "zones", "square", "next_building_id"):
        del old[key]
    for building in old["buildings"]:
        del building["id"], building["x"], building["y"]
    state = state_from_dict(old)
    assert not state.has_map() and state.zones == [] and state.buildings[0].id == 0
