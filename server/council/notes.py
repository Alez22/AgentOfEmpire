"""@brief Secret notes between council members: at most one a month per
counsellor, to one colleague, written inside its usual council reply (no
extra model call) and delivered at the next meeting.

SECRECY: nothing outside the `counsel_notes` table records a note, not
even that one was sent. Only the sender and the recipient read it (in
their own briefings), and the admin view. The sovereign can only ask in
a private audience; the counsellor decides whether to tell.
"""

import psycopg

from server.council.briefing import MONTHS

NOTE_ROLES = ("treasurer", "architect", "chancellor")
MAX_NOTE_CHARS = 400
NOTE_HISTORY_TURNS = 3  # notes of the last turns in each briefing


def store_note(conn: psycopg.Connection, game_id: int, realm_id: int, turn: int,
               actors: dict, sender, raw: object) -> str:
    """@brief Keep a valid note; ignore anything else.
    @param actors role -> Actor of the realm.
    @return "" if stored or there was no note, otherwise why it was dropped
            (for the admin's eyes in the call log).
    """
    if raw is None:
        return ""
    if not isinstance(raw, dict):
        return "note dropped: not an object"
    recipient_role = str(raw.get("to", "")).strip().lower()
    text = str(raw.get("text", "")).strip()[:MAX_NOTE_CHARS]
    recipient = actors.get(recipient_role)
    if recipient_role not in NOTE_ROLES or recipient is None or recipient.id == sender.id:
        return f"note dropped: unknown recipient {recipient_role!r}"
    if not text:
        return "note dropped: empty"
    # A second council round (after a directive) cannot add a second note.
    conn.execute(
        "INSERT INTO counsel_notes (game_id, realm_id, turn, sender_actor_id, recipient_actor_id, content)"
        " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (sender_actor_id, turn) DO NOTHING",
        (game_id, realm_id, turn, sender.id, recipient.id, text),
    )
    return ""


def note_lines(conn: psycopg.Connection, actor_id: int, first_turn: int, last_turn: int,
               names_by_actor: dict[int, str]) -> list[str]:
    """@brief This actor's own notes, received and sent, oldest first.
    @param last_turn Inclusive; pass turn - 1 so a note is read the month after."""
    rows = conn.execute(
        "SELECT turn, sender_actor_id, recipient_actor_id, content FROM counsel_notes"
        " WHERE (sender_actor_id = %s OR recipient_actor_id = %s) AND turn >= %s AND turn <= %s"
        " ORDER BY turn, id",
        (actor_id, actor_id, first_turn, last_turn),
    ).fetchall()
    if not rows:
        return []
    lines = ["## Secret notes (nobody else knows they exist, not even the sovereign)"]
    for turn, sender, recipient, content in rows:
        month = MONTHS[(turn - 1) % 12]
        if sender == actor_id:
            lines.append(f"- {month}: you wrote to {names_by_actor.get(recipient, '?')}: «{content}»")
        else:
            lines.append(f"- {month}: {names_by_actor.get(sender, '?')} wrote to you: «{content}»")
    return lines


def notes_of_turn(conn: psycopg.Connection, realm_id: int, turn: int) -> list[dict]:
    """@brief Every note written in a turn (admin view only)."""
    rows = conn.execute(
        "SELECT s.role, r.role, n.content FROM counsel_notes n"
        " JOIN actors s ON s.id = n.sender_actor_id JOIN actors r ON r.id = n.recipient_actor_id"
        " WHERE n.realm_id = %s AND n.turn = %s ORDER BY n.id",
        (realm_id, turn),
    ).fetchall()
    return [{"sender": s, "recipient": r, "content": c} for s, r, c in rows]
