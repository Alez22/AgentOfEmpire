"""@brief Re-run a stored game from its first snapshot and compare every turn.

If a replayed state differs from the stored snapshot, the engine is no
longer deterministic (or a rule changed without bumping ENGINE_VERSION,
or the data was altered).
"""

from dataclasses import dataclass

import psycopg

from engine import resolve_turn
from engine.config import config_from_dict
from engine.snapshot import state_from_dict, state_to_json
from server.db.games import load_parsed_orders, load_people_choice


@dataclass
class ReplayMismatch:
    realm_id: int
    turn: int  # first snapshot turn whose stored state differs from the replay
    stored: str  # canonical JSON
    replayed: str


def _replay_realm(conn: psycopg.Connection, realm_id: int, config) -> ReplayMismatch | None:
    snapshots = conn.execute(
        "SELECT turn, state FROM snapshots WHERE realm_id = %s ORDER BY turn", (realm_id,)
    ).fetchall()
    state = state_from_dict(snapshots[0][1])
    for turn, stored_state in snapshots[1:]:
        parsed, _ = load_parsed_orders(conn, realm_id, turn - 1)
        people = load_people_choice(conn, realm_id, turn - 1)
        state = resolve_turn(state, [order for _, order in parsed], config, people).state
        stored_json = state_to_json(state_from_dict(stored_state))
        replayed_json = state_to_json(state)
        if stored_json != replayed_json:
            return ReplayMismatch(realm_id, turn, stored_json, replayed_json)
    return None


def replay_game(conn: psycopg.Connection, game_id: int) -> ReplayMismatch | None:
    """@brief Replay every realm of a game with its stored config and orders.
    @return None if every snapshot matches, otherwise the first mismatch.
    @throws ValueError if the game does not exist.
    """
    row = conn.execute("SELECT config FROM games WHERE id = %s", (game_id,)).fetchone()
    if row is None:
        raise ValueError(f"game {game_id} does not exist")
    config = config_from_dict(row[0])
    realm_ids = [r[0] for r in conn.execute(
        "SELECT id FROM realms WHERE game_id = %s ORDER BY id", (game_id,)
    )]
    for realm_id in realm_ids:
        mismatch = _replay_realm(conn, realm_id, config)
        if mismatch:
            return mismatch
    return None
