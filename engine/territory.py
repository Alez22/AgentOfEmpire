"""@brief The territory: the map, the town plan and where buildings stand.

Pure functions over GameState (docs/DESIGN.md, "Territory"). Coordinates
are world tiles: x = column (0 west), y = row (0 north). Every search
runs in a fixed order, so the same state always gives the same place
(deterministic replay).

Resources: the world is 64 x 64 = 4096 tiles, kept as rows of characters
in the state (about 8 KB per snapshot with the ownership rows). The
occupancy map is rebuilt on each call, a few hundred tiles at most; a
search for a place tries every top-left tile of the zones (at most the
whole territory) and is cheap at this size.

Two grids ([map] grid, docs/DESIGN.md "Hex grid"): "square", 4 neighbours
and width x height footprints (games saved before), or "hex", pointy-top
hexes in odd-r offset rows (odd rows sit half a hex to the east), 6
neighbours and footprints walked from an anchor. The rows of the state keep
the same format on both; only what "neighbour" means changes, and every
rule asks neighbours() or footprint() for it.
"""

import tomllib
from pathlib import Path

from engine.config import Config
from engine.state import Building, Event, GameState, Zone

MAPS_DIR = Path(__file__).with_name("maps")
TERRAIN_CHARS = {"plain": ".", "river": "~", "forest": "T", "hill": "^"}
NOT_OWNED, OWNED, WILD = "-", "o", "w"
ZONE_PURPOSES = ("fields", "center", "houses", "workshops", "reserve", "market", "watch")
# Zone purposes each building kind may stand in (houses also around the square).
# The market only in its own zone: in the lab, houses filled the center first
# and two realms of eight never found room for it (2026-11-08).
KIND_PURPOSES = {"farm": ("fields",), "sawmill": ("workshops",), "quarry": ("workshops",),
                 "house": ("houses", "center"), "market": ("market",), "watchtower": ("watch",)}
SQUARE = "square"
# Shifts tried, in this order, when a building given by coordinates does
# not fit: one tile north, east, south, west, then the diagonals.
NUDGES = ((0, -1), (1, 0), (0, 1), (-1, 0), (1, -1), (1, 1), (-1, 1), (-1, -1))
SQUARE_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))
# Hex neighbours in the fixed order E, SE, SW, W, NW, NE; the step depends on
# the row's parity (odd-r offset coordinates).
HEX_DIRECTIONS = ("E", "SE", "SW", "W", "NW", "NE")
HEX_STEPS_EVEN = ((1, 0), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1))
HEX_STEPS_ODD = ((1, 0), (1, 1), (0, 1), (-1, 0), (0, -1), (1, -1))


def is_hex(config: Config) -> bool:
    return config.map.grid == "hex"


def _hex_steps(y: int) -> tuple[tuple[int, int], ...]:
    # y & 1 is also right for negative rows (-1 & 1 == 1): row -1 is odd.
    return HEX_STEPS_ODD if y & 1 else HEX_STEPS_EVEN


def neighbours(config: Config, x: int, y: int) -> list[tuple[int, int]]:
    """@brief The tiles next to (x, y), in a fixed order; they may lie
    outside the map. Square: east, west, south, north. Hex: E, SE, SW, W,
    NW, NE."""
    steps = _hex_steps(y) if is_hex(config) else SQUARE_STEPS
    return [(x + dx, y + dy) for dx, dy in steps]


def hex_step(x: int, y: int, direction: str) -> tuple[int, int]:
    dx, dy = _hex_steps(y)[HEX_DIRECTIONS.index(direction)]
    return x + dx, y + dy


def _walk(x: int, y: int, paths: list[list[str]]) -> list[tuple[int, int]]:
    """@brief The anchor (x, y) and the tile at the end of each path of steps.
    Steps, not fixed offsets: the offset of SE changes with the row's parity."""
    tiles = [(x, y)]
    for path in paths:
        tx, ty = x, y
        for direction in path:
            tx, ty = hex_step(tx, ty, direction)
        tiles.append((tx, ty))
    return tiles


def hex_distance(x1: int, y1: int, x2: int, y2: int) -> int:
    """@brief Steps between two hexes, through axial coordinates (integers)."""
    q1, q2 = x1 - (y1 - (y1 & 1)) // 2, x2 - (y2 - (y2 & 1)) // 2
    dq, dr = q1 - q2, y1 - y2
    return max(abs(dq), abs(dr), abs(dq + dr))


def _hex_to_square(state: GameState, config: Config, x: int, y: int) -> int:
    """@brief Hex steps from (x, y) to the nearest tile of the square."""
    return min(hex_distance(x, y, sx, sy) for sx, sy in square_tiles(state, config))


def _load_core(config: Config) -> dict:
    with open(MAPS_DIR / config.map.core_file, "rb") as core_file:
        core = tomllib.load(core_file)
    core["rows"] = [row.strip() for row in core["terrain"].strip().splitlines()]
    return core


def _load_world(config: Config) -> list[str]:
    rows = (MAPS_DIR / config.map.world_file).read_text(encoding="utf-8").splitlines()
    return [row for row in rows if row]


def start_territory(state: GameState, config: Config, seed: int, site_index: int | None = None) -> None:
    """@brief Put a new realm on the map: copy the world, pick the site,
    own the core and place the core's square, buildings and zones, and
    give the realm the site's land levels when the game has them.
    The core's buildings replace the counted ones of [start]; they are the
    same 4 farms, 1 sawmill, 1 quarry and 6 houses.
    @param site_index Index into [map] sites; None = picked by the seed
           (games with one realm, as before).
    @throws ValueError if the world or the core file is malformed.
    """
    world = _load_world(config)
    core = _load_core(config)
    size, core_size = len(world), config.map.core_size
    if any(len(row) != size for row in world) or len(core["rows"]) != core_size:
        raise ValueError("world must be square and the core core_size x core_size")
    site = (seed if site_index is None else site_index) % len(config.map.sites)
    site_x, site_y = config.map.sites[site]
    if [row[site_x:site_x + core_size] for row in world[site_y:site_y + core_size]] != core["rows"]:
        raise ValueError(f"the world at site ({site_x},{site_y}) does not match the core")
    state.terrain = world
    state.owned = [
        "".join(OWNED if site_x <= x < site_x + core_size and site_y <= y < site_y + core_size else NOT_OWNED
                for x in range(size))
        for y in range(size)
    ]
    state.square = [site_x + core["square"]["x"], site_y + core["square"]["y"]]
    state.buildings = []
    for item in core["buildings"]:
        state.buildings.append(Building(item["kind"], 0, state.next_building_id,
                                        site_x + item["x"], site_y + item["y"]))
        state.next_building_id += 1
    state.zones = [Zone(z["name"], z["purpose"], site_x + z["x1"], site_y + z["y1"],
                        site_x + z["x2"], site_y + z["y2"]) for z in core["zones"]]
    state.free_tiles = 0  # free space comes from the map
    if config.levels is not None and config.map.site_levels is not None:
        state.land_levels = dict(zip(("food", "wood", "stone"), config.map.site_levels[site]))


def footprint(config: Config, kind: str, x: int, y: int) -> list[tuple[int, int]]:
    """@brief The tiles of a building whose anchor (top-left tile on the
    square grid) is (x, y)."""
    spec = config.buildings[kind]
    if is_hex(config):
        return _walk(x, y, spec.hex_steps)
    return [(x + dx, y + dy) for dy in range(spec.height) for dx in range(spec.width)]


def square_tiles(state: GameState, config: Config) -> list[tuple[int, int]]:
    sx, sy = state.square
    if is_hex(config):
        return _walk(sx, sy, config.map.square_hex_steps)
    size = config.map.square_size
    return [(sx + dx, sy + dy) for dy in range(size) for dx in range(size)]


def occupancy(state: GameState, config: Config) -> dict[tuple[int, int], str]:
    """@brief Tile -> what stands on it: a building id as text, or "square".
    Buildings under construction already hold their tiles."""
    taken = {tile: SQUARE for tile in square_tiles(state, config)}
    for building in state.buildings:
        for tile in footprint(config, building.kind, building.x, building.y):
            taken[tile] = str(building.id)
    return taken


def zone_at(zones: list[Zone], x: int, y: int) -> Zone | None:
    for zone in zones:
        if zone.x1 <= x <= zone.x2 and zone.y1 <= y <= zone.y2:
            return zone
    return None


def single_zone(zones: list[Zone], tiles: list[tuple[int, int]]) -> Zone | None:
    """@brief The zone holding every one of these tiles, or None if they lie
    in different zones or outside any zone."""
    first = zone_at(zones, *tiles[0])
    if first is None or any(zone_at(zones, x, y) is not first for x, y in tiles[1:]):
        return None
    return first


def _in_map(state: GameState, x: int, y: int) -> bool:
    return 0 <= y < len(state.terrain) and 0 <= x < len(state.terrain[0])


def _touches_owned(state: GameState, config: Config, tiles: list[tuple[int, int]], terrain: str) -> bool:
    """@brief True if a tile next to these is of this terrain and belongs to
    the realm: a sawmill needs its own forest."""
    char = TERRAIN_CHARS[terrain]
    for x, y in tiles:
        for nx, ny in neighbours(config, x, y):
            if _in_map(state, nx, ny) and state.terrain[ny][nx] == char and state.owned[ny][nx] != NOT_OWNED:
                return True
    return False


def building_works(state: GameState, config: Config, building: Building) -> bool:
    """@brief False for a building whose terrain need is gone: a sawmill that
    no longer touches a forest of the realm (felled) produces nothing.
    Always True without a map."""
    spec = config.buildings[building.kind]
    if not state.has_map() or not spec.needs_forest:
        return True
    return _touches_owned(state, config, footprint(config, building.kind, building.x, building.y), "forest")


def place_error(state: GameState, config: Config, kind: str, x: int, y: int,
                zone_name: str | None = None,
                taken: dict[tuple[int, int], str] | None = None) -> tuple[str, str] | None:
    """@brief Why a building of this kind cannot stand with its top-left
    tile at (x, y), or None if it can.
    @param zone_name If given, every tile must be inside that zone.
    @param taken Occupancy, passed by callers that test many places.
    @return (code, message) of the first failed rule.
    """
    tiles = footprint(config, kind, x, y)
    if not all(_in_map(state, tx, ty) for tx, ty in tiles):
        return "OUT_OF_MAP", f"{kind} at ({x},{y}) leaves the map"
    if any(state.owned[ty][tx] != OWNED for tx, ty in tiles):
        return "NOT_OWNED", f"{kind} at ({x},{y}) is not all on the realm's cleared land"
    spec = config.buildings[kind]
    if any(state.terrain[ty][tx] != TERRAIN_CHARS[spec.terrain] for tx, ty in tiles):
        return "WRONG_TERRAIN", f"{kind} at ({x},{y}) must stand on {spec.terrain} only"
    if spec.needs_forest and not _touches_owned(state, config, tiles, "forest"):
        return "NO_FOREST", f"{kind} at ({x},{y}) must touch a forest tile"
    taken = occupancy(state, config) if taken is None else taken
    if any(tile in taken for tile in tiles):
        return "OVERLAP", f"{kind} at ({x},{y}) overlaps another building or the square"
    zone = single_zone(state.zones, tiles)
    if zone is None or zone.purpose not in KIND_PURPOSES[kind] or zone_name not in (None, zone.name):
        where = f"zone '{zone_name}'" if zone_name else f"one {' or '.join(KIND_PURPOSES[kind])} zone"
        return "OUTSIDE_ZONE", f"{kind} at ({x},{y}) is not all inside {where}"
    return None


def _distance_to_square(state: GameState, config: Config, kind: str, x: int, y: int) -> int:
    """@brief Squared distance between the footprint's centre and the
    square's centre, in half tiles (integers only)."""
    spec = config.buildings[kind]
    size = config.map.square_size
    dx = (2 * x + spec.width) - (2 * state.square[0] + size)
    dy = (2 * y + spec.height) - (2 * state.square[1] + size)
    return dx * dx + dy * dy


def _packing(config: Config, tiles: list[tuple[int, int]], zone: Zone,
             taken: dict[tuple[int, int], str]) -> int:
    """@brief Tiles around a footprint that are taken or outside the zone (or
    the map): the more, the tighter the building packs against the others."""
    inside = set(tiles)
    ring = {tile for x, y in tiles for tile in neighbours(config, x, y) if tile not in inside}
    return sum(1 for x, y in ring
               if (x, y) in taken or not (zone.x1 <= x <= zone.x2 and zone.y1 <= y <= zone.y2))


def _hex_place_key(state: GameState, config: Config, kind: str, x: int, y: int, zone: Zone,
                   taken: dict[tuple[int, int], str]) -> tuple:
    """@brief Sort key of a valid hex place: tightest packing first (no lone
    hexes left in the zone; lab: 6 farm flowers in a 9 x 6 zone, 5 by
    distance alone), then nearest the square, then row, column."""
    tiles = footprint(config, kind, x, y)
    return -_packing(config, tiles, zone, taken), _hex_to_square(state, config, x, y), y, x


def find_place(state: GameState, config: Config, kind: str, zone_name: str | None = None) -> tuple[int, int] | None:
    """@brief The valid place nearest the square, in the named zone or in any
    zone that allows this kind; ties broken by row, then column.

    Places aligned on the zone's grid (whole footprints from its top-left
    corner) come first: buildings then stand in tidy rows and leave room
    for the next one; a farm placed half-way would waste the zone. On hexes
    packing replaces the alignment (see _hex_place_key).
    @return (x, y) anchor tile, or None if nothing fits.
    """
    taken = occupancy(state, config)
    spec = config.buildings[kind]
    zones = [z for z in state.zones if (zone_name is None and z.purpose in KIND_PURPOSES[kind])
             or z.name == zone_name]
    candidates = []
    for zone in zones:
        for y in range(zone.y1, zone.y2 + 1):
            for x in range(zone.x1, zone.x2 + 1):
                if place_error(state, config, kind, x, y, zone.name, taken) is not None:
                    continue
                if is_hex(config):
                    candidates.append(_hex_place_key(state, config, kind, x, y, zone, taken))
                    continue
                aligned = (x - zone.x1) % spec.width == 0 and (y - zone.y1) % spec.height == 0
                candidates.append((not aligned, _distance_to_square(state, config, kind, x, y), y, x))
    if not candidates:
        return None
    *_, y, x = min(candidates)
    return x, y


def nudge(state: GameState, config: Config, kind: str, x: int, y: int,
          zone_name: str | None = None) -> tuple[int, int] | None:
    """@brief A place one tile away when (x, y) itself does not fit (a model
    off by one), in the fixed order of NUDGES (hex: the 6 neighbours of the
    anchor, E first); None if none fits."""
    taken = occupancy(state, config)
    shifted = (neighbours(config, x, y) if is_hex(config)
               else [(x + dx, y + dy) for dx, dy in NUDGES])
    for nx, ny in shifted:
        if place_error(state, config, kind, nx, ny, zone_name, taken) is None:
            return nx, ny
    return None


def zones_error(state: GameState, config: Config, zones: list[Zone]) -> str | None:
    """@brief Why a new town plan cannot replace the one in force, or None.

    A zone may reach beyond the realm's land (planning ahead for tiles to
    claim); buildings are still placed only on owned, cleared tiles.
    """
    if not zones or len(zones) > config.map.max_zones:
        return f"between 1 and {config.map.max_zones} zones"
    names = [zone.name for zone in zones]
    if len(set(names)) != len(names) or not all(name.strip() for name in names):
        return "every zone needs its own name"
    for zone in zones:
        if zone.purpose not in ZONE_PURPOSES:
            return f"zone '{zone.name}': unknown purpose '{zone.purpose}'"
        if not (_in_map(state, zone.x1, zone.y1) and _in_map(state, zone.x2, zone.y2)
                and zone.x1 <= zone.x2 and zone.y1 <= zone.y2):
            return f"zone '{zone.name}' leaves the map or has its corners reversed"
    for index, first in enumerate(zones):
        for second in zones[index + 1:]:
            if first.x1 <= second.x2 and second.x1 <= first.x2 and first.y1 <= second.y2 and second.y1 <= first.y2:
                return f"zones '{first.name}' and '{second.name}' overlap"
    return _buildings_outside(state, config, zones)


def _buildings_outside(state: GameState, config: Config, zones: list[Zone]) -> str | None:
    """@brief The first existing building (or the square) not wholly inside
    one zone of its purpose under the new plan."""
    for building in state.buildings:
        tiles = footprint(config, building.kind, building.x, building.y)
        zone = single_zone(zones, tiles)
        if zone is None or zone.purpose not in KIND_PURPOSES[building.kind]:
            return f"{building.kind} {building.id} at ({building.x},{building.y}) would not be inside a zone of its kind"
    zone = single_zone(zones, square_tiles(state, config))
    if zone is None or zone.purpose != "center":
        return "the square would not be inside a center zone"
    return None


def _set_tile(rows: list[str], x: int, y: int, char: str) -> None:
    rows[y] = rows[y][:x] + char + rows[y][x + 1:]


def _in_direction(state: GameState, config: Config, x: int, y: int, direction: str | None) -> bool:
    """@brief True if the tile lies on that side of the square: within the
    quarter of the plane around the direction (diagonals count for both)."""
    if direction is None:
        return True
    dx, dy = _hex_offset(state, config, x, y) if is_hex(config) else _square_offset(state, config, x, y)
    return {"north": -dy >= abs(dx), "south": dy >= abs(dx),
            "east": dx >= abs(dy), "west": -dx >= abs(dy)}[direction]


def _square_offset(state: GameState, config: Config, x: int, y: int) -> tuple[int, int]:
    """@brief (dx, dy) from the square's centre to the tile's, in half tiles."""
    size = config.map.square_size
    return (2 * x + 1) - (2 * state.square[0] + size), (2 * y + 1) - (2 * state.square[1] + size)


def _hex_offset(state: GameState, config: Config, x: int, y: int) -> tuple[int, int]:
    """@brief (dx, dy) from the square's centre to the hex's, on an integer
    scale that keeps the angles: columns in half hex widths times 4 (odd rows
    shifted by one half), rows times 7 (7/4 stands in for sqrt(3), the row
    height in half widths). The square's centre is the mean of its tiles,
    so the tile is weighted by their count (integers only)."""
    tiles = square_tiles(state, config)
    count = len(tiles)
    dx = 4 * (count * (2 * x + (y & 1)) - sum(2 * sx + (sy & 1) for sx, sy in tiles))
    dy = 7 * (count * y - sum(sy for _, sy in tiles))
    return dx, dy


def _tile_distance(state: GameState, config: Config, x: int, y: int) -> int:
    if is_hex(config):
        return _hex_to_square(state, config, x, y)
    size = config.map.square_size
    dx = (2 * x + 1) - (2 * state.square[0] + size)
    dy = (2 * y + 1) - (2 * state.square[1] + size)
    return dx * dx + dy * dy


def _borders_the_realm(state: GameState, config: Config, x: int, y: int) -> bool:
    return any(_in_map(state, nx, ny) and state.owned[ny][nx] != NOT_OWNED
               for nx, ny in neighbours(config, x, y))


def owned_count(state: GameState) -> int:
    return sum(row.count(OWNED) + row.count(WILD) for row in state.owned)


def claim_price(state: GameState, config: Config) -> int:
    """@brief Gold for the next tile: it grows with the land beyond the core."""
    beyond = max(0, owned_count(state) - config.map.core_size ** 2)
    return config.map.claim_base_gold + beyond // config.map.claim_step_tiles


def next_claim(state: GameState, config: Config, terrain: str | None, direction: str | None,
               zone: Zone | None = None) -> tuple[int, int] | None:
    """@brief The tile a claim would take: not owned, bordering the realm,
    inside the zone (any land but river, or of the terrain if given) or of
    the terrain on that side; nearest the square, then row, column.

    Why the zone: claiming by side took the tiles nearest the square all
    along the border, so the realm grew in thin strips and never held the
    3 x 3 block of a farm (lab 2026-11-08: 24 tiles in three years, no farm).
    """
    chars = ({TERRAIN_CHARS[terrain]} if terrain else
             {c for name, c in TERRAIN_CHARS.items() if name != "river"})
    best = None
    for y, row in enumerate(state.terrain):
        for x, tile in enumerate(row):
            if tile not in chars or state.owned[y][x] != NOT_OWNED:
                continue
            if zone is not None and not (zone.x1 <= x <= zone.x2 and zone.y1 <= y <= zone.y2):
                continue
            if not _in_direction(state, config, x, y, direction) or not _borders_the_realm(state, config, x, y):
                continue
            key = (_tile_distance(state, config, x, y), y, x)
            best = key if best is None or key < best else best
    return None if best is None else (best[2], best[1])


def unclaimed_in_zone(state: GameState, zone: Zone) -> int:
    """@brief Land tiles (not river) of the zone the realm does not own yet."""
    river = TERRAIN_CHARS["river"]
    size = len(state.terrain)
    return sum(1 for y in range(max(0, zone.y1), min(size, zone.y2 + 1))
               for x in range(max(0, zone.x1), min(size, zone.x2 + 1))
               if state.owned[y][x] == NOT_OWNED and state.terrain[y][x] != river)


def clearing_work(config: Config, terrain_char: str) -> int:
    return {".": config.map.clear_work_plain, "^": config.map.clear_work_hill,
            "T": config.map.clear_work_forest}[terrain_char]


def claim_tile(state: GameState, config: Config, x: int, y: int) -> None:
    """@brief Own one tile. A forest stands and is usable at once (it feeds
    the sawmills); plain and hill arrive wild and wait for clearing."""
    if state.terrain[y][x] == TERRAIN_CHARS["forest"]:
        _set_tile(state.owned, x, y, OWNED)
        return
    _set_tile(state.owned, x, y, WILD)
    state.clearing_queue.append([x, y, clearing_work(config, state.terrain[y][x])])


def forest_to_fell(state: GameState, config: Config, direction: str | None) -> tuple[int, int] | None:
    """@brief The owned forest tile a felling order would take: not queued
    yet, on that side; the one nearest the square first."""
    queued = {(x, y) for x, y, _ in state.clearing_queue}
    best = None
    for y, row in enumerate(state.terrain):
        for x, tile in enumerate(row):
            if tile != TERRAIN_CHARS["forest"] or state.owned[y][x] != OWNED or (x, y) in queued:
                continue
            if not _in_direction(state, config, x, y, direction):
                continue
            key = (_tile_distance(state, config, x, y), y, x)
            best = key if best is None or key < best else best
    return None if best is None else (best[2], best[1])


def clear_land(state: GameState, config: Config, events: list[Event]) -> None:
    """@brief This month's clearing work, one worker-month per worker, on the
    queue in order. Felling gives wood for each worker-month and leaves a
    plain; a finished tile becomes usable. Workers with no queue are idle.
    No strike or effort modifier: clearing is plain labour, kept simple."""
    work = state.workers.clearing
    while work > 0 and state.clearing_queue:
        x, y, left = state.clearing_queue[0]
        spent = min(work, left)
        work -= spent
        felling = state.terrain[y][x] == TERRAIN_CHARS["forest"]
        if felling:
            state.wood += spent * config.map.fell_wood_per_work
        if spent < left:
            state.clearing_queue[0][2] = left - spent
            continue
        state.clearing_queue.pop(0)
        if felling:
            _set_tile(state.terrain, x, y, TERRAIN_CHARS["plain"])
        _set_tile(state.owned, x, y, OWNED)
        events.append(Event("tile_cleared", {"x": x, "y": y, "felled": felling}))
