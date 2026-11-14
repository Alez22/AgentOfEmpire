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

from engine.territory import is_hex
from server.council import audience, meeting, notes, voice
from server.council.meeting import render_prompt
from server.council.personality import TRAITS, trait_word
from server.db import games
from server.db.replay import replay_game
from server.ui import labels, world_view
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


def _all_bands(conn: psycopg.Connection, game: dict, turn: int | None = None) -> list[dict]:
    """@brief Every band of the game at the start of `turn` (None: its latest
    stored month), with its adults and target (the admin sees the whole truth;
    players never do)."""
    if turn is None:
        turn = conn.execute("SELECT max(turn) FROM bandit_pools WHERE game_id = %s", (game["id"],)).fetchone()[0]
    pool = games.load_pool(conn, game["id"], turn) if turn else None
    if pool is None:
        return []
    names = {str(r["id"]): r["name"] for r in game["realms"]}
    marks = []
    for band in pool.bands:
        target = f", ultimo bersaglio {names.get(band.target, band.target)}" if band.target else ""
        marks.append({"x": band.x, "y": band.y, "text": str(band.adults),
                      "title": f"Banda {band.id}: {band.adults} adulti, {band.children} bambini, "
                               f"{band.food} cibo{target}"})
    return marks


# Seconds between two frames of the timelapse: long enough to read the month's
# events, short enough to watch a 24-month game in under a minute.
TIMELAPSE_SECONDS = 2


def _month_events(conn: psycopg.Connection, game: dict, turn: int) -> list[dict]:
    """@brief Every event of one month in every realm, read as the server
    (the admin sees all): each {"key", "realm", "kind", "data"}, where key is
    the engine's realm key (the realm id as text)."""
    names = {r["id"]: r["name"] for r in game["realms"]}
    rows = conn.execute("SELECT realm_id, kind, data FROM events WHERE game_id = %s AND turn = %s ORDER BY id",
                        (game["id"], turn)).fetchall()
    return [{"key": str(realm_id), "realm": names.get(realm_id, ""), "kind": kind, "data": data}
            for realm_id, kind, data in rows]


def _notable_lines(events: list[dict]) -> list[dict]:
    """@brief The month's lines beside the timelapse: the chronicle's boxed
    events (raids, flights, arrivals, robbed caravans), finished buildings and falls."""
    lines = []
    for event in events:
        kind, data = event["kind"], event["data"]
        if labels.event_alert(kind, data) is None and kind not in ("building_completed", "game_over"):
            continue
        lines.append({"realm": event["realm"], "text": labels.event_label(kind, data)})
    return lines


def _month_moves(conn: psycopg.Connection, config, game: dict, frame: int, realms: list[dict],
                 events: list[dict]) -> dict:
    """@brief What moved on the roads in the month before `frame`: the
    caravans and the raids (world_view.caravan_routes, raid_arrows), and the
    bandits in the woods, who have no place on the map.
    Why only the realms whose snapshot is exactly `frame`: those are the
    realms the world step of that month resolved (a realm fallen earlier
    gets no more snapshots and was not on the month's RoadMap)."""
    month_states = {r["key"]: r["state"] for r in realms if r["state"].turn == frame}
    colors = {r["key"]: r["color"] for r in realms}
    pool = games.load_pool(conn, game["id"], frame)
    bands = pool.bands if pool is not None else []
    return {"caravans": world_view.caravan_routes(config, month_states, events, colors),
            "raids": world_view.raid_arrows(config, month_states, events, bands),
            "pool_adults": pool.adults if pool is not None else None}


def _timelapse(game_id: int, turn: int, last_turn: int, play: bool, zoom: int) -> dict:
    """@brief Links and labels of the timelapse controls for the frame `turn`.
    Frame N is the world at the start of month N (snapshot turn N), so the
    events beside it are those of month N - 1, the ones that led to it."""
    base = f"/admin/games/{game_id}/world?zoom={zoom}&turn="
    playing = play and turn < last_turn  # the last frame stops the play
    return {"turn": turn, "last": last_turn, "playing": playing,
            "month": labels.month_name(turn), "year": (turn - 1) // 12 + 1,
            "prev_href": base + str(turn - 1) if turn > 1 else None,
            "next_href": base + str(turn + 1) if turn < last_turn else None,
            "play_href": base + str(1 if turn >= last_turn else turn) + "&play=1",
            "pause_href": base + str(turn),
            "refresh": f"{TIMELAPSE_SECONDS};url={base}{turn + 1}&play=1" if playing else None,
            "turns": list(range(1, last_turn + 1))}


@router.get("/games/{game_id}/world", response_class=HTMLResponse)
def admin_world(request: Request, game_id: int, zoom: int = 0, turn: int = 0, play: int = 0,
                conn=Depends(_admin_connection)):
    """@brief The whole world in the clear: every realm's land, buildings and
    border, each in its colour (server/ui/world_view.py); fallen realms in grey.
    @param turn 0 = the latest state; N = the world at the start of month N
           (the timelapse: no JavaScript, a page per frame).
    @param play 1 = the page reloads itself on the next frame (meta refresh)."""
    game = _game_or_404(conn, game_id)
    config = games.load_game_config(conn, game_id)
    last_turn = games.last_snapshot_turn(conn, game_id)
    frame = min(turn, last_turn) if turn > 0 else None
    realms, terrain = [], None
    for index, realm in enumerate(game["realms"]):
        if frame is None:
            state = games.load_latest_state(conn, realm["id"])
        else:
            state = games.load_state_at(conn, realm["id"], frame)
        if state is None or not state.has_map():
            continue
        terrain = terrain or state.terrain
        realms.append({"key": str(realm["id"]), "name": realm["name"], "state": state,
                       "fallen": state.game_over is not None,
                       "color": world_view.REALM_COLORS[index % len(world_view.REALM_COLORS)]})
    board, events, moves = None, [], {}
    if frame and frame > 1:
        events = _month_events(conn, game, frame - 1)
    if terrain and is_hex(config):
        board = world_view.world_board(config, terrain, realms, _all_bands(conn, game, frame))
        if frame and frame > 1:
            moves = _month_moves(conn, config, game, frame, realms, events)
    zoom_query = "" if zoom else "?zoom=1"
    if frame is not None:
        zoom_query = f"?zoom={0 if zoom else 1}&turn={frame}"
    timelapse = _timelapse(game_id, frame or last_turn, last_turn, bool(play), zoom)
    context = {"game": game, "turn": frame or game["open_turn"], "board": board, "admin": True,
               "zoom": bool(zoom), "timelapse": timelapse, "moves": moves,
               "month_events": _notable_lines(events),
               "bands_legend": "Banda (adulti dentro)" if config.bands is not None else None,
               "zoom_href": f"/admin/games/{game_id}/world" + zoom_query}
    return templates.TemplateResponse(request, "world.html", context)


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
        "people": _people_decision(conn, realm_id, turn),
        "notes": notes.notes_of_turn(conn, realm_id, turn),  # secret: admin only
    }
    return templates.TemplateResponse(request, "admin_turn.html", context)


def _people_decision(conn: psycopg.Connection, realm_id: int, turn: int) -> dict | None:
    """@brief The whole decision of the people, the model's reason included."""
    row = conn.execute(
        "SELECT d.effort_pct, d.birth_pct, d.petition, d.petition_text, d.reason, d.source, a.answer,"
        " d.petition_weight"
        " FROM people_decisions d LEFT JOIN petition_answers a ON a.decision_id = d.id"
        " WHERE d.realm_id = %s AND d.turn = %s",
        (realm_id, turn),
    ).fetchone()
    keys = ("effort_pct", "birth_pct", "petition", "petition_text", "reason", "source", "answer",
            "petition_weight")
    return None if row is None else dict(zip(keys, row))


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


# ------------------------------------------------------------------ agents

AGENT_ORDER = ("chancellor", "treasurer", "architect", "gastaldo", "square_voice", "people")


def _prompt_context(conn: psycopg.Connection, realm_id: int, settings) -> meeting.MeetingContext:
    """@brief Enough context to render system prompts, with or without an open turn.

    meeting.load_context needs an open turn; a finished game has none, and
    the prompts depend only on realm name, settings, config and personality.
    No client: nothing here may call a model.
    """
    game_id, realm_name = conn.execute(
        "SELECT game_id, name FROM realms WHERE id = %s", (realm_id,)
    ).fetchone()
    actors = {
        role: meeting.Actor(actor_id, role, model, personality.get("traits", {}), personality)
        for actor_id, role, model, personality in conn.execute(
            "SELECT id, role, model, personality FROM actors WHERE realm_id = %s", (realm_id,)
        )
    }
    state = games.load_latest_state(conn, realm_id)
    return meeting.MeetingContext(
        conn, None, settings, game_id, realm_id, realm_name, state.turn,
        state, games.load_game_config(conn, game_id), actors,
    )


def _system_prompts(ctx: meeting.MeetingContext, actor: meeting.Actor) -> list[dict]:
    """@brief Every system prompt this agent can receive, built by the same
    functions the council uses, so the page cannot drift from what is sent.
    """
    if actor.role == "people":
        return [{"label": "Decisione del mese", "text": render_prompt(
            "people_system.txt", realm_name=ctx.realm_name, language=ctx.settings.language)}]
    if actor.role == "square_voice":
        return [
            {"label": "Racconto del mese", "text": voice.voice_system(ctx, season=False)},
            {"label": "Racconto di inizio stagione", "text": voice.voice_system(ctx, season=True)},
        ]
    if actor.role == "chancellor":
        council = meeting._chancellor_system(ctx, actor)
    else:
        council = meeting._minister_system(ctx, actor)
    return [
        {"label": "Riunione del consiglio", "text": council},
        {"label": "Revisione delle lezioni (fine stagione)", "text": meeting._lessons_system(ctx, actor)},
        {"label": "Udienza privata", "text": audience._system(ctx, actor)},
    ]


def _last_call(conn: psycopg.Connection, actor_id: int) -> dict | None:
    """@brief The newest call that stored its prompts (migration 006 onwards)."""
    row = conn.execute(
        "SELECT turn, prompt_user, created_at FROM model_calls"
        " WHERE actor_id = %s AND prompt_user IS NOT NULL ORDER BY id DESC LIMIT 1",
        (actor_id,),
    ).fetchone()
    return None if row is None else {"turn": row[0], "briefing": row[1], "created_at": row[2]}


def _agent_card(conn: psycopg.Connection, ctx: meeting.MeetingContext, actor: meeting.Actor) -> dict:
    calls, usd = conn.execute(
        "SELECT count(*), coalesce(sum(cost_usd), 0) FROM model_calls WHERE actor_id = %s",
        (actor.id,),
    ).fetchone()
    traits = [
        {"name": trait, "value": actor.traits[trait], "words": trait_word(trait, actor.traits[trait])}
        for trait in TRAITS if trait in actor.traits
    ]
    return {
        "role": actor.role,
        "model": actor.model,
        "reasoning": ctx.settings.reasoning_effort.get(actor.role),
        "calls": calls,
        "usd": usd,
        "traits": traits,
        "prompts": _system_prompts(ctx, actor),
        "last_call": _last_call(conn, actor.id),
    }


@router.get("/realms/{realm_id}/agents", response_class=HTMLResponse)
def admin_agents(request: Request, realm_id: int, conn=Depends(_admin_connection)):
    game_id = _realm_game_or_404(conn, realm_id)
    ctx = _prompt_context(conn, realm_id, request.app.state.council_settings)
    cards = [_agent_card(conn, ctx, ctx.actors[role]) for role in AGENT_ORDER if role in ctx.actors]
    missing = [role for role in AGENT_ORDER if role not in ctx.actors]
    context = {"game": _game_or_404(conn, game_id), "realm_id": realm_id,
               "realm_name": ctx.realm_name, "cards": cards, "missing": missing}
    return templates.TemplateResponse(request, "admin_agents.html", context)
