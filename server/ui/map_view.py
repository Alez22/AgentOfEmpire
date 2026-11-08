"""@brief The sovereign's map page: the realm's land as tiles, buildings and zones.

Pure functions over the engine state; the template draws what they return
as a CSS grid of illustrated tiles (server/ui/static/map/*.svg), with no
JavaScript: choosing a building, a zone, the zoom or the zone overlay is a
plain link with query parameters.

Cost: the window is the realm's land plus a ring of 2 tiles, about 16 x 17
tiles (one <div> each, plus about 60 border pieces) at the start; the room
per zone is counted as in the Architect's briefing (server/council/map_text.py).

On the hex grid the board is one SVG instead (server/ui/hex_board.py); the
CSS grid of tiles stays for games saved on the square grid.
"""

from urllib.parse import urlencode

from engine.config import Config
from engine.state import GameState
from engine.territory import NOT_OWNED, TERRAIN_CHARS, WILD, building_works, claim_price, is_hex, owned_count
from server.council import map_text
from server.council.manual import HEX_SIZES_IT
from server.ui.hex_board import KIND_ICON, SPRITE, hex_board

TILE_PX = {False: 22, True: 34}  # zoom off / on
PURPOSE_IT = {"fields": "Campi", "center": "Centro", "houses": "Case", "workshops": "Botteghe", "reserve": "Riserva"}
PURPOSE_COLOR = {"fields": "#F2D27A", "center": "#FFF6E0", "houses": "#F2A08A", "workshops": "#E0B98F",
                 "reserve": "#A9CBE0"}
KIND_IT = {"farm": "Fattoria", "house": "Casa", "sawmill": "Segheria", "quarry": "Cava"}
PLURAL_IT = {"farm": ("fattoria", "fattorie"), "house": ("casa", "case"), "sawmill": ("segheria", "segherie"),
             "quarry": ("cava", "cave")}
TERRAIN_IT = {"plain": "pianura", "hill": "collina", "forest": "bosco"}
BORDER_GOLD = "#E8C778"


def _river_piece(state: GameState, x: int, y: int) -> str:
    """@brief The river drawing that joins this tile to its river neighbours
    (north, south, east, west); a river leaving the map goes on straight."""
    river = TERRAIN_CHARS["river"]
    size = len(state.terrain)

    def is_river(nx: int, ny: int) -> bool:
        ny = min(max(ny, 0), size - 1)  # past the top or bottom edge: as the edge row
        return 0 <= nx < size and state.terrain[ny][nx] == river

    n, s, e, w = is_river(x, y - 1), is_river(x, y + 1), is_river(x + 1, y), is_river(x - 1, y)
    for corner, (a, b) in (("ne", (n, e)), ("nw", (n, w)), ("se", (s, e)), ("sw", (s, w))):
        if a and b:
            return f"t-river-{corner}"
    return "t-river-ew" if (e or w) and not (n or s) else "t-river-ns"


def _tile_sprite(state: GameState, x: int, y: int) -> str:
    if state.owned[y][x] == WILD:
        return "t-wild"
    char = state.terrain[y][x]
    if char == TERRAIN_CHARS["forest"]:
        return "t-forest"
    if char == TERRAIN_CHARS["hill"]:
        return "t-hill"
    if char == TERRAIN_CHARS["river"]:
        return _river_piece(state, x, y)
    return "t-plain2" if (x * 7 + y * 13) % 3 == 0 else "t-plain"  # two grasses, so it is no chessboard


def _is_owned(state: GameState, x: int, y: int) -> bool:
    size = len(state.terrain)
    return 0 <= x < size and 0 <= y < size and state.owned[y][x] != NOT_OWNED


def _tiles(state: GameState, bounds: tuple[int, int, int, int]) -> tuple[list[dict], list[dict]]:
    """@brief (tiles, border pieces): every tile with its drawing, and a gold
    line on each side of the realm's land that faces land outside it."""
    x1, y1, x2, y2 = bounds
    tiles, edges = [], []
    for y in range(y1, y2 + 1):
        for x in range(x1, x2 + 1):
            col, row = x - x1 + 1, y - y1 + 1
            owned = _is_owned(state, x, y)
            tiles.append({"col": col, "row": row, "cls": _tile_sprite(state, x, y) + ("" if owned else " out")})
            if not owned:
                continue
            sides = [shadow for (dx, dy), shadow in (((0, -1), "inset 0 2px 0"), ((0, 1), "inset 0 -2px 0"),
                                                       ((-1, 0), "inset 2px 0 0"), ((1, 0), "inset -2px 0 0"))
                     if not _is_owned(state, x + dx, y + dy)]
            if sides:
                edges.append({"col": col, "row": row, "shadow": ", ".join(f"{s} {BORDER_GOLD}" for s in sides)})
    return tiles, edges


def _building_sprite(kind: str, building_id: int) -> str:
    if kind == "house":
        return "b-house2" if building_id % 3 == 0 else "b-house"  # thatch among the tiles
    return f"b-{kind}"


def _building_lines(state: GameState, config: Config, building) -> list[str]:
    spec = config.buildings[building.kind]
    size = HEX_SIZES_IT[building.kind] if is_hex(config) else f"{spec.width}×{spec.height} caselle"
    where = f"{size} di {TERRAIN_IT.get(spec.terrain, spec.terrain)}"
    if spec.needs_forest:
        where += ", accanto al bosco del regno"
    lines = [where]
    if spec.jobs:
        lines.append(f"{spec.jobs} posti di lavoro")
    else:
        lines.append(f"Ospita {spec.housing} persone")
    if building.turns_left:
        lines.append(f"In costruzione: ancora {building.turns_left} mesi")
    elif not building_works(state, config, building):
        lines.append("Ferma: non tocca più un bosco del regno")
    else:
        lines.append("In uso")
    return lines


def _room_it(state: GameState, config: Config, zone) -> str:
    """@brief "posto per 2 fattorie", "nessun posto", "tenuta libera" (Italian)."""
    kinds = [kind for kind in PLURAL_IT if zone.purpose in map_text.KIND_PURPOSES[kind]]
    if not kinds:
        return "tenuta libera"
    parts = []
    for kind in kinds:
        room = map_text.room_in_zone(state, config, kind, zone.name)
        if room:
            count = "20 o più" if room >= map_text.MAX_ROOM else str(room)
            parts.append(f"{count} {PLURAL_IT[kind][0 if room == 1 else 1]}")
    return ("posto per " + ", ".join(parts)) if parts else "nessun posto"


def map_page(state: GameState, config: Config, realm_id: int, selected: int | None, zone_name: str | None,
             show_zones: bool, zoom: bool) -> dict:
    """@brief Everything the map template draws.
    @param selected Building id chosen by the sovereign (0 = the square; None = the newest building).
    @param zone_name Zone to light up on the map, or None.
    """
    bounds = map_text._bounds(state, ring=2)
    x1, y1, x2, y2 = bounds
    tiles, edges = _tiles(state, bounds)
    tile_px = TILE_PX[zoom]

    def link(**changes) -> str:
        params = {"zones": int(show_zones), "zoom": int(zoom), "b": selected, "zone": zone_name}
        params.update(changes)
        query = {k: v for k, v in params.items() if v not in (None, 0, "")}
        return f"/ui/realms/{realm_id}/map" + (f"?{urlencode(query)}" if query else "")

    if selected is None:
        selected = state.buildings[-1].id if state.buildings else 0
    square = {"id": 0, "kind": "square", "x": state.square[0], "y": state.square[1],
              "w": config.map.square_size, "h": config.map.square_size}
    items = [square] + [{"id": b.id, "kind": b.kind, "x": b.x, "y": b.y, "w": config.buildings[b.kind].width,
                         "h": config.buildings[b.kind].height, "building": b} for b in state.buildings]
    buildings, labels = [], {}
    for item in items:
        label = "Piazza" if item["kind"] == "square" else f"{KIND_IT[item['kind']]} n. {item['id']}"
        labels[item["id"]] = label
        building = item.get("building")
        buildings.append({
            "col": item["x"] - x1 + 1, "row": item["y"] - y1 + 1, "w": item["w"], "h": item["h"], "label": label,
            "cls": _building_sprite(item["kind"], item["id"]), "selected": item["id"] == selected,
            "building_site": bool(building and building.turns_left), "href": link(b=item["id"]),
        })
    chosen = next((i for i in items if i["id"] == selected), square)
    if chosen["kind"] == "square":
        detail = {"title": "Piazza", "cls": "b-square",
                  "lines": ["Il cuore della città: gli edifici nuovi sorgono il più vicino possibile"]}
    else:
        detail = {"title": f"{KIND_IT[chosen['kind']]} n. {chosen['id']}",
                  "cls": _building_sprite(chosen["kind"], chosen["id"]),
                  "lines": _building_lines(state, config, chosen["building"])}

    zones = []
    for zone in state.zones:
        if zone.x2 < x1 or zone.x1 > x2 or zone.y2 < y1 or zone.y1 > y2:
            continue  # planned wholly beyond the window
        lit = zone.name == zone_name
        zones.append({
            "name": zone.name, "purpose": PURPOSE_IT.get(zone.purpose, zone.purpose),
            "color": PURPOSE_COLOR.get(zone.purpose, "#ECE5D6"), "room": _room_it(state, config, zone), "lit": lit,
            "href": link(zone=None if lit else zone.name), "shown": show_zones or lit,
            # Clipped to the window: a zone may reach beyond the realm's land.
            "col1": max(zone.x1, x1) - x1 + 1, "col2": min(zone.x2, x2) - x1 + 2,
            "row1": max(zone.y1, y1) - y1 + 1, "row2": min(zone.y2, y2) - y1 + 2,
            "x1": zone.x1, "y1": zone.y1, "x2": zone.x2, "y2": zone.y2,  # for the hex board
        })

    board = hex_board(state, config, bounds, selected, zones, labels, link) if is_hex(config) else None
    if board is not None:  # the detail and legend pictures come from the icon sprite
        detail["icon"] = f"{SPRITE}#i-{KIND_ICON[chosen['kind']]}"
    queue = state.clearing_queue
    return {
        "board": board, "sprite": SPRITE,
        "cols": x2 - x1 + 1, "rows": y2 - y1 + 1, "tile_px": tile_px,
        "tiles": tiles, "edges": edges, "buildings": buildings, "zones": zones, "detail": detail,
        "land": {"owned": owned_count(state), "price": claim_price(state, config), "paid": state.land_paid_total,
                 "queued": len(queue), "work_left": sum(entry[2] for entry in queue),
                 "clearing": state.workers.clearing},
        "show_zones": show_zones, "zoom": zoom,
        "zones_href": link(zones=int(not show_zones)), "zoom_href": link(zoom=int(not zoom)),
    }
