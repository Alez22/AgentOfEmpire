"""@brief Store games in PostgreSQL and resolve turns through the engine.

No game rules here: this module only moves data between the database and
the engine. All writes of a turn resolution happen in ONE transaction, so
a failure leaves the turn open and nothing half-written.
"""

from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from engine import ENGINE_VERSION, parse_order, resolve_turn
from engine.config import Config, config_from_dict
from engine.snapshot import FORMAT_VERSION, state_from_dict, state_to_dict
from engine.state import GameState, new_game
from server.council.personality import generate_traits
from server.db.access import Clearance, agent_context

# Who may see each engine event (approved table in the design doc).
# An event kind missing here stops the resolution on purpose: every new
# event needs an explicit decision about its audience.
EVENT_VISIBILITY = {
    "famine": "public",
    "unrest_changed": "public",
    "game_over": "public",
    "building_completed": "court",
    "season_end": "court",
    "demography": "council",
    "food_spoiled": "council",
    "upkeep_unpaid": "council",
    "rule_workers_to_food": "council",
    "workers_rescaled": "council",
}


class TurnClosedError(Exception):
    """An order arrived for a game with no open turn."""


class NoOpenTurnError(Exception):
    """resolve_open_turn() found nothing to resolve."""


class UnknownEventKindError(Exception):
    """The engine produced an event with no entry in EVENT_VISIBILITY."""


class GamePausedError(Exception):
    """Turns are not resolved while a game is paused (e.g. holidays)."""


class EngineVersionError(Exception):
    """The game was started with another engine version: results could differ."""


@dataclass
class TurnSummary:
    turn: int  # the turn that was resolved
    game_finished: bool


def is_season_end_snapshot(state: GameState) -> bool:
    """@brief True for the state right after turns 3, 6, 9, ... (end of a season)."""
    return state.turn > 1 and (state.turn - 1) % 3 == 0


def _insert_snapshot(conn: psycopg.Connection, game_id: int, realm_id: int, state: GameState) -> None:
    conn.execute(
        "INSERT INTO snapshots"
        " (game_id, realm_id, turn, is_season_end, format_version, engine_version, state)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            game_id,
            realm_id,
            state.turn,
            is_season_end_snapshot(state),
            FORMAT_VERSION,
            ENGINE_VERSION,
            Jsonb(state_to_dict(state)),
        ),
    )


def create_game(
    conn: psycopg.Connection,
    raw_config: dict,
    seed: int,
    realm_names: list[str],
    council_models: dict[str, str],
) -> int:
    """@brief Create a game with its realms, councils, turn 1 and first snapshots.
    @param conn Connection in autocommit mode.
    @param raw_config Plain config data (engine.config.load_raw_config()); a copy
           is stored, so later tuning of config.toml never alters this game.
    @param seed Seed of the game.
    @param realm_names One realm per name (the prototype uses one).
    @param council_models Role -> model, e.g. {"chancellor": "...", "treasurer": "..."};
           the same council is created in every realm.
    @return The new game id.
    """
    config = config_from_dict(raw_config)  # fail before writing anything
    with conn.transaction():
        game_id = conn.execute(
            "INSERT INTO games (seed, config, engine_version) VALUES (%s, %s, %s) RETURNING id",
            (seed, Jsonb(raw_config), ENGINE_VERSION),
        ).fetchone()[0]
        for name in realm_names:
            realm_id = conn.execute(
                "INSERT INTO realms (game_id, name) VALUES (%s, %s) RETURNING id", (game_id, name)
            ).fetchone()[0]
            for role, model in council_models.items():
                personality = {"traits": generate_traits(seed, realm_id, role)}
                conn.execute(
                    "INSERT INTO actors (realm_id, role, model, personality) VALUES (%s, %s, %s, %s)",
                    (realm_id, role, model, Jsonb(personality)),
                )
            _insert_snapshot(conn, game_id, realm_id, new_game(config, seed))
        conn.execute("INSERT INTO turns (game_id, number) VALUES (%s, 1)", (game_id,))
    return game_id


def submit_order(
    conn: psycopg.Connection,
    realm_id: int,
    raw_order: object,
    priority: int = 0,
    actor_id: int | None = None,
) -> int:
    """@brief Store an order exactly as received; it is parsed at resolution.
    @param raw_order Decoded JSON, even malformed: the raw text is the debug trace.
    @param priority Lower runs first; this column wins over any "priority" in the JSON.
    @param actor_id Issuing minister, None for the sovereign.
    @return The order id.
    @throws TurnClosedError if the realm's game has no open turn.
    """
    with conn.transaction():
        # FOR SHARE waits for a resolution in progress; after it commits the
        # turn is no longer open and the order is refused.
        row = conn.execute(
            "SELECT t.game_id, t.number FROM turns t JOIN realms r ON r.game_id = t.game_id"
            " WHERE r.id = %s AND t.status = 'open' FOR SHARE OF t",
            (realm_id,),
        ).fetchone()
        if row is None:
            raise TurnClosedError(f"no open turn for realm {realm_id}")
        game_id, turn = row
        return conn.execute(
            "INSERT INTO orders (game_id, realm_id, turn, issued_by_actor_id, raw, priority)"
            " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (game_id, realm_id, turn, actor_id, Jsonb(raw_order), priority),
        ).fetchone()[0]


def load_parsed_orders(conn: psycopg.Connection, realm_id: int, turn: int) -> tuple[list, list]:
    """@brief Parse the stored orders of one realm and turn, in submission order.
    @return (accepted_by_parser, rejected) where accepted_by_parser is a list of
            (order_id, order) and rejected a list of (order_id, code, message).
    """
    rows = conn.execute(
        "SELECT id, raw, priority FROM orders WHERE realm_id = %s AND turn = %s ORDER BY id",
        (realm_id, turn),
    ).fetchall()
    parsed, rejected = [], []
    for order_id, raw_order, priority in rows:
        order, code, message = parse_order(raw_order)
        if order is None:
            rejected.append((order_id, code, message))
            continue
        parsed.append((order_id, order.model_copy(update={"priority": priority})))
    return parsed, rejected


def load_latest_state(conn: psycopg.Connection, realm_id: int) -> GameState | None:
    """@brief Most recent snapshot of a realm, None if the realm does not exist."""
    row = conn.execute(
        "SELECT state FROM snapshots WHERE realm_id = %s ORDER BY turn DESC LIMIT 1", (realm_id,)
    ).fetchone()
    return state_from_dict(row[0]) if row else None


def load_game_config(conn: psycopg.Connection, game_id: int) -> Config:
    """@brief The config copy stored with the game (not the current config.toml)."""
    raw_config = conn.execute("SELECT config FROM games WHERE id = %s", (game_id,)).fetchone()[0]
    return config_from_dict(raw_config)


def realm_game_id(conn: psycopg.Connection, realm_id: int) -> int | None:
    row = conn.execute("SELECT game_id FROM realms WHERE id = %s", (realm_id,)).fetchone()
    return row[0] if row else None


def load_game(conn: psycopg.Connection, game_id: int) -> dict | None:
    """@brief Game header, its open turn (None if finished) and its realms."""
    row = conn.execute(
        "SELECT id, seed, status::text, engine_version, created_at FROM games WHERE id = %s",
        (game_id,),
    ).fetchone()
    if row is None:
        return None
    open_turn = conn.execute(
        "SELECT number FROM turns WHERE game_id = %s AND status = 'open'", (game_id,)
    ).fetchone()
    realms = conn.execute(
        "SELECT id, name, player_id FROM realms WHERE game_id = %s ORDER BY id", (game_id,)
    ).fetchall()
    return {
        "id": row[0],
        "seed": row[1],
        "status": row[2],
        "engine_version": row[3],
        "created_at": row[4],
        "open_turn": open_turn[0] if open_turn else None,
        "realms": [{"id": r[0], "name": r[1], "player_id": r[2]} for r in realms],
    }


def list_orders(conn: psycopg.Connection, realm_id: int, turn: int) -> list[dict]:
    """@brief Orders of one turn with their verdict (None while the turn is open)."""
    rows = conn.execute(
        "SELECT o.id, o.raw, o.priority, o.issued_by_actor_id, o.submitted_at,"
        " r.accepted, r.rejection_code, r.message"
        " FROM orders o LEFT JOIN order_results r ON r.order_id = o.id"
        " WHERE o.realm_id = %s AND o.turn = %s ORDER BY o.id",
        (realm_id, turn),
    ).fetchall()
    keys = ("id", "raw", "priority", "issued_by_actor_id", "submitted_at",
            "accepted", "rejection_code", "message")
    return [dict(zip(keys, row)) for row in rows]


def list_events_for_sovereign(
    conn: psycopg.Connection, game_id: int, realm_id: int, turn: int
) -> list[dict]:
    """@brief Events of one turn as the realm's sovereign may see them.
    Read through agent_context, so the same row-level security that filters
    the agents filters the player too (public events of other realms included).
    """
    return list_visible_events(conn, game_id, realm_id, turn, Clearance.SOVEREIGN)


def list_visible_events(
    conn: psycopg.Connection, game_id: int, realm_id: int, turn: int, clearance: Clearance
) -> list[dict]:
    """@brief Events of one turn filtered by row-level security for a reader grade."""
    with agent_context(conn, game_id, realm_id, clearance) as reader:
        rows = reader.execute(
            "SELECT id, realm_id, turn, kind, data, visibility::text FROM events"
            " WHERE turn = %s ORDER BY id",
            (turn,),
        ).fetchall()
    keys = ("id", "realm_id", "turn", "kind", "data", "visibility")
    return [dict(zip(keys, row)) for row in rows]


def _insert_order_result(conn, order_id: int, accepted: bool, code: str | None, message: str) -> None:
    conn.execute(
        "INSERT INTO order_results (order_id, accepted, rejection_code, message)"
        " VALUES (%s, %s, %s, %s)",
        (order_id, accepted, code, message),
    )


def _insert_events(conn, game_id: int, realm_id: int, turn: int, events) -> None:
    for event in events:
        visibility = EVENT_VISIBILITY.get(event.kind)
        if visibility is None:
            raise UnknownEventKindError(f"no visibility decided for event '{event.kind}'")
        conn.execute(
            "INSERT INTO events (game_id, realm_id, turn, kind, data, visibility)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (game_id, realm_id, turn, event.kind, Jsonb(event.data), visibility),
        )


def _resolve_realm(conn, game_id: int, realm_id: int, turn: int, config) -> bool:
    """@brief Resolve one realm and store everything it produced.
    @return True if this realm's game is over (now or already before).
    """
    state = load_latest_state(conn, realm_id)
    if state.game_over:
        return True  # nothing left to simulate for this realm
    if state.turn != turn:
        raise RuntimeError(f"realm {realm_id}: latest snapshot is turn {state.turn}, not {turn}")
    parsed, rejected = load_parsed_orders(conn, realm_id, turn)
    for order_id, code, message in rejected:
        _insert_order_result(conn, order_id, False, code, message)
    result = resolve_turn(state, [order for _, order in parsed], config)
    # The engine returns verdicts in its own evaluation order (by priority);
    # match them back to the stored rows through the order objects themselves.
    order_id_by_object = {id(order): order_id for order_id, order in parsed}
    for verdict in result.order_results:
        _insert_order_result(
            conn, order_id_by_object[id(verdict.order)], verdict.accepted, verdict.code, verdict.message
        )
    _insert_events(conn, game_id, realm_id, turn, result.events)
    _insert_snapshot(conn, game_id, realm_id, result.state)
    return result.state.game_over is not None


def resolve_open_turn(conn: psycopg.Connection, game_id: int) -> TurnSummary:
    """@brief Resolve the open turn of a game for every realm, in one transaction.
    @param conn Connection in autocommit mode.
    @return Which turn was resolved and whether the game is now finished.
    @throws NoOpenTurnError, GamePausedError, EngineVersionError, UnknownEventKindError
    """
    if not conn.autocommit:
        raise ValueError("resolve_open_turn needs an autocommit connection")
    with conn.transaction():
        # FOR UPDATE: a second resolution of the same turn waits here, then
        # finds the turn already resolved and stops.
        row = conn.execute(
            "SELECT number FROM turns WHERE game_id = %s AND status = 'open' FOR UPDATE",
            (game_id,),
        ).fetchone()
        if row is None:
            raise NoOpenTurnError(f"game {game_id} has no open turn")
        turn = row[0]
        raw_config, engine_version, status = conn.execute(
            "SELECT config, engine_version, status FROM games WHERE id = %s", (game_id,)
        ).fetchone()
        if status == "paused":
            raise GamePausedError(f"game {game_id} is paused")
        if engine_version != ENGINE_VERSION:
            raise EngineVersionError(
                f"game {game_id} uses engine {engine_version}, this server runs {ENGINE_VERSION}"
            )
        config = config_from_dict(raw_config)
        realm_ids = [r[0] for r in conn.execute(
            "SELECT id FROM realms WHERE game_id = %s ORDER BY id", (game_id,)
        )]
        realms_over = [_resolve_realm(conn, game_id, realm_id, turn, config) for realm_id in realm_ids]

        conn.execute(
            "UPDATE turns SET status = 'resolved', resolved_at = now()"
            " WHERE game_id = %s AND number = %s",
            (game_id, turn),
        )
        # Prototype rule: the game ends when no realm is left playing.
        game_finished = all(realms_over)
        if game_finished:
            conn.execute("UPDATE games SET status = 'finished' WHERE id = %s", (game_id,))
        else:
            conn.execute("INSERT INTO turns (game_id, number) VALUES (%s, %s)", (game_id, turn + 1))
    return TurnSummary(turn, game_finished)
