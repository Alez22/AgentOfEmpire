"""@brief Our own pixel-art terrain for the map mockup: forest and hills,
drawn by code in the colours of the Tiny Town palette.

Why our own: Tiny Town's forest pieces showed odd roots on the edges and
the hills were scattered pebbles (feedback 2026-11-08). Here a forest tile
holds a few round trees and conifers at fixed pseudo-random spots, drawn
back to front so canopies overlap; a hill tile holds rock outcrops with
light and shade and a few grass tufts.

Coordinates are pixels of the mockup canvas; one engine tile is a 32 x 32
block. Deterministic: positions come from the tile's coordinates.
"""

from pixel_buildings import INK, put

LEAF_LIGHT, LEAF, LEAF_DARK = 15, 22, 2   # darker greens: the forest is a mass, not a lawn
TRUNK = 12
ROCK_LIGHT, ROCK, ROCK_DARK, ROCK_OUTLINE = 9, 16, 27, 23
TUFT = 22

# Tree spots inside a 32 x 32 block: (x, y of the trunk base, kind).
TREE_LAYOUTS = (
    ((6, 10, "round"), (18, 8, "pine"), (27, 12, "round"), (12, 20, "pine"), (24, 22, "round"),
     (5, 29, "round"), (17, 31, "pine"), (28, 31, "pine")),
    ((8, 9, "pine"), (21, 10, "round"), (4, 19, "round"), (15, 19, "round"), (27, 21, "pine"),
     (10, 30, "pine"), (22, 30, "round")),
    ((13, 9, "round"), (26, 9, "pine"), (5, 17, "pine"), (20, 19, "round"), (9, 28, "round"),
     (24, 30, "pine"), (30, 24, "round")),
)


def tile_hash(x: int, y: int, modulo: int) -> int:
    return ((x * 92837111) ^ (y * 689287499) ^ 0x2545F491) % modulo


def disc(canvas, palette, centre_x: int, centre_y: int, radius: int, light: int, mid: int, dark: int,
         outline: int = INK) -> None:
    """@brief A shaded disc: light towards the top left, dark towards the
    bottom right, an outline ring. Used for canopies and rocks."""
    for dy in range(-radius - 1, radius + 2):
        for dx in range(-radius - 1, radius + 2):
            distance = dx * dx + dy * dy
            if distance > (radius + 1) * (radius + 1) - 1:
                continue
            if distance > radius * radius:
                colour = outline
            elif dx + dy < -radius * 0.5:
                colour = light
            elif dx + dy > radius * 0.6:
                colour = dark
            else:
                colour = mid
            put(canvas, palette, centre_x + dx, centre_y + dy, colour)


def draw_round_tree(canvas, palette, base_x: int, base_y: int) -> None:
    for y in range(base_y - 4, base_y + 1):
        put(canvas, palette, base_x, y, TRUNK)
        put(canvas, palette, base_x + 1, y, INK)
    disc(canvas, palette, base_x, base_y - 9, 7, LEAF_LIGHT, LEAF, LEAF_DARK)


def draw_pine(canvas, palette, base_x: int, base_y: int) -> None:
    """@brief A conifer: two stacked triangles, sunlit left, dark right."""
    for y in range(base_y - 2, base_y + 1):
        put(canvas, palette, base_x, y, TRUNK)
    for tier_top, tier_height in ((base_y - 19, 10), (base_y - 12, 10)):
        for row in range(tier_height):
            half = 1 + row * 7 // tier_height
            for dx in range(-half, half + 1):
                colour = LEAF_LIGHT if dx < -half // 2 else LEAF_DARK if dx > half // 2 else LEAF
                if dx in (-half, half) or row == tier_height - 1:
                    colour = INK
                put(canvas, palette, base_x + dx, tier_top + row, colour)


def draw_forest(canvas, palette, tile_origins: list[tuple[int, int]]) -> None:
    """@brief Trees of every forest tile, sorted by their base so the ones
    in front overlap the ones behind across tile borders."""
    trees = []
    for px, py in tile_origins:
        layout = TREE_LAYOUTS[tile_hash(px, py, len(TREE_LAYOUTS))]
        for x, y, kind in layout:
            trees.append((py + y, px + x, kind))
    for base_y, base_x, kind in sorted(trees):
        if kind == "round":
            draw_round_tree(canvas, palette, base_x, base_y)
        else:
            draw_pine(canvas, palette, base_x, base_y)


def draw_outcrop(canvas, palette, centre_x: int, centre_y: int, radius: int) -> None:
    """@brief A rock outcrop: a big shaded boulder, a smaller one leaning on
    it, a crack."""
    disc(canvas, palette, centre_x, centre_y, radius, ROCK_LIGHT, ROCK, ROCK_DARK, ROCK_OUTLINE)
    disc(canvas, palette, centre_x + radius, centre_y + radius // 2 + 1, max(2, radius // 2),
         ROCK_LIGHT, ROCK, ROCK_DARK, ROCK_OUTLINE)
    for i in range(radius - 1):
        put(canvas, palette, centre_x - 1 + i // 2, centre_y - radius // 2 + i, ROCK_DARK)


def draw_tuft(canvas, palette, x: int, y: int) -> None:
    for dx, dy in ((0, 0), (1, -1), (2, 0), (-1, -1)):
        put(canvas, palette, x + dx, y + dy, TUFT)


def draw_hills(canvas, palette, tile_origins: list[tuple[int, int]]) -> None:
    """@brief One big outcrop or two small ones per hill tile, plus tufts."""
    for px, py in tile_origins:
        if tile_hash(px, py, 2) == 0:
            draw_outcrop(canvas, palette, px + 14, py + 15, 7)
        else:
            draw_outcrop(canvas, palette, px + 9, py + 10, 4)
            draw_outcrop(canvas, palette, px + 21, py + 21, 5)
        for i in range(3):
            draw_tuft(canvas, palette, px + 3 + tile_hash(px + i, py, 26), py + 4 + tile_hash(px, py + i, 25))
