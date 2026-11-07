"""@brief Admin pages: the whole truth of every game, read-only.

Enabled only when the app is created with admin_view=True (ADMIN_VIEW=1 in
.env); otherwise every /admin page answers 404, as if it did not exist.
Until accounts exist anyone who reaches the server reaches these pages:
the server is only exposed on this PC and on the owner's Tailscale network.

OPEN DECISION (design doc): in games with friends this view shows their
private audiences and their ministers' lessons. Decide before the first
real multiplayer game whether the admin does not play, or whether running
games hide the other players' secrets here.
"""

import json
from collections.abc import Iterator
from dataclasses import asdict

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from server.council import meeting
from server.db import games
from server.db.replay import replay_game
from server.ui.routes import templates

router = APIRouter(prefix="/admin", include_in_schema=False)


def _admin_connection(request: Request) -> Iterator[psycopg.Connection]:
    """@brief 404 unless the admin view is on; then a pooled connection."""
    if not request.app.state.admin_view:
        raise HTTPException(404)
    with request.app.state.pool.connection() as conn:
        yield conn


def _pretty(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)


def _game_or_404(conn: psycopg.Connection, game_id: int) -> dict:
    game = games.load_game(conn, game_id)
    if game is None:
        raise HTTPException(404)
    return game


def _realm_game_or_404(conn: psycopg.Connection, realm_id: int) -> int:
    game_id = games.realm_game_id(conn, realm_id)
    if game_id is None:
        raise HTTPException(404)
    return game_id


@router.get("", response_class=HTMLResponse)
def admin_games(request: Request, conn=Depends(_admin_connection)):
    rows = conn.execute(
        "SELECT g.id, g.status::text, g.created_at,"
        " (SELECT number FROM turns t WHERE t.game_id = g.id AND t.status = 'open'),"
        " (SELECT string_agg(r.name, ', ' ORDER BY r.id) FROM realms r WHERE r.game_id = g.id),"
        " (SELECT coalesce(sum(c.cost_usd), 0) FROM model_calls c WHERE c.game_id = g.id),"
        " (SELECT count(*) FROM model_calls c WHERE c.game_id = g.id)"
        " FROM games g ORDER BY g.id DESC"
    ).fetchall()
    keys = ("id", "status", "created_at", "open_turn", "realms", "spent_usd", "calls")
    return templates.TemplateResponse(
        request, "admin_games.html", {"games": [dict(zip(keys, row)) for row in rows]}
    )


def _game_context(conn: psycopg.Connection, game_id: int) -> dict:
    game = _game_or_404(conn, game_id)
    realms = []
    for realm in game["realms"]:
        state = games.load_latest_state(conn, realm["id"])
        realms.append({
            **realm,
            "turn": state.turn,
            "mood": state.mood,
            "state_json": _pretty(asdict(state)),  # the FULL state, mood included
        })
    spend = conn.execute(
        "SELECT a.role, count(*), coalesce(sum(c.cost_usd), 0),"
        " count(*) FILTER (WHERE c.status <> 'ok')"
        " FROM model_calls c JOIN actors a ON a.id = c.actor_id WHERE c.game_id = %s"
        " GROUP BY a.role ORDER BY a.role",
        (game_id,),
    ).fetchall()
    return {
        "game": game,
        "realms": realms,
        "spend": [{"role": r[0], "calls": r[1], "usd": r[2], "failed": r[3]} for r in spend],
        "replay": None,
    }


@router.get("/games/{game_id}", response_class=HTMLResponse)
def admin_game(request: Request, game_id: int, conn=Depends(_admin_connection)):
    return templates.TemplateResponse(request, "admin_game.html", _game_context(conn, game_id))


@router.post("/games/{game_id}/replay", response_class=HTMLResponse)
def admin_replay(request: Request, game_id: int, conn=Depends(_admin_connection)):
    """@brief Re-run the game from its first snapshot. Writes nothing."""
    context = _game_context(conn, game_id)
    mismatch = replay_game(conn, game_id)
    context["replay"] = {"ok": mismatch is None, "mismatch": mismatch}
    return templates.TemplateResponse(request, "admin_game.html", context)


@router.get("/realms/{realm_id}/turns/{turn}", response_class=HTMLResponse)
def admin_turn(request: Request, realm_id: int, turn: int, conn=Depends(_admin_connection)):
    game_id = _realm_game_or_404(conn, realm_id)
    messages = meeting.list_messages(conn, realm_id, turn)
    for message in messages:
        message["payload_json"] = _pretty(message["payload"])
    calls = conn.execute(
        "SELECT c.id, a.role, c.model, c.status, c.input_tokens, c.output_tokens, c.cost_usd,"
        " c.latency_ms, c.error, c.reply_excerpt, c.prompt_system, c.prompt_user, c.created_at"
        " FROM model_calls c LEFT JOIN actors a ON a.id = c.actor_id"
        " WHERE c.realm_id = %s AND c.turn = %s ORDER BY c.id",
        (realm_id, turn),
    ).fetchall()
    keys = ("id", "role", "model", "status", "input_tokens", "output_tokens", "cost_usd",
            "latency_ms", "error", "reply_excerpt", "prompt_system", "prompt_user", "created_at")
    latest_turn = games.load_latest_state(conn, realm_id).turn
    context = {
        "game": _game_or_404(conn, game_id),
        "realm_id": realm_id,
        "turn": turn,
        "turns": list(range(1, latest_turn + 1)),
        "messages": messages,
        "calls": [dict(zip(keys, row)) for row in calls],
        "orders": games.list_orders(conn, realm_id, turn),
    }
    return templates.TemplateResponse(request, "admin_turn.html", context)


@router.get("/realms/{realm_id}/lessons", response_class=HTMLResponse)
def admin_lessons(request: Request, realm_id: int, conn=Depends(_admin_connection)):
    game_id = _realm_game_or_404(conn, realm_id)
    rows = conn.execute(
        "SELECT a.role, l.id, l.text, l.status::text, l.origin_turn, l.confirmations,"
        " l.last_confirmed_turn, l.status_turn, l.status_reason, l.previous_lesson_id"
        " FROM lessons l JOIN actors a ON a.id = l.actor_id WHERE l.realm_id = %s"
        " ORDER BY a.role, l.id",
        (realm_id,),
    ).fetchall()
    keys = ("role", "id", "text", "status", "origin_turn", "confirmations",
            "last_confirmed_turn", "status_turn", "status_reason", "previous_lesson_id")
    by_role: dict[str, list] = {}
    for row in rows:
        lesson = dict(zip(keys, row))
        by_role.setdefault(lesson["role"], []).append(lesson)
    context = {"game": _game_or_404(conn, game_id), "realm_id": realm_id, "by_role": by_role}
    return templates.TemplateResponse(request, "admin_lessons.html", context)


@router.get("/realms/{realm_id}/audiences", response_class=HTMLResponse)
def admin_audiences(request: Request, realm_id: int, conn=Depends(_admin_connection)):
    game_id = _realm_game_or_404(conn, realm_id)
    rows = conn.execute(
        "SELECT a.role, au.turn, au.speaker, au.content FROM audiences au"
        " JOIN actors a ON a.id = au.actor_id WHERE au.realm_id = %s ORDER BY a.role, au.id",
        (realm_id,),
    ).fetchall()
    by_role: dict[str, list] = {}
    for role, turn, speaker, content in rows:
        by_role.setdefault(role, []).append({"turn": turn, "speaker": speaker, "content": content})
    context = {"game": _game_or_404(conn, game_id), "realm_id": realm_id, "by_role": by_role}
    return templates.TemplateResponse(request, "admin_audiences.html", context)
