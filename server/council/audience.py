"""@brief Private audience: the sovereign talks with one council member.

Words only: no order is given here, the council keeps that role. The
dialogue is secret (table `audiences`, see migration 005); only the fact
that an audience happened is recorded as a council-level event.

One reply = one model call (plain text, no JSON), logged in model_calls and
counted in the game's budget like every other call.
"""

import psycopg
from psycopg.types.json import Jsonb

from server.council import briefing, memory
from server.council.meeting import (
    DISPLAY_NAMES,
    ROLE_DUTIES,
    ROLE_TITLES,
    CouncilError,
    MeetingContext,
    ask_text,
    load_context,
    render_prompt,
    square_voice_text,
)
from server.council.personality import describe_traits
from server.council.settings import CouncilSettings
from server.db import games
from server.db.access import Clearance

AUDIENCE_ROLES = ("treasurer", "architect", "chancellor")
MAX_REPLY_CHARS = 1500
MAX_SOVEREIGN_CHARS = 500


class UnknownCounsellorError(CouncilError):
    pass


class AudienceLimitError(CouncilError):
    pass


def _actor(ctx: MeetingContext, role: str):
    if role not in AUDIENCE_ROLES or role not in ctx.actors:
        raise UnknownCounsellorError(f"no council member '{role}' in this realm")
    return ctx.actors[role]


def _sovereign_lines(conn: psycopg.Connection, actor_id: int, turn: int) -> int:
    return conn.execute(
        "SELECT count(*) FROM audiences WHERE actor_id = %s AND turn = %s AND speaker = 'sovereign'",
        (actor_id, turn),
    ).fetchone()[0]


def _check(ctx: MeetingContext, role: str, settings: CouncilSettings):
    actor = _actor(ctx, role)
    used = _sovereign_lines(ctx.conn, actor.id, ctx.turn)
    if used >= settings.max_audience_messages_per_turn:
        raise AudienceLimitError(
            f"at most {settings.max_audience_messages_per_turn} lines per council member per turn"
        )
    return actor


def check_audience_allowed(conn: psycopg.Connection, realm_id: int, role: str,
                           settings: CouncilSettings) -> None:
    """@brief Same checks as speak(), without any model call (for the web UI).
    @throws NoOpenTurnError, UnknownCounsellorError, AudienceLimitError
    """
    _check(load_context(conn, realm_id, None, settings), role, settings)


def lines_left(conn: psycopg.Connection, realm_id: int, role: str, settings: CouncilSettings) -> int:
    ctx = load_context(conn, realm_id, None, settings)
    actor = _actor(ctx, role)
    return max(0, settings.max_audience_messages_per_turn - _sovereign_lines(conn, actor.id, ctx.turn))


def _insert_line(ctx: MeetingContext, actor, speaker: str, content: str) -> None:
    ctx.conn.execute(
        "INSERT INTO audiences (game_id, realm_id, actor_id, turn, speaker, content)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (ctx.game_id, ctx.realm_id, actor.id, ctx.turn, speaker, content),
    )


def _record_fact(ctx: MeetingContext, actor) -> None:
    """@brief First sovereign line of the turn with this member: the council
    (and the chronicle) learns THAT the audience took place, not what was said."""
    ctx.conn.execute(
        "INSERT INTO events (game_id, realm_id, turn, kind, data, visibility)"
        " VALUES (%s, %s, %s, 'audience', %s, 'council')",
        (ctx.game_id, ctx.realm_id, ctx.turn, Jsonb({"role": actor.role})),
    )


def _briefing(ctx: MeetingContext, actor) -> str:
    """@brief The member's usual view of the realm, its lessons and its
    previous audiences (the current one included, up to the new line)."""
    events = games.list_visible_events(ctx.conn, ctx.game_id, ctx.realm_id, ctx.turn - 1, Clearance.COUNCIL)
    lessons = [memory.lesson_line(lesson) for lesson in memory.current_lessons(ctx.conn, actor.id)]
    if actor.role == "treasurer":
        sections = briefing.treasury_lines(ctx.state, ctx.config)
    elif actor.role == "architect":
        sections = briefing.works_lines(ctx.state, ctx.config)
    else:
        sections = briefing.treasury_lines(ctx.state, ctx.config) + briefing.works_lines(ctx.state, ctx.config)
    dialogue = memory.audience_dialogue(
        ctx.conn, actor.id, ctx.turn - memory.AUDIENCE_HISTORY_TURNS, ctx.turn
    )
    lines = (briefing.header_lines(ctx.state) + briefing.lessons_lines(lessons) + sections
             + briefing.events_lines(events) + briefing.square_lines(square_voice_text(ctx))
             + briefing.audience_lines(dialogue))
    lines.append("Answer the sovereign's last words above.")
    return "\n".join(lines)


def _system(ctx: MeetingContext, actor) -> str:
    return render_prompt(
        "audience_system.txt",
        role_title=ROLE_TITLES[actor.role],
        display_name=DISPLAY_NAMES[actor.role],
        realm_name=ctx.realm_name,
        duties=ROLE_DUTIES[actor.role],
        traits=describe_traits(actor.traits),
        language=ctx.settings.language,
    )


def _reply(ctx: MeetingContext, actor) -> str:
    """@brief The member's answer, or "" if none arrived (the caller shows it)."""
    return ask_text(ctx, actor, _system(ctx, actor), _briefing(ctx, actor), MAX_REPLY_CHARS)


def speak(conn: psycopg.Connection, realm_id: int, role: str, text: str,
          client, settings: CouncilSettings) -> str:
    """@brief Store the sovereign's line, then the member's answer.
    @return The answer, or "" if the member did not answer (the sovereign's
            line stays; the next line will be answered together with it).
    @throws NoOpenTurnError, UnknownCounsellorError, AudienceLimitError
    """
    ctx = load_context(conn, realm_id, client, settings)
    actor = _check(ctx, role, settings)
    if _sovereign_lines(conn, actor.id, ctx.turn) == 0:
        _record_fact(ctx, actor)
    _insert_line(ctx, actor, "sovereign", text.strip()[:MAX_SOVEREIGN_CHARS])
    answer = _reply(ctx, actor)
    if answer:
        _insert_line(ctx, actor, "actor", answer)
    return answer


def dialogue_for_sovereign(conn: psycopg.Connection, realm_id: int, role: str) -> list[dict]:
    """@brief The whole dialogue with one member, for the sovereign's own page.
    Never exposed anywhere else (secret from the other council members)."""
    rows = conn.execute(
        "SELECT au.turn, au.speaker, au.content, au.created_at FROM audiences au"
        " JOIN actors a ON a.id = au.actor_id WHERE au.realm_id = %s AND a.role = %s ORDER BY au.id",
        (realm_id, role),
    ).fetchall()
    return [{"turn": r[0], "speaker": r[1], "content": r[2], "created_at": r[3]} for r in rows]
