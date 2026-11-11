"""@brief When the sovereign plays in a seasonal game (docs/DESIGN.md,
"Seasonal sovereign"). The engine stays monthly and the council meets every
month; the sovereign plays the first month of each season and the months
after an alarm. The other months are automatic: the automatic sovereign
approves the plan and the laws stay locked (server/sovereign/auto.py, R12).

The pure part decides from last month's events; the database part only reads
them. A realm's own events are read by the server itself (as auto.py does),
never shown as they are to a counsellor.
"""

import psycopg

from engine.turn import season_of
from server.ui import labels

SEASON_FIRST_MONTHS = (1, 4, 7, 10)  # January, April, July, October
UNREST_STEPS = ("calm", "protests", "strike", "revolt")
ALARM_STEPS = ("protests", "strike")  # revolt ends the game: no month to play after it
SEASON_OPENINGS = {"winter": "Inizio dell'inverno", "spring": "Inizio della primavera",
                   "summer": "Inizio dell'estate", "autumn": "Inizio dell'autunno"}


def is_season_start(turn: int) -> bool:
    return (turn - 1) % 12 + 1 in SEASON_FIRST_MONTHS


def next_season_start(turn: int) -> int:
    """@brief The first turn after this one that opens a season."""
    later = turn + 1
    while not is_season_start(later):
        later += 1
    return later


def _kinds(events: list[dict]) -> set[str]:
    return {e["kind"] for e in events}


def alarms(last_month: list[dict], month_before: list[dict]) -> list[str]:
    """@brief What calls the sovereign outside the season, in Italian.
    @param last_month The realm's events of the month just resolved.
    @param month_before The realm's events of the month before it (for the
           first flight of a stretch).
    Why only the first flight: in game 37 flight came every month from the
    protests on and called the sovereign every month; after the first one
    the unrest step already says the same."""
    reasons = []
    for event in last_month:
        kind, data = event["kind"], event["data"] or {}
        if kind == "famine":
            reasons.append("carestia")
        elif kind == "raid" and not data.get("repelled"):
            reasons.append("razzia non respinta")
        elif kind == "unrest_changed" and data.get("to") in ALARM_STEPS and \
                UNREST_STEPS.index(data["to"]) > UNREST_STEPS.index(data.get("from", "calm")):
            reasons.append(labels.UNREST[data["to"]])
    if "flight" in _kinds(last_month) and "flight" not in _kinds(month_before):
        reasons.append("fuga dal regno")
    return list(dict.fromkeys(reasons))  # in order, each once


def why_sovereign(turn: int, last_month: list[dict], month_before: list[dict]) -> str | None:
    """@brief Why the sovereign plays this month, in Italian; None for an automatic month."""
    if is_season_start(turn):
        return SEASON_OPENINGS[season_of(turn)]
    found = alarms(last_month, month_before)
    if found:
        return f"Allarme {labels.at_month(turn - 1)}: " + ", ".join(found)
    return None


# ------------------------------------------------------------ database

def game_rhythm(conn: psycopg.Connection, game_id: int) -> str:
    return conn.execute("SELECT rhythm FROM games WHERE id = %s", (game_id,)).fetchone()[0]


def _realm_events(conn: psycopg.Connection, realm_id: int, turn: int) -> list[dict]:
    if turn < 1:
        return []
    rows = conn.execute("SELECT kind, data FROM events WHERE realm_id = %s AND turn = %s ORDER BY id",
                        (realm_id, turn)).fetchall()
    return [{"kind": kind, "data": data} for kind, data in rows]


def sovereign_reason(conn: psycopg.Connection, game_id: int, realm_id: int, turn: int) -> str | None:
    """@brief Why the sovereign plays this turn; None when the month is automatic.
    A monthly game is the sovereign's every month."""
    if game_rhythm(conn, game_id) != "seasonal":
        return "Ogni mese"
    return why_sovereign(turn, _realm_events(conn, realm_id, turn - 1), _realm_events(conn, realm_id, turn - 2))


def is_automatic(conn: psycopg.Connection, game_id: int, realm_id: int, turn: int) -> bool:
    return sovereign_reason(conn, game_id, realm_id, turn) is None
