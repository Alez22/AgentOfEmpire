"""Tools: farms, sawmills and quarries improved in levels (docs/DESIGN.md, "Tools")."""

from dataclasses import replace

from engine import parse_order, resolve_turn
from engine.snapshot import state_from_dict, state_to_dict
from engine.turn import _output_per_worker, expected_output, season_of, stone_upkeep
from engine.validator import apply_orders

JUNE = 6


def _improve(building_id):
    order, _, _ = parse_order({"action": "improve", "building_id": building_id})
    return order


def _first(state, kind):
    return next(b for b in state.buildings if b.kind == kind)


def _codes(state, config, *orders):
    return [r.code for r in apply_orders(state, list(orders), config)]


def test_improve_pays_and_finishes_after_its_months(start_state, config):
    farm = _first(start_state, "farm")
    step = config.tools.levels["farm"][0]
    start_state.wood, start_state.stone, start_state.gold = 100, 100, 100
    month1 = resolve_turn(start_state, [_improve(farm.id)], config)
    assert month1.order_results[0].accepted
    improved = next(b for b in month1.state.buildings if b.id == farm.id)
    assert improved.level == 0 and improved.improving == step.build_turns - 1
    month2 = resolve_turn(month1.state, [], config)
    improved = next(b for b in month2.state.buildings if b.id == farm.id)
    assert improved.level == 1 and improved.improving == 0
    assert any(e.kind == "tools_finished" and e.data["id"] == farm.id for e in month2.events)


def test_improve_costs_the_level(start_state, config):
    farm = _first(start_state, "farm")
    step = config.tools.levels["farm"][0]
    before = (start_state.wood, start_state.stone, start_state.gold)
    assert _codes(start_state, config, _improve(farm.id)) == [None]
    assert (start_state.wood, start_state.stone, start_state.gold) == (
        before[0] - step.wood, before[1] - step.stone, before[2] - step.gold)


def test_improve_rejections(start_state, config):
    farm, house = _first(start_state, "farm"), _first(start_state, "house")
    assert _codes(start_state, replace(config, tools=None), _improve(farm.id)) == ["NO_TOOLS"]
    assert _codes(start_state, config, _improve(999)) == ["UNKNOWN_BUILDING"]
    assert _codes(start_state, config, _improve(house.id)) == ["TOP_LEVEL"]  # a house has no tools
    # The second order for the same building in one plan finds it busy.
    assert _codes(start_state, config, _improve(farm.id), _improve(farm.id)) == [None, "BUSY"]
    quarry = _first(start_state, "quarry")
    quarry.level = len(config.tools.levels["quarry"])
    assert _codes(start_state, config, _improve(quarry.id)) == ["TOP_LEVEL"]
    sawmill = _first(start_state, "sawmill")
    sawmill.turns_left = 1  # a site is not improved
    assert _codes(start_state, config, _improve(sawmill.id)) == ["BUSY"]


def test_improve_needs_resources_and_the_unlocking_building(start_state, config):
    farm = _first(start_state, "farm")
    start_state.stone = 0
    assert _codes(start_state, config, _improve(farm.id)) == ["INSUFFICIENT_RESOURCES"]
    start_state.stone = 100
    locked = replace(config.tools.levels["farm"][0], needs="market")
    locked_config = replace(config, tools=replace(config.tools, levels={**config.tools.levels, "farm": [locked]}))
    assert _codes(start_state, locked_config, _improve(farm.id)) == ["NEEDS_BUILDING"]


def test_workers_fill_the_improved_buildings_first(start_state, config):
    """One improved farm of four: its 15 jobs are the first filled."""
    state = start_state
    state.turn = JUNE
    plain = expected_output(state, config)["food"]
    _first(state, "farm").level = 1
    improved = expected_output(state, config)["food"]
    per_worker = _output_per_worker(state, config, "food", "farm")
    jobs = config.buildings["farm"].jobs
    bonus = config.tools.levels["farm"][0].bonus_pct
    base = state.workers.food * per_worker
    season = getattr(config.economy, f"farm_{season_of(state.turn)}_pct")
    assert state.workers.food > jobs
    assert plain == base * season // 100
    assert improved == (base + per_worker * jobs * bonus // 100) * season // 100
    # Fewer workers than the improved farm's jobs: all of them get the tools.
    state.workers.food = 10
    state.food = 10_000  # above the reserve alert: the fixed rule leaves the idle adults idle
    assert expected_output(state, config)["food"] == (10 * per_worker + per_worker * 10 * bonus // 100) * season // 100


def test_the_works_do_not_stop_the_building(start_state, config):
    start_state.turn = JUNE
    plain = expected_output(start_state, config)
    _first(start_state, "farm").improving = 2
    assert expected_output(start_state, config) == plain


def test_each_level_costs_stone_upkeep(start_state, config):
    plain = stone_upkeep(start_state, config)
    _first(start_state, "farm").level = 1
    _first(start_state, "quarry").level = 1
    assert stone_upkeep(start_state, config) == plain + 2 * config.tools.stone_per_level


def test_games_without_tools_are_unchanged(start_state, config):
    """A game saved before tools has no [tools]: no bonus, no upkeep."""
    old_config = replace(config, tools=None)
    start_state.turn = JUNE
    plain = expected_output(start_state, old_config)
    upkeep = stone_upkeep(start_state, old_config)
    _first(start_state, "farm").level = 1  # cannot happen there, and changes nothing anyway
    assert expected_output(start_state, old_config) == plain
    assert stone_upkeep(start_state, old_config) == upkeep


def test_an_old_snapshot_loads_without_tools(start_state):
    data = state_to_dict(start_state)
    for building in data["buildings"]:
        del building["level"], building["improving"]
    loaded = state_from_dict(data)
    assert all(b.level == 0 and b.improving == 0 for b in loaded.buildings)


def test_the_counsellors_and_the_sovereign_read_the_tools(start_state, config):
    from server.council import briefing, manual, map_text
    from server.ui import labels
    assert "heavy plough" in manual.prompt_text(config)
    assert any(section["title"] == "Attrezzi" for section in manual.page_sections(config))
    assert "Attrezzi" not in [s["title"] for s in manual.page_sections(replace(config, tools=None))]
    farm = _first(start_state, "farm")
    farm.level, farm.improving = 1, 0
    _first(start_state, "quarry").improving = 2
    works = "\n".join(briefing.works_lines(start_state, config))
    assert "Buildings with tools: farm 1 of 4, sawmill 0 of 1, quarry 0 of 1 (1 in works)." in works
    buildings = "\n".join(map_text.building_lines(start_state, config))
    assert f"farm {farm.id} at" in buildings and "tools level 1" in buildings and "new tools in 2 months" in buildings
    assert labels.order_label({"action": "improve", "building_id": 7}) == "Attrezzi nuovi per l'edificio n. 7"
    assert "aratro" not in labels.event_label("tools_finished", {"kind": "farm", "id": 7, "level": 1})
    assert "fattoria n. 7" in labels.event_label("tools_finished", {"kind": "farm", "id": 7, "level": 1})


def test_the_map_shows_a_building_s_tools(start_state, config):
    from server.ui.map_view import _building_lines
    farm = _first(start_state, "farm")
    farm.level, farm.improving = 1, 0
    assert "Attrezzi: aratro pesante (+25% a chi ci lavora)" in _building_lines(start_state, config, farm)
    quarry = _first(start_state, "quarry")
    quarry.improving = 2
    assert "Attrezzi nuovi tra 2 mesi" in _building_lines(start_state, config, quarry)


def test_the_tools_event_has_an_audience():
    """Game 39, month 2: the first finished tools stopped the resolution (no visibility decided)."""
    from server.db.games import EVENT_VISIBILITY
    assert EVENT_VISIBILITY["tools_finished"] == "court"
