"""The Architect's briefing and the manual on the hex grid (docs/DESIGN.md,
"Hex grid", step 3): rows as runs, a ring of 4, shapes in hexes."""

import re

from engine import new_game
from server.council import manual
from server.council.map_text import HEX_LEGEND, HEX_RING, _map_cells, architect_lines, grid_lines


def _parse_runs(lines):
    """Back from "y=13 (odd): x2-3 , | x4-5 F" to {(x, y): char}."""
    cells = {}
    for line in lines:
        y = int(re.match(r"y=(\d+)", line).group(1))
        for span, char in re.findall(r"x(\d+(?:-\d+)?) (\S)", line.split(": ", 1)[1]):
            first, _, last = span.partition("-")
            for x in range(int(first), int(last or first) + 1):
                cells[(x, y)] = char
    return cells


def test_the_runs_describe_every_hex_in_view(hex_world_config):
    state = new_game(hex_world_config, seed=0)
    lines = grid_lines(state, hex_world_config)
    assert _parse_runs(lines) == _map_cells(state, hex_world_config, HEX_RING)
    core_y = state.square[1] - 2  # the square is at core (5, 2)
    assert lines[0].startswith(f"y={core_y - HEX_RING} (even)")
    assert len(lines) == 12 + 2 * HEX_RING


def test_the_architect_reads_hexes_and_anchors(hex_world_config):
    text = "\n".join(architect_lines(new_game(hex_world_config, seed=0), hex_world_config))
    assert HEX_LEGEND in text and "anchor hex" in text and "top-left" not in text
    assert "room for 2 farm" in text


def test_the_square_briefing_keeps_its_grid(config):
    text = "\n".join(architect_lines(new_game(config, seed=0), config))
    assert HEX_LEGEND not in text and "top-left tile" in text


def test_the_manual_gives_shapes_in_hexes(hex_world_config, config):
    hex_text = manual.prompt_text(hex_world_config)
    assert "farm 7 hexes" in hex_text and "rhombus of 4 hexes" in hex_text and "3 x 3" not in hex_text
    assert "farm 3 x 3 tiles" in manual.prompt_text(config)
    notes = next(s for s in manual.page_sections(hex_world_config) if s["title"] == "Territorio")["notes"]
    assert "esagoni" in notes[0] and "7 esagoni" in notes[0]
