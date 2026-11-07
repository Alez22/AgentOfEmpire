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
# Engine events the people would talk about. The voice reads them with COURT
# clearance, so council-only bookkeeping (upkeep, spoilage, rescaled
# workers) never reaches the square even if listed here.
TOLD_EVENTS = ("famine", "unrest_changed", "building_completed", "demography", "game_over", "audience")
# How far back the peasants remember (mood and events). One value while the
# peasants are the only class; later each class gets its own horizon
# (e.g. merchants and clergy a year or more): see docs/DESIGN.md.
PEASANT_MEMORY_MONTHS = 3
OWN_WORDS_TURNS = 2  # the voice rereads what it said in the last turns, for continuity


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
        for event in games.list_visible_events(ctx.conn, ctx.game_id, ctx.realm_id, turn, Clearance.COURT):
            if event["realm_id"] == ctx.realm_id and event["kind"] in TOLD_EVENTS:
                told.append(f"{event['kind']} {event['data']} ({MONTHS[(turn - 1) % 12]})")
    return told


def _own_words(ctx: MeetingContext) -> list[str]:
    rows = ctx.conn.execute(
        "SELECT turn, content FROM council_messages WHERE realm_id = %s AND kind = 'voice'"
        " AND turn >= %s AND turn < %s ORDER BY id",
        (ctx.realm_id, ctx.turn - OWN_WORDS_TURNS, ctx.turn),
    ).fetchall()
    return [f"- {MONTHS[(turn - 1) % 12]}: {text}" for turn, text in dict(rows).items()]


def facts_for_the_square(ctx: MeetingContext, season: bool) -> str:
    """@brief What the people live through, with exact numbers the voice must
    turn into words. A season covers the three months just ended; the mood
    series starts one value earlier so the trend of those months shows."""
    state = ctx.state
    months_told = 3 if season else 1
    first_turn = ctx.turn - months_told
    mood_from = ctx.turn - (months_told if season else PEASANT_MEMORY_MONTHS - 1)
    lines = [
        f"# The square of {ctx.realm_name}, {MONTHS[(ctx.turn - 1) % 12]}",
        "- Mood of the peasants (0-1000; NEVER say these numbers), oldest first: "
        + _mood_series(ctx.conn, ctx.realm_id, mood_from, ctx.turn) + ".",
        f"- Unrest: {state.unrest}; months in a row of deep discontent: {state.low_mood_turns}.",
        # No granaries, not even in words: the people cannot know the stock,
        # they can only guess it from the ration, hunger and feasts.
        f"- Ration: {state.ration}. Taxes: {state.tax_rate}%.",
        f"- People: {state.children} children, {state.adults} adults, {state.elders} elders.",
    ]
    events = _told_events(ctx, first_turn, ctx.turn - 1)
    lines.append("- What happened: " + ("; ".join(events) if events else "nothing remarkable") + ".")
    orders = _carried_out(ctx.conn, ctx.realm_id, first_turn, ctx.turn - 1)
    lines.append("- Decisions of the crown carried out: " + ("; ".join(orders) if orders else "none") + ".")
    own = _own_words(ctx)
    if own:
        lines += ["## What you said before (keep the thread; do not repeat the same images)"] + own
    return "\n".join(lines)


def voice_system(ctx: MeetingContext, season: bool) -> str:
    """@brief System prompt of the Voice: monthly, or the long season story."""
    return render_prompt(
        "voice_system.txt",
        realm_name=ctx.realm_name,
        language=ctx.settings.language,
        length_rule=SEASON_RULE if season else MONTHLY_RULE,
    )


def speak_in_square(ctx: MeetingContext) -> str:
    """@brief Store this turn's voice as a court-level council message.
    @return The text, or "" if the voice did not speak (the meeting goes on).
    """
    actor = ensure_voice_actor(ctx)
    if actor is None:
        return ""
    season = is_reflection_turn(ctx.turn)
    system = voice_system(ctx, season)
    text = ask_text(ctx, actor, system, facts_for_the_square(ctx, season), MAX_VOICE_CHARS)
    if text:
        insert_message(ctx, 1, "voice", actor, text, {"season": season}, visibility="court")
    return text
