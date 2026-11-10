"""@brief Re-run a stored game from its first snapshot and compare every turn.

The whole game is replayed month by month (engine/market.py resolve_month),
because realms trading at the common market depend on each other. If a
replayed state differs from the stored snapshot, the engine is no
longer deterministic (or a rule changed without bumping ENGINE_VERSION,
or the data was altered).
"""

import json
from dataclasses import dataclass

import psycopg

from engine.bandits import pool_from_dict, pool_to_dict, resolve_world
from engine.config import config_from_dict
from engine.market import RealmMonth, market_from_dict, market_to_dict, resolve_month
from engine.snapshot import state_from_dict, state_to_json
from server.db.games import load_parsed_orders, load_people_choice


@dataclass
class ReplayMismatch:
    realm_id: int | None  # None: the market's or the bandits' state differs
    turn: int  # first snapshot turn whose stored state differs from the replay
    stored: str  # canonical JSON
    replayed: str


def _canonical(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _stored_states(conn: psycopg.Connection, realm_ids: list[int]) -> dict[int, dict[int, dict]]:
    """@brief {realm id: {turn: snapshot state}} of every realm."""
    return {realm_id: dict(conn.execute(
        "SELECT turn, state FROM snapshots WHERE realm_id = %s ORDER BY turn", (realm_id,)).fetchall())
        for realm_id in realm_ids}


def _replay_month(conn, config, market, pool, states, stored, turn):
    """@brief Replay one month of the game and compare it with what is stored.
    @return (market, bandits after the month, mismatch or None). states is updated."""
    months = {str(realm_id): RealmMonth(
        state, [order for _, order in load_parsed_orders(conn, realm_id, turn)[0]],
        load_people_choice(conn, realm_id, turn))
        for realm_id, state in states.items() if turn + 1 in stored[realm_id]}
    market, results = resolve_month(market, months, config)
    pool = resolve_world(pool, results, config, turn)
    for key, result in results.items():
        realm_id = int(key)
        states[realm_id] = result.state
        stored_json = state_to_json(state_from_dict(stored[realm_id][turn + 1]))
        replayed_json = state_to_json(result.state)
        if stored_json != replayed_json:
            return market, pool, ReplayMismatch(realm_id, turn + 1, stored_json, replayed_json)
    return market, pool, None


def replay_game(conn: psycopg.Connection, game_id: int) -> ReplayMismatch | None:
    """@brief Replay a game month by month with its stored config and orders:
    the market and every realm together, as the turns were resolved.
    @return None if every snapshot and market state matches, otherwise the
            first mismatch.
    @throws ValueError if the game does not exist.
    """
    row = conn.execute("SELECT config FROM games WHERE id = %s", (game_id,)).fetchone()
    if row is None:
        raise ValueError(f"game {game_id} does not exist")
    config = config_from_dict(row[0])
    realm_ids = [r[0] for r in conn.execute(
        "SELECT id FROM realms WHERE game_id = %s ORDER BY id", (game_id,)
    )]
    stored = _stored_states(conn, realm_ids)
    markets = dict(conn.execute(
        "SELECT turn, state FROM market_states WHERE game_id = %s", (game_id,)).fetchall())
    states = {realm_id: state_from_dict(stored[realm_id][1]) for realm_id in realm_ids}
    market = market_from_dict(markets[1]) if 1 in markets else None
    pools = dict(conn.execute(
        "SELECT turn, state FROM bandit_pools WHERE game_id = %s", (game_id,)).fetchall())
    pool = pool_from_dict(pools[1]) if 1 in pools else None
    last_turn = max(max(turns) for turns in stored.values())
    for turn in range(1, last_turn):
        market, pool, mismatch = _replay_month(conn, config, market, pool, states, stored, turn)
        if mismatch:
            return mismatch
        if pool is not None and turn + 1 in pools:
            # Through the dataclass, as the states: a pool stored before a new
            # field compares with its default.
            stored_pool = _canonical(pool_to_dict(pool_from_dict(pools[turn + 1])))
            replayed_pool = _canonical(pool_to_dict(pool))
            if stored_pool != replayed_pool:
                return ReplayMismatch(None, turn + 1, stored_pool, replayed_pool)
        if market is not None and turn + 1 in markets:
            stored_market = _canonical(markets[turn + 1])
            replayed_market = _canonical(market_to_dict(market))
            if stored_market != replayed_market:
                return ReplayMismatch(None, turn + 1, stored_market, replayed_market)
    return None
