"""@brief Debate on request: before approving, the sovereign may ask the
ministers what they think of the Chancellor's plan. Each one answers in
one or two sentences, agreeing or objecting; the plan does not change,
the sovereign decides.

One debate per plan (per council round). Cost: one model call per
minister (two today), about $0.001-0.002 and 10-30 seconds.
"""

from typing import Literal

import psycopg
from pydantic import BaseModel

from server.council.memory import order_text
from server.council.meeting import (
    DISPLAY_NAMES,
    MINISTERS,
    ROLE_DUTIES,
    ROLE_TITLES,
    AlreadyApprovedError,
    CouncilError,
    MeetingContext,
    NoMeetingYetError,
    _ask,
    _plan_approved,
    _rounds_held,
    insert_message,
    load_context,
    mandate_block,
    render_prompt,
)
from server.council import manual
from server.council.personality import describe_traits

MAX_COMMENT_CHARS = 600


class DebateAlreadyHeldError(CouncilError):
    """The ministers already gave their opinion on this plan."""


class _CommentSchema(BaseModel):
    stance: Literal["agree", "object"]
    comment: str


class _CommentReply(BaseModel):
    stance: str = "agree"
    comment: str


def _latest_round_messages(ctx: MeetingContext) -> list[tuple]:
    return ctx.conn.execute(
        "SELECT m.kind, a.role, m.content, m.payload FROM council_messages m"
        " LEFT JOIN actors a ON a.id = m.speaker_actor_id"
        " WHERE m.realm_id = %s AND m.turn = %s AND m.round = %s ORDER BY m.id",
        (ctx.realm_id, ctx.turn, _rounds_held(ctx)),
    ).fetchall()


def _check(ctx: MeetingContext) -> None:
    if _rounds_held(ctx) == 0:
        raise NoMeetingYetError("hold the meeting before asking for a debate")
    if _plan_approved(ctx):
        raise AlreadyApprovedError("the plan of this turn is already approved")
    if any(kind == "comment" for kind, *_ in _latest_round_messages(ctx)):
        raise DebateAlreadyHeldError("the ministers already spoke on this plan")


def check_debate_allowed(conn: psycopg.Connection, realm_id: int) -> None:
    """@brief Same checks as hold_debate(), without any model call."""
    _check(load_context(conn, realm_id, None, None))


def _user_prompt(ctx: MeetingContext, role: str, messages: list[tuple], comments: list[str]) -> str:
    lines = [f"# The plan of {ctx.realm_name}, turn {ctx.turn}"]
    for kind, speaker, content, payload in messages:
        if kind == "report" and speaker == role:
            proposals = ", ".join(order_text(o) for o in payload.get("proposals", [])) or "nothing"
            lines += ["## Your report", content, f"- You proposed: {proposals}."]
        if kind == "summary":
            lines += ["## The Chancellor's summary", content, "## The plan"]
            check = payload.get("check", {}).get("verdicts", [])
            for index, item in enumerate(payload.get("plan", [])):
                verdict = check[index] if index < len(check) else {"accepted": True}
                status = "feasible" if verdict.get("accepted") else f"not feasible: {verdict.get('code')}"
                proposer = DISPLAY_NAMES.get(item["proposer"], item["proposer"])
                lines.append(f"- {index + 1}) {order_text(item['order'])} ({proposer}; {status})")
            if not payload.get("plan"):
                lines.append("- The plan is empty.")
    if comments:
        lines += ["## Already said in this debate"] + comments
    return "\n".join(lines)


def hold_debate(conn: psycopg.Connection, realm_id: int, client, settings) -> None:
    """@brief Each minister comments on the latest plan, in turn.
    @throws NoOpenTurnError, NoMeetingYetError, AlreadyApprovedError, DebateAlreadyHeldError
    """
    ctx = load_context(conn, realm_id, client, settings)
    _check(ctx)
    round_number = _rounds_held(ctx)
    messages = _latest_round_messages(ctx)
    comments: list[str] = []
    for role in MINISTERS:
        actor = ctx.actors.get(role)
        if actor is None:
            continue
        system = render_prompt(
            "debate_system.txt", role_title=ROLE_TITLES[role], display_name=DISPLAY_NAMES[role],
            realm_name=ctx.realm_name, duties=ROLE_DUTIES[role], traits=describe_traits(actor.traits),
            language=settings.language, mandate=mandate_block(ctx, actor),
            manual=manual.prompt_text(ctx.config),
        )
        reply, _status = _ask(ctx, actor, system, _user_prompt(ctx, role, messages, comments),
                              _CommentSchema.model_json_schema(), _CommentReply)
        if reply is None:
            continue  # a silent minister simply does not speak in the debate
        stance = reply.stance if reply.stance in ("agree", "object") else "agree"
        text = reply.comment.strip()[:MAX_COMMENT_CHARS]
        if not text:
            continue
        insert_message(ctx, round_number, "comment", actor, text, {"stance": stance})
        comments.append(f"- {DISPLAY_NAMES[role]} ({stance}): {text}")
