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


def draw_gable_roof(canvas, palette, centre_x: int, top: int, half_base: int, height: int,
                    kind: str, seed: int) -> None:
    """@brief A roof seen gable-on: a triangle, sunlit left slope, shaded
    right slope, courses (or straw) and an ink outline."""
    light, mid, dark = ROOFS[kind]
    for row in range(height):
        half = 1 + (half_base - 1) * row // (height - 1)
        x0, x1 = centre_x - half, centre_x + half - 1
        for x in range(x0, x1 + 1):
            colour = mid
            if kind == "thatch" and (x * 7 + row + seed) % 5 == 0:
                colour = dark
            elif kind != "thatch" and row % 3 == 2 and (x + row) % 4 != 0:
                colour = dark
            put(canvas, palette, x, top + row, colour)
        if half > 2:
            put(canvas, palette, x0 + 1, top + row, light)
            put(canvas, palette, x1 - 1, top + row, dark)
        put(canvas, palette, x0, top + row, INK)
        put(canvas, palette, x1, top + row, INK)
    for x in range(centre_x - half_base, centre_x + half_base):
        put(canvas, palette, x, top + height - 1, INK)


def cast_shadow(canvas, x_right: int, y0: int, y1: int, x_left: int) -> None:
    """@brief Shadow on the grass: two columns right of the building and one
    row under it, so neighbours read as separate volumes."""
    for y in range(y0, y1 + 1):
        shade_pixel(canvas, x_right + 1, y)
        shade_pixel(canvas, x_right + 2, y)
    for x in range(x_left + 2, x_right + 3):
        shade_pixel(canvas, x, y1 + 1)


def shade_pixel(canvas, x: int, y: int, factor: float = 0.72) -> None:
    canvas.pixels[y][x] = tuple(int(c * factor) for c in canvas.pixels[y][x])


def draw_house(canvas, palette, px: int, py: int, building_id: int, era: int) -> None:
    """@brief One house in its 32 x 32 block, narrower than the block so
    6 px of grass separate two neighbours. Houses alternate by id between
    eaves-on (long roof, chimney on some) and gable-on (triangle over the
    front), so a row of houses never reads as one block."""
    roof, wall = ERA_STYLES[era][building_id % len(ERA_STYLES[era])]
    if building_id % 2 == 0:
        draw_gable_house(canvas, palette, px, py, building_id, roof, wall)
    else:
        draw_eaves_house(canvas, palette, px, py, building_id, roof, wall)


def draw_eaves_house(canvas, palette, px, py, building_id, roof, wall) -> None:
    door_left = building_id % 4 == 1
    if building_id % 3 == 0:
        fill(canvas, palette, px + 20, py + 3, 4, 6, WALLS["stone"][1])
        frame(canvas, palette, px + 20, py + 3, 4, 6)
    draw_roof(canvas, palette, px + 3, py + 7, 26, 12, roof, building_id)
    draw_wall(canvas, palette, px + 6, py + 19, 20, 10, wall, building_id)
    draw_door(canvas, palette, px + (8 if door_left else 19), py + 22, 5, 7)
    draw_window(canvas, palette, px + (19 if door_left else 8), py + 21, 4, 4)
    cast_shadow(canvas, px + 28, py + 9, py + 28, px + 6)


def draw_gable_house(canvas, palette, px, py, building_id, roof, wall) -> None:
    draw_gable_roof(canvas, palette, px + 16, py + 3, 12, 15, roof, building_id)
    draw_wall(canvas, palette, px + 6, py + 18, 20, 11, wall, building_id)
    draw_window(canvas, palette, px + 15, py + 11, 3, 3)
    draw_door(canvas, palette, px + 13, py + 21, 6, 8)
    cast_shadow(canvas, px + 27, py + 10, py + 28, px + 6)


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


def draw_log_end(canvas, palette, x0: int, y0: int) -> None:
    """@brief The cut end of a log, 6 x 6: bark ring, light wood, a dark heart."""
    for dy in range(6):
        for dx in range(6):
            if (dx in (0, 5)) and (dy in (0, 5)):
                continue
            edge = dx in (0, 5) or dy in (0, 5)
            put(canvas, palette, x0 + dx, y0 + dy, INK if edge else WALLS["planks"][0])
    put(canvas, palette, x0 + 2, y0 + 2, WALLS["planks"][1])
    put(canvas, palette, x0 + 3, y0 + 3, WALLS["planks"][2])


def draw_sawmill(canvas, palette, px: int, py: int) -> None:
    """@brief The sawmill on its 64 x 32 block (2 x 1 engine tiles): an open
    shed (roof on two posts, a log on the sawing trestle inside) and a
    pyramid of logs beside it."""
    draw_roof(canvas, palette, px + 2, py + 3, 38, 11, "tiles", 5)
    fill(canvas, palette, px + 5, py + 14, 32, 14, DOOR_DARK)
    for post_x in (px + 5, px + 35):
        fill(canvas, palette, post_x, py + 14, 2, 14, WALLS["planks"][2])
    # The sawing trestle with a log on it, light wood against the dark shed.
    for leg_x in (px + 11, px + 29):
        fill(canvas, palette, leg_x, py + 22, 2, 6, WALLS["planks"][0])
    fill(canvas, palette, px + 9, py + 17, 24, 5, WALLS["planks"][0])
    frame(canvas, palette, px + 9, py + 17, 24, 5)
    for x in range(px + 10, px + 32, 4):
        put(canvas, palette, x, py + 19, WALLS["planks"][1])
    draw_log_end(canvas, palette, px + 27, py + 16)
    shade(canvas, px + 4, py + 28, 34)
    for row, count in enumerate((4, 3, 2)):
        for i in range(count):
            draw_log_end(canvas, palette, px + 42 + row * 3 + i * 5, py + 22 - row * 5)
    shade(canvas, px + 42, py + 28, 20)


def draw_quarry(canvas, palette, px: int, py: int) -> None:
    """@brief The quarry on its 64 x 64 block: three benches cut into the
    rock, stepping down to the front, cut blocks and a wooden crane."""
    stone_light, stone, stone_dark = WALLS["stone"]
    # The pit: a sunken floor of broken stone, then the benches as terraces
    # whose fronts are cut faces, each one wider than the one above.
    fill(canvas, palette, px + 2, py + 2, 60, 58, stone_dark)
    frame(canvas, palette, px + 2, py + 2, 60, 58)
    for i in range(40):
        put(canvas, palette, px + 4 + (i * 37) % 56, py + 44 + (i * 11) % 14, stone)
    for step, (x0, y0, width) in enumerate(((4, 4, 56), (4, 16, 56), (4, 28, 56))):
        fill(canvas, palette, px + x0, py + y0, width, 4, stone_light)
        fill(canvas, palette, px + x0, py + y0 + 4, width, 8, stone)
        for x in range(px + x0, px + x0 + width):
            put(canvas, palette, x, py + y0 + 11, INK)
        for x in range(px + x0 + 4 + step * 3, px + x0 + width - 2, 9):
            for y in range(py + y0 + 4, py + y0 + 9):
                put(canvas, palette, x, y, stone_dark)
    for bx, by in ((8, 48), (17, 50), (12, 43)):
        fill(canvas, palette, px + bx, py + by, 8, 6, stone_light)
        fill(canvas, palette, px + bx, py + by + 4, 8, 2, stone_dark)
        frame(canvas, palette, px + bx, py + by, 8, 6)
    # The crane: a post, an arm, a rope and a block in the air.
    wood_light, wood, wood_dark = WALLS["planks"]
    fill(canvas, palette, px + 50, py + 30, 3, 28, wood)
    frame(canvas, palette, px + 50, py + 30, 3, 28)
    fill(canvas, palette, px + 36, py + 29, 17, 3, wood_light)
    frame(canvas, palette, px + 36, py + 29, 17, 3)
    for y in range(py + 32, py + 44):
        put(canvas, palette, px + 39, y, INK)
    fill(canvas, palette, px + 36, py + 44, 7, 5, stone_light)
    frame(canvas, palette, px + 36, py + 44, 7, 5)
    shade(canvas, px + 50, py + 58, 6)


def draw_crenellations(canvas, palette, x0: int, y0: int, width: int) -> None:
    """@brief Merlons along a wall top: 3 px wide, 3 px tall, 3 px apart."""
    light = WALLS["stone"][0]
    for x in range(x0, x0 + width):
        if (x - x0) // 3 % 2 == 0:
            for y in range(y0, y0 + 3):
                put(canvas, palette, x, y, light)
            put(canvas, palette, x, y0 - 1, INK)
    for x in range(x0, x0 + width):
        put(canvas, palette, x, y0 + 3, INK)


def draw_arrow_slit(canvas, palette, x: int, y: int) -> None:
    for dy in range(5):
        put(canvas, palette, x, y + dy, INK)
    put(canvas, palette, x - 1, y + 2, INK)
    put(canvas, palette, x + 1, y + 2, INK)


def draw_castle(canvas, palette, px: int, py: int) -> None:
    """@brief Era 3: the castle on its 64 x 64 block: a keep at the back,
    two corner towers, a curtain wall with the gate and its portcullis,
    the gold banner on the keep."""
    draw_wall(canvas, palette, px + 18, py + 9, 28, 22, "stone", 7)
    draw_crenellations(canvas, palette, px + 18, py + 5, 28)
    draw_window(canvas, palette, px + 30, py + 15, 4, 5)
    draw_wall(canvas, palette, px + 14, py + 34, 36, 25, "stone", 8)
    draw_crenellations(canvas, palette, px + 14, py + 30, 36)
    draw_arch(canvas, palette, px + 26, py + 42, 12, 17, WALLS["stone"][1])
    for x in range(px + 28, px + 37, 2):
        for y in range(py + 44, py + 54):
            put(canvas, palette, x, y, WALLS["stone"][2])
    for y in range(py + 46, py + 54, 3):
        for x in range(px + 27, px + 37):
            put(canvas, palette, x, y, WALLS["stone"][2])
    for tower_x in (px + 2, px + 48):
        draw_wall(canvas, palette, tower_x, py + 20, 14, 39, "stone", 9)
        draw_crenellations(canvas, palette, tower_x, py + 16, 14)
        draw_arrow_slit(canvas, palette, tower_x + 7, py + 27)
        draw_arrow_slit(canvas, palette, tower_x + 7, py + 42)
    shade(canvas, px + 2, py + 59, 60)
    draw_banner(canvas, palette, px + 32, py + 0, 6, flag_left=False)
