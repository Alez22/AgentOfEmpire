"""@brief What a council member remembers: the consequences of past proposals
or plans, and the lessons revised at the end of each season.

Only database reads/writes and text formatting here, no model calls.

PRIVACY: lessons are secret from the sovereign and from the other council
members. The `lessons` table has no visibility label and no grant to
agent_reader; no endpoint returns it. Only the server reads it, by
actor_id, to build that same actor's briefing.
"""

import json
from dataclasses import dataclass

from server.council.briefing import MONTHS
from server.db.access import Clearance, agent_context

MAX_LESSON_CHARS = 300  # the maximum number of lessons is in council.toml

# Numbers each role follows after its decisions ("idle" = adults without work).
# No "mood": the council knows the people only from the square's words.
ROLE_METRICS = {
    "treasurer": ("food", "gold"),
    "architect": ("food", "wood", "stone", "idle"),
    "chancellor": ("food", "gold", "wood", "stone"),
}
# Events worth remembering; routine ones (demography, spoilage) would be noise.
NOTABLE_EVENTS = ("famine", "unrest_changed", "upkeep_unpaid", "building_completed", "game_over")
FOLLOW_UP_MONTHS = 2  # "Afterwards" shows the start of the turn and the next two months


def order_text(order: dict) -> str:
    """@brief Compact wording of an order: 'set_tax 12', 'build farm'."""
    values = [f"{key} {value}" if key in ("food", "wood", "stone") else str(value)
              for key, value in order.items() if key not in ("action", "priority")]
    return " ".join([order["action"], *values])


def _metric(state: dict, name: str) -> int:
    if name == "idle":
        workers = state["workers"]
        return state["adults"] - workers["food"] - workers["wood"] - workers["stone"]
    return state[name]


def _proposals_by_turn(conn, actor_id: int, first_turn: int, last_turn: int) -> dict[int, list]:
    proposed = {}
    for turn, payload in conn.execute(
        "SELECT turn, payload FROM council_messages WHERE speaker_actor_id = %s AND kind = 'report'"
        " AND turn >= %s AND turn < %s ORDER BY turn, round",
        (actor_id, first_turn, last_turn),
    ):
        proposed[turn] = payload.get("proposals", [])  # the last round of a turn wins
    return proposed


def _orders_by_turn(conn, realm_id: int, first_turn: int, last_turn: int) -> dict[int, list]:
    orders = {}
    for turn, raw, issued_by, priority, accepted, code in conn.execute(
        "SELECT o.turn, o.raw, o.issued_by_actor_id, o.priority, r.accepted, r.rejection_code"
        " FROM orders o"
        " LEFT JOIN order_results r ON r.order_id = o.id"
        " WHERE o.realm_id = %s AND o.turn >= %s AND o.turn < %s ORDER BY o.id",
        (realm_id, first_turn, last_turn),
    ):
        orders.setdefault(turn, []).append(
            {"raw": raw, "issued_by": issued_by, "priority": priority,
             "accepted": accepted, "code": code}
        )
    return orders


def _snapshots(conn, realm_id: int, first_turn: int, last_turn: int) -> dict[int, dict]:
    return dict(conn.execute(
        "SELECT turn, state FROM snapshots WHERE realm_id = %s AND turn >= %s AND turn <= %s",
        (realm_id, first_turn, last_turn),
    ).fetchall())


def _notable_events(conn, game_id: int, realm_id: int, first_turn: int, last_turn: int) -> dict[int, list]:
    """@brief Read as the council would (row-level security), so a minister
    never remembers something it could not have known."""
    events = {}
    with agent_context(conn, game_id, realm_id, Clearance.COUNCIL) as reader:
        for turn, kind, data in reader.execute(
            "SELECT turn, kind, data FROM events WHERE realm_id = %s AND turn >= %s AND turn < %s"
            " AND kind = ANY(%s) ORDER BY id",
            (realm_id, first_turn, last_turn, list(NOTABLE_EVENTS)),
        ):
            events.setdefault(turn, []).append(f"{kind} {json.dumps(data)} (turn {turn})")
    return events


def _outcome_text(own_orders: list[dict]) -> str:
    if not own_orders:
        return "None approved by the sovereign."
    parts = []
    for order in own_orders:
        if order["accepted"]:
            parts.append(f"{order_text(order['raw'])} carried out")
        else:
            parts.append(f"{order_text(order['raw'])} failed ({order['code']})")
    return "Approved: " + "; ".join(parts) + "."


def _afterwards_text(role: str, turn: int, snapshots: dict[int, dict]) -> str:
    turns = [t for t in range(turn, turn + FOLLOW_UP_MONTHS + 1) if t in snapshots]
    if len(turns) < 2:
        return "Afterwards: too early to tell."
    series = [
        f"{name} " + " → ".join(str(_metric(snapshots[t], name)) for t in turns)
        for name in ROLE_METRICS[role]
    ]
    return "Afterwards: " + "; ".join(series) + "."


def consequence_lines(
    conn, game_id: int, realm_id: int, actor_id: int, role: str,
    first_turn: int, current_turn: int, names_by_actor: dict[int | None, str],
) -> list[str]:
    """@brief One entry per past turn in which the minister proposed something.
    @param first_turn First turn to remember (inclusive).
    @param current_turn The open turn (excluded; its snapshot is the latest).
    @param names_by_actor actor_id -> display name; None -> the sovereign.
    @return Multi-line entries, oldest first.
    """
    proposed = _proposals_by_turn(conn, actor_id, first_turn, current_turn)
    orders = _orders_by_turn(conn, realm_id, first_turn, current_turn)
    snapshots = _snapshots(conn, realm_id, first_turn, current_turn)
    events = _notable_events(conn, game_id, realm_id, first_turn, current_turn)
    entries = []
    for turn in sorted(proposed):
        turn_orders = orders.get(turn, [])
        own = [o for o in turn_orders if o["issued_by"] == actor_id]
        others = [o for o in turn_orders if o["issued_by"] != actor_id]
        month = MONTHS[(turn - 1) % 12]
        proposals = ", ".join(order_text(p) for p in proposed[turn]) or "nothing"
        lines = [f"turn {turn} ({month}): you proposed {proposals}. {_outcome_text(own)}"]
        if others:
            decided = ", ".join(
                f"{order_text(o['raw'])} ({names_by_actor.get(o['issued_by'], 'the sovereign')})"
                for o in others
            )
            lines.append(f"Also decided that turn: {decided}.")
        lines.append(_afterwards_text(role, turn, snapshots))
        follow_up_events = [e for t in range(turn, turn + FOLLOW_UP_MONTHS) for e in events.get(t, [])]
        if follow_up_events:
            lines.append("Events: " + "; ".join(follow_up_events) + ".")
        entries.append("\n  ".join(lines))
    return entries


def _outcome_parts(orders: list[dict]) -> list[str]:
    return [
        f"{order_text(o['raw'])} carried out" if o["accepted"]
        else f"{order_text(o['raw'])} failed ({o['code']})"
        for o in orders
    ]


def _plan_entry(turn: int, plan: list[dict], directives: list[str], turn_orders: list[dict],
                names_by_role: dict[str, str], role_snapshots_text: str, events: list[str]) -> str:
    month = MONTHS[(turn - 1) % 12]
    numbered = "; ".join(
        f"{index + 1}) {order_text(item['order'])} ({names_by_role.get(item['proposer'], item['proposer'])})"
        for index, item in enumerate(plan)
    ) or "nothing"
    lines = [f"turn {turn} ({month}): your plan: {numbered}."]
    if directives:
        lines.append("Directives of the sovereign: " + "; ".join(f'"{d}"' for d in directives) + ".")
    # approve_plan() stores each plan order with its plan position as priority.
    from_plan = [o for o in turn_orders if o["issued_by"] is not None]
    by_sovereign = [o for o in turn_orders if o["issued_by"] is None]
    if not from_plan:
        lines.append("The sovereign did not approve the plan.")
    else:
        kept = {o["priority"] for o in from_plan}
        removed = [f"{i + 1}) {order_text(item['order'])}" for i, item in enumerate(plan) if i not in kept]
        lines.append("The sovereign approved it" + (f", removing {', '.join(removed)}." if removed else " whole."))
        lines.append("Outcome: " + "; ".join(_outcome_parts(from_plan)) + ".")
    if by_sovereign:
        lines.append("The sovereign also ordered: " + "; ".join(_outcome_parts(by_sovereign)) + ".")
    lines.append(role_snapshots_text)
    if events:
        lines.append("Events: " + "; ".join(events) + ".")
    return "\n  ".join(lines)


def chancellor_consequence_lines(
    conn, game_id: int, realm_id: int, actor_id: int,
    first_turn: int, current_turn: int, names_by_role: dict[str, str],
) -> list[str]:
    """@brief One entry per past turn with a plan of the Chancellor: what the
    sovereign kept, removed or asked for, and what followed. This is where the
    Chancellor can learn the sovereign's preferences.
    """
    plans = {}
    for turn, payload in conn.execute(
        "SELECT turn, payload FROM council_messages WHERE speaker_actor_id = %s AND kind = 'summary'"
        " AND turn >= %s AND turn < %s ORDER BY turn, round",
        (actor_id, first_turn, current_turn),
    ):
        plans[turn] = payload.get("plan", [])  # the last round of a turn wins
    directives = {}
    for turn, content in conn.execute(
        "SELECT turn, content FROM council_messages WHERE realm_id = %s AND kind = 'directive'"
        " AND turn >= %s AND turn < %s ORDER BY id",
        (realm_id, first_turn, current_turn),
    ):
        directives.setdefault(turn, []).append(content)
    orders = _orders_by_turn(conn, realm_id, first_turn, current_turn)
    snapshots = _snapshots(conn, realm_id, first_turn, current_turn)
    events = _notable_events(conn, game_id, realm_id, first_turn, current_turn)
    return [
        _plan_entry(
            turn, plans[turn], directives.get(turn, []), orders.get(turn, []), names_by_role,
            _afterwards_text("chancellor", turn, snapshots),
            [e for t in range(turn, turn + FOLLOW_UP_MONTHS) for e in events.get(t, [])],
        )
        for turn in sorted(plans)
    ]


# -------------------------------------------------------------- audiences

AUDIENCE_HISTORY_TURNS = 3  # turns of private audiences a council member remembers
AUDIENCE_HISTORY_LINES = 12  # newest lines kept, to bound the prompt size


def audience_dialogue(conn, actor_id: int, first_turn: int, last_turn: int) -> list[str]:
    """@brief The actor's private audiences with the sovereign, oldest first.
    SECRET: only for that same actor's prompts and for the sovereign's page.
    @param last_turn Inclusive (the open turn's audience is part of the memory).
    """
    rows = conn.execute(
        "SELECT turn, speaker, content FROM audiences WHERE actor_id = %s"
        " AND turn >= %s AND turn <= %s ORDER BY id DESC LIMIT %s",
        (actor_id, first_turn, last_turn, AUDIENCE_HISTORY_LINES),
    ).fetchall()
    return [
        f"turn {turn} · {'the sovereign' if speaker == 'sovereign' else 'you'}: «{content}»"
        for turn, speaker, content in reversed(rows)
    ]


def audience_facts(conn, realm_id: int, turn: int, exclude_actor_id: int,
                   names_by_actor: dict[int, str]) -> list[str]:
    """@brief Who else the sovereign received in private this turn: the FACT
    only, never the content (approved design decision)."""
    rows = conn.execute(
        "SELECT DISTINCT actor_id FROM audiences WHERE realm_id = %s AND turn = %s"
        " AND speaker = 'sovereign' AND actor_id <> %s ORDER BY actor_id",
        (realm_id, turn, exclude_actor_id),
    ).fetchall()
    return [f"The sovereign received {names_by_actor.get(row[0], 'someone')} in private." for row in rows]


# ---------------------------------------------------------------- lessons

@dataclass
class Lesson:
    id: int
    text: str
    origin_turn: int
    confirmations: int
    last_confirmed_turn: int | None
    is_revision: bool


def current_lessons(conn, actor_id: int) -> list[Lesson]:
    """@brief Active lessons of one actor, oldest first."""
    return [
        Lesson(row[0], row[1], row[2], row[3], row[4], row[5] is not None)
        for row in conn.execute(
            "SELECT id, text, origin_turn, confirmations, last_confirmed_turn, previous_lesson_id"
            " FROM lessons WHERE actor_id = %s AND status = 'active' ORDER BY id",
            (actor_id,),
        )
    ]


def lesson_line(lesson: Lesson) -> str:
    """@brief How solid a lesson is, then its text: the briefing shows both."""
    if lesson.confirmations > 0:
        times = "once" if lesson.confirmations == 1 else f"{lesson.confirmations} times"
        tag = f"confirmed {times}, last in turn {lesson.last_confirmed_turn}"
    elif lesson.is_revision:
        tag = f"revised in turn {lesson.origin_turn}"
    else:
        tag = f"new in turn {lesson.origin_turn}"
    return f"[{tag}] {lesson.text}"


def _clean_action(raw: object) -> dict | None:
    """@brief Tolerate small format slips: key case and spaces ("reason "),
    a lesson number written as a string. None if it is not an object."""
    if not isinstance(raw, dict):
        return None
    item = {str(key).strip().lower(): value for key, value in raw.items()}
    number = item.get("lesson")
    if isinstance(number, str) and number.strip().isdigit():
        item["lesson"] = int(number.strip())
    item["action"] = str(item.get("action", "")).strip().lower()
    item["text"] = str(item.get("text", "")).strip()
    item["reason"] = str(item.get("reason", "")).strip()
    return item


def _action_error(item: dict, lesson_count: int, seen: set[int]) -> str:
    number = item.get("lesson")
    if not isinstance(number, int) or not 1 <= number <= lesson_count:
        return f"unknown lesson number {number!r}"
    if number in seen:
        return f"lesson {number} has more than one action"
    if item["action"] not in ("confirm", "revise", "drop"):
        return f"unknown action {item['action']!r} for lesson {number}"
    if item["action"] in ("revise", "drop") and not item["reason"]:
        return f"{item['action']} of lesson {number} needs a reason"
    if item["action"] == "revise" and not item["text"]:
        return f"revise of lesson {number} needs the new text"
    return ""


def split_revision(lessons: list[Lesson], actions: list, new_lessons: list[str],
                   max_lessons: int) -> tuple[list[dict], list[str], list[str]]:
    """@brief Keep the valid part of a reflection answer, discard the rest.

    One bad action no longer throws away the whole season (game 7 lost a
    season to a revise without a reason): it is discarded, the others apply.
    New lessons beyond the maximum are cut, the first ones kept.
    @param actions Items {lesson: 1-based number, action, text?, reason?}.
    @return (valid actions, new lessons to add, why each discarded item was discarded).
    """
    kept, discarded, seen = [], [], set()
    for raw in actions:
        item = _clean_action(raw)
        if item is None:
            discarded.append("an action that is not an object")
            continue
        error = _action_error(item, len(lessons), seen)
        if error:
            discarded.append(error)
            continue
        seen.add(item["lesson"])
        kept.append(item)
    new = [text for text in new_lessons if text.strip()]
    dropped = sum(1 for item in kept if item["action"] == "drop")
    room = max(max_lessons - (len(lessons) - dropped), 0)
    if len(new) > room:
        discarded.append(f"{len(new) - room} new lessons beyond the maximum of {max_lessons}")
        new = new[:room]
    return kept, new, discarded


def apply_revision(conn, game_id: int, realm_id: int, actor_id: int, turn: int,
                   lessons: list[Lesson], actions: list[dict], new_lessons: list[str]) -> None:
    """@brief Write the valid part of a revision (see split_revision), atomically."""
    with conn.transaction():
        for item in actions:
            lesson = lessons[item["lesson"] - 1]
            reason = item["reason"][:MAX_LESSON_CHARS]
            if item["action"] == "confirm":
                conn.execute(
                    "UPDATE lessons SET confirmations = confirmations + 1, last_confirmed_turn = %s"
                    " WHERE id = %s",
                    (turn, lesson.id),
                )
                continue
            new_status = "revised" if item["action"] == "revise" else "dropped"
            conn.execute(
                "UPDATE lessons SET status = %s, status_turn = %s, status_reason = %s WHERE id = %s",
                (new_status, turn, reason, lesson.id),
            )
            if item["action"] == "revise":
                _insert_lesson(conn, game_id, realm_id, actor_id, turn, item["text"], lesson.id)
        for text in new_lessons:
            if text.strip():
                _insert_lesson(conn, game_id, realm_id, actor_id, turn, text, None)


def _insert_lesson(conn, game_id, realm_id, actor_id, turn, text: str, previous_id: int | None) -> None:
    conn.execute(
        "INSERT INTO lessons (game_id, realm_id, actor_id, text, origin_turn, previous_lesson_id)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (game_id, realm_id, actor_id, text.strip()[:MAX_LESSON_CHARS], turn, previous_id),
    )
