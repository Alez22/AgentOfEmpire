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

from engine.bands import RoadMap
from engine.caravans import caravans_on, fair_hex_of, road_home_to_fair
from engine.config import Config
from engine.state import GameState
from engine.territory import NOT_OWNED, WILD, footprint, hex_distance, neighbours, square_tiles
from server.ui.hex_board import LOT_CLASS, TERRAIN_CLASS
from server.ui.labels import event_label

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


def band_marks(bands: list[dict]) -> list[dict]:
    """@brief The bands to draw (roads of the world): a red mark on their hex.
    @param bands Each {"x", "y", "text", "title"}: the mark's short text (a
           letter for a player, the adults for the admin) and its tooltip."""
    marks = []
    for band in bands:
        cx, cy = centre(band["x"], band["y"])
        marks.append({"x": f"{cx:.1f}", "y": f"{cy:.1f}", "text": band["text"], "title": band["title"]})
    return marks


def fair_mark(config: Config, terrain: list[str], realms: list[dict]) -> dict | None:
    """@brief The fair (roads of the world, phase 2) as the viewer can place it:
    the free hex nearest the middle among the realms it knows (a player knows
    only its own land; the fair is in the empty middle of the ring, so they
    agree unless a realm grows over the middle). None without caravans."""
    if not caravans_on(config):
        return None
    owned = {(x, y) for realm in realms for y, row in enumerate(realm["state"].owned)
             for x, char in enumerate(row) if char != NOT_OWNED}
    cx, cy = centre(*fair_hex_of(len(terrain), owned))
    return {"x": f"{cx:.1f}", "y": f"{cy:.1f}", "title": "La fiera: il magazzino del mercato"}


def _points(tiles: list[tuple[int, int]]) -> str:
    """@brief SVG polyline points through the centres of a list of hexes."""
    return " ".join("{:.1f},{:.1f}".format(*centre(x, y)) for x, y in tiles)


def caravan_routes(config: Config, month_states: dict[str, GameState], events: list[dict],
                   colors: dict[str, str]) -> list[dict]:
    """@brief The caravans of one month as the admin timelapse draws them.
    The engine stores no caravan (engine/caravans.py): the road is found again
    with the same RoadMap the world step used (the month's new states, i.e.
    the snapshots of the next turn) and the leg's end comes from its event.
    @param month_states {realm key: state} of the realms resolved that month.
    @param events The month's events, each {"key", "realm", "kind", "data"}.
    @return Each {"points", "color", "robbed", "end_x", "end_y", "title"}.
    """
    if not caravans_on(config) or not month_states:
        return []
    roads = RoadMap(config, month_states)
    home_to_fair = {}  # realm key -> road, found once per realm
    routes = []
    for event in events:
        if event["kind"] not in ("caravan_arrived", "caravan_robbed") or event["key"] not in month_states:
            continue
        key, data = event["key"], event["data"]
        if key not in home_to_fair:
            home_to_fair[key] = road_home_to_fair(roads, key)
        path = home_to_fair[key] if data.get("leg") == "out" else home_to_fair[key][::-1]
        robbed = event["kind"] == "caravan_robbed"
        if robbed and (data.get("x"), data.get("y")) in path:
            path = path[:path.index((data["x"], data["y"])) + 1]  # the road stops where the band met it
        if not path:
            continue  # no road: the leg just arrived, nothing to draw
        end_x, end_y = centre(*path[-1])
        routes.append({"points": _points(path), "color": colors.get(key, FALLEN_COLOR), "robbed": robbed,
                       "end_x": f"{end_x:.1f}", "end_y": f"{end_y:.1f}",
                       "title": f"{event['realm']}: {event_label(event['kind'], data)}"})
    return routes


def raid_arrows(config: Config, month_states: dict[str, GameState], events: list[dict], bands: list) -> list[dict]:
    """@brief One arrow per raid of the month, from the band's camp to the
    nearest hex of the realm it raided.
    Assumption: the pool at the start of the next month still carries each
    band's `target` and `raided` (engine/bands.py resets them only when it
    picks new targets), and the band is back at its camp. When two bands raid
    the same realm, raids and bands are paired in order: the raid event names
    no band.
    @param bands The engine Bands at the start of the next month.
    @return Each {"x1", "y1", "x2", "y2", "repelled", "title"}."""
    raids: dict[str, list[dict]] = {}
    for event in events:
        if event["kind"] == "raid":
            raids.setdefault(event["key"], []).append(event)
    arrows = []
    for band in bands:
        key = band.target
        if not band.raided or not raids.get(key) or key not in month_states:
            continue
        event = raids[key].pop(0)
        land = [(x, y) for y, row in enumerate(month_states[key].owned) for x, char in enumerate(row)
                if char != NOT_OWNED]
        if not land:
            continue
        x2, y2 = centre(*min(land, key=lambda tile: hex_distance(band.x, band.y, *tile)))
        x1, y1 = centre(band.x, band.y)
        arrows.append({"x1": f"{x1:.1f}", "y1": f"{y1:.1f}", "x2": f"{x2:.1f}", "y2": f"{y2:.1f}",
                       "repelled": bool(event["data"].get("repelled")),
                       "title": f"Banda {band.id} su {event['realm']}: {event_label('raid', event['data'])}"})
    return arrows


def world_board(config: Config, terrain: list[str], realms: list[dict], bands: list[dict] = ()) -> dict:
    """@brief Everything the template draws in the world SVG.
    @param terrain The world's terrain rows (any realm's state: the same world).
    @param realms The realms to draw, each {"name", "state", "color", "fallen"};
           only these realms' land, buildings and borders are drawn.
    @param bands The bands this viewer may see (band_marks): the caller
           decides, as for the realms (a player: the sightings of last month).
    @return width, height, hex points, hexes grouped by class, letters, borders, bands.
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
            "letters": letters, "borders": borders, "legend": LEGEND, "bands": band_marks(list(bands)),
            "fair": fair_mark(config, terrain, realms)}
