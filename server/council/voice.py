"""@brief The Voice of the square: what the people say, told before every
council meeting. The sovereign has no mood number: this voice and the
council members are how the people are known.

The voice knows the exact numbers but must never say them, and it gives
more weight to what just happened than to slow trends (approved design:
it may exaggerate after a shock and miss a slow change).
"""

import psycopg
from psycopg.types.json import Jsonb

from engine.turn import class_factors, food_needed, mood_factors
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
# Cold, worn buildings and carts of bought goods are seen by everyone ([needs], market).
TOLD_EVENTS = ("famine", "unrest_changed", "building_completed", "demography", "game_over", "audience",
               "firewood_short", "stone_upkeep_short", "trade_bought", "class_unrest_changed",
               "flight", "raid")  # village block B+C: families gone to the woods, bands at the gate
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


RATION_RANK = {"reduced": 0, "normal": 1, "abundant": 2}


def _decision_words(raw: dict, before: dict | None) -> str:
    """@brief A tax or ration order told with its direction ("taxes lowered
    from 10% to 7%"). Game 4: given only "set_tax 7", the square twice spoke
    of "a new tax nobody asked for" after a cut.
    @param before State at the start of that turn (None if missing)."""
    if before is None:
        return order_text(raw)
    if raw["action"] == "set_tax":
        old, new = before["tax_rate"], raw["rate"]
        way = "lowered" if new < old else "raised" if new > old else "kept"
        return f"taxes {way} from {old}% to {new}%"
    if raw["action"] == "set_ration":
        old, new = before["ration"], raw["ration"]
        way = "cut" if RATION_RANK[new] < RATION_RANK[old] else "increased" if new != old else "kept"
        return f"ration {way} from {old} to {new}"
    return order_text(raw)


def carried_out(conn: psycopg.Connection, realm_id: int, first_turn: int, last_turn: int) -> list[str]:
    rows = conn.execute(
        "SELECT o.turn, o.raw FROM orders o JOIN order_results r ON r.order_id = o.id"
        " WHERE o.realm_id = %s AND o.turn >= %s AND o.turn <= %s AND r.accepted ORDER BY o.id",
        (realm_id, first_turn, last_turn),
    ).fetchall()
    starts = dict(conn.execute(
        "SELECT turn, state FROM snapshots WHERE realm_id = %s AND turn >= %s AND turn <= %s",
        (realm_id, first_turn, last_turn),
    ).fetchall())
    return [f"{_decision_words(raw, starts.get(turn))} ({MONTHS[(turn - 1) % 12]})" for turn, raw in rows]


def _told_events(ctx: MeetingContext, first_turn: int, last_turn: int) -> list[str]:
    told = []
    for turn in range(max(1, first_turn), last_turn + 1):
        for event in games.list_visible_events(ctx.conn, ctx.game_id, ctx.realm_id, turn, Clearance.COURT):
            if event["realm_id"] == ctx.realm_id and event["kind"] in TOLD_EVENTS:
                told.append(f"{event['kind']} {event['data']} ({MONTHS[(turn - 1) % 12]})")
    return told


# What the people feel directly. "reserve" (the engine's bonus for a large
# stock) is left out on purpose: telling it would reveal the granaries.
FELT_FACTORS = {
    "taxes": ("the taxes", "the taxes"),
    "ration": ("the short ration", "the generous ration"),
    "hunger": ("hunger", "hunger"),
    "housing": ("crowded houses, no room for new families", "crowded houses"),
    "deaths": ("mourning for the dead", "mourning"),
}


def _weight_words(value: int) -> str:
    size = abs(value)
    if size >= 200:
        return "crushing" if value < 0 else "great"
    if size >= 100:
        return "heavy" if value < 0 else "strong"
    if size >= 40:
        return "felt"
    return "slight"


def _last_month(ctx: MeetingContext) -> tuple[int, int]:
    """@brief (missing food %, deaths) of the month just resolved."""
    missing_pct, deaths = 0, 0
    for event in games.list_visible_events(ctx.conn, ctx.game_id, ctx.realm_id, ctx.turn - 1, Clearance.COURT):
        if event["kind"] == "famine":
            missing_pct = event["data"].get("missing_pct", 0)
        if event["kind"] == "demography":
            deaths = event["data"].get("deaths", 0)
    return missing_pct, deaths


def feelings_line(ctx: MeetingContext) -> str:
    """@brief Why the people feel as they do, heaviest first, in words.

    Game 1: with only the mood series the voice guessed the cause and chose
    hunger while the taxes weighed most; the council believed it. These are
    the engine's own mood factors, so the square complains about real causes.
    """
    missing_pct, deaths = _last_month(ctx) if ctx.turn > 1 else (0, 0)
    factors = mood_factors(ctx.state, ctx.config, food_needed(ctx.state, ctx.config), missing_pct, deaths)
    felt = [(name, value) for name, value in factors.items() if name in FELT_FACTORS and value]
    felt.sort(key=lambda item: -abs(item[1]))
    burdens = [f"{FELT_FACTORS[n][0]} ({_weight_words(v)})" for n, v in felt if v < 0]
    joys = [f"{FELT_FACTORS[n][1]} ({_weight_words(v)})" for n, v in felt if v > 0]
    return ("- What weighs on the people, heaviest first: " + ("; ".join(burdens) or "nothing in particular")
            + ". What cheers them: " + ("; ".join(joys) or "nothing in particular") + ".")


# What the merchants feel (village block A). Their trade factor is told by
# its cause, so the square blames the crown only when the crown is to blame.
MERCHANT_FELT = {
    "taxes": ("the merchants' tax", "the merchants' tax"),
    "ration": ("the short ration", "the generous ration"),
    "hunger": ("hunger", "hunger"),
    "housing": ("crowded houses", "crowded houses"),
    "deaths": ("mourning for the dead", "mourning"),
}


def _trade_words(value: int, rules) -> str:
    if value == rules.idle_malus:
        return "a market kept idle while goods wait in the warehouse"
    if value == rules.empty_malus:
        return "an empty warehouse, nothing to trade"
    return "a busy market"


def merchants_lines(ctx: MeetingContext) -> list[str]:
    """@brief The merchants' part of the square: their own mood band, unrest
    and burdens, from the engine's class factors. [] without merchants."""
    cls = ctx.state.classes.get("merchants")
    if cls is None:
        return []
    rules = ctx.config.classes["merchants"]
    missing_pct, deaths = _last_month(ctx) if ctx.turn > 1 else (0, 0)
    factors = class_factors(ctx.state, ctx.config, "merchants", food_needed(ctx.state, ctx.config), missing_pct,
                            deaths)
    felt = sorted(((n, v) for n, v in factors.items() if v), key=lambda item: -abs(item[1]))
    burdens, joys = [], []
    for name, value in felt:
        words = _trade_words(value, rules) if name == "trade" else MERCHANT_FELT[name][0 if value < 0 else 1]
        (burdens if value < 0 else joys).append(f"{words} ({_weight_words(value)})")
    return [
        "## The merchants (the few families at the market; give them a sentence or two of their own, "
        "\"at the market they say...\", after the peasants)",
        f"- Mood of the merchants (0-1000; NEVER say it): {cls.mood}. Unrest: {cls.unrest}.",
        "- What weighs on them, heaviest first: " + ("; ".join(burdens) or "nothing in particular")
        + ". What cheers them: " + ("; ".join(joys) or "nothing in particular") + ".",
    ]


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
        feelings_line(ctx),
        # No granaries, not even in words: the people cannot know the stock,
        # they can only guess it from the ration, hunger and feasts.
        f"- Ration: {state.ration}. Taxes: {state.tax_rate}%.",
        f"- People: {state.children} children, {state.adults} adults, {state.elders} elders.",
        *merchants_lines(ctx),
    ]
    events = _told_events(ctx, first_turn, ctx.turn - 1)
    lines.append("- What happened: " + ("; ".join(events) if events else "nothing remarkable") + ".")
    orders = carried_out(ctx.conn, ctx.realm_id, first_turn, ctx.turn - 1)
    lines.append("- Decisions of the crown carried out: " + ("; ".join(orders) if orders else "none") + ".")
    # Imported here: the people module builds on this one (no import cycle).
    from server.council import people
    past = people.recent_decisions(ctx.conn, ctx.realm_id, first_turn, ctx.turn - 1)
    if past:
        lines += ["## What the people did (tell it, in your own words)"] + people.decision_lines(past, ctx.turn)
    own = _own_words(ctx)
    if own:
        lines += ["## What you said before (keep the thread; do not repeat the same images)"] + own
    return "\n".join(lines)


def square_text(ctx: MeetingContext) -> str:
    """@brief What the Voice said this turn ("" if it was silent)."""
    row = ctx.conn.execute(
        "SELECT content FROM council_messages WHERE realm_id = %s AND turn = %s AND kind = 'voice'"
        " ORDER BY id DESC LIMIT 1",
        (ctx.realm_id, ctx.turn),
    ).fetchone()
    return row[0] if row else ""


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
    already = square_text(ctx)
    if already:
        return already  # a meeting held again after a crash: the square spoke once
    season = is_reflection_turn(ctx.turn)
    system = voice_system(ctx, season)
    text = ask_text(ctx, actor, system, facts_for_the_square(ctx, season), MAX_VOICE_CHARS)
    if text:
        insert_message(ctx, 1, "voice", actor, text, {"season": season}, visibility="court")
    return text
