"""@brief Convert a GameState to and from plain JSON data for snapshots.

FORMAT_VERSION must go up whenever GameState changes shape; old snapshots
then need a conversion function, otherwise old games cannot be reloaded.
"""

import json
from dataclasses import asdict

from engine.state import Building, GameState, Workers, Zone

# 2: the territory (map rows, zones, square, building ids and places). Format 1
# snapshots still load: the new fields have defaults (no map).
# 3: land_levels (hidden levels of the site). Older snapshots load with none.
FORMAT_VERSION = 3


def state_to_dict(state: GameState) -> dict:
    """@brief Plain dict (only JSON types) of the whole state."""
    return asdict(state)


def state_from_dict(data: dict) -> GameState:
    """@brief Rebuild a GameState from state_to_dict() output.
    @throws TypeError on missing or unknown keys (format mismatch).
    """
    fields = dict(data)
    fields["workers"] = Workers(**fields["workers"])
    fields["buildings"] = [Building(**building) for building in fields["buildings"]]
    fields["zones"] = [Zone(**zone) for zone in fields.get("zones", [])]
    return GameState(**fields)


def state_to_json(state: GameState) -> str:
    """@brief Canonical JSON text: sorted keys, so equal states give equal text."""
    return json.dumps(state_to_dict(state), sort_keys=True, separators=(",", ":"))


def state_from_json(text: str) -> GameState:
    return state_from_dict(json.loads(text))
