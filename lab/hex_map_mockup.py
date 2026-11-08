"""@brief Map mockup, hex variant: the realm's starting core as a board of
flat-coloured hexagons with game-icons silhouettes on them (CC BY 3.0,
lab/assets/game_icons, authors in AUTHORS.txt). Output is SVG, sharp at
any zoom.

The engine's grid is square. Here every engine tile is drawn as one
pointy-top hexagon in "odd-r" offset layout (odd world rows shifted by half
a hex). This is a look-only mockup: on a real hex grid a tile has 6
neighbours instead of 4, so footprints, adjacency rules and the river
would have to be redesigned in the engine.

Usage: python3 lab/hex_map_mockup.py OUT_DIR
Writes OUT_DIR/hex_parchment_era{1,2,3}.svg and hex_night_era2.svg.
Not part of the game; reads engine/maps directly.

Resources: a few hundred polygons and <use> references per file; each icon
path is written once as a <symbol>. About 60-90 KB per SVG.
"""

import math
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = Path(__file__).resolve().parent / "assets" / "game_icons"
SITE = (4, 4)                 # first starting site of engine/maps/world.txt
VIEW = (2, 2, 16, 16)         # x, y, width, height in engine tiles
RADIUS = 24                   # hex centre to corner, in SVG units
HEX_WIDTH = math.sqrt(3) * RADIUS
PAD = 12
PALACE_CORE_TILE = (7, 3)     # proposed palace, as in lab/tiny_town_mockup.py
PALACE_ICON = {1: "viking-longhouse", 2: "clock-tower", 3: "castle"}

THEMES = {
    "parchment": {
        "bg": "#3B3026", "grid": "#C7B994", "lot_edge": "#7A6440", "dim": "rgba(40,28,18,0.42)", "border": "#B08A2E",
        "plain": "#E4D7B4", "forest": "#BCC096", "hill": "#D0BE9A", "river": "#8FA9B2", "wave": "#D5E2E4",
        "field": "#E3C67E", "quarry": "#C8C1B3", "square": "#D9D1C1", "palace": "#EBD394", "sawmill": "#D6BC94",
        "tree": "#4C5933", "hill_icon": "#6E5B43", "wheat": "#8A6A22", "building": "#3B3026", "palace_icon": "#3B3026",
    },
    "night": {
        "bg": "#14120E", "grid": "#3A352B", "lot_edge": "#8A7448", "dim": "rgba(0,0,0,0.5)", "border": "#D4AF5A",
        "plain": "#2A261D", "forest": "#222A1C", "hill": "#302A21", "river": "#1C2C34", "wave": "#4F7584",
        "field": "#3D3420", "quarry": "#33302B", "square": "#3A352D", "palace": "#43381F", "sawmill": "#382E21",
        "tree": "#74845A", "hill_icon": "#8E8068", "wheat": "#C9A54E", "building": "#ECE5D6", "palace_icon": "#D4AF5A",
    },
}

# Neighbour steps (dx, dy) for odd-r offset, by edge index 0..5:
# E, SE, SW, W, NW, NE (edge k joins corner k and corner k + 1).
NEIGHBOURS_EVEN = ((1, 0), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1))
NEIGHBOURS_ODD = ((1, 0), (1, 1), (0, 1), (-1, 0), (0, -1), (1, -1))


def load_icon_paths(name: str) -> list[str]:
    """@brief The path data of a game-icons SVG, without its black background square."""
    text = (ICONS_DIR / f"{name}.svg").read_text()
    return [d for d in re.findall(r'<path[^>]*\sd="([^"]+)"', text) if d != "M0 0h512v512H0z"]


def hex_centre(world_x: int, world_y: int) -> tuple[float, float]:
    col, row = world_x - VIEW[0], world_y - VIEW[1]
    shift = 0.5 if world_y % 2 else 0.0
    return PAD + HEX_WIDTH * (col + shift + 0.5), PAD + RADIUS + 1.5 * RADIUS * row


def hex_corners(cx: float, cy: float) -> list[tuple[float, float]]:
    """@brief Corners of a pointy-top hex, corner k at angle 60k - 30 degrees."""
    return [(cx + RADIUS * math.cos(math.radians(60 * k - 30)), cy + RADIUS * math.sin(math.radians(60 * k - 30)))
            for k in range(6)]


def polygon(corners, fill: str, stroke: str = "none", width: float = 0) -> str:
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in corners)
    return f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>'


def icon(name: str, cx: float, cy: float, size: float, colour: str) -> str:
    return (f'<use href="#i-{name}" x="{cx - size / 2:.1f}" y="{cy - size / 2:.1f}" '
            f'width="{size:.1f}" height="{size:.1f}" fill="{colour}"/>')


def waves(cx: float, cy: float, colour: str) -> str:
    """@brief Two short wave strokes on a river hex."""
    strokes = []
    for dy, dx in ((-5, -3), (6, 3)):
        x0, y0 = cx - 9 + dx, cy + dy
        strokes.append(f'<path d="M{x0:.1f} {y0:.1f} q4.5 -4 9 0 t9 0" fill="none" '
                       f'stroke="{colour}" stroke-width="1.6" stroke-linecap="round"/>')
    return "".join(strokes)


def outline_edges(tiles: list, colour: str, width: float) -> list[str]:
    """@brief Lines along the edges of a group of tiles that face a tile
    outside the group: the outline of a building's lot, or of the realm."""
    inside = set(tiles)
    lines = []
    for x, y in tiles:
        corners = hex_corners(*hex_centre(x, y))
        steps = NEIGHBOURS_ODD if y % 2 else NEIGHBOURS_EVEN
        for edge, (dx, dy) in enumerate(steps):
            if (x + dx, y + dy) in inside:
                continue
            (x0, y0), (x1, y1) = corners[edge], corners[(edge + 1) % 6]
            lines.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" '
                         f'stroke="{colour}" stroke-width="{width}" stroke-linecap="round"/>')
    return lines


def footprints(core: dict, config_sizes: dict, era: int) -> tuple[dict, list]:
    """@brief Tile -> lot kind for every building tile, and the list of
    (kind, tiles, building id) to place icons on."""
    site_x, site_y = SITE
    lots, groups = {}, []
    square = [(site_x + core["square"]["x"] + dx, site_y + core["square"]["y"] + dy)
              for dy in range(2) for dx in range(2)]
    groups.append(("square", square, 0))
    palace = [(site_x + PALACE_CORE_TILE[0] + dx, site_y + PALACE_CORE_TILE[1] + dy)
              for dy in range(2) for dx in range(2)]
    groups.append(("palace", palace, era))
    for building_id, item in enumerate(core["buildings"], start=1):
        width, height = config_sizes[item["kind"]]
        tiles = [(site_x + item["x"] + dx, site_y + item["y"] + dy) for dy in range(height) for dx in range(width)]
        groups.append((item["kind"], tiles, building_id))
    for kind, tiles, _ in groups:
        for tile in tiles:
            lots[tile] = kind
    return lots, groups


def group_icons(kind: str, tiles: list, building_id: int, theme: dict) -> list[str]:
    """@brief Icons of one building: big and centred for square and palace,
    one per tile for fields and quarries, one per tile for the sawmill."""
    centres = [hex_centre(x, y) for x, y in tiles]
    mid_x = sum(c[0] for c in centres) / len(centres)
    mid_y = sum(c[1] for c in centres) / len(centres)
    if kind == "palace":
        return [icon(PALACE_ICON[building_id], mid_x, mid_y, RADIUS * 2.6, theme["palace_icon"])]
    if kind == "square":
        return [icon("well", mid_x, mid_y, RADIUS * 1.9, theme["building"])]
    if kind == "house":
        name = "family-house" if building_id % 2 else "house"
        return [icon(name, *centres[0], RADIUS * 1.25, theme["building"])]
    if kind == "farm":
        out = [icon("wheat", cx, cy, RADIUS * 1.05, theme["wheat"]) for cx, cy in centres]
        out[-1] = icon("barn", *centres[-1], RADIUS * 1.2, theme["building"])
        return out
    if kind == "sawmill":
        return [icon("circular-saw", *centres[0], RADIUS * 1.15, theme["building"]),
                icon("wood-pile", *centres[1], RADIUS * 1.2, theme["building"])]
    if kind == "quarry":
        return [icon("mining" if i == 0 else "stone-pile", cx, cy, RADIUS * 1.1, theme["building"])
                for i, (cx, cy) in enumerate(centres)]
    return []


LOT_FILL = {"farm": "field", "quarry": "quarry", "square": "square", "palace": "palace", "sawmill": "sawmill"}
TERRAIN_FILL = {".": "plain", "T": "forest", "^": "hill", "~": "river"}


def render(world: list[str], core: dict, sizes: dict, theme: dict, era: int) -> str:
    site_x, site_y = SITE
    core_size = len(core["terrain"].strip().splitlines())

    def owned(x, y):
        return site_x <= x < site_x + core_size and site_y <= y < site_y + core_size

    lots, groups = footprints(core, sizes, era)
    used_icons = {"pine-tree", "oak", "hills"}
    body, overlay = [], []
    for y in range(VIEW[1], VIEW[1] + VIEW[3]):
        for x in range(VIEW[0], VIEW[0] + VIEW[2]):
            cx, cy = hex_centre(x, y)
            corners = hex_corners(cx, cy)
            char = world[y][x]
            fill_key = LOT_FILL.get(lots.get((x, y)), TERRAIN_FILL[char])
            body.append(polygon(corners, theme[fill_key], theme["grid"], 1))
            if (x, y) not in lots:
                if char == "T":
                    body.append(icon("pine-tree" if (x + y) % 2 else "oak", cx, cy, RADIUS * 1.35, theme["tree"]))
                elif char == "^":
                    body.append(icon("hills", cx, cy, RADIUS * 1.3, theme["hill_icon"]))
                elif char == "~":
                    body.append(waves(cx, cy, theme["wave"]))
            if not owned(x, y):
                overlay.append(polygon(corners, theme["dim"]))
    for kind, tiles, building_id in groups:
        if len(tiles) > 1:
            body.extend(outline_edges(tiles, theme["lot_edge"], 1.6))
        snippets = group_icons(kind, tiles, building_id, theme)
        body.extend(snippets)
        used_icons.update(re.findall(r'href="#i-([a-z-]+)"', "".join(snippets)))
    realm = [(x, y) for y in range(site_y, site_y + core_size) for x in range(site_x, site_x + core_size)]
    borders = outline_edges(realm, theme["border"], 3)
    symbols = "".join(f'<symbol id="i-{name}" viewBox="0 0 512 512">'
                      + "".join(f'<path d="{d}"/>' for d in load_icon_paths(name)) + "</symbol>"
                      for name in sorted(used_icons))
    width = 2 * PAD + HEX_WIDTH * (VIEW[2] + 0.5)
    height = 2 * PAD + RADIUS * 2 + 1.5 * RADIUS * (VIEW[3] - 1)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
            f'width="{width:.0f}" height="{height:.0f}">'
            f'<defs>{symbols}</defs><rect width="100%" height="100%" fill="{theme["bg"]}"/>'
            + "".join(body) + "".join(overlay) + "".join(borders) + "</svg>")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python3 lab/hex_map_mockup.py OUT_DIR")
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    world = [row for row in (ROOT / "engine/maps/world.txt").read_text().splitlines() if row]
    core = tomllib.loads((ROOT / "engine/maps/core.toml").read_text())
    config = tomllib.loads((ROOT / "engine/config.toml").read_text())
    sizes = {kind: (spec["width"], spec["height"]) for kind, spec in config["buildings"].items()}
    for era in (1, 2, 3):
        (out_dir / f"hex_parchment_era{era}.svg").write_text(render(world, core, sizes, THEMES["parchment"], era))
    (out_dir / "hex_night_era2.svg").write_text(render(world, core, sizes, THEMES["night"], 2))


if __name__ == "__main__":
    main()
