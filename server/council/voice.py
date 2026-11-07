"""@brief The Voice of the square: what the people say, told before every
council meeting. The sovereign has no mood number: this voice and the
council members are how the people are known.

The voice knows the exact numbers but must never say them, and it gives
more weight to what just happened than to slow trends (approved design:
it may exaggerate after a shock and miss a slow change).
"""

import psycopg
from psycopg.types.json import Jsonb

from server.council.briefing import MONTHS
from server.council.memory import order_text
from server.council.meeting import (
    Actor,
    MeetingContext,
    ask_text,
    insert_message,
    is_reflection_turn,
    render_prompt,
)
from server.db import games
from server.db.access import Clearance

VOICE_ROLE = "square_voice"
MAX_VOICE_CHARS = 1200
MONTHLY_RULE = "Say it in two or three sentences, at most 60 words."
SEASON_RULE = ("A season has just ended: tell how the people lived it, month after month, "
               "in at most 150 words.")
# Engine events the people would talk about (routine bookkeeping left out).
TOLD_EVENTS = ("famine", "unrest_changed", "building_completed", "demography", "upkeep_unpaid",
               "game_over", "audience")


def ensure_voice_actor(ctx: MeetingContext) -> Actor | None:
    """@brief Games created before the voice existed get it at their next
    meeting, with the model of council.toml. None if no model is configured."""
    if VOICE_ROLE in ctx.actors:
        return ctx.actors[VOICE_ROLE]
    model = ctx.settings.models.get(VOICE_ROLE)
    if model is None:
        return None
    actor_id = ctx.conn.execute(
        "INSERT INTO actors (realm_id, role, model, personality) VALUES (%s, %s, %s, %s) RETURNING id",
        (ctx.realm_id, VOICE_ROLE, model, Jsonb({})),
    ).fetchone()[0]
    ctx.actors[VOICE_ROLE] = Actor(actor_id, VOICE_ROLE, model, {})
    return ctx.actors[VOICE_ROLE]


def _mood_series(conn: psycopg.Connection, realm_id: int, first_turn: int, last_turn: int) -> str:
    rows = conn.execute(
        "SELECT turn, (state->>'mood')::int FROM snapshots WHERE realm_id = %s"
        " AND turn >= %s AND turn <= %s ORDER BY turn",
        (realm_id, first_turn, last_turn),
    ).fetchall()
    return ", ".join(f"{MONTHS[(turn - 1) % 12]} {mood}" for turn, mood in rows)


def _carried_out(conn: psycopg.Connection, realm_id: int, first_turn: int, last_turn: int) -> list[str]:
    rows = conn.execute(
        "SELECT o.turn, o.raw FROM orders o JOIN order_results r ON r.order_id = o.id"
        " WHERE o.realm_id = %s AND o.turn >= %s AND o.turn <= %s AND r.accepted ORDER BY o.id",
        (realm_id, first_turn, last_turn),
    ).fetchall()
    return [f"{order_text(raw)} ({MONTHS[(turn - 1) % 12]})" for turn, raw in rows]


def _told_events(ctx: MeetingContext, first_turn: int, last_turn: int) -> list[str]:
    told = []
    for turn in range(max(1, first_turn), last_turn + 1):
        for event in games.list_visible_events(ctx.conn, ctx.game_id, ctx.realm_id, turn, Clearance.COUNCIL):
            if event["realm_id"] == ctx.realm_id and event["kind"] in TOLD_EVENTS:
                told.append(f"{event['kind']} {event['data']} ({MONTHS[(turn - 1) % 12]})")
    return told


def facts_for_the_square(ctx: MeetingContext, season: bool) -> str:
    """@brief What the people live through, with exact numbers the voice must
    turn into words. A season covers the three months just ended."""
    state = ctx.state
    months_back = 3 if season else 1
    first_turn = ctx.turn - months_back
    population = state.children + state.adults + state.elders
    food_per_person = state.food // population if population else 0
    lines = [
        f"# The square of {ctx.realm_name}, {MONTHS[(ctx.turn - 1) % 12]}",
        "- Mood of the peasants (0-1000; NEVER say these numbers), oldest first: "
        + _mood_series(ctx.conn, ctx.realm_id, ctx.turn - 2 - (2 if season else 0), ctx.turn) + ".",
        f"- Unrest: {state.unrest}; months in a row of deep discontent: {state.low_mood_turns}.",
        f"- Food in the granaries per person: {food_per_person} (each eats about 8 to 10 a month). "
        f"Ration: {state.ration}. Taxes: {state.tax_rate}%.",
        f"- People: {state.children} children, {state.adults} adults, {state.elders} elders.",
    ]
    events = _told_events(ctx, first_turn, ctx.turn - 1)
    lines.append("- What happened: " + ("; ".join(events) if events else "nothing remarkable") + ".")
    orders = _carried_out(ctx.conn, ctx.realm_id, first_turn, ctx.turn - 1)
    lines.append("- Decisions of the crown carried out: " + ("; ".join(orders) if orders else "none") + ".")
    return "\n".join(lines)


def speak_in_square(ctx: MeetingContext) -> str:
    """@brief Store this turn's voice as a court-level council message.
    @return The text, or "" if the voice did not speak (the meeting goes on).
    """
    actor = ensure_voice_actor(ctx)
    if actor is None:
        return ""
    season = is_reflection_turn(ctx.turn)
    system = render_prompt(
        "voice_system.txt",
        realm_name=ctx.realm_name,
        language=ctx.settings.language,
        length_rule=SEASON_RULE if season else MONTHLY_RULE,
    )
    text = ask_text(ctx, actor, system, facts_for_the_square(ctx, season), MAX_VOICE_CHARS)
    if text:
        insert_message(ctx, 1, "voice", actor, text, {"season": season}, visibility="court")
    return text
