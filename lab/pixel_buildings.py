"""@brief Our own pixel-art buildings for the map mockup (houses and the
palace), drawn by code in the colours of the Tiny Town palette so the
recolouring treats them like the Kenney tiles.

Why our own: Tiny Town's roofs are flat bands one tile high, so houses side
by side merged into one strip and the palace looked like a big house
(feedback 2026-11-08). Here every house has a pitched roof with ridge and
eaves, a strip of grass on each side, and varies by era and by id.

Coordinates are pixels of the mockup canvas; a house fills one 32 x 32
block (one engine tile), the palace a 64 x 64 block (2 x 2 engine tiles).
All choices are deterministic (by building id), so the same map gives the
same picture.
"""

# Palette indices of the Kenney Tiny Town sheet (see lab/tiny_town_mockup.py).
INK = 18
GOLD_LIGHT, GOLD_DARK = 24, 21
ROOFS = {
    "thatch": (24, 21, 1),     # straw: light, mid, dark
    "tiles": (20, 26, 25),     # red clay tiles
    "slate": (16, 27, 2),      # grey slate
}
WALLS = {
    "planks": (6, 1, 12),      # wood: light, mid, dark
    "plaster": (11, 17, 6),    # whitewash
    "stone": (9, 16, 27),      # grey stone
}
DOOR, DOOR_DARK, GLASS, GLASS_LIGHT = 12, 25, 27, 9

# Roof and wall per era, picked in turn by building id.
ERA_STYLES = {
    1: (("thatch", "planks"), ("thatch", "plaster"), ("thatch", "planks")),
    2: (("tiles", "plaster"), ("tiles", "planks"), ("slate", "plaster"), ("tiles", "stone")),
    3: (("slate", "stone"), ("tiles", "stone"), ("slate", "plaster")),
}


def put(canvas, palette, x: int, y: int, index: int) -> None:
    canvas.pixels[y][x] = palette[index]


def fill(canvas, palette, x0: int, y0: int, width: int, height: int, index: int) -> None:
    for y in range(y0, y0 + height):
        for x in range(x0, x0 + width):
            put(canvas, palette, x, y, index)


def frame(canvas, palette, x0: int, y0: int, width: int, height: int, index: int = INK) -> None:
    for x in range(x0, x0 + width):
        put(canvas, palette, x, y0, index)
        put(canvas, palette, x, y0 + height - 1, index)
    for y in range(y0, y0 + height):
        put(canvas, palette, x0, y, index)
        put(canvas, palette, x0 + width - 1, y, index)


def shade(canvas, x0: int, y0: int, width: int, factor: float = 0.7) -> None:
    """@brief Darken one row of what is already drawn (a cast shadow on the grass)."""
    row = canvas.pixels[y0]
    for x in range(x0, x0 + width):
        row[x] = tuple(int(c * factor) for c in row[x])


def draw_roof(canvas, palette, x0, y0, width, height, kind: str, seed: int) -> None:
    """@brief A pitched roof seen from the front and above: outline, light
    ridge, texture (tile courses or straw), dark eaves, shaded ends."""
    light, mid, dark = ROOFS[kind]
    fill(canvas, palette, x0, y0, width, height, mid)
    frame(canvas, palette, x0, y0, width, height)
    for x in range(x0 + 1, x0 + width - 1):
        put(canvas, palette, x, y0 + 1, light)
        put(canvas, palette, x, y0 + height - 2, dark)
    for y in range(y0 + 2, y0 + height - 2):
        put(canvas, palette, x0 + 1, y, dark)
        put(canvas, palette, x0 + width - 2, y, dark)
    if kind == "thatch":
        for x in range(x0 + 3, x0 + width - 3, 2):
            start = y0 + 3 + (x * 7 + seed) % 3
            for y in range(start, min(start + 4, y0 + height - 3)):
                put(canvas, palette, x, y, dark)
        return
    for course, y in enumerate(range(y0 + 4, y0 + height - 3, 3)):
        for x in range(x0 + 2, x0 + width - 2):
            if (x + course * 2) % 4 != 0:
                put(canvas, palette, x, y, dark)


def draw_wall(canvas, palette, x0, y0, width, height, kind: str, seed: int) -> None:
    """@brief Front wall under the eaves: shadow line on top, texture."""
    light, mid, dark = WALLS[kind]
    fill(canvas, palette, x0, y0, width, height, mid)
    frame(canvas, palette, x0, y0 - 1, width, height + 1)
    for x in range(x0 + 1, x0 + width - 1):
        put(canvas, palette, x, y0, dark)
    if kind == "planks":
        for y in range(y0 + 3, y0 + height - 1, 3):
            for x in range(x0 + 1, x0 + width - 1):
                put(canvas, palette, x, y, dark)
    elif kind == "stone":
        for course, y in enumerate(range(y0 + 3, y0 + height - 1, 3)):
            for x in range(x0 + 1, x0 + width - 1):
                put(canvas, palette, x, y, dark)
            for x in range(x0 + 2 + (course % 2) * 3, x0 + width - 1, 6):
                put(canvas, palette, x, y - 1, dark)
                put(canvas, palette, x, y - 2, dark)
    else:
        for i in range(4):
            put(canvas, palette, x0 + 2 + (seed * 5 + i * 7) % (width - 4), y0 + 2 + (seed + i * 3) % (height - 3), light)


def draw_door(canvas, palette, x0, y0, width, height) -> None:
    fill(canvas, palette, x0, y0, width, height, DOOR)
    frame(canvas, palette, x0, y0, width, height)
    for y in range(y0 + 1, y0 + height - 1):
        put(canvas, palette, x0 + width // 2, y, DOOR_DARK)
    put(canvas, palette, x0 + width - 2, y0 + height // 2, GOLD_LIGHT)


def draw_window(canvas, palette, x0, y0, width=5, height=4) -> None:
    fill(canvas, palette, x0, y0, width, height, GLASS)
    frame(canvas, palette, x0, y0, width, height)
    put(canvas, palette, x0 + 1, y0 + 1, GLASS_LIGHT)


def draw_arch(canvas, palette, x0, y0, width, height, wall_index: int) -> None:
    """@brief A dark arched opening: an ink rectangle whose top corners are
    given back to the wall, so the top reads as rounded."""
    fill(canvas, palette, x0, y0, width, height, INK)
    for x, y in ((x0, y0), (x0 + 1, y0), (x0, y0 + 1),
                 (x0 + width - 1, y0), (x0 + width - 2, y0), (x0 + width - 1, y0 + 1)):
        put(canvas, palette, x, y, wall_index)


def draw_banner(canvas, palette, pole_x, top_y, pole_height, flag_left: bool = True) -> None:
    """@brief The sovereign's banner: a dark pole and a gold flag."""
    for y in range(top_y, top_y + pole_height):
        put(canvas, palette, pole_x, y, INK)
    flag_x0 = pole_x - 7 if flag_left else pole_x + 1
    fill(canvas, palette, flag_x0, top_y + 1, 7, 5, GOLD_LIGHT)
    frame(canvas, palette, flag_x0, top_y + 1, 7, 5, GOLD_DARK)


def draw_house(canvas, palette, px: int, py: int, building_id: int, era: int) -> None:
    """@brief One house in its 32 x 32 block: grass shows 1-2 px on each
    side, so neighbours stay apart. Door left or right, chimney on some."""
    roof, wall = ERA_STYLES[era][building_id % len(ERA_STYLES[era])]
    door_left = building_id % 2 == 0
    if building_id % 3 == 0:
        fill(canvas, palette, px + 21, py + 1, 4, 6, WALLS["stone"][1])
        frame(canvas, palette, px + 21, py + 1, 4, 6)
    draw_roof(canvas, palette, px + 1, py + 4, 30, 14, roof, building_id)
    draw_wall(canvas, palette, px + 4, py + 18, 24, 12, wall, building_id)
    draw_door(canvas, palette, px + (7 if door_left else 19), py + 22, 6, 8)
    draw_window(canvas, palette, px + (19 if door_left else 8), py + 21)
    shade(canvas, px + 4, py + 30, 24)


def draw_lord_hall(canvas, palette, px: int, py: int) -> None:
    """@brief Era 1: the lord's hall, a long thatched hall behind a fence,
    the only building with the gold banner."""
    draw_roof(canvas, palette, px + 3, py + 10, 54, 24, "thatch", 3)
    draw_wall(canvas, palette, px + 7, py + 34, 46, 22, "planks", 1)
    draw_door(canvas, palette, px + 25, py + 44, 10, 12)
    for wx in (12, 43):
        draw_window(canvas, palette, px + wx, py + 40)
    shade(canvas, px + 7, py + 56, 46)
    for x in range(px + 1, px + 63):
        put(canvas, palette, x, py + 60, WALLS["planks"][1])
    for x in range(px + 1, px + 63, 4):
        for y in range(py + 58, py + 63):
            put(canvas, palette, x, y, WALLS["planks"][2])
    draw_banner(canvas, palette, px + 60, py + 1, 33)


def draw_town_hall(canvas, palette, px: int, py: int) -> None:
    """@brief Era 2: the town hall, a civic tower on the left and a loggia
    of three arches under the main hall; the banner flies from the tower."""
    draw_roof(canvas, palette, px + 18, py + 16, 44, 16, "tiles", 2)
    draw_wall(canvas, palette, px + 20, py + 32, 40, 26, "plaster", 4)
    for ax in (24, 36, 48):
        draw_arch(canvas, palette, px + ax, py + 46, 8, 12, WALLS["plaster"][1])
        draw_window(canvas, palette, px + ax + 1, py + 37)
    shade(canvas, px + 20, py + 58, 40)
    # The tower: a narrow stone shaft with a pyramid roof and a bell opening.
    for row in range(8):
        inset = 7 - row
        fill(canvas, palette, px + 3 + inset, py + 2 + row, 14 - 2 * inset, 1, ROOFS["slate"][1 if row > 2 else 0])
        put(canvas, palette, px + 3 + inset, py + 2 + row, INK)
        put(canvas, palette, px + 16 - inset, py + 2 + row, INK)
    draw_wall(canvas, palette, px + 4, py + 11, 12, 48, "stone", 2)
    draw_arch(canvas, palette, px + 7, py + 15, 6, 7, WALLS["stone"][1])
    draw_window(canvas, palette, px + 8, py + 30, 4, 4)
    shade(canvas, px + 4, py + 59, 12)
    draw_banner(canvas, palette, px + 58, py + 3, 13)
