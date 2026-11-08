"""@brief Drawing aid for the static world map: writes engine/maps/world.txt
from the core template (engine/maps/core.toml) and a few hand-placed
features, and prints a preview with the starting buildings.

Usage: docker compose run --rm -T tests python lab/draw_world.py [--write]

The output file is the source of truth and may be edited by hand
afterwards; this script is not part of the game. Deterministic: the
blobs use a fixed random seed, so the same script draws the same map.
"""

import random
import sys
import tomllib
from pathlib import Path

MAPS_DIR = Path(__file__).resolve().parent.parent / "engine" / "maps"
SIZE = 64
CORE = 12
# Top-left tile of the 8 starting sites: a ring of 3 + 2 + 3, the centre left free.
SITES = [(4, 4), (26, 4), (48, 4), (4, 26), (48, 26), (4, 48), (26, 48), (48, 48)]
# Hand-placed features outside the cores: (centre x, centre y, radius, terrain).
BLOBS = [
    # between the cores of the top row
    (20, 6, 3, "T"), (42, 10, 3, "^"), (20, 14, 2, "^"), (42, 3, 2, "T"),
    # between the top row and the middle
    (9, 20, 3, "T"), (31, 20, 3, "T"), (54, 20, 3, "^"), (21, 21, 2, "^"), (43, 21, 3, "T"),
    # the free centre: forest, hill and plain along the river
    (28, 29, 3, "T"), (34, 34, 2, "^"), (38, 28, 2, "T"),
    # between the middle and the bottom row
    (9, 43, 3, "^"), (31, 43, 3, "T"), (54, 43, 3, "T"), (21, 42, 2, "T"), (43, 42, 2, "^"),
    # between the cores of the bottom row
    (20, 53, 3, "^"), (42, 57, 3, "T"), (20, 61, 2, "T"), (42, 50, 2, "^"),
    # along the edges
    (1, 32, 2, "T"), (62, 32, 2, "^"), (32, 1, 2, "^"), (32, 62, 2, "^"),
]
LETTERS = {"farm": "F", "sawmill": "S", "quarry": "Q", "house": "H", "square": "P"}
FOOTPRINTS = {"farm": (3, 3), "sawmill": (2, 1), "quarry": (2, 2), "house": (1, 1), "square": (2, 2)}


def load_core() -> dict:
    with open(MAPS_DIR / "core.toml", "rb") as core_file:
        core = tomllib.load(core_file)
    core["rows"] = [row.strip() for row in core["terrain"].strip().splitlines()]
    assert len(core["rows"]) == CORE and all(len(row) == CORE for row in core["rows"])
    return core


def in_core(x: int, y: int) -> bool:
    return any(sx <= x < sx + CORE and sy <= y < sy + CORE for sx, sy in SITES)


def draw_blobs(grid: list[list[str]]) -> None:
    """@brief Rounded patches with a ragged edge, never inside a core."""
    rng = random.Random(2026_11_08)
    for cx, cy, radius, terrain in BLOBS:
        for y in range(cy - radius - 1, cy + radius + 2):
            for x in range(cx - radius - 1, cx + radius + 2):
                if not (0 <= x < SIZE and 0 <= y < SIZE) or in_core(x, y):
                    continue
                distance_sq = (x - cx) ** 2 + (y - cy) ** 2
                if distance_sq <= radius * radius + rng.randint(-2, 2):
                    grid[y][x] = terrain


def river_ends(core: dict) -> tuple[int, int]:
    """@brief Column of the river on the core's first and last row."""
    return core["rows"][0].index("~"), core["rows"][-1].index("~")


def draw_rivers(grid: list[list[str]], core: dict) -> None:
    """@brief Each core's river runs on to the world edge or to the core
    below; a step is drawn where the columns differ, so the river stays
    connected side to side."""
    top, bottom = river_ends(core)
    for sx, sy in SITES:
        above = [s for s in SITES if s[0] == sx and s[1] < sy]
        if not above:  # up to the world edge; otherwise the core above draws the stretch
            for y in range(0, sy):
                grid[y][sx + top] = "~"
        below = [s for s in SITES if s[0] == sx and s[1] > sy]
        end = min((s[1] for s in below), default=SIZE)
        for y in range(sy + CORE, end):
            grid[y][sx + bottom] = "~"
        if below and top != bottom:
            grid[end - 1][sx + top] = "~"  # the step into the next core's river


def paste_cores(grid: list[list[str]], core: dict) -> None:
    for sx, sy in SITES:
        for y, row in enumerate(core["rows"]):
            for x, terrain in enumerate(row):
                grid[sy + y][sx + x] = terrain


def preview(grid: list[list[str]], core: dict) -> str:
    """@brief The world with the starting buildings and the site numbers."""
    shown = [row[:] for row in grid]
    for index, (sx, sy) in enumerate(SITES):
        for building in core["buildings"]:
            width, height = FOOTPRINTS[building["kind"]]
            for dy in range(height):
                for dx in range(width):
                    shown[sy + building["y"] + dy][sx + building["x"] + dx] = LETTERS[building["kind"]]
        shown[sy][sx] = str(index + 1)  # site number on the core's top-left tile
    header = "    " + "".join(str(x // 10) if x % 10 == 0 else " " for x in range(SIZE))
    return "\n".join([header] + [f"{y:>3} " + "".join(row) for y, row in enumerate(shown)])


def core_report(core: dict) -> str:
    counts = {}
    for row in core["rows"]:
        for terrain in row:
            counts[terrain] = counts.get(terrain, 0) + 1
    built = sum(FOOTPRINTS[b["kind"]][0] * FOOTPRINTS[b["kind"]][1] for b in core["buildings"])
    return (f"core 12 x 12: plain {counts.get('.', 0)}, river {counts.get('~', 0)}, forest {counts.get('T', 0)},"
            f" hill {counts.get('^', 0)}; built {built} tiles; plain left free {counts.get('.', 0) - built + 4}"
            " (the quarry stands on hill)")


def main(argv: list[str]) -> None:
    core = load_core()
    grid = [["."] * SIZE for _ in range(SIZE)]
    draw_blobs(grid)
    draw_rivers(grid, core)
    paste_cores(grid, core)
    print(core_report(core))
    print(preview(grid, core))
    if "--write" in argv:
        (MAPS_DIR / "world.txt").write_text("\n".join("".join(row) for row in grid) + "\n", encoding="utf-8")
        print(f"written {MAPS_DIR / 'world.txt'}")


if __name__ == "__main__":
    main(sys.argv[1:])
