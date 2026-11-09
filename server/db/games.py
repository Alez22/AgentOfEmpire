"""@brief Store games in PostgreSQL and resolve turns through the engine.

No game rules here: this module only moves data between the database and
the engine. All writes of a turn resolution happen in ONE transaction, so
a failure leaves the turn open and nothing half-written.
"""

from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from engine import ENGINE_VERSION, parse_order
from engine.bandits import BanditPool, new_pool, pool_from_dict, pool_to_dict, resolve_world
from engine.config import Config, config_from_dict
from engine.market import MarketState, RealmMonth, market_from_dict, market_to_dict, new_market, resolve_month
from engine.people import PeopleChoice
from engine.snapshot import FORMAT_VERSION, state_from_dict, state_to_dict
from engine.state import GameState, new_game
from server.council.persons import draw_council
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
    # Births and deaths are seen by everyone in a small town: court level,
    # so the Voice of the square (court clearance) knows them.
    "demography": "court",
    "food_spoiled": "council",
    "upkeep_unpaid": "council",
    "rule_workers_to_food": "council",
    "workers_rescaled": "council",
    "salaries_unpaid": "council",  # the counsellors know they were not paid
    "tile_cleared": "court",  # the people clear the land: everyone sees the town grow
    # The people feel the cold and see the walls crumble ([needs]). Court, not
    # public: other states must not learn a realm's land levels from them.
    "firewood_short": "court",
    "stone_upkeep_short": "court",
    # The realm's own trades (engine/market.py): known at court. Who trades
    # what is never public; the market's totals are (market state).
    "trade_bought": "court",
    "trade_on_sale": "court",
    "trade_paid": "court",
    "merchant_tax": "court",  # the merchants' own tax, paid with the trades (village block A)
    # A class's unrest is public like the peasants'; its mood never is.
    "class_unrest_changed": "public",
    # Village block B+C: families leaving are seen at court (the Voice tells
    # them); a raid is public like unrest. The pool's size is never shown.
    "flight": "court",
    "raid": "public",
}


# Offices that open during the game with a building, not at its start: the
# Gastaldo comes with the watchtower (server/council/meeting.py ensure_gastaldo).
LATE_ROLES = ("gastaldo",)


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
    personas: list[dict] | None = None,
    model_tiers: dict[str, str] | None = None,
) -> int:
    """@brief Create a game with its realms, councils, turn 1 and first snapshots.
    @param conn Connection in autocommit mode.
    @param raw_config Plain config data (engine.config.load_raw_config()); a copy
           is stored, so later tuning of config.toml never alters this game.
    @param seed Seed of the game.
    @param realm_names One realm per name (the prototype uses one).
    @param council_models Role -> model, e.g. {"chancellor": "...", "treasurer": "..."};
           the same council is created in every realm.
    @param personas The catalog (server/council/persons.py). If given, each
           realm's Treasurer, Architect and Chancellor are drawn from its
           moderates and bring their own name, gender, traits, story, model
           and salary; other roles (Voice, people) still use council_models.
    @param model_tiers Tier -> model id ([model_tiers] in council.toml);
           required with personas. The tier is kept with the person.
    @return The new game id.
    """
    config = config_from_dict(raw_config)  # fail before writing anything
    with conn.transaction():
        game_id = conn.execute(
            "INSERT INTO games (seed, config, engine_version) VALUES (%s, %s, %s) RETURNING id",
            (seed, Jsonb(raw_config), ENGINE_VERSION),
        ).fetchone()[0]
        taken: set[str] = set()
        for index, name in enumerate(realm_names):
            realm_id = conn.execute(
                "INSERT INTO realms (game_id, name) VALUES (%s, %s) RETURNING id", (game_id, name)
            ).fetchone()[0]
            council = draw_council(personas, seed, index, taken) if personas else {}
            # Each realm its own site, in a row from the one the seed picks
            # (a one-realm game keeps the site it had before).
            state = new_game(config, seed, site_index=seed + index)
            for role, model in council_models.items():
                if role in LATE_ROLES:
                    continue
                person = council.get(role)
                if person is None:
                    personality = {"traits": generate_traits(seed, realm_id, role)}
                else:
                    model = model_tiers[person["tier"]]
                    personality = {key: person[key] for key in
                                   ("traits", "name", "gender", "resume", "salary", "tier")} | {"persona": person["id"]}
                    state.council_salary += person["salary"]
                conn.execute(
                    "INSERT INTO actors (realm_id, role, model, personality) VALUES (%s, %s, %s, %s)",
                    (realm_id, role, model, Jsonb(personality)),
                )
            _insert_snapshot(conn, game_id, realm_id, state)
        if config.market is not None:
            _insert_market(conn, game_id, 1, new_market(config, len(realm_names)))
        pool = new_pool(config, seed, len(realm_names))
        if pool is not None:
            _insert_pool(conn, game_id, 1, pool)
        conn.execute("INSERT INTO turns (game_id, number) VALUES (%s, 1)", (game_id,))
    return game_id


def _insert_market(conn: psycopg.Connection, game_id: int, turn: int, market: MarketState) -> None:
    conn.execute("INSERT INTO market_states (game_id, turn, state) VALUES (%s, %s, %s)",
                 (game_id, turn, Jsonb(market_to_dict(market))))


def _insert_pool(conn: psycopg.Connection, game_id: int, turn: int, pool: BanditPool) -> None:
    conn.execute("INSERT INTO bandit_pools (game_id, turn, state) VALUES (%s, %s, %s)",
                 (game_id, turn, Jsonb(pool_to_dict(pool))))


def load_pool(conn: psycopg.Connection, game_id: int, turn: int) -> BanditPool | None:
    """@brief The bandits at the start of a turn; None for a game without them."""
    row = conn.execute("SELECT state FROM bandit_pools WHERE game_id = %s AND turn = %s",
                       (game_id, turn)).fetchone()
    return pool_from_dict(row[0]) if row else None


def load_market_history(conn: psycopg.Connection, game_id: int, last_turn: int,
                        months: int) -> list[tuple[int, MarketState]]:
    """@brief (turn, market at its start) for the last `months` turns up to
    last_turn, oldest first; empty for a game without a market."""
    rows = conn.execute(
        "SELECT turn, state FROM market_states WHERE game_id = %s AND turn > %s AND turn <= %s ORDER BY turn",
        (game_id, last_turn - months, last_turn)).fetchall()
    return [(turn, market_from_dict(state)) for turn, state in rows]


def load_market(conn: psycopg.Connection, game_id: int, turn: int) -> MarketState | None:
    """@brief The warehouse at the start of a turn; None for a game without a market."""
    row = conn.execute("SELECT state FROM market_states WHERE game_id = %s AND turn = %s",
                       (game_id, turn)).fetchone()
    return market_from_dict(row[0]) if row else None


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


def role_names(conn: psycopg.Connection, realm_id: int) -> dict[str, str]:
    """@brief Role -> how the game calls its holder in this realm, for pages
    ("Gisella da Valle, l'Architetta"; the bare title for older games)."""
    from server.council.persons import display_name  # persons is a leaf module
    return {role: display_name(role, personality) for role, personality in conn.execute(
        "SELECT role, personality FROM actors WHERE realm_id = %s", (realm_id,))}


def load_people_choice(conn: psycopg.Connection, realm_id: int, turn: int) -> PeopleChoice | None:
    """@brief What the people decided for this turn, as the engine needs it.
    A petition left unanswered counts as refused. None if nobody decided
    (no meeting held, or a game created before the people decided)."""
    row = conn.execute(
        "SELECT d.effort_pct, d.birth_pct, d.petition IS NOT NULL, a.answer, d.petition_weight"
        " FROM people_decisions d LEFT JOIN petition_answers a ON a.decision_id = d.id"
        " WHERE d.realm_id = %s AND d.turn = %s",
        (realm_id, turn),
    ).fetchone()
    if row is None:
        return None
    effort_pct, birth_pct, has_petition, answer, weight = row
    petition = (answer or "refused") if has_petition else None
    return PeopleChoice(effort_pct, birth_pct, petition, weight)


def _load_realm_month(conn, realm_id: int, turn: int) -> tuple[RealmMonth, list] | None:
    """@brief A realm's input to the month, with its parsed orders' ids; the
    orders the parser refused are stored as refused at once.
    @return None if this realm's game is already over.
    """
    state = load_latest_state(conn, realm_id)
    if state.game_over:
        return None  # nothing left to simulate for this realm
    if state.turn != turn:
        raise RuntimeError(f"realm {realm_id}: latest snapshot is turn {state.turn}, not {turn}")
    parsed, rejected = load_parsed_orders(conn, realm_id, turn)
    for order_id, code, message in rejected:
        _insert_order_result(conn, order_id, False, code, message)
    month = RealmMonth(state, [order for _, order in parsed], load_people_choice(conn, realm_id, turn))
    return month, parsed


def _store_realm_result(conn, game_id: int, realm_id: int, turn: int, parsed: list, result) -> bool:
    """@brief Store what one realm's month produced.
    @return True if this realm's game is now over.
    """
    # The engine returns verdicts in its own evaluation order (trades, then by
    # priority); match them back to the stored rows through the order objects.
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
        months, parsed_by_realm = {}, {}
        for realm_id in realm_ids:
            loaded = _load_realm_month(conn, realm_id, turn)
            if loaded is not None:
                months[str(realm_id)], parsed_by_realm[str(realm_id)] = loaded
        # The market and every realm together (engine/market.py); a game
        # without a market resolves each realm alone, as before.
        market, results = resolve_month(load_market(conn, game_id, turn), months, config)
        # The world step (engine/bandits.py): flight and raids change the
        # realms' new states before they are stored.
        pool = resolve_world(load_pool(conn, game_id, turn), results, config, turn)
        realms_over = [True] * (len(realm_ids) - len(months))  # those already over
        for key, result in results.items():
            realms_over.append(_store_realm_result(conn, game_id, int(key), turn, parsed_by_realm[key], result))
        if market is not None:
            _insert_market(conn, game_id, turn + 1, market)
        if pool is not None:
            _insert_pool(conn, game_id, turn + 1, pool)

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
