"""@brief The world view: the whole 64 x 64 hex map, small, one SVG.

A second view beside the realm's map (server/ui/map_view.py): terrain as
plain colour, buildings as one letter on their anchor hex, each realm's
border in its colour with its name by the square. No illustrations, no
JavaScript.

Who sees what is decided by the caller, which passes the realms to draw:
the admin passes every realm of the game, a player only their own, so the
other realms never reach a player's HTML. The terrain is the same world
for everyone (copied into every state at game start), so showing it hides
nothing. Land levels are never drawn.

Pure functions; the template writes out the lists returned here, so the
realm names stay escaped by Jinja. Geometry as server/ui/hex_board.py
(pointy-top hexes, odd-r rows) but with a small radius: kept as separate
functions so the realm board stays untouched.

Cost: 4096 hexes, each a <use> of one hex in <defs>, grouped by colour:
about 160 KB of markup, a few hundred lines per realm border, one letter
per building.
"""

import math

from engine.config import Config
from engine.state import GameState
from engine.territory import NOT_OWNED, WILD, footprint, neighbours, square_tiles
from server.ui.hex_board import LOT_CLASS, TERRAIN_CLASS

RADIUS = 6  # hex centre to corner, SVG units
HEX_WIDTH = math.sqrt(3) * RADIUS
PAD = 4
# One colour per realm, in realm id order; the player's own realm is gold.
REALM_COLORS = ("#E8C778", "#E8907A", "#9CCB8A", "#8FB8DE", "#C9A3E0", "#E0B98F", "#7FD1C7", "#F2A0C0")
FALLEN_COLOR = "#6B655A"
LETTER = {"square": "P", "farm": "F", "house": "C", "sawmill": "S", "quarry": "K", "market": "M",
          "watchtower": "T"}
LEGEND = (("P", "Piazza"), ("F", "Fattoria"), ("C", "Casa"), ("S", "Segheria"), ("K", "Cava"),
          ("M", "Mercato"), ("T", "Torre di guardia"))


def centre(x: int, y: int) -> tuple[float, float]:
    """@brief SVG centre of world hex (x, y); odd rows half a hex to the east."""
    shift = 0.5 if y & 1 else 0.0
    return PAD + HEX_WIDTH * (x + shift + 0.5), PAD + RADIUS + 1.5 * RADIUS * y


def corners(cx: float, cy: float) -> list[tuple[float, float]]:
    """@brief Corners of a pointy-top hex; edge k faces neighbour k of
    engine.territory.neighbours (E, SE, SW, W, NW, NE)."""
    return [(cx + RADIUS * math.cos(math.radians(60 * k - 30)), cy + RADIUS * math.sin(math.radians(60 * k - 30)))
            for k in range(6)]


def border_path(config: Config, tiles: list[tuple[int, int]]) -> str:
    """@brief One SVG path along the edges of a group of hexes that face a
    hex outside the group (a realm's land)."""
    inside = set(tiles)
    moves = []
    for x, y in tiles:
        hex_corners = corners(*centre(x, y))
        for edge, tile in enumerate(neighbours(config, x, y)):
            if tile in inside:
                continue
            (ax, ay), (bx, by) = hex_corners[edge], hex_corners[(edge + 1) % 6]
            moves.append(f"M{ax:.1f} {ay:.1f}L{bx:.1f} {by:.1f}")
    return "".join(moves)


def _lots(state: GameState, config: Config) -> list[tuple[str, list[tuple[int, int]], bool]]:
    """@brief (kind, hexes, under construction) of the square and every building."""
    lots = [("square", square_tiles(state, config), False)]
    for building in state.buildings:
        lots.append((building.kind, footprint(config, building.kind, building.x, building.y),
                     building.turns_left > 0))
    return lots


def _letter(kind: str, tiles: list[tuple[int, int]], site: bool) -> dict:
    """@brief The building's letter: on its anchor hex (the farm's centre,
    the others' first hex), the square's in the middle of its four hexes."""
    centres = [centre(x, y) for x, y in tiles]
    if kind == "square":
        cx = sum(c[0] for c in centres) / len(centres)
        cy = sum(c[1] for c in centres) / len(centres)
    else:
        cx, cy = centres[0]
    return {"x": f"{cx:.1f}", "y": f"{cy:.1f}", "text": LETTER.get(kind, "?"), "site": site}


def world_board(config: Config, terrain: list[str], realms: list[dict]) -> dict:
    """@brief Everything the template draws in the world SVG.
    @param terrain The world's terrain rows (any realm's state: the same world).
    @param realms The realms to draw, each {"name", "state", "color", "fallen"};
           only these realms' land, buildings and borders are drawn.
    @return width, height, hex points, hexes grouped by class, letters, borders.
    """
    cls_of = {}  # (x, y) -> class; the land of a drawn realm overrides the terrain
    letters, borders = [], []
    for realm in realms:
        state = realm["state"]
        land = [(x, y) for y, row in enumerate(state.owned) for x, char in enumerate(row) if char != NOT_OWNED]
        for x, y in land:
            # The realm's own terrain: felled forest is plain only in its state.
            cls_of[(x, y)] = "h-wild" if state.owned[y][x] == WILD else TERRAIN_CLASS[state.terrain[y][x]]
        for kind, tiles, site in _lots(state, config):
            for tile in tiles:
                cls_of[tile] = LOT_CLASS[kind]
            letters.append(_letter(kind, tiles, site))
        # The name just above the realm's top border, over its middle: inside
        # the land it would cover the letters.
        xs = [centre(x, y)[0] for x, y in land]
        top = min(centre(x, y)[1] for x, y in land)
        borders.append({"name": realm["name"], "color": FALLEN_COLOR if realm["fallen"] else realm["color"],
                        "fallen": realm["fallen"], "path": border_path(config, land),
                        "label_x": f"{(min(xs) + max(xs)) / 2:.1f}", "label_y": f"{top - 1.8 * RADIUS:.1f}"})
    groups: dict[str, list[dict]] = {}
    for y, row in enumerate(terrain):
        for x, char in enumerate(row):
            cx, cy = centre(x, y)
            cls = cls_of.get((x, y), TERRAIN_CLASS[char])
            groups.setdefault(cls, []).append({"x": f"{cx:.1f}", "y": f"{cy:.1f}"})
    size = len(terrain)
    width = 2 * PAD + HEX_WIDTH * (size + 0.5)
    height = 2 * PAD + 2 * RADIUS + 1.5 * RADIUS * (size - 1)
    return {"width": f"{width:.0f}", "height": f"{height:.0f}",
            "hex_points": " ".join(f"{px:.2f},{py:.2f}" for px, py in corners(0, 0)),
            "groups": [{"cls": cls, "hexes": hexes} for cls, hexes in groups.items()],
            "letters": letters, "borders": borders, "legend": LEGEND}
