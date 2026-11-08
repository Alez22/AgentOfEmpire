"""@brief Probe of the hex text grid (docs/DESIGN.md, "Hex grid", step 3):
can a council model still plan a town when the map is made of hexes?

Usage (inside the server container, which has the key):
  docker compose exec -T -e PYTHONPATH=/app server python lab/hex_probe.py [--repeat N] [--by-zone] MODEL[:EFFORT] ...

--max-tokens N: output cap of each call, reasoning included (default: the
game's, server/council.toml); --timeout S: deadline of each call. Raised to
read what the model does when it reasons long: the reasoning of every
reply is printed after it.
--by-zone: the new buildings are given by zone only and the engine picks
the hex (find_place), as the Architect mostly builds in the game; without
it the model gives each anchor hex.

One realm on the real hex world (world_hex.txt, core_hex.toml, site of seed
0): its land and a ring of 2 hexes, printed as the briefing would print it
(cells of 4 characters, odd rows shifted east by 2). The Architect redraws
the town plan, adds a fields zone beyond the border (planning ahead) and
places a farm, a house and a sawmill by their anchor hex. Every reply is
judged by the engine's own rules (zones_error, place_error), so the probe
checks the same geometry the game will.

Nothing touches the database or a game. Hidden costs: real OpenRouter
calls, one at a time, each blocking up to timeout_seconds; 10 calls of
GLM 5.3 Flash "high" cost about $0.01.
Limit: one map; the probe measures validity, the sense of the plan is
judged by reading the printed plans in the output.
"""

import copy
import dataclasses
import json
import os
import sys

from engine import load_config, new_game
from engine.state import Building, Zone
from engine.territory import NOT_OWNED, WILD, find_place, footprint, place_error, square_tiles, zones_error
from server.council.llm import LLMError, OpenRouterClient
from server.council.settings import load_settings

RING = 2
SEED = 0
LETTERS = {"farm": "F", "sawmill": "S", "quarry": "Q", "house": "H"}
NOT_OWNED_CHARS = {".": ",", "T": "t", "^": "n", "~": "~"}
PURPOSES = ("fields", "center", "houses", "workshops", "reserve")
NEW_BUILDINGS = ("farm", "house", "sawmill")


def hex_config():
    config = load_config()
    return dataclasses.replace(config, map=dataclasses.replace(
        config.map, grid="hex", world_file="world_hex.txt", core_file="core_hex.toml"))


def bounds(state) -> tuple[int, int, int, int]:
    tiles = [(x, y) for y, row in enumerate(state.owned) for x, char in enumerate(row) if char != NOT_OWNED]
    size = len(state.terrain)
    return (max(0, min(x for x, _ in tiles) - RING), max(0, min(y for _, y in tiles) - RING),
            min(size - 1, max(x for x, _ in tiles) + RING), min(size - 1, max(y for _, y in tiles) + RING))


def cell(state, x: int, y: int) -> str:
    if state.owned[y][x] == WILD:
        return "w"
    terrain = state.terrain[y][x]
    return terrain if state.owned[y][x] != NOT_OWNED else NOT_OWNED_CHARS[terrain]


def render(state, config, marks: dict[tuple[int, int], str] | None = None) -> str:
    """@brief The hex text grid: 4 characters a cell, odd rows 2 to the east,
    world coordinates on the edges."""
    x1, y1, x2, y2 = bounds(state)
    cells = {(x, y): cell(state, x, y) for y in range(y1, y2 + 1) for x in range(x1, x2 + 1)}
    for tile in square_tiles(state, config):
        cells[tile] = "P"
    for building in state.buildings:
        for tile in footprint(config, building.kind, building.x, building.y):
            cells[tile] = LETTERS[building.kind]
    cells.update({tile: mark for tile, mark in (marks or {}).items() if tile in cells})
    header = "    " + "".join(f"{x:>4}" for x in range(x1, x2 + 1))
    rows = [f"{y:>4}" + ("  " if y & 1 else "") + "".join(f"{cells[(x, y)]:>4}" for x in range(x1, x2 + 1))
            for y in range(y1, y2 + 1)]
    return "\n".join([header] + rows)


def town_text(state, config) -> str:
    zones = "\n".join(f"- {z.name} ({z.purpose}): ({z.x1},{z.y1}) to ({z.x2},{z.y2})" for z in state.zones)
    buildings = "\n".join(f"- {b.kind} {b.id}, anchor ({b.x},{b.y})" for b in state.buildings)
    sx, sy = state.square
    return (f"The town today:\n{render(state, config)}\n\nThe square, anchor ({sx},{sy}).\n"
            f"Buildings:\n{buildings}\n\nTown plan in force:\n{zones}")


SYSTEM = """You are the Architect of the realm of Roccafonda, a medieval city ruled by a sovereign. Besides building, you plan the town: where the fields go, where the houses, where the workshops, around the square at the centre. The sovereign wants a town that is well organised and that grows in order.

The map is made of hexagons. Each tile has coordinates (x, y): x is the column (growing to the east), y is the row (growing to the south). The rows are drawn as on a honeycomb: odd rows sit half a cell to the east. So every hex has 6 neighbours:
- on an even row y, the neighbours of (x, y) are (x+1,y) east, (x-1,y) west, (x-1,y-1) and (x,y-1) above, (x-1,y+1) and (x,y+1) below;
- on an odd row y, they are (x+1,y) east, (x-1,y) west, (x,y-1) and (x+1,y-1) above, (x,y+1) and (x+1,y+1) below.

Legend of the realm's land: . plain   ~ river   T forest   ^ hill   P town square   H house   F farm fields   S sawmill   Q quarry
Land outside the realm (not owned yet): , plain   t forest   n hill   ~ river

Shapes, placed by their anchor hex:
- farm: 7 hexes, the anchor and its 6 neighbours (a flower); on plain only;
- sawmill: 2 hexes, the anchor and its east neighbour; on plain, and one of its hexes must be next to a forest hex of the realm;
- house: 1 hex, on plain;
- quarry: 4 hexes on hill (not asked today).
Nothing is built on the river or on the forest; buildings never overlap and stand only on the realm's land.

Your task:
1. Draw the full town plan as rectangles of tiles (x1, y1) to (x2, y2), corners included. Purposes: "fields", "center" (the square and the houses around it), "houses", "workshops" (sawmills, quarries), "reserve" (land kept free). Zones must not overlap; every existing building and the square must lie wholly inside one zone of its purpose (houses may also stand in the center). Keep the zones of the plan in force where they work. Add one new "fields" zone beyond the realm's border, on land outside it, for the next farms (a zone may reach beyond the border; it is claimed later). A farm needs 3 rows and 3 columns of a zone.
2. Place these new buildings on the realm's land, each wholly inside a zone of its purpose: one farm, one house, one sawmill. Give the anchor hex of each.
3. Explain the plan to the sovereign in Italian, at most 80 words.

Reply with JSON only:
{"zones": [{"name": "...", "purpose": "fields", "x1": 0, "y1": 0, "x2": 0, "y2": 0}, ...],
 "placements": [{"building": "farm", "x": 0, "y": 0}, ...],
 "reason": "..."}"""

# The by-zone variant: step 2 and the reply format name a zone, not a hex.
STEP_ANCHOR = "2. Place these new buildings on the realm's land, each wholly inside a zone of its purpose: one farm, one house, one sawmill. Give the anchor hex of each."
STEP_BY_ZONE = ("2. Build these new buildings: one farm, one house, one sawmill. For each, name the zone of your plan "
                "where it goes; the engine picks the best hex inside it, so make sure the zone has room on the realm's land.")
FORMAT_ANCHOR = '"placements": [{"building": "farm", "x": 0, "y": 0}, ...],'
FORMAT_BY_ZONE = '"placements": [{"building": "farm", "zone": "..."}, ...],'


def system_prompt(by_zone: bool) -> str:
    if not by_zone:
        return SYSTEM
    return SYSTEM.replace(STEP_ANCHOR, STEP_BY_ZONE).replace(FORMAT_ANCHOR, FORMAT_BY_ZONE)


def schema(by_zone: bool) -> dict:
    if not by_zone:
        return SCHEMA
    by_zone_schema = copy.deepcopy(SCHEMA)
    by_zone_schema["properties"]["placements"]["items"] = {"type": "object", "properties": {
        "building": {"type": "string", "enum": list(NEW_BUILDINGS)}, "zone": {"type": "string"}},
        "required": ["building", "zone"]}
    return by_zone_schema


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


def _outside_land(state, zone: Zone) -> bool:
    """@brief True if the zone holds at least one hex the realm does not own."""
    return any(state.owned[y][x] == NOT_OWNED
               for y in range(max(0, zone.y1), min(len(state.owned), zone.y2 + 1))
               for x in range(max(0, zone.x1), min(len(state.owned), zone.x2 + 1)))


def judge(state, config, text: str) -> dict:
    """@brief Parse and check one reply with the engine's rules. Placements
    are checked in order against the reply's plan when it is valid (else
    the plan in force), each after the ones before it."""
    try:
        reply = json.loads(text)
        zones = [Zone(z["name"], z["purpose"], z["x1"], z["y1"], z["x2"], z["y2"]) for z in reply["zones"]]
        placements = reply["placements"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        return {"parsed": False, "zone_problem": None, "placement_problems": [f"unreadable: {error}"],
                "zones": [], "placements": [], "reason": text[:300], "new_fields": False}
    trial = copy.deepcopy(state)
    zone_problem = zones_error(trial, config, zones)
    if zone_problem is None:
        trial.zones = zones
    new_fields = any(z.purpose == "fields" and _outside_land(state, z) for z in zones)
    problems = []
    kinds = sorted(p.get("building") for p in placements)
    if kinds != sorted(NEW_BUILDINGS):
        problems.append(f"asked farm, house, sawmill; got {kinds}")
    for placement in placements:
        kind = placement.get("building")
        if kind not in NEW_BUILDINGS:
            continue
        if "zone" in placement:  # by zone: the engine picks the hex, as in the game
            place = find_place(trial, config, kind, placement["zone"])
            if place is None:
                problems.append(f"NO_SPACE: no room for a {kind} in zone '{placement['zone']}'")
                continue
        else:
            place = placement["x"], placement["y"]
            error = place_error(trial, config, kind, *place)
            if error:
                problems.append(f"{error[0]}: {error[1]}")
                continue
        trial.buildings.append(Building(kind, 0, trial.next_building_id, *place))
        trial.next_building_id += 1
    return {"parsed": True, "zone_problem": zone_problem, "placement_problems": problems, "zones": zones,
            "placements": placements, "reason": reply.get("reason", ""), "new_fields": new_fields,
            "trial": trial}


def report_lines(candidate: str, attempt: int, result: dict, config, tokens: int, seconds: float) -> list[str]:
    clean = result["parsed"] and result["zone_problem"] is None and not result["placement_problems"]
    lines = [f"\n--- {candidate} #{attempt} | {tokens} tok | {seconds:.1f} s | {'ok' if clean else 'FAIL'}"
             f" | new fields zone beyond the border: {'yes' if result['new_fields'] else 'NO'}"]
    if result["zone_problem"]:
        lines.append(f"    zones: {result['zone_problem']}")
    lines += [f"    placement: {p}" for p in result["placement_problems"]]
    lines.append(f"    reason: {result['reason']}")
    if result["parsed"]:
        lines.append("    zones: " + "; ".join(f"{z.name} ({z.purpose}) ({z.x1},{z.y1})-({z.x2},{z.y2})"
                                               for z in result["zones"]))
        lines.append("    placements: " + ", ".join(f"{p.get('building')} " + (f"in '{p['zone']}'" if "zone" in p
                                                     else f"({p.get('x')},{p.get('y')})")
                                                     for p in result["placements"]))
        lines.append(render(result["trial"], config))
    return lines


def main(argv: list[str]) -> None:
    repeat = 10
    if argv[:1] == ["--repeat"]:
        repeat, argv = int(argv[1]), argv[2:]
    by_zone = "--by-zone" in argv
    argv = [arg for arg in argv if arg != "--by-zone"]
    settings = load_settings()
    max_tokens, timeout = settings.max_output_tokens, settings.timeout_seconds
    if argv[:1] == ["--max-tokens"]:
        max_tokens, argv = int(argv[1]), argv[2:]
    if argv[:1] == ["--timeout"]:
        timeout, argv = int(argv[1]), argv[2:]
    candidates = argv or ["z-ai/glm-5.3-flash:high"]
    config = hex_config()
    state = new_game(config, SEED)
    client = OpenRouterClient(settings.base_url, os.environ.get("OPENROUTER_API_KEY", ""),
                              timeout, settings.prices, max_tokens,
                              settings.models_without_json_schema, settings.models_without_reasoning)
    user = town_text(state, config)
    out = ["# Map sent", user]
    for candidate in candidates:
        model, _, effort = candidate.partition(":")
        counts = {"zones": 0, "places": 0, "clean": 0, "fields": 0}
        cost = 0.0
        for attempt in range(1, repeat + 1):
            try:
                reply = client.complete("architect", model, system_prompt(by_zone), user, schema(by_zone), effort or None)
            except LLMError as error:
                out.append(f"\n--- {candidate} #{attempt} | ERROR {error.status}: {str(error)[:200]}")
                continue
            result = judge(state, config, reply.text)
            cost += reply.cost_usd
            zones_ok = result["parsed"] and result["zone_problem"] is None
            places_ok = result["parsed"] and not result["placement_problems"]
            counts["zones"] += zones_ok
            counts["places"] += places_ok
            counts["clean"] += zones_ok and places_ok
            counts["fields"] += result["new_fields"]
            out += report_lines(candidate, attempt, result, config, reply.output_tokens, reply.latency_ms / 1000)
            out.append(f"    reasoning ({len(reply.reasoning)} chars):\n{reply.reasoning}")
            print(f"{candidate} #{attempt}: zones {'ok' if zones_ok else 'FAIL'},"
                  f" placements {len(result['placement_problems'])} problems", file=sys.stderr, flush=True)
        out.insert(0, f"{candidate}: {repeat} runs | zones clean {counts['zones']} | placements clean"
                      f" {counts['places']} | all clean {counts['clean']} | fields zone beyond the border"
                      f" {counts['fields']} | ${cost:.4f}")
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
