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


# --- Claiming (gold) and clearing (labour) ---

from engine import resolve_turn  # noqa: E402
from engine.territory import WILD, claim_price, next_claim, owned_count  # noqa: E402
from engine.turn import jobs_in_sector  # noqa: E402


def _claim(state, config, **order):
    return apply_orders(state, _orders({"action": "claim_tiles", **order}), config)[0]


def test_claiming_pays_the_fund_and_the_tiles_wait_for_clearing(start_state, config):
    gold = start_state.gold
    result = _claim(start_state, config, direction="south", terrain="plain", count=4)
    assert result.accepted
    assert start_state.gold == gold - 4 * config.map.claim_base_gold
    assert start_state.land_paid_total == 4 * config.map.claim_base_gold
    assert owned_count(start_state) == 144 + 4
    assert [entry[2] for entry in start_state.clearing_queue] == [config.map.clear_work_plain] * 4
    for x, y, _ in start_state.clearing_queue:
        assert start_state.owned[y][x] == WILD and y > start_state.square[1]  # south of the square


def test_the_price_grows_with_the_land(start_state, config):
    start_state.gold = 1000
    _claim(start_state, config, direction="south", terrain="plain", count=4)
    _claim(start_state, config, direction="north", terrain="plain", count=4)
    assert claim_price(start_state, config) == config.map.claim_base_gold + 1  # 8 tiles beyond the core


def test_a_claim_is_all_or_nothing(start_state, config):
    start_state.gold = 15
    assert _claim(start_state, config, direction="south", terrain="plain", count=2).code == "INSUFFICIENT_RESOURCES"
    assert _claim(start_state, config, direction="south", terrain="plain", count=9).code == "INVALID_PARAM"
    sx, sy = _site(start_state)
    # No hill left outside the core: nothing to claim.
    start_state.terrain = [row if sy <= y < sy + 12 else row.replace("^", ".")
                           for y, row in enumerate(start_state.terrain)]
    start_state.terrain = [row[:sx].replace("^", ".") + row[sx:sx + 12] + row[sx + 12:].replace("^", ".")
                           for row in start_state.terrain]
    assert next_claim(start_state, config, "hill", "west") is None
    assert _claim(start_state, config, direction="west", terrain="hill", count=1).code == "NO_LAND"
    assert start_state.gold == 15 and start_state.land_paid_total == 0 and start_state.clearing_queue == []


def test_a_claimed_forest_stands_and_is_not_queued(start_state, config):
    sx, sy = _site(start_state)
    row = start_state.terrain[sy + 5]
    start_state.terrain[sy + 5] = row[:sx - 1] + "T" + row[sx:]  # a forest on the western border
    tile = next_claim(start_state, config, "forest", "west")
    assert tile == (sx - 1, sy + 5)
    assert _claim(start_state, config, direction="west", terrain="forest", count=1).accepted
    x, y = tile
    assert start_state.owned[y][x] == OWNED and start_state.clearing_queue == []


def test_clearing_workers_make_the_land_usable(start_state, config):
    _claim(start_state, config, direction="south", terrain="plain", count=2)
    first, second = [tuple(entry[:2]) for entry in start_state.clearing_queue]
    apply_orders(start_state, _orders({"action": "assign_workers", "food": 54, "wood": 4, "stone": 0,
                                       "clearing": 2}), config)
    state = resolve_turn(start_state, [], config).state
    assert state.clearing_queue[0][:2] == list(first) and state.clearing_queue[0][2] == 4
    state.workers.clearing = 10
    result = resolve_turn(state, [], config)
    assert result.state.owned[first[1]][first[0]] == OWNED
    assert result.state.owned[second[1]][second[0]] == OWNED
    assert result.state.clearing_queue == []
    assert sum(1 for e in result.events if e.kind == "tile_cleared") == 2


def test_felling_gives_wood_and_leaves_a_plain(start_state, config):
    result = apply_orders(start_state, _orders({"action": "fell_forest", "count": 1}), config)[0]
    assert result.accepted
    x, y, work = start_state.clearing_queue[0]
    assert work == config.map.clear_work_forest
    start_state.workers.food -= work
    start_state.workers.clearing = work
    before = start_state.wood
    state = resolve_turn(start_state, [], config).state
    assert state.terrain[y][x] == "." and state.owned[y][x] == OWNED
    produced_by_sawmill = state.workers.wood * config.buildings["sawmill"].output_per_worker
    assert state.wood >= before + work * config.map.fell_wood_per_work + produced_by_sawmill - 1


def test_a_sawmill_without_its_forest_stops(start_state, config):
    sx, sy = _site(start_state)
    assert jobs_in_sector(start_state, config, "wood") == config.buildings["sawmill"].jobs
    row = start_state.terrain[sy]
    start_state.terrain[sy] = row[:sx + 3] + "." + row[sx + 4:]  # the only forest tile it touches
    assert jobs_in_sector(start_state, config, "wood") == 0


def test_clearing_needs_a_map(start_state, config):
    start_state.terrain = []
    raw = {"action": "assign_workers", "food": 53, "wood": 4, "stone": 2, "clearing": 1}
    assert apply_orders(start_state, _orders(raw), config)[0].code == "NO_MAP"


def test_the_clearing_queue_survives_a_snapshot(start_state, config):
    _claim(start_state, config, direction="south", terrain="plain", count=1)
    assert state_from_json(state_to_json(start_state)).clearing_queue == start_state.clearing_queue
