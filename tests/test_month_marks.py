"""The month's marks on the realm's map (server/ui/month_marks.py, hex_board.place_marks)."""

import copy

from engine import new_game
from engine.territory import NOT_OWNED, TERRAIN_CHARS, hex_distance, square_tiles
from server.ui.hex_board import place_marks
from server.ui.month_marks import month_marks


def _event(kind, **data):
    return {"kind": kind, "data": data}


def _owned(state):
    return [(x, y) for y, row in enumerate(state.owned) for x, c in enumerate(row) if c != NOT_OWNED]


def test_a_raid_comes_to_the_gate_nearest_the_band(hex_world_config):
    state = new_game(hex_world_config, seed=0)
    sx, sy = state.square
    band = (sx + 3, sy + 14)  # south of the realm, outside it
    events = [_event("band_seen", x=band[0], y=band[1], band=1, week=2, tower=False, adults=3),
              _event("raid", food=0, wood=0, guards=6, raiders=3, repelled=True),
              _event("arrival", adults=2, children=0, grumbled=False, from_raids=2)]
    marks = {m["id"]: m for m in month_marks(events, state, state, hex_world_config)["marks"]}
    seen, raid, arrival = marks["e0"], marks["e1"], marks["e2"]
    assert (seen["x"], seen["y"]) == band and seen["tone"] == "danger"
    gate = (raid["x"], raid["y"])
    assert gate in _owned(state) and raid["glyph"] == "shield" and raid["tone"] == "ok"
    assert hex_distance(*gate, *band) == min(hex_distance(*t, *band) for t in _owned(state))
    assert raid["from"] == band and (arrival["x"], arrival["y"]) == gate


def test_without_a_band_seen_the_raid_is_marked_on_the_square(hex_world_config):
    state = new_game(hex_world_config, seed=0)
    marks = month_marks([_event("raid", food=100, wood=0, guards=0, raiders=4, repelled=False)],
                        state, state, hex_world_config)["marks"]
    assert (marks[0]["x"], marks[0]["y"]) == square_tiles(state, hex_world_config)[0]
    assert marks[0]["glyph"] == "band" and marks[0]["from"] is None


def test_quiet_events_have_no_mark(hex_world_config):
    state = new_game(hex_world_config, seed=0)
    events = [_event("food_spoiled", amount=6), _event("demography", births=1, deaths=0)]
    assert month_marks(events, state, state, hex_world_config)["marks"] == []


def test_new_land_glows_and_felled_forest_shows_stumps(hex_world_config):
    state = new_game(hex_world_config, seed=0)
    before = copy.deepcopy(state)
    forest = next((x, y) for x, y in _owned(state) if state.terrain[y][x] == TERRAIN_CHARS["forest"])
    outside = next((x, y) for y, row in enumerate(state.owned) for x, c in enumerate(row)
                   if c == NOT_OWNED and any(n in _owned(state) for n in [(x - 1, y), (x + 1, y)]))
    state.terrain[forest[1]] = state.terrain[forest[1]][:forest[0]] + "." + state.terrain[forest[1]][forest[0] + 1:]
    state.owned[outside[1]] = state.owned[outside[1]][:outside[0]] + "w" + state.owned[outside[1]][outside[0] + 1:]
    month = month_marks([], state, before, hex_world_config)
    assert month["claimed"] == [outside] and month["felled"] == [forest]
    assert {m["id"] for m in month["marks"]} == {"claimed", "felled"}
    assert "1 casella" in next(m for m in month["marks"] if m["id"] == "claimed")["text"]


def test_marks_outside_the_view_are_left_out(hex_world_config):
    state = new_game(hex_world_config, seed=0)
    sx, sy = state.square
    events = [_event("band_seen", x=sx + 3, y=sy + 14, band=1, week=2, tower=False, adults=3),
              _event("raid", food=0, wood=0, guards=6, raiders=3, repelled=True)]
    month = month_marks(events, state, state, hex_world_config)
    near = place_marks(month, (sx - 8, sy - 8, sx + 10, sy + 10))  # the band lies beyond
    assert [p["id"] for p in near["pins"]] == ["e1"] and near["paths"] == []
    wide = place_marks(month, (sx - 8, sy - 8, sx + 8, sy + 16))
    assert len(wide["pins"]) == 2 and len(wide["paths"]) == 1
