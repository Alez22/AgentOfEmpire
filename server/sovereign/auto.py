"""@brief One month of a realm played by the automatic sovereign, through the
same functions the sovereign's buttons use (docs/DESIGN.md, "Automatic
sovereign, first version"). The decisions come from server/sovereign/rules.py.
"""

import psycopg

from server.council import meeting, people
from server.council.settings import CouncilSettings
from server.sovereign import rules
from server.ui import labels

NOTHING_TO_SAY = "Il sovrano approva il piano così com'è."


def _latest_plan(conn: psycopg.Connection, realm_id: int, turn: int) -> dict:
    summaries = [m for m in meeting.list_messages(conn, realm_id, turn) if m["kind"] == "summary"]
    return summaries[-1]["payload"]


def _month(ctx: meeting.MeetingContext) -> rules.Month:
    return rules.Month(ctx.state, ctx.config, ctx.market, str(ctx.realm_id))


def _give_directive(conn, realm_id: int, client, settings: CouncilSettings, ctx, lines: list[str]) -> str | None:
    """@brief R7 or R5, when the council may still take a directive."""
    if settings.max_directives_per_turn < 1 or meeting.council_state(conn, realm_id, settings).approved:
        return None
    found = rules.directive(_month(ctx), rules.plan_items(_latest_plan(conn, realm_id, ctx.turn)))
    if found is None:
        return None
    text, reason = found
    meeting.give_directive(conn, realm_id, client, settings, text)
    lines.append(reason)
    return text


def _answer_petition(conn, realm_id: int, ctx, items: list[rules.Item], lines: list[str]) -> dict | None:
    """@brief R1. @return The granted petition's order, or None."""
    decision = people.decision_for_sovereign(conn, realm_id, ctx.turn)
    if not decision or not decision["petition"] or decision["answer"]:
        return None
    answer, reason = rules.petition_answer(_month(ctx), decision["petition"], items)
    people.answer_petition(conn, realm_id, answer)
    lines.append(reason)
    return decision["petition"] if answer == "granted" else None


def play_month(conn: psycopg.Connection, realm_id: int, client, settings: CouncilSettings) -> list[str]:
    """@brief Meeting, at most one directive, the petition, the exclusions,
    the approval; then the reasons in a council message of kind 'sovereign'.
    @return The reasons, in Italian.
    @throws meeting.CouncilError (no open turn, plan already approved, ...)
    """
    if meeting.council_state(conn, realm_id, settings).rounds_held == 0:
        meeting.hold_meeting(conn, realm_id, client, settings)
    ctx = meeting.load_context(conn, realm_id, client, settings)
    lines: list[str] = []
    directive = _give_directive(conn, realm_id, client, settings, ctx, lines)
    payload = _latest_plan(conn, realm_id, ctx.turn)
    items = rules.plan_items(payload)
    granted = _answer_petition(conn, realm_id, ctx, items, lines)
    excluded = rules.exclusions(_month(ctx), items, granted)
    for index, reason in excluded:
        lines.append(f"Escluso «{labels.order_label(payload['plan'][index]['order'])}»: {reason}.")
    meeting.approve_plan(conn, realm_id, [index for index, _ in excluded])
    rounds = meeting.council_state(conn, realm_id, settings).rounds_held
    meeting.insert_message(ctx, rounds, "sovereign", None, "\n".join(lines) or NOTHING_TO_SAY,
                           {"lines": lines, "excluded": [index for index, _ in excluded], "directive": directive})
    return lines
