"""@brief The territory in words and a text grid, for the counsellors' briefings.

Pure functions over the engine state; every number is counted here, so
the models never count tiles themselves (lab/urban_probe.py: they place
rectangles well, but miscount footprints).

Cost: the grid covers the realm's land plus a ring of RING tiles, about
16 x 16 cells at the start (about 350 tokens); room_in_zone places copies
of a building on a scratch state, a few hundred tile checks per zone.
"""

import copy

from engine.config import Config
from engine.state import Building, GameState
from engine.territory import (KIND_PURPOSES, NOT_OWNED, OWNED, TERRAIN_CHARS, WILD, building_works,
                              claim_price, find_place, footprint, owned_count, square_tiles, _in_direction)

RING = 2  # tiles shown around the realm's land
MAX_ROOM = 20  # room counts stop here: "20 or more" is enough to plan
LETTERS = {"farm": "F", "sawmill": "S", "quarry": "Q", "house": "H"}
# Tiles outside the realm: the same terrain, another character.
NOT_OWNED_CHARS = {".": ",", "T": "t", "^": "n", "~": "~"}
DIRECTIONS = ("north", "south", "east", "west")
LEGEND = ("Legend: realm's land: . plain, T forest, ^ hill, ~ river, w claimed but still wild; "
          "outside the realm: , plain, t forest, n hill; P square; buildings F farm, S sawmill, Q quarry, "
          "H house (lower case while under construction). x is the column, y the row; north is up.")


def _bounds(state: GameState) -> tuple[int, int, int, int]:
    """@brief (x1, y1, x2, y2) of the realm's land plus the ring, inside the map."""
    tiles = [(x, y) for y, row in enumerate(state.owned) for x, char in enumerate(row) if char != NOT_OWNED]
    size = len(state.terrain)
    return (max(0, min(x for x, _ in tiles) - RING), max(0, min(y for _, y in tiles) - RING),
            min(size - 1, max(x for x, _ in tiles) + RING), min(size - 1, max(y for _, y in tiles) + RING))


def _cell(state: GameState, x: int, y: int) -> str:
    owned = state.owned[y][x]
    if owned == WILD:
        return "w"
    terrain = state.terrain[y][x]
    return terrain if owned == OWNED else NOT_OWNED_CHARS[terrain]


def grid_lines(state: GameState, config: Config) -> list[str]:
    """@brief The text map of the realm and its ring, with world coordinates."""
    x1, y1, x2, y2 = _bounds(state)
    cells = {(x, y): _cell(state, x, y) for y in range(y1, y2 + 1) for x in range(x1, x2 + 1)}
    for tile in square_tiles(state, config):
        cells[tile] = "P"
    for building in state.buildings:
        letter = LETTERS[building.kind]
        for tile in footprint(config, building.kind, building.x, building.y):
            cells[tile] = letter if building.turns_left == 0 else letter.lower()
    header = "   " + "".join(f"{x:>3}" for x in range(x1, x2 + 1))
    rows = [f"{y:>3}" + "".join(f"{cells[(x, y)]:>3}" for x in range(x1, x2 + 1)) for y in range(y1, y2 + 1)]
    return [header] + rows


def room_in_zone(state: GameState, config: Config, kind: str, zone_name: str) -> int:
    """@brief How many buildings of this kind still fit in the zone, placed
    one after the other as the engine would (counted up to MAX_ROOM)."""
    scratch = copy.deepcopy(state)
    count = 0
    while count < MAX_ROOM:
        place = find_place(scratch, config, kind, zone_name)
        if place is None:
            break
        scratch.buildings.append(Building(kind, 0, -1 - count, *place))
        count += 1
    return count


def _room_text(state: GameState, config: Config, zone) -> str:
    kinds = [kind for kind, purposes in KIND_PURPOSES.items() if zone.purpose in purposes]
    if not kinds:
        return "kept free"
    parts = []
    for kind in kinds:
        room = room_in_zone(state, config, kind, zone.name)
        if room:
            parts.append(f"{'20 or more' if room >= MAX_ROOM else room} {kind}")
    return ("room for " + ", ".join(parts)) if parts else "full"


def zone_lines(state: GameState, config: Config) -> list[str]:
    return [f"- {zone.name} ({zone.purpose}), from ({zone.x1},{zone.y1}) to ({zone.x2},{zone.y2}): "
            f"{_room_text(state, config, zone)}" for zone in state.zones]


def _status(state: GameState, config: Config, building: Building) -> str:
    if building.turns_left:
        return f", under construction ({building.turns_left} months left)"
    if not building_works(state, config, building):
        return ", NOT WORKING: it no longer touches a forest of the realm"
    return ""


def building_lines(state: GameState, config: Config) -> list[str]:
    return ["- " + "; ".join(f"{b.kind} {b.id} at ({b.x},{b.y}){_status(state, config, b)}"
                             for b in state.buildings) + "."]


def _frontier_counts(state: GameState, config: Config) -> dict[str, dict[str, int]]:
    """@brief Unowned tiles of each terrain bordering the realm, per side."""
    counts = {d: {"plain": 0, "forest": 0, "hill": 0} for d in DIRECTIONS}
    by_char = {char: name for name, char in TERRAIN_CHARS.items() if name != "river"}
    size = len(state.terrain)
    for y in range(size):
        for x in range(size):
            terrain = by_char.get(state.terrain[y][x])
            if terrain is None or state.owned[y][x] != NOT_OWNED:
                continue
            if not any(0 <= nx < size and 0 <= ny < size and state.owned[ny][nx] != NOT_OWNED
                       for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))):
                continue
            for direction in DIRECTIONS:
                if _in_direction(state, config, x, y, direction):
                    counts[direction][terrain] += 1
    return counts


def frontier_line(state: GameState, config: Config) -> str:
    counts = _frontier_counts(state, config)
    parts = [f"{d}: " + ", ".join(f"{n} {t}" for t, n in counts[d].items()) for d in DIRECTIONS]
    return "- Bordering tiles you could claim, by side of the square: " + "; ".join(parts) + "."


def _forest_warnings(state: GameState, config: Config) -> list[str]:
    """@brief A sawmill whose every forest tile is queued for felling."""
    queued = {(x, y) for x, y, _ in state.clearing_queue}
    forest = TERRAIN_CHARS["forest"]
    warnings = []
    for building in state.buildings:
        if not config.buildings[building.kind].needs_forest or not building_works(state, config, building):
            continue
        touching = {(nx, ny) for x, y in footprint(config, building.kind, building.x, building.y)
                    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                    if 0 <= ny < len(state.terrain) and 0 <= nx < len(state.terrain)
                    and state.terrain[ny][nx] == forest and state.owned[ny][nx] != NOT_OWNED}
        if touching and touching <= queued:
            warnings.append(f"- WARNING: the last forest of sawmill {building.id} is queued for felling: "
                            "once felled, that sawmill produces nothing.")
    return warnings


def clearing_line(state: GameState) -> str:
    if not state.clearing_queue:
        return f"- Clearing: nothing queued. Clearing workers: {state.workers.clearing}."
    left = sum(entry[2] for entry in state.clearing_queue)
    felling = sum(1 for x, y, _ in state.clearing_queue if state.terrain[y][x] == TERRAIN_CHARS["forest"])
    x, y, first_left = state.clearing_queue[0]
    return (f"- Clearing: {len(state.clearing_queue)} tiles queued ({felling} of them forest to fell), "
            f"{left} worker-months in all; first ({x},{y}) needs {first_left} more. "
            f"Clearing workers: {state.workers.clearing} (one worker-month each a month).")


def price_line(state: GameState, config: Config) -> str:
    return (f"- Land: {owned_count(state)} tiles owned. The next tile costs {claim_price(state, config)} gold "
            f"(one more for every {config.map.claim_step_tiles} tiles beyond the core); "
            f"this realm has paid {state.land_paid_total} gold into the land fund.")


def architect_lines(state: GameState, config: Config) -> list[str]:
    """@brief The Architect's view of the territory: map, zones, buildings, land."""
    return (["## The town and its land", LEGEND] + grid_lines(state, config)
            + ["- Zones of the town plan (a building goes where it fits, nearest the square):"]
            + zone_lines(state, config)
            + ["- Buildings (kind, id, top-left tile):"] + building_lines(state, config)
            + [price_line(state, config), frontier_line(state, config), clearing_line(state)]
            + _forest_warnings(state, config))


def summary_line(state: GameState, config: Config) -> str:
    """@brief One line for the Chancellor: land, clearing, price, room per zone."""
    left = sum(entry[2] for entry in state.clearing_queue)
    zones = "; ".join(f"{zone.name}: {_room_text(state, config, zone)}" for zone in state.zones)
    return (f"- Territory: {owned_count(state)} tiles owned, {len(state.clearing_queue)} queued for clearing "
            f"({left} worker-months); the next tile costs {claim_price(state, config)} gold. Zones: {zones}.")
