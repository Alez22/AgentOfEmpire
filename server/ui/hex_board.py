"""@brief The map page's board on the hex grid: one server-built SVG.

The look of lab/hex_map_mockup.py, night theme (docs/DESIGN.md, "Hex grid",
"Interface"): flat hexes coloured by terrain or lot, game-icons silhouettes
from the sprite (server/ui/static/icons/sprite.svg, coloured from CSS),
building lots outlined, the realm's border in gold, land outside it dimmed.
Buildings are <a> links inside the SVG: still no JavaScript.

Pure functions; the template only writes out the lists returned here, so
every text (zone names from the models) stays escaped by Jinja. Geometry
in SVG units: pointy-top hexes of radius RADIUS, odd-r rows (odd world
rows half a hex to the east), as the engine (engine/territory.py).

Cost: about 400 hexes and 250 icon references for the start view (ring of
2 hexes), about 50 KB of markup; the sprite is fetched once and cached.
"""

import math

from engine.config import Config
from engine.state import GameState
from engine.territory import NOT_OWNED, TERRAIN_CHARS, WILD, footprint, neighbours, square_tiles

RADIUS = 24  # hex centre to corner
HEX_WIDTH = math.sqrt(3) * RADIUS
PAD = 12
TERRAIN_CLASS = {".": "h-plain", "T": "h-forest", "^": "h-hill", "~": "h-river"}
LOT_CLASS = {"farm": "h-field", "quarry": "h-quarry", "square": "h-square", "sawmill": "h-sawmill",
             "house": "h-plain", "market": "h-market"}
SPRITE = "/static/icons/sprite.svg"
# Icon of each building kind for the detail card and the legend.
KIND_ICON = {"farm": "barn", "house": "family-house", "sawmill": "circular-saw", "quarry": "mining",
             "square": "well", "market": "shop"}


def centre(x: int, y: int, x1: int, y1: int) -> tuple[float, float]:
    """@brief SVG centre of world hex (x, y) in a view whose top-left hex is (x1, y1)."""
    shift = 0.5 if y & 1 else 0.0
    return PAD + HEX_WIDTH * (x - x1 + shift + 0.5), PAD + RADIUS + 1.5 * RADIUS * (y - y1)


def corners(cx: float, cy: float) -> list[tuple[float, float]]:
    """@brief Corners of a pointy-top hex, corner k at 60k - 30 degrees; edge
    k (corner k to k + 1) faces neighbour k of engine.territory.neighbours
    (E, SE, SW, W, NW, NE)."""
    return [(cx + RADIUS * math.cos(math.radians(60 * k - 30)), cy + RADIUS * math.sin(math.radians(60 * k - 30)))
            for k in range(6)]


def _points(cx: float, cy: float) -> str:
    return " ".join(f"{px:.1f},{py:.1f}" for px, py in corners(cx, cy))


def outline(config: Config, tiles: list[tuple[int, int]], x1: int, y1: int) -> list[dict]:
    """@brief Segments along the edges of a group of hexes that face a hex
    outside the group: a lot, a zone or the realm."""
    inside = set(tiles)
    segments = []
    for x, y in tiles:
        hex_corners = corners(*centre(x, y, x1, y1))
        for edge, tile in enumerate(neighbours(config, x, y)):
            if tile in inside:
                continue
            (ax, ay), (bx, by) = hex_corners[edge], hex_corners[(edge + 1) % 6]
            segments.append({"x1": f"{ax:.1f}", "y1": f"{ay:.1f}", "x2": f"{bx:.1f}", "y2": f"{by:.1f}"})
    return segments


def _icon(name: str, cx: float, cy: float, scale: float, cls: str) -> dict:
    size = RADIUS * scale
    return {"href": f"{SPRITE}#i-{name}", "x": f"{cx - size / 2:.1f}", "y": f"{cy - size / 2:.1f}",
            "size": f"{size:.1f}", "cls": cls}


def _building_icons(kind: str, tiles: list[tuple[int, int]], building_id: int, x1: int, y1: int,
                    site: bool) -> list[dict]:
    """@brief The icons of one lot: the barn in the farm's centre and wheat
    around it, saw and log pile, pick and stones, a house, the square's well."""
    cls = "i-building site" if site else "i-building"
    centres = [centre(x, y, x1, y1) for x, y in tiles]
    if kind == "square":
        mid_x = sum(c[0] for c in centres) / len(centres)
        mid_y = sum(c[1] for c in centres) / len(centres)
        return [_icon("well", mid_x, mid_y, 1.9, cls)]
    if kind == "house":
        return [_icon("family-house" if building_id % 2 else "house", *centres[0], 1.25, cls)]
    if kind == "farm":  # the anchor is the flower's centre
        wheat = "i-wheat site" if site else "i-wheat"
        return [_icon("barn", *centres[0], 1.2, cls)] + [_icon("wheat", cx, cy, 1.05, wheat) for cx, cy in centres[1:]]
    if kind == "sawmill":
        return [_icon("circular-saw", *centres[0], 1.15, cls), _icon("wood-pile", *centres[1], 1.2, cls)]
    if kind == "quarry":
        return [_icon("mining" if index == 0 else "stone-pile", cx, cy, 1.1, cls)
                for index, (cx, cy) in enumerate(centres)]
    return []


def _waves(cx: float, cy: float) -> str:
    """@brief Path of two short wave strokes on a river hex."""
    return " ".join(f"M{cx - 9 + dx:.1f} {cy + dy:.1f} q4.5 -4 9 0 t9 0" for dy, dx in ((-5, -3), (6, 3)))


def _owned(state: GameState, x: int, y: int) -> bool:
    size = len(state.terrain)
    return 0 <= x < size and 0 <= y < size and state.owned[y][x] != NOT_OWNED


def _lots(state: GameState, config: Config) -> list[tuple[str, int, list[tuple[int, int]], bool]]:
    """@brief (kind, id, hexes, under construction) of the square (id 0) and every building."""
    lots = [("square", 0, square_tiles(state, config), False)]
    for building in state.buildings:
        lots.append((building.kind, building.id, footprint(config, building.kind, building.x, building.y),
                     building.turns_left > 0))
    return lots


def _terrain_layer(state: GameState, bounds: tuple[int, int, int, int],
                   lot_of: dict[tuple[int, int], str]) -> tuple[list, list, list, list]:
    """@brief (hexes, terrain icons, wave paths, dimmed hexes) of the view."""
    x1, y1, x2, y2 = bounds
    hexes, icons, waves, dimmed = [], [], [], []
    for y in range(y1, y2 + 1):
        for x in range(x1, x2 + 1):
            cx, cy = centre(x, y, x1, y1)
            char = state.terrain[y][x]
            cls = LOT_CLASS[lot_of[(x, y)]] if (x, y) in lot_of else TERRAIN_CLASS[char]
            if state.owned[y][x] == WILD:
                cls = "h-wild"
            hexes.append({"points": _points(cx, cy), "cls": cls})
            if (x, y) not in lot_of:
                if char == TERRAIN_CHARS["forest"]:
                    icons.append(_icon("pine-tree" if (x + y) % 2 else "oak", cx, cy, 1.35, "i-tree"))
                elif char == TERRAIN_CHARS["hill"]:
                    icons.append(_icon("hills", cx, cy, 1.3, "i-hill"))
                elif char == TERRAIN_CHARS["river"]:
                    waves.append(_waves(cx, cy))
            if not _owned(state, x, y):
                dimmed.append(_points(cx, cy))
    return hexes, icons, waves, dimmed


def hex_board(state: GameState, config: Config, bounds: tuple[int, int, int, int], selected: int,
              zones: list[dict], labels: dict[int, str], link) -> dict:
    """@brief Everything the template draws in the SVG board.
    @param bounds (x1, y1, x2, y2) world hexes in view.
    @param selected Building id chosen (0 = the square).
    @param zones The page's zones (name, color, lit, shown, and the zone's
           corners x1..y2), already filtered to the view.
    @param labels Building id -> its name on the page ("Fattoria n. 1"; 0 the square).
    @param link Builds a page link from query changes (b=building id).
    """
    x1, y1, x2, y2 = bounds

    def in_view(x: int, y: int) -> bool:
        return x1 <= x <= x2 and y1 <= y <= y2

    lots = _lots(state, config)
    lot_of = {tile: kind for kind, _, tiles, _ in lots for tile in tiles}
    hexes, icons, waves, dimmed = _terrain_layer(state, bounds, lot_of)
    lot_lines, buildings = [], []
    for kind, building_id, tiles, site in lots:
        tiles = [tile for tile in tiles if in_view(*tile)]
        if not tiles:
            continue
        if len(tiles) > 1:
            lot_lines += outline(config, tiles, x1, y1)
        icons += _building_icons(kind, tiles, building_id, x1, y1, site)
        buildings.append({"id": building_id, "label": labels[building_id], "href": link(b=building_id),
                          "selected": building_id == selected,
                          "polygons": [_points(*centre(x, y, x1, y1)) for x, y in tiles],
                          "outline": outline(config, tiles, x1, y1) if building_id == selected else []})
    realm = [(x, y) for y in range(y1, y2 + 1) for x in range(x1, x2 + 1) if _owned(state, x, y)]
    border = outline(config, realm, x1, y1)
    zone_outlines = []
    for zone in zones:
        if not zone["shown"]:
            continue
        tiles = [(x, y) for y in range(max(zone["y1"], y1), min(zone["y2"], y2) + 1)
                 for x in range(max(zone["x1"], x1), min(zone["x2"], x2) + 1)]
        zone_outlines.append({"color": zone["color"], "lit": zone["lit"], "segments": outline(config, tiles, x1, y1)})
    width = 2 * PAD + HEX_WIDTH * (x2 - x1 + 1.5)
    height = 2 * PAD + 2 * RADIUS + 1.5 * RADIUS * (y2 - y1)
    return {"width": f"{width:.0f}", "height": f"{height:.0f}", "hexes": hexes, "icons": icons, "waves": waves,
            "dimmed": dimmed, "lot_lines": lot_lines, "border": border, "zones": zone_outlines,
            "buildings": buildings, "sprite": SPRITE}
