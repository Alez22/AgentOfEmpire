"""@brief The month's marks on the realm's map (docs/DESIGN.md, "The map as
the realm's first page", C): what happened last month, drawn where it happened.

Pure functions over what the sovereign may already see: their own realm's
events of the last month and their own two snapshots. Nothing from other
realms is read, so a mark can never leak a neighbour's land or state.

A mark is a dict with world coordinates; the board turns them into SVG
units (server/ui/hex_board.py, place_marks).
"""

from engine.territory import NOT_OWNED, TERRAIN_CHARS, hex_distance, square_tiles
from server.ui import labels
from server.ui.map_view import KIND_IT


def _mark(mark_id: str, glyph: str, tone: str, tile: tuple[int, int], text: str, event: int | None = None) -> dict:
    """@param glyph Symbol id in the page (band, shield, arrive, hammer, star, cart, flag, stump, flight).
    @param tone danger, ok or new: the pin's colour.
    @param event Index of the event in the month's list, so the sheet can point at the mark."""
    return {"id": mark_id, "glyph": glyph, "tone": tone, "x": tile[0], "y": tile[1], "text": text, "event": event,
            "dx": 0, "dy": 0, "from": None}


def _owned_tiles(state) -> list[tuple[int, int]]:
    return [(x, y) for y, row in enumerate(state.owned) for x, char in enumerate(row) if char != NOT_OWNED]


def _gate(state, band: tuple[int, int]) -> tuple[int, int]:
    """@brief The realm's hex nearest a band: where it came to the walls.
    Ties by (y, x), so the choice is stable."""
    return min(_owned_tiles(state), key=lambda t: (hex_distance(t[0], t[1], band[0], band[1]), t[1], t[0]))


def _anchor(building) -> tuple[int, int]:
    return building.x, building.y


def _newest(state, kind: str):
    """@brief The newest finished building of a kind: building_completed has no id."""
    finished = [b for b in state.buildings if b.kind == kind and b.turns_left == 0]
    return max(finished, key=lambda b: b.id) if finished else None


def _event_marks(events: list[dict], state, square: tuple[int, int]) -> list[dict]:
    """@brief One mark per event that has a place; the others stay lines in the sheet."""
    band = next(((e["data"]["x"], e["data"]["y"]) for e in events if e["kind"] == "band_seen"), None)
    gate = _gate(state, band) if band is not None else square
    market = _newest(state, "market")
    by_id = {b.id: b for b in state.buildings}
    marks = []
    for index, event in enumerate(events):
        kind, data, text = event["kind"], event["data"], labels.event_label(event["kind"], event["data"])
        if kind == "band_seen":
            marks.append(_mark(f"e{index}", "band", "danger", (data["x"], data["y"]), text, index))
        elif kind == "raid":
            mark = _mark(f"e{index}", "shield" if data.get("repelled") else "band",
                         "ok" if data.get("repelled") else "danger", gate, text, index)
            mark.update(dy=6, **{"from": band})
            marks.append(mark)
        elif kind == "arrival":
            marks.append({**_mark(f"e{index}", "arrive", "new", gate, text, index), "dx": -30, "dy": -8})
        elif kind == "flight":
            marks.append({**_mark(f"e{index}", "flight", "danger", square, text, index), "dx": 22, "dy": -18})
        elif kind == "building_completed" and _newest(state, data.get("kind")) is not None:
            marks.append(_mark(f"e{index}", "star", "new", _anchor(_newest(state, data["kind"])), text, index))
        elif kind == "tools_finished" and data.get("id") in by_id:
            marks.append({**_mark(f"e{index}", "hammer", "new", _anchor(by_id[data["id"]]), text, index), "dx": 16})
        elif kind in ("caravan_arrived", "caravan_robbed"):
            # On the market the caravans leave from (the road itself needs the
            # other realms' land: never read here), else on the square.
            place = _anchor(market) if market is not None else square
            tone = "danger" if kind == "caravan_robbed" else "new"
            marks.append({**_mark(f"e{index}", "cart", tone, place, text, index), "dx": -18, "dy": -16})
    return marks


def _site_marks(state) -> list[dict]:
    """@brief A hammer on every building site, with the months left."""
    marks = []
    for building in state.buildings:
        if building.turns_left > 0:
            months = "1 mese" if building.turns_left == 1 else f"{building.turns_left} mesi"
            text = f"{KIND_IT.get(building.kind, building.kind)} in costruzione: manca {months}."
            marks.append({**_mark(f"s{building.id}", "hammer", "new", _anchor(building), text), "dx": 16, "dy": -16})
    return marks


def land_changes(state, before) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """@brief (claimed, felled) hexes since the previous snapshot: land that
    became the realm's, and forest of the realm turned to plain."""
    if before is None or not before.owned:
        return [], []
    claimed, felled = [], []
    forest, plain = TERRAIN_CHARS["forest"], TERRAIN_CHARS["plain"]
    for y, row in enumerate(state.owned):
        for x, char in enumerate(row):
            if char == NOT_OWNED:
                continue
            if before.owned[y][x] == NOT_OWNED:
                claimed.append((x, y))
            if before.terrain[y][x] == forest and state.terrain[y][x] == plain:
                felled.append((x, y))
    return claimed, felled


def month_marks(events: list[dict], state, before, config) -> dict:
    """@brief Everything the board draws for last month.
    @param events The sovereign's own events of last month, in order.
    @param before The snapshot a month earlier, or None in the first month.
    @return {"marks", "claimed", "felled"}: marks in world coordinates.
    """
    square = square_tiles(state, config)[0]
    marks = _event_marks(events, state, square) + _site_marks(state)
    claimed, felled = land_changes(state, before)
    if claimed:
        count = len(claimed)
        text = f"Il regno si è allargato di {count} {'casella' if count == 1 else 'caselle'}."
        marks.append(_mark("claimed", "flag", "new", claimed[0], text))
    if felled:
        count = len(felled)
        text = f"Abbattut{'a' if count == 1 else 'e'} {count} {'casella' if count == 1 else 'caselle'} di bosco."
        marks.append({**_mark("felled", "stump", "new", felled[0], text), "dy": -16})
    return {"marks": marks, "claimed": claimed, "felled": felled}
