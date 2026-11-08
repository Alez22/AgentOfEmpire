"""Hex grid (docs/DESIGN.md, "Hex grid", step 1): neighbours, distance,
footprints, placement, directions. The world and core on hexes come in
step 2, so these tests draw a small hex land by hand."""

from dataclasses import replace

import pytest

from engine import new_game
from engine.config import config_from_dict, load_raw_config
from engine.state import Building, Zone
from engine.territory import (OWNED, find_place, footprint, hex_distance, neighbours, next_claim, nudge,
                              occupancy, place_error, square_tiles, zone_at, zones_error, _in_direction)

SIZE = 20


@pytest.fixture
def hex_config(config):
    return replace(config, map=replace(config.map, grid="hex"))


@pytest.fixture
def hex_state(config):
    """A 20 x 20 plain land, all owned and cleared, the square's rhombus at
    (10, 10), one forest hex at (4, 1), a fields, a workshops and a centre zone."""
    state = new_game(config, seed=42)
    state.terrain = ["." * SIZE for _ in range(SIZE)]
    state.terrain[1] = "...." + "T" + "." * (SIZE - 5)
    state.owned = [OWNED * SIZE for _ in range(SIZE)]
    state.square = [10, 10]
    state.buildings = []
    state.clearing_queue = []
    state.zones = [Zone("Campi", "fields", 0, 12, 8, 17), Zone("Botteghe", "workshops", 5, 0, 8, 3),
                   Zone("Centro", "center", 9, 9, 12, 12)]
    return state


def test_six_neighbours_depend_on_the_row_parity(hex_config):
    assert neighbours(hex_config, 5, 2) == [(6, 2), (5, 3), (4, 3), (4, 2), (4, 1), (5, 1)]
    assert neighbours(hex_config, 5, 3) == [(6, 3), (6, 4), (5, 4), (4, 3), (5, 2), (6, 2)]


def test_neighbours_are_mutual_and_one_step_away(hex_config):
    for x, y in ((5, 2), (5, 3), (0, 0), (7, 11)):
        for nx, ny in neighbours(hex_config, x, y):
            assert (x, y) in neighbours(hex_config, nx, ny)
            assert hex_distance(x, y, nx, ny) == 1
    assert hex_distance(0, 0, 3, 0) == 3
    assert hex_distance(0, 0, 0, 4) == 4  # straight down zigzags: one step a row


def test_square_grid_keeps_four_neighbours(config):
    assert len(neighbours(config, 5, 2)) == 4


def test_footprints_are_walked_so_the_shape_follows_the_row(hex_config):
    assert footprint(hex_config, "quarry", 10, 0) == [(10, 0), (11, 0), (10, 1), (11, 1)]
    assert footprint(hex_config, "quarry", 10, 1) == [(10, 1), (11, 1), (11, 2), (12, 2)]
    farm = footprint(hex_config, "farm", 4, 7)
    assert len(set(farm)) == 7 and all(hex_distance(4, 7, x, y) <= 1 for x, y in farm)
    assert footprint(hex_config, "house", 3, 3) == [(3, 3)]


def test_the_square_is_a_rhombus(hex_state, hex_config):
    assert square_tiles(hex_state, hex_config) == [(10, 10), (11, 10), (10, 11), (11, 11)]


def test_a_sawmill_touches_the_forest_across_a_hex_side(hex_state, hex_config, config):
    # (4, 1) is the north-west hex of (5, 2): a neighbour on hexes, a corner on squares.
    assert place_error(hex_state, hex_config, "sawmill", 5, 2) is None
    assert place_error(hex_state, config, "sawmill", 5, 2)[0] == "NO_FOREST"


def test_farm_flowers_pack_six_in_a_nine_by_six_zone(hex_state, hex_config):
    places = []
    while (place := find_place(hex_state, hex_config, "farm", "Campi")) is not None:
        places.append(place)
        hex_state.buildings.append(Building("farm", 0, len(places), *place))
    assert len(places) == 6
    tiles = [tile for x, y in places for tile in footprint(hex_config, "farm", x, y)]
    assert len(tiles) == len(set(tiles)) == 42


def test_placement_is_deterministic(hex_state, hex_config):
    assert find_place(hex_state, hex_config, "farm") == find_place(hex_state, hex_config, "farm")


def test_nudge_tries_the_six_neighbours_east_first(hex_state, hex_config):
    # A farm centred on the zone's top row sticks out: the nearest fitting neighbour is taken.
    assert place_error(hex_state, hex_config, "farm", 4, 12) is not None
    assert nudge(hex_state, hex_config, "farm", 4, 12) == (4, 13)  # SE of an even row


def test_directions_follow_the_angle_to_the_square(hex_state, hex_config):
    assert _in_direction(hex_state, hex_config, 14, 10, "east")
    assert not _in_direction(hex_state, hex_config, 14, 10, "north")
    assert _in_direction(hex_state, hex_config, 14, 4, "north")
    assert not _in_direction(hex_state, hex_config, 14, 4, "east")
    assert _in_direction(hex_state, hex_config, 10, 16, "south")
    assert _in_direction(hex_state, hex_config, 3, 11, "west")


def test_a_claim_borders_the_realm_across_a_hex_side(hex_state, hex_config):
    square = set(square_tiles(hex_state, hex_config))
    hex_state.owned = ["".join(OWNED if (x, y) in square else "-" for x in range(SIZE)) for y in range(SIZE)]
    x, y = next_claim(hex_state, hex_config, "plain", None)
    assert any((x, y) in neighbours(hex_config, sx, sy) for sx, sy in square)


def test_games_saved_before_have_no_grid_key_and_stay_square():
    raw = load_raw_config()
    del raw["map"]["grid"]
    assert config_from_dict(raw).map.grid == "square"


# The hex world and core (step 2). config.toml stays square until the
# briefing and the map page speak hexes (steps 3 and 4).

def _room(state, config, kind, zone_name=None):
    """How many more buildings of this kind fit, placed one after the other."""
    count = 0
    while (place := find_place(state, config, kind, zone_name)) is not None:
        count += 1
        state.buildings.append(Building(kind, 0, 1000 + count, *place))
    return count


def test_every_site_of_the_hex_world_holds_the_hex_core(hex_world_config):
    squares = set()
    for seed in range(len(hex_world_config.map.sites)):
        state = new_game(hex_world_config, seed)  # raises if the world does not match the core
        squares.add(tuple(state.square))
        assert state.square[1] % 2 == 0  # every core starts on an even row: the same shapes
    assert len(squares) == len(hex_world_config.map.sites)


def test_the_hex_core_starts_valid(hex_world_config):
    state = new_game(hex_world_config, seed=42)
    assert zones_error(state, hex_world_config, state.zones) is None
    buildings = list(state.buildings)
    for building in buildings:  # each building would be accepted where it stands
        state.buildings = [b for b in buildings if b is not building]
        assert place_error(state, hex_world_config, building.kind, building.x, building.y) is None, building
    state.buildings = buildings
    tiles = [t for b in buildings for t in footprint(hex_world_config, b.kind, b.x, b.y)]
    assert len(tiles) + len(square_tiles(state, hex_world_config)) == 44


def test_the_hex_core_leaves_room_to_grow(hex_world_config):
    state = new_game(hex_world_config, seed=42)
    assert _room(state, hex_world_config, "farm") == 2
    assert _room(state, hex_world_config, "sawmill") == 1
    assert _room(state, hex_world_config, "quarry") == 1
    assert _room(state, hex_world_config, "house") == 14


def test_the_palace_rhombus_is_left_free(hex_world_config):
    state = new_game(hex_world_config, seed=42)
    sx, sy = state.square
    taken = occupancy(state, hex_world_config)
    palace = footprint(hex_world_config, "quarry", sx + 2, sy)  # the same rhombus, east of the square
    assert not any(tile in taken for tile in palace)
    assert {zone_at(state.zones, x, y).name for x, y in palace} == {"Riserva del palazzo"}
