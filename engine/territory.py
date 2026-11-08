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
"""

import tomllib
from pathlib import Path

from engine.config import Config
from engine.state import Building, GameState, Zone

MAPS_DIR = Path(__file__).with_name("maps")
TERRAIN_CHARS = {"plain": ".", "river": "~", "forest": "T", "hill": "^"}
NOT_OWNED, OWNED = "-", "o"
ZONE_PURPOSES = ("fields", "center", "houses", "workshops", "reserve")
# Zone purposes each building kind may stand in (houses also around the square).
KIND_PURPOSES = {"farm": ("fields",), "sawmill": ("workshops",), "quarry": ("workshops",),
                 "house": ("houses", "center")}
SQUARE = "square"
# Shifts tried, in this order, when a building given by coordinates does
# not fit: one tile north, east, south, west, then the diagonals.
NUDGES = ((0, -1), (1, 0), (0, 1), (-1, 0), (1, -1), (1, 1), (-1, 1), (-1, -1))


def _load_core(config: Config) -> dict:
    with open(MAPS_DIR / config.map.core_file, "rb") as core_file:
        core = tomllib.load(core_file)
    core["rows"] = [row.strip() for row in core["terrain"].strip().splitlines()]
    return core


def _load_world(config: Config) -> list[str]:
    rows = (MAPS_DIR / config.map.world_file).read_text(encoding="utf-8").splitlines()
    return [row for row in rows if row]


def start_territory(state: GameState, config: Config, seed: int) -> None:
    """@brief Put a new realm on the map: copy the world, pick the site from
    the seed, own the core and place the core's square, buildings and zones.
    The core's buildings replace the counted ones of [start]; they are the
    same 4 farms, 1 sawmill, 1 quarry and 6 houses.
    @throws ValueError if the world or the core file is malformed.
    """
    world = _load_world(config)
    core = _load_core(config)
    size, core_size = len(world), config.map.core_size
    if any(len(row) != size for row in world) or len(core["rows"]) != core_size:
        raise ValueError("world must be square and the core core_size x core_size")
    site_x, site_y = config.map.sites[seed % len(config.map.sites)]
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


def footprint(config: Config, kind: str, x: int, y: int) -> list[tuple[int, int]]:
    spec = config.buildings[kind]
    return [(x + dx, y + dy) for dy in range(spec.height) for dx in range(spec.width)]


def square_tiles(state: GameState, config: Config) -> list[tuple[int, int]]:
    sx, sy = state.square
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


def _touches(state: GameState, tiles: list[tuple[int, int]], terrain: str) -> bool:
    char = TERRAIN_CHARS[terrain]
    for x, y in tiles:
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if _in_map(state, nx, ny) and state.terrain[ny][nx] == char:
                return True
    return False


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
    if spec.needs_forest and not _touches(state, tiles, "forest"):
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


def find_place(state: GameState, config: Config, kind: str, zone_name: str | None = None) -> tuple[int, int] | None:
    """@brief The valid place nearest the square, in the named zone or in any
    zone that allows this kind; ties broken by row, then column.

    Places aligned on the zone's grid (whole footprints from its top-left
    corner) come first: buildings then stand in tidy rows and leave room
    for the next one; a farm placed half-way would waste the zone.
    @return (x, y) top-left tile, or None if nothing fits.
    """
    taken = occupancy(state, config)
    spec = config.buildings[kind]
    zones = [z for z in state.zones if (zone_name is None and z.purpose in KIND_PURPOSES[kind])
             or z.name == zone_name]
    candidates = []
    for zone in zones:
        for y in range(zone.y1, zone.y2 + 1):
            for x in range(zone.x1, zone.x2 + 1):
                if place_error(state, config, kind, x, y, zone.name, taken) is None:
                    aligned = (x - zone.x1) % spec.width == 0 and (y - zone.y1) % spec.height == 0
                    candidates.append((not aligned, _distance_to_square(state, config, kind, x, y), y, x))
    if not candidates:
        return None
    _, _, y, x = min(candidates)
    return x, y


def nudge(state: GameState, config: Config, kind: str, x: int, y: int,
          zone_name: str | None = None) -> tuple[int, int] | None:
    """@brief A place one tile away when (x, y) itself does not fit (a model
    off by one), in the fixed order of NUDGES; None if none fits."""
    taken = occupancy(state, config)
    for dx, dy in NUDGES:
        if place_error(state, config, kind, x + dx, y + dy, zone_name, taken) is None:
            return x + dx, y + dy
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
