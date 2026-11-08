"""@brief Feasibility probe: can a council model plan a town on a tile grid?

Usage (inside the server container, which has the key):
  docker compose exec -T -e PYTHONPATH=/app server python lab/urban_probe.py [--repeat N] MODEL[:EFFORT] ...
  e.g. ... lab/urban_probe.py --repeat 10 z-ai/glm-5.3-flash:high

A fixed 16 x 16 map (river, forest, hill, the 12 starting buildings) is
sent as a text grid. The Architect draws the zones of a town plan
(rectangles) and places three new buildings (top-left corner). Every reply
is checked by plain geometry: bounds, overlaps, terrain, zone purpose.

Nothing touches the database or a game. Hidden costs: real OpenRouter
calls, one at a time, each blocking up to timeout_seconds; 10 calls of
GLM 5.3 Flash "high" cost about $0.01.
Limit: one hand-made map; the probe measures validity, the sense of the
plan is judged by reading the rendered maps in the output.
"""

import json
import os
import sys

from server.council.llm import LLMError, OpenRouterClient
from server.council.settings import load_settings

SIZE = 16
PLAIN, RIVER, FOREST, HILL = ".", "~", "T", "^"
# Footprint (width, height) and map letter of every building kind.
FOOTPRINTS = {"farm": (3, 3), "sawmill": (2, 1), "quarry": (2, 2), "house": (1, 1), "square": (2, 2)}
LETTERS = {"farm": "F", "sawmill": "S", "quarry": "Q", "house": "H", "square": "P"}
# Zone purpose each building kind belongs to.
PURPOSE_OF = {"farm": "fields", "sawmill": "workshops", "quarry": "workshops", "house": "houses",
              "square": "center"}
PURPOSES = ("fields", "center", "houses", "workshops", "reserve")
NEW_BUILDINGS = ("farm", "house", "sawmill")

# Existing buildings: kind, x, y (top-left corner; x = column, y = row, north up).
EXISTING = [
    ("square", 6, 7),
    ("house", 5, 6), ("house", 6, 6), ("house", 7, 6), ("house", 8, 6), ("house", 5, 9), ("house", 8, 9),
    ("farm", 1, 10), ("farm", 4, 10), ("farm", 1, 13), ("farm", 4, 13),
    ("sawmill", 4, 4),
    ("quarry", 12, 12),
]


def build_terrain() -> list[list[str]]:
    """@brief The hand-made terrain: a river from north to south, forest in
    the north-west, hills in the south-east, plain elsewhere."""
    grid = [[PLAIN] * SIZE for _ in range(SIZE)]
    for y in range(SIZE):
        grid[y][10 if y < 8 else 11] = RIVER
    for y in range(0, 6):
        for x in range(0, 4):
            grid[y][x] = FOREST
    for y in range(11, SIZE):
        for x in range(12, SIZE):
            grid[y][x] = HILL
    return grid


def cells(kind: str, x: int, y: int) -> list[tuple[int, int]]:
    width, height = FOOTPRINTS[kind]
    return [(x + dx, y + dy) for dy in range(height) for dx in range(width)]


def occupied_map() -> dict[tuple[int, int], str]:
    """@brief Cell -> building kind for the existing buildings."""
    taken = {}
    for kind, x, y in EXISTING:
        for cell in cells(kind, x, y):
            taken[cell] = kind
    return taken


def render(terrain: list[list[str]], buildings: list[tuple[str, int, int]], lower: bool = False) -> str:
    """@brief Text grid with column and row numbers; buildings over terrain
    (new buildings in lower case when lower is set)."""
    grid = [row[:] for row in terrain]
    for kind, x, y in buildings:
        for cx, cy in cells(kind, x, y):
            if 0 <= cx < SIZE and 0 <= cy < SIZE:
                grid[cy][cx] = LETTERS[kind].lower() if lower else LETTERS[kind]
    header = "   " + "".join(f"{x:>3}" for x in range(SIZE))
    rows = [f"{y:>3}" + "".join(f"{cell:>3}" for cell in row) for y, row in enumerate(grid)]
    return "\n".join([header] + rows)


def render_zones(zones: list[dict]) -> str:
    """@brief Zone index per cell ('#' where zones overlap, '.' outside)."""
    grid = [["."] * SIZE for _ in range(SIZE)]
    for index, zone in enumerate(zones):
        for y in range(max(0, zone["y1"]), min(SIZE, zone["y2"] + 1)):
            for x in range(max(0, zone["x1"]), min(SIZE, zone["x2"] + 1)):
                grid[y][x] = "#" if grid[y][x] != "." else str(index % 10)
    header = "   " + "".join(f"{x:>3}" for x in range(SIZE))
    return "\n".join([header] + [f"{y:>3}" + "".join(f"{c:>3}" for c in row) for y, row in enumerate(grid)])


SYSTEM = """You are the Architect of the realm of Roccafonda, a medieval city ruled by a sovereign. Besides building, you plan the town: where the fields go, where the houses, where the workshops, around the square at the centre. The sovereign wants a town that is well organised and pleasant to look at, and that grows in order as new buildings come.

The map is a grid of 16 x 16 tiles. x is the column (0 at the west, 15 at the east), y is the row (0 at the north, 15 at the south). Legend:
. plain   ~ river   T forest   ^ hill
P town square   H house   F farm fields   S sawmill   Q quarry

Footprints (width x height, placed by the top-left tile):
farm 3 x 3, sawmill 2 x 1, quarry 2 x 2, house 1 x 1.

Terrain rules:
- Nothing is built on the river or on the forest.
- A farm stands on plain only.
- A sawmill stands on plain, with at least one tile touching the forest (north, south, east or west).
- A quarry stands on hill only.
- A house stands on plain only.
- Buildings never overlap.

Your task:
1. Draw the zones of the town plan as rectangles (x1, y1) to (x2, y2), corners included. Purposes: "fields", "center" (the square and what surrounds it), "houses", "workshops" (sawmills, quarries), "reserve" (land kept free for later). Zones must not overlap. Every existing building should fall inside a zone of its purpose. Leave room for growth.
2. Place these new buildings, each inside a zone of its purpose and following the terrain rules: one farm, one house, one sawmill. Give the top-left tile of each.
3. Explain the plan to the sovereign in Italian, at most 80 words.

Reply with JSON only:
{"zones": [{"name": "...", "purpose": "fields", "x1": 0, "y1": 0, "x2": 0, "y2": 0}, ...],
 "placements": [{"building": "farm", "x": 0, "y": 0}, ...],
 "reason": "..."}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "zones": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "purpose": {"type": "string", "enum": list(PURPOSES)},
            "x1": {"type": "integer"}, "y1": {"type": "integer"},
            "x2": {"type": "integer"}, "y2": {"type": "integer"}},
            "required": ["name", "purpose", "x1", "y1", "x2", "y2"]}},
        "placements": {"type": "array", "items": {"type": "object", "properties": {
            "building": {"type": "string", "enum": list(NEW_BUILDINGS)},
            "x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["building", "x", "y"]}},
        "reason": {"type": "string"},
    },
    "required": ["zones", "placements", "reason"],
}


def zone_of(zones: list[dict], cell: tuple[int, int]) -> dict | None:
    x, y = cell
    for zone in zones:
        if zone["x1"] <= x <= zone["x2"] and zone["y1"] <= y <= zone["y2"]:
            return zone
    return None


def check_zones(zones: list[dict]) -> list[str]:
    """@brief Problems of the zone plan: bad rectangles, overlaps, existing
    buildings outside a zone of their purpose."""
    problems = []
    for zone in zones:
        if not (0 <= zone["x1"] <= zone["x2"] < SIZE and 0 <= zone["y1"] <= zone["y2"] < SIZE):
            problems.append(f"zone '{zone['name']}' out of the map or reversed")
    for i, first in enumerate(zones):
        for second in zones[i + 1:]:
            if (first["x1"] <= second["x2"] and second["x1"] <= first["x2"]
                    and first["y1"] <= second["y2"] and second["y1"] <= first["y2"]):
                problems.append(f"zones '{first['name']}' and '{second['name']}' overlap")
    for kind, x, y in EXISTING:
        zone = zone_of(zones, (x, y))
        if zone is None or zone["purpose"] != PURPOSE_OF[kind]:
            found = zone["purpose"] if zone else "no zone"
            problems.append(f"existing {kind} at ({x},{y}) in {found}")
    return problems


def _touches_forest(terrain, footprint) -> bool:
    for x, y in footprint:
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < SIZE and 0 <= ny < SIZE and terrain[ny][nx] == FOREST:
                return True
    return False


def check_placement(terrain, taken, zones, kind: str, x: int, y: int) -> list[str]:
    """@brief Problems of one new building: bounds, overlap, terrain, zone."""
    footprint = cells(kind, x, y)
    if any(not (0 <= cx < SIZE and 0 <= cy < SIZE) for cx, cy in footprint):
        return [f"{kind} at ({x},{y}) out of the map"]
    problems = []
    if any(cell in taken for cell in footprint):
        problems.append(f"{kind} at ({x},{y}) overlaps a building")
    if any(terrain[cy][cx] != PLAIN for cx, cy in footprint):
        problems.append(f"{kind} at ({x},{y}) not all on plain")
    if kind == "sawmill" and not _touches_forest(terrain, footprint):
        problems.append(f"sawmill at ({x},{y}) does not touch the forest")
    if any((z := zone_of(zones, cell)) is None or z["purpose"] != PURPOSE_OF[kind] for cell in footprint):
        problems.append(f"{kind} at ({x},{y}) not all inside a '{PURPOSE_OF[kind]}' zone")
    return problems


def judge(terrain, text: str) -> dict:
    """@brief Parse and check one reply; placements are checked in order,
    each against the existing buildings and the new ones before it."""
    try:
        reply = json.loads(text)
        zones, placements = reply["zones"], reply["placements"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        return {"parsed": False, "zone_problems": [], "placement_problems": [f"unreadable: {error}"],
                "zones": [], "placements": [], "reason": text[:300]}
    taken = occupied_map()
    placement_problems = []
    kinds = sorted(p.get("building") for p in placements)
    if kinds != sorted(NEW_BUILDINGS):
        placement_problems.append(f"asked farm, house, sawmill; got {kinds}")
    for placement in placements:
        kind = placement.get("building")
        if kind not in NEW_BUILDINGS:
            continue
        placement_problems += check_placement(terrain, taken, zones, kind, placement["x"], placement["y"])
        for cell in cells(kind, placement["x"], placement["y"]):
            taken[cell] = kind
    return {"parsed": True, "zone_problems": check_zones(zones), "placement_problems": placement_problems,
            "zones": zones, "placements": placements, "reason": reply.get("reason", "")}


def report_lines(candidate: str, attempt: int, result: dict, terrain, tokens: int, seconds: float) -> list[str]:
    status = "ok" if result["parsed"] and not result["zone_problems"] and not result["placement_problems"] else "FAIL"
    lines = [f"\n--- {candidate} #{attempt} | {tokens} tok | {seconds:.1f} s | {status}"]
    lines += [f"    zone: {p}" for p in result["zone_problems"]]
    lines += [f"    placement: {p}" for p in result["placement_problems"]]
    lines.append(f"    reason: {result['reason']}")
    if result["parsed"]:
        zone_list = [f"{i % 10}={z['name']} ({z['purpose']}) ({z['x1']},{z['y1']})-({z['x2']},{z['y2']})"
                     for i, z in enumerate(result["zones"])]
        lines.append("    zones: " + "; ".join(zone_list))
        lines.append(render_zones(result["zones"]))
        new = [(p["building"], p["x"], p["y"]) for p in result["placements"] if p.get("building") in NEW_BUILDINGS]
        lines.append(render(render_terrain_with_existing(terrain), new, lower=True))
    return lines


def render_terrain_with_existing(terrain) -> list[list[str]]:
    grid = [row[:] for row in terrain]
    for kind, x, y in EXISTING:
        for cx, cy in cells(kind, x, y):
            grid[cy][cx] = LETTERS[kind]
    return grid


def main(argv: list[str]) -> None:
    repeat = 10
    if argv[:1] == ["--repeat"]:
        repeat, argv = int(argv[1]), argv[2:]
    candidates = argv or ["z-ai/glm-5.3-flash:high"]
    settings = load_settings()
    client = OpenRouterClient(settings.base_url, os.environ.get("OPENROUTER_API_KEY", ""),
                              settings.timeout_seconds, settings.prices, settings.max_output_tokens,
                              settings.models_without_json_schema, settings.models_without_reasoning)
    terrain = build_terrain()
    user = "The town today:\n" + render(terrain, EXISTING)
    out = ["# Map sent", user]
    for candidate in candidates:
        model, _, effort = candidate.partition(":")
        valid_zones = valid_places = clean = 0
        cost = 0.0
        for attempt in range(1, repeat + 1):
            try:
                reply = client.complete("architect", model, SYSTEM, user, SCHEMA, effort or None)
            except LLMError as error:
                out.append(f"\n--- {candidate} #{attempt} | ERROR {error.status}: {str(error)[:200]}")
                continue
            result = judge(terrain, reply.text)
            cost += reply.cost_usd
            valid_zones += result["parsed"] and not result["zone_problems"]
            valid_places += result["parsed"] and not result["placement_problems"]
            clean += result["parsed"] and not result["zone_problems"] and not result["placement_problems"]
            out += report_lines(candidate, attempt, result, terrain, reply.output_tokens, reply.latency_ms / 1000)
            print(f"{candidate} #{attempt}: zones {len(result['zone_problems'])} problems,"
                  f" placements {len(result['placement_problems'])} problems", file=sys.stderr, flush=True)
        out.insert(0, f"{candidate}: {repeat} runs | zones clean {valid_zones} | placements clean {valid_places}"
                      f" | all clean {clean} | ${cost:.4f}")
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
