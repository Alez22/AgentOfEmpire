"""@brief The sovereign sees when a counsellor's plan reverses one of its recent
decisions (after game 34: ministers undid the sovereign's tax, doors and
merchants' tax the month after, and nothing on the page said so).

Only laws count: the people's tax, the merchants' tax, the ration and the
doors, decided in an approved plan or a granted petition in the last
WINDOW_MONTHS months. Workers, buildings and the militia change often and for
good reasons: flagging them would be noise. Information only: nothing is
blocked or unchecked.
"""

import psycopg

from server.db import games
from server.ui import labels

WINDOW_MONTHS = 3
LAWS = {"set_tax": "rate", "set_merchant_tax": "rate", "set_ration": "ration", "set_doors": "doors"}


def recent_decisions(conn: psycopg.Connection, realm_id: int, turn: int) -> dict[str, tuple[int, object]]:
    """@brief The latest executed law of each kind in the last WINDOW_MONTHS turns.
    Every stored order was approved by the sovereign (plan) or granted by it
    (petition); only the accepted ones changed the law.
    @return {action: (turn, value)}."""
    decisions = {}
    for past in range(max(1, turn - WINDOW_MONTHS), turn):
        for order in games.list_orders(conn, realm_id, past):
            action = order["raw"].get("action")
            if action in LAWS and order["accepted"]:
                decisions[action] = (past, order["raw"].get(LAWS[action]))
    return decisions


def _change(action: str, old, new) -> str:
    if action == "set_tax":
        return f"gabella dal {old}% al {new}%"
    if action == "set_merchant_tax":
        return f"tassa dei mercanti dal {old}% al {new}%"
    if action == "set_ration":
        return f"razione da {labels.RATIONS.get(old, old)} a {labels.RATIONS.get(new, new)}"
    return f"porte da {labels.DOORS.get(old, old)} a {labels.DOORS.get(new, new)}"


def reversal_lines(decisions: dict[str, tuple[int, object]], plan: list[dict],
                   names: dict[str, str]) -> dict[int, str]:
    """@brief Pure: the plan items that change a law the sovereign set recently.
    @param plan The Chancellor's plan items ({"order": ..., "proposer": ...}).
    @param names The counsellors' names by role (games.role_names).
    @return {plan index: Italian line}."""
    lines = {}
    for index, item in enumerate(plan):
        action = item["order"].get("action")
        if action not in decisions:
            continue
        past, old = decisions[action]
        new = item["order"].get(LAWS[action])
        if new == old:
            continue
        who = names.get(item.get("proposer"), labels.ROLES.get(item.get("proposer"), labels.SOVEREIGN)["name"])
        lines[index] = f"{who} cambia una tua decisione di {labels.month_name(past)}: {_change(action, old, new)}."
    return lines
