"""@brief Map mockup: the realm's starting core drawn with Kenney's Tiny Town
tiles (CC0, lab/assets/kenney_tiny_town), in the original palette and in a
"serious" one (desaturated, earthy, ink outlines).

Scale (decided 2026-11-08): one engine tile = 2 x 2 Tiny Town tiles of
16 px, so a 1 x 1 house is drawn as a 2 x 2 house (roof above, wall and door
below), a 3 x 3 farm as 6 x 6, and so on. The engine does not change.

Tiles Tiny Town lacks (water, hills, crops) are drawn here as 16 x 16
character grids or by simple rules, using colours of the Kenney palette,
so the recolouring treats them like the rest.

Usage: python3 lab/tiny_town_mockup.py OUT_DIR
Writes OUT_DIR/core_original.png, core_serious.png, core_dark.png and,
with the proposed palace, core_era1.png .. core_era3.png (serious palette). Not part
of the game; reads engine/maps directly and needs no database.

Resources: the view is 16 x 16 engine tiles = 32 x 32 sub-tiles = 512 x 512
pixels, written at 2x (1024 x 1024). Held as Python tuples: some tens of MB,
a few seconds of run time.
"""

import colorsys
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pixel_png import read_indexed, write_rgb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHEET = Path(__file__).resolve().parent / "assets" / "kenney_tiny_town" / "tilemap_packed.png"
TILE, SHEET_COLUMNS = 16, 12
SITE = (4, 4)                 # first starting site of engine/maps/world.txt
VIEW = (2, 2, 16, 16)         # x, y, width, height in engine tiles (core plus a margin)
SCALE_OUT = 2                 # each pixel written as 2 x 2

# Tiny Town tile indices (row * 12 + column of the packed sheet).
GRASS = (0, 0, 0, 0, 0, 0, 1, 1, 2)  # weighted: plain grass most often, few flowers
FOREST = {"TL": 6, "T": 7, "TR": 8, "L": 18, "M": 19, "R": 20, "BL": 30, "B": 31, "BR": 32}
DIRT = {"TL": 12, "T": 13, "TR": 14, "L": 24, "M": 25, "R": 26, "BL": 36, "B": 37, "BR": 38}
PAVING = {"TL": 96, "T": 97, "TR": 98, "L": 108, "M": 109, "R": 110, "BL": 120, "B": 121, "BR": 122}
SLATE_ROOF, RED_ROOF = (60, 61, 62), (64, 65, 66)
WOOD_WALL = {"left": 72, "mid": 73, "door_open": 74, "right": 75, "window": 84, "door": 85}
STONE_WALL = {"window": 88, "door": 89}
WELL_TOP, WELL_BOTTOM, SIGN = 92, 104, 83
PICKAXE, AXE, LOG, BRICKS, SPROUT = 115, 127, 106, 126, 17

# Palette indices of the sheet used by the hand-drawn tiles.
INK, OUTLINE_BLUE = 18, 23
WATER, WATER_LIGHT, WATER_DARK = 10, 5, 2
SAND, EARTH = 6, 13
ROCK_LIGHT, ROCK, ROCK_DARK = 9, 16, 27
WHEAT, WHEAT_DARK, LEAF = 24, 21, 15
GOLD = (212, 175, 90)

# Hand-drawn tiles: '.' transparent, the other characters name palette indices.
HAND_COLOURS = {"o": OUTLINE_BLUE, "l": ROCK_LIGHT, "g": ROCK, "d": ROCK_DARK}
ROCK_MOUND = """
................
................
................
......oooo......
....oollllo.....
...ollllllgo....
..olllllggggo...
..ollllgggggo...
.olllggggggddo..
.ollgggggddddo..
.olggggddddddo..
..oooooooooooo..
................
................
................
................
"""
SMALL_ROCKS = """
................
................
..........ooo...
.........ollgo..
.........olgdo..
..........ooo...
................
................
...ooo..........
..ollgo.........
..olgddo........
...ooooo........
................
.............oo.
............olgo
.............oo.
"""


def parse_hand_tile(text: str) -> list[list[int | None]]:
    """@brief Character grid -> rows of palette indices (None = transparent)."""
    rows = [line for line in text.strip("\n").splitlines()]
    return [[None if ch == "." else HAND_COLOURS[ch] for ch in row] for row in rows]


def crop_tile() -> list[list[int | None]]:
    """@brief Rows of wheat over soil: four furrows, light ears, dark shadow."""
    tile = [[None] * TILE for _ in range(TILE)]
    for top in (0, 4, 8, 12):
        for x in range(TILE):
            tile[top][x] = WHEAT if x % 4 != 3 else WHEAT_DARK
            tile[top + 1][x] = WHEAT
            tile[top + 2][x] = WHEAT_DARK
    return tile


def spot_hash(x: int, y: int, modulo: int) -> int:
    """@brief Deterministic pseudo-random choice per tile (same map, same picture)."""
    return ((x * 73856093) ^ (y * 19349663) ^ 0x5bd1e995) % modulo


class Canvas:
    """@brief The picture in palette indices of the sheet plus explicit RGB overrides."""

    def __init__(self, width_px: int, height_px: int):
        self.pixels: list[list[tuple[int, int, int]]] = [[(0, 0, 0)] * width_px for _ in range(height_px)]

    def put_sheet_tile(self, sheet, index: int, sub_x: int, sub_y: int) -> None:
        rows, palette, alpha = sheet
        sheet_x, sheet_y = (index % SHEET_COLUMNS) * TILE, (index // SHEET_COLUMNS) * TILE
        for dy in range(TILE):
            for dx in range(TILE):
                colour_index = rows[sheet_y + dy][sheet_x + dx]
                if alpha[colour_index] > 0:
                    self.pixels[sub_y * TILE + dy][sub_x * TILE + dx] = palette[colour_index]

    def put_hand_tile(self, palette, tile, sub_x: int, sub_y: int) -> None:
        for dy, row in enumerate(tile):
            for dx, colour_index in enumerate(row):
                if colour_index is not None:
                    self.pixels[sub_y * TILE + dy][sub_x * TILE + dx] = palette[colour_index]


def load_map() -> tuple[list[str], dict]:
    world = [row for row in (ROOT / "engine/maps/world.txt").read_text().splitlines() if row]
    core = tomllib.loads((ROOT / "engine/maps/core.toml").read_text())
    return world, core


def terrain_at(world: list[str], sub_x: int, sub_y: int) -> str:
    """@brief Terrain char of the engine tile under a sub-tile of the view."""
    return world[VIEW[1] + sub_y // 2][VIEW[0] + sub_x // 2]


def edge_piece(inside, sub_x: int, sub_y: int) -> str:
    """@brief Nine-slice piece name for a sub-tile of a region (TL, T, ..., M)."""
    vertical = "T" if not inside(sub_x, sub_y - 1) else "B" if not inside(sub_x, sub_y + 1) else ""
    horizontal = "L" if not inside(sub_x - 1, sub_y) else "R" if not inside(sub_x + 1, sub_y) else ""
    return (vertical + horizontal) or "M"


def draw_terrain(canvas: Canvas, sheet, world: list[str]) -> None:
    rows, palette, alpha = sheet
    size = VIEW[2] * 2
    mound, rocks = parse_hand_tile(ROCK_MOUND), parse_hand_tile(SMALL_ROCKS)

    def is_forest(x, y):
        return 0 <= x < size and 0 <= y < size and terrain_at(world, x, y) == "T"

    for sub_y in range(size):
        for sub_x in range(size):
            char = terrain_at(world, sub_x, sub_y)
            canvas.put_sheet_tile(sheet, GRASS[spot_hash(sub_x, sub_y, len(GRASS))], sub_x, sub_y)
            if char == "T":
                canvas.put_sheet_tile(sheet, FOREST[edge_piece(is_forest, sub_x, sub_y)], sub_x, sub_y)
            elif char == "^":
                shade_tile(canvas, sub_x, sub_y, 0.8)
                canvas.put_hand_tile(palette, mound if spot_hash(sub_x, sub_y, 2) == 0 else rocks, sub_x, sub_y)
            elif char == "~":
                draw_water(canvas, palette, world, sub_x, sub_y)


def shade_tile(canvas: Canvas, sub_x: int, sub_y: int, factor: float) -> None:
    """@brief Darken a sub-tile already drawn (hills stand on darker, drier ground)."""
    for dy in range(TILE):
        row = canvas.pixels[sub_y * TILE + dy]
        for dx in range(TILE):
            x = sub_x * TILE + dx
            row[x] = tuple(int(c * factor) for c in row[x])


def draw_water(canvas: Canvas, palette, world: list[str], sub_x: int, sub_y: int) -> None:
    """@brief Water by rule: base colour, a few ripples, a sand bank and an
    ink line on every side that touches land (no autotile set needed)."""
    size = VIEW[2] * 2

    def is_water(x, y):
        return not (0 <= x < size and 0 <= y < size) or terrain_at(world, x, y) == "~"

    left, top = sub_x * TILE, sub_y * TILE
    for dy in range(TILE):
        for dx in range(TILE):
            canvas.pixels[top + dy][left + dx] = palette[WATER_DARK if (dy + spot_hash(sub_x, sub_y, 4)) % 7 == 0 and dx % 5 < 3 else WATER]
    for ripple in range(2):
        rx, ry = 2 + spot_hash(sub_x + ripple, sub_y, 9), 3 + spot_hash(sub_x, sub_y + ripple, 10)
        for dx in range(3):
            canvas.pixels[top + ry][left + rx + dx] = palette[WATER_LIGHT]
    sides = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}
    for side, (step_x, step_y) in sides.items():
        if is_water(sub_x + step_x, sub_y + step_y):
            continue
        for i in range(TILE):
            for depth, colour in ((0, SAND), (1, SAND), (2, INK)):
                px, py = {"N": (i, depth), "S": (i, TILE - 1 - depth),
                          "W": (depth, i), "E": (TILE - 1 - depth, i)}[side]
                canvas.pixels[top + py][left + px] = palette[colour]


def view_sub(x: int, y: int) -> tuple[int, int]:
    """@brief Engine tile (world coordinates) -> top-left sub-tile of the view."""
    return (x - VIEW[0]) * 2, (y - VIEW[1]) * 2


def draw_patch(canvas: Canvas, sheet, pieces: dict, sub_x: int, sub_y: int, width: int, height: int) -> None:
    """@brief Fill a width x height block of sub-tiles with a nine-slice set."""
    def inside(x, y):
        return sub_x <= x < sub_x + width and sub_y <= y < sub_y + height
    for y in range(sub_y, sub_y + height):
        for x in range(sub_x, sub_x + width):
            canvas.put_sheet_tile(sheet, pieces[edge_piece(inside, x, y)], x, y)


# The palace, proposed 2026-11-08: a fixed 2 x 2 building east of the square
# (core tiles (7,3)-(8,4), free plain in the centre zone). Mockup only: the
# engine does not know it yet. One 4 x 4 drawing per era, rows top to bottom.
PALACE_CORE_TILE = (7, 3)
PALACE_BY_ERA = {
    1: ((52, 53, 53, 54),          # village: the lord's hall, wood and red tiles
        (64, 65, 65, 66),
        (72, 73, 73, 75),
        (84, 86, 87, 84)),
    2: ((48, 51, 49, 50),          # town: the town hall, stone, slate, a dormer
        (60, 61, 61, 62),
        (76, 77, 77, 79),
        (88, 90, 91, 88)),
    3: ((99, 100, 100, 101),       # kingdom: the castle, battlements and gate
        (125, 126, 126, 125),
        (126, 111, 112, 126),
        (126, 123, 124, 126)),
}


def draw_palace(canvas: Canvas, sheet, era: int, sub_x: int, sub_y: int) -> None:
    for dy, row in enumerate(PALACE_BY_ERA[era]):
        for dx, index in enumerate(row):
            canvas.put_sheet_tile(sheet, index, sub_x + dx, sub_y + dy)


def house_style(building_id: int, era: int | None) -> tuple[tuple, dict]:
    """@brief Roof and walls of a house: the village builds in wood, the
    town mixes wood and stone, the kingdom builds in stone and slate."""
    if era == 1:
        return (RED_ROOF if building_id % 2 else SLATE_ROOF), WOOD_WALL
    if era == 3:
        return SLATE_ROOF, STONE_WALL
    return (SLATE_ROOF if building_id % 2 else RED_ROOF), (WOOD_WALL if building_id % 3 else STONE_WALL)


def draw_house(canvas: Canvas, sheet, building_id: int, sub_x: int, sub_y: int, era: int | None = None) -> None:
    roof, walls = house_style(building_id, era)
    canvas.put_sheet_tile(sheet, roof[0], sub_x, sub_y)
    canvas.put_sheet_tile(sheet, roof[2], sub_x + 1, sub_y)
    canvas.put_sheet_tile(sheet, walls["window"], sub_x, sub_y + 1)
    canvas.put_sheet_tile(sheet, walls["door"], sub_x + 1, sub_y + 1)


def draw_farm(canvas: Canvas, sheet, sub_x: int, sub_y: int) -> None:
    rows, palette, alpha = sheet
    draw_patch(canvas, sheet, DIRT, sub_x, sub_y, 6, 6)
    crops = crop_tile()
    for y in range(sub_y + 1, sub_y + 5):
        for x in range(sub_x + 1, sub_x + 5):
            canvas.put_hand_tile(palette, crops, x, y)
    canvas.put_sheet_tile(sheet, SPROUT, sub_x, sub_y + 5)


def draw_sawmill(canvas: Canvas, sheet, sub_x: int, sub_y: int) -> None:
    for i, index in enumerate((SLATE_ROOF[0], SLATE_ROOF[1], SLATE_ROOF[1], SLATE_ROOF[2])):
        canvas.put_sheet_tile(sheet, index, sub_x + i, sub_y)
    for i, index in enumerate((WOOD_WALL["left"], WOOD_WALL["door_open"], WOOD_WALL["mid"], WOOD_WALL["right"])):
        canvas.put_sheet_tile(sheet, index, sub_x + i, sub_y + 1)


def draw_quarry(canvas: Canvas, sheet, sub_x: int, sub_y: int) -> None:
    rows, palette, alpha = sheet
    draw_patch(canvas, sheet, DIRT, sub_x, sub_y, 4, 4)
    canvas.put_hand_tile(palette, parse_hand_tile(ROCK_MOUND), sub_x + 1, sub_y + 1)
    canvas.put_sheet_tile(sheet, BRICKS, sub_x + 2, sub_y + 1)
    canvas.put_sheet_tile(sheet, PICKAXE, sub_x + 1, sub_y + 2)
    canvas.put_hand_tile(palette, parse_hand_tile(SMALL_ROCKS), sub_x + 2, sub_y + 2)


def draw_square(canvas: Canvas, sheet, sub_x: int, sub_y: int, era: int | None = None) -> None:
    """@brief The square: beaten earth in the village, paved from the town on."""
    draw_patch(canvas, sheet, DIRT if era == 1 else PAVING, sub_x, sub_y, 4, 4)
    canvas.put_sheet_tile(sheet, WELL_TOP, sub_x + 1, sub_y + 1)
    canvas.put_sheet_tile(sheet, WELL_BOTTOM, sub_x + 1, sub_y + 2)
    canvas.put_sheet_tile(sheet, SIGN, sub_x + 2, sub_y + 2)


def draw_buildings(canvas: Canvas, sheet, core: dict, era: int | None = None) -> None:
    """@brief Square, buildings and, when an era is given, the proposed palace."""
    site_x, site_y = SITE
    draw_square(canvas, sheet, *view_sub(site_x + core["square"]["x"], site_y + core["square"]["y"]), era)
    if era is not None:
        draw_palace(canvas, sheet, era, *view_sub(site_x + PALACE_CORE_TILE[0], site_y + PALACE_CORE_TILE[1]))
    drawers = {"farm": draw_farm, "sawmill": draw_sawmill, "quarry": draw_quarry}
    for building_id, item in enumerate(core["buildings"], start=1):
        sub_x, sub_y = view_sub(site_x + item["x"], site_y + item["y"])
        if item["kind"] == "house":
            draw_house(canvas, sheet, building_id, sub_x, sub_y, era)
        else:
            drawers[item["kind"]](canvas, sheet, sub_x, sub_y)


def make_recolour(saturation_kept: float, sepia_mix: float, darken: float):
    """@brief A recolouring: less saturation, darker, greens pulled to olive,
    everything tinted towards sepia. Two strengths are rendered to compare."""
    return lambda rgb: tone_colour(rgb, saturation_kept, sepia_mix, darken)


def tone_colour(rgb, saturation_kept: float, sepia_mix: float, darken: float) -> tuple[int, int, int]:
    red, green, blue = (c / 255 for c in rgb)
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    if 0.2 < hue < 0.45:
        hue -= 0.035
    saturation *= saturation_kept
    lightness = 0.06 + lightness * darken
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    sepia = (0.42, 0.35, 0.26)
    mix = sepia_mix
    return tuple(int(255 * ((1 - mix) * c + mix * s)) for c, s in zip((red, green, blue), sepia))


SERIOUS = make_recolour(0.5, 0.18, 0.8)  # the chosen palette (mockup 2, 2026-11-08)


def finish(canvas: Canvas, world_owned, recolour) -> list[list[tuple[int, int, int]]]:
    """@brief Recolour, dim the land outside the realm, draw the border, scale up."""
    height, width = len(canvas.pixels), len(canvas.pixels[0])
    out = []
    for y in range(height):
        row = []
        for x in range(width):
            colour = recolour(canvas.pixels[y][x])
            if not world_owned(x // (2 * TILE), y // (2 * TILE)):
                colour = tuple(int(c * 0.5 + 18) for c in colour)
            row.append(colour)
        out.append(row)
    draw_border(out, world_owned)
    return [[pixel for pixel in row for _ in range(SCALE_OUT)] for row in out for _ in range(SCALE_OUT)]


def draw_border(pixels, world_owned) -> None:
    """@brief A 2 px gold line along every edge between owned and not owned tiles."""
    block = 2 * TILE
    for tile_y in range(VIEW[3]):
        for tile_x in range(VIEW[2]):
            if not world_owned(tile_x, tile_y):
                continue
            for step_x, step_y in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                if world_owned(tile_x + step_x, tile_y + step_y):
                    continue
                for i in range(block):
                    for depth in range(2):
                        px = tile_x * block + (i if step_x == 0 else (depth if step_x < 0 else block - 1 - depth))
                        py = tile_y * block + (i if step_y == 0 else (depth if step_y < 0 else block - 1 - depth))
                        pixels[py][px] = GOLD


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python3 lab/tiny_town_mockup.py OUT_DIR")
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = read_indexed(str(SHEET))
    world, core = load_map()
    core_size = len(core["terrain"].strip().splitlines())

    def owned(view_x: int, view_y: int) -> bool:
        x, y = VIEW[0] + view_x, VIEW[1] + view_y
        return SITE[0] <= x < SITE[0] + core_size and SITE[1] <= y < SITE[1] + core_size

    canvas = Canvas(VIEW[2] * 2 * TILE, VIEW[3] * 2 * TILE)
    draw_terrain(canvas, sheet, world)
    draw_buildings(canvas, sheet, core)
    write_rgb(str(out_dir / "core_original.png"), finish(canvas, owned, lambda c: c))
    write_rgb(str(out_dir / "core_serious.png"), finish(canvas, owned, SERIOUS))
    write_rgb(str(out_dir / "core_dark.png"), finish(canvas, owned, make_recolour(0.35, 0.3, 0.68)))
    for era in PALACE_BY_ERA:
        canvas = Canvas(VIEW[2] * 2 * TILE, VIEW[3] * 2 * TILE)
        draw_terrain(canvas, sheet, world)
        draw_buildings(canvas, sheet, core, era)
        write_rgb(str(out_dir / f"core_era{era}.png"), finish(canvas, owned, SERIOUS))


if __name__ == "__main__":
    main()
