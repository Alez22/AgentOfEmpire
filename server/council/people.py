"""@brief The people decide: how hard they work, whether families want
children, and sometimes a petition to the sovereign.

Called at every meeting, right after the Voice of the square. A cheap
model reads what weighs on the people and what the square said, and
chooses inside the limits of the mood band (engine/people.py). The choice
is stored per turn and read by the resolution like an order, so replays
stay exact. When the model is silent, the fixed rules take the middle of
each range.

Hidden cost: one more model call per meeting (cheap tier, no reasoning,
about $0.0002).
"""

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from engine import parse_order
from engine.people import allowed_ranges, clamp_choice, mood_band, rule_choice
from server.council import voice
from server.council.briefing import MONTHS
from server.council.meeting import (
    Actor,
    CouncilError,
    MeetingContext,
    _ask,
    _changes_nothing,
    load_context,
    render_prompt,
)
from server.db import games

PEOPLE_ROLE = "people"
OWN_DECISIONS_TURNS = 2
# What the people may ask for: what they feel directly, nothing else.
PETITION_ACTIONS = ("set_tax", "set_ration", "hold_feast")
MAX_PETITION_CHARS = 300


class _PetitionSchema(BaseModel):
    order: dict
    text: str


class _PeopleSchema(BaseModel):
    effort_pct: int
    birth_pct: int
    petition: _PetitionSchema | None = None
    reason: str


class _PeopleReply(BaseModel):
    # Loose on purpose: a bad petition is dropped on its own, not the reply.
    effort_pct: int
    birth_pct: int
    petition: dict | None = None
    reason: str = ""


class PetitionError(CouncilError):
    """No petition to answer this turn, or it was already answered."""


def behaviour_words(effort_pct: int, birth_pct: int) -> str:
    """@brief The month's behaviour in plain words (English, for prompts)."""
    if effort_pct >= 5:
        work = "the peasants work with zeal"
    elif effort_pct > 0:
        work = "the peasants work willingly"
    elif effort_pct == 0:
        work = "the peasants work as usual"
    elif effort_pct > -10:
        work = "the peasants work reluctantly"
    else:
        work = "the peasants drag their feet in the fields"
    if birth_pct > 100:
        families = "families want children"
    elif birth_pct < 100:
        families = "families put off having children"
    else:
        families = "families live as usual"
    return f"{work}; {families}"


def ensure_people_actor(ctx: MeetingContext) -> Actor | None:
    """@brief Games created before the people decided get the actor at their
    next meeting, with the model of council.toml. None if no model is set."""
    if PEOPLE_ROLE in ctx.actors:
        return ctx.actors[PEOPLE_ROLE]
    model = ctx.settings.models.get(PEOPLE_ROLE)
    if model is None:
        return None
    actor_id = ctx.conn.execute(
        "INSERT INTO actors (realm_id, role, model, personality) VALUES (%s, %s, %s, %s) RETURNING id",
        (ctx.realm_id, PEOPLE_ROLE, model, Jsonb({})),
    ).fetchone()[0]
    ctx.actors[PEOPLE_ROLE] = Actor(actor_id, PEOPLE_ROLE, model, {})
    return ctx.actors[PEOPLE_ROLE]


def recent_decisions(conn: psycopg.Connection, realm_id: int, first_turn: int,
                     last_turn: int) -> list[dict]:
    """@brief Decisions of turns first..last with the sovereign's answers."""
    rows = conn.execute(
        "SELECT d.turn, d.effort_pct, d.birth_pct, d.petition, d.petition_text, a.answer"
        " FROM people_decisions d LEFT JOIN petition_answers a ON a.decision_id = d.id"
        " WHERE d.realm_id = %s AND d.turn >= %s AND d.turn <= %s ORDER BY d.turn",
        (realm_id, first_turn, last_turn),
    ).fetchall()
    keys = ("turn", "effort_pct", "birth_pct", "petition", "petition_text", "answer")
    return [dict(zip(keys, row)) for row in rows]


def decision_lines(decisions: list[dict], open_turn: int) -> list[str]:
    """@brief Past decisions in words, for the square, the council and the people."""
    lines = []
    for item in decisions:
        line = f"- {MONTHS[(item['turn'] - 1) % 12]}: {behaviour_words(item['effort_pct'], item['birth_pct'])}"
        if item["petition"]:
            answer = item["answer"] or ("not answered yet" if item["turn"] == open_turn else "refused")
            line += f'; they petitioned the crown: "{item["petition_text"]}" ({answer})'
        lines.append(line + ".")
    return lines


def _facts(ctx: MeetingContext) -> str:
    state = ctx.state
    ranges = allowed_ranges(state, ctx.config)
    band = mood_band(state, ctx.config.people)
    past = recent_decisions(ctx.conn, ctx.realm_id, ctx.turn - OWN_DECISIONS_TURNS, ctx.turn - 1)
    square = voice.square_text(ctx)
    lines = [
        f"# The people of {ctx.realm_name}, {MONTHS[(ctx.turn - 1) % 12]}",
        f"- How you feel: {band} (mood {state.mood}/1000; never write this number).",
        voice.feelings_line(ctx),
        f"- Unrest: {state.unrest}. Ration: {state.ration}. Taxes: {state.tax_rate}%.",
        "- What the square says this month: " + (square or "nothing was heard."),
        "- Decisions of the crown last month: "
        + ("; ".join(voice.carried_out(ctx.conn, ctx.realm_id, ctx.turn - 1, ctx.turn - 1)) or "none") + ".",
        f"- Allowed this month: effort_pct from {ranges['effort_pct'][0]} to {ranges['effort_pct'][1]}; "
        f"birth_pct from {ranges['birth_pct'][0]} to {ranges['birth_pct'][1]}.",
    ]
    if past:
        lines += ["## What you did before"] + decision_lines(past, ctx.turn)
    return "\n".join(lines)


def _petition_order(ctx: MeetingContext, raw: dict | None) -> tuple[dict | None, str]:
    """@brief A petition the crown can actually grant, or (None, "")."""
    if not isinstance(raw, dict):
        return None, ""
    order, code, _message = parse_order(raw.get("order"))
    text = str(raw.get("text", "")).strip()[:MAX_PETITION_CHARS]
    if order is None or order.action not in PETITION_ACTIONS or not text:
        return None, ""
    clean = order.model_dump(exclude={"priority"})
    if _changes_nothing(ctx.state, clean):
        return None, ""
    if clean["action"] == "hold_feast" and clean["gold"] > ctx.state.gold:
        return None, ""
    return clean, text


def decide(ctx: MeetingContext) -> None:
    """@brief Store this turn's choice of the people (model, else rules).
    Does nothing for games without [people] rules or already decided."""
    if ctx.config.people is None:
        return
    if ctx.conn.execute(
        "SELECT 1 FROM people_decisions WHERE realm_id = %s AND turn = %s", (ctx.realm_id, ctx.turn)
    ).fetchone():
        return
    actor = ensure_people_actor(ctx)
    reply = None
    if actor is not None:
        system = render_prompt("people_system.txt", realm_name=ctx.realm_name,
                               language=ctx.settings.language)
        reply, _status = _ask(ctx, actor, system, _facts(ctx), _PeopleSchema.model_json_schema(),
                              _PeopleReply)
    if reply is not None:
        effort, births = clamp_choice(ctx.state, ctx.config, reply.effort_pct, reply.birth_pct)
        petition, text = _petition_order(ctx, reply.petition)
        reason, source = reply.reason.strip()[:MAX_PETITION_CHARS], "model"
    else:
        effort, births = rule_choice(ctx.state, ctx.config)
        petition, text, reason, source = None, "", "fixed rules: the model did not answer", "rules"
    ctx.conn.execute(
        "INSERT INTO people_decisions (game_id, realm_id, turn, actor_id, effort_pct, birth_pct,"
        " petition, petition_text, reason, source) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (ctx.game_id, ctx.realm_id, ctx.turn, actor.id if actor else None, effort, births,
         Jsonb(petition) if petition else None, text, reason, source),
    )


def answer_petition(conn: psycopg.Connection, realm_id: int, answer: str) -> None:
    """@brief The sovereign grants or refuses this turn's petition. Granting
    submits the asked order first in the turn (priority -1), as the crown's.
    @throws PetitionError, NoOpenTurnError
    """
    if answer not in ("granted", "refused"):
        raise ValueError("answer must be 'granted' or 'refused'")
    ctx = load_context(conn, realm_id, None, None)
    row = conn.execute(
        "SELECT d.id, d.petition, a.id FROM people_decisions d"
        " LEFT JOIN petition_answers a ON a.decision_id = d.id"
        " WHERE d.realm_id = %s AND d.turn = %s",
        (realm_id, ctx.turn),
    ).fetchone()
    if row is None or row[1] is None:
        raise PetitionError("no petition this turn")
    decision_id, petition, answered = row
    if answered is not None:
        raise PetitionError("the petition was already answered")
    with conn.transaction():
        order_id = None
        if answer == "granted":
            # Plan already approved with the very same order: link it, no duplicate.
            order_id = _same_order_this_turn(conn, realm_id, ctx.turn, petition)
            if order_id is None:
                order_id = games.submit_order(conn, realm_id, petition, priority=-1)
        conn.execute(
            "INSERT INTO petition_answers (decision_id, answer, order_id) VALUES (%s, %s, %s)",
            (decision_id, answer, order_id),
        )


def _same_order_this_turn(conn: psycopg.Connection, realm_id: int, turn: int, order: dict) -> int | None:
    row = conn.execute(
        "SELECT id FROM orders WHERE realm_id = %s AND turn = %s AND raw = %s ORDER BY id LIMIT 1",
        (realm_id, turn, Jsonb(order)),
    ).fetchone()
    return row[0] if row else None


def decision_for_sovereign(conn: psycopg.Connection, realm_id: int, turn: int) -> dict | None:
    """@brief What the sovereign may see: behaviour, numbers on demand and
    the petition. Not the model's reason (admin only)."""
    decisions = recent_decisions(conn, realm_id, turn, turn)
    if not decisions:
        return None
    item = decisions[0]
    return {
        "turn": item["turn"],
        "effort_pct": item["effort_pct"],
        "birth_pct": item["birth_pct"],
        "petition": item["petition"],
        "petition_text": item["petition_text"],
        "answer": item["answer"],
    }
