"""The territory in the Architect's briefing (server/council/map_text.py)."""

from engine.state import Zone
from server.council import map_text


def _stretch_fields(state, rows):
    """The core's fields zone (rows 6-11 of the core) stretched south beyond the border."""
    campi = next(z for z in state.zones if z.name == "Campi")
    state.zones = [z for z in state.zones if z.name != "Campi"] + [
        Zone("Campi", "fields", campi.x1, campi.y1, campi.x2, campi.y2 + rows)]


def _campi_line(state, config):
    return next(line for line in map_text.zone_lines(state, config) if line.startswith("- Campi "))


def test_a_zone_too_narrow_for_a_farm_says_so(start_state, config):
    """Game 22: two rows beyond the border held no farm, and nothing said it."""
    _stretch_fields(start_state, 2)
    line = _campi_line(start_state, config)
    assert "18 tiles still to claim" in line
    assert "its land still to claim adds no room (a farm needs 3 x 3 tiles)" in line


def test_a_zone_deep_enough_tells_its_future_room(start_state, config):
    _stretch_fields(start_state, 3)
    line = _campi_line(start_state, config)
    assert "once all its land is claimed and cleared: room for 3 more farm" in line


def test_a_zone_with_no_land_to_claim_adds_nothing(start_state, config):
    assert "still to claim" not in _campi_line(start_state, config)
