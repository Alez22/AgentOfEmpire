"""@brief Web UI for the phone: HTML pages rendered on the server (Jinja2),
plain forms for every action, HTMX only to poll the council while it meets.

Every action is a POST form answered with a redirect to a GET page
(post/redirect/get), so it works even without JavaScript and a reload
never repeats an action. Errors travel back as an ?error= message.

Security: every text from the models or the player is escaped by Jinja2
(autoescape on), so a model answering with HTML cannot inject markup.
There is no authentication yet: see the ports comment in compose.yaml.
"""

import secrets
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import jinja2
import psycopg
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from engine import migration
from engine.config import load_raw_config
from engine.territory import owned_count
from engine.turn import food_needed, housing_capacity, jobs_in_sector, season_of
from server.council import audience, debate, mandates, manual, meeting, people, persons
from server.council.briefing import GATE_MEMORY_TURNS, months_until_winter
from server.db import games
from server.sovereign_view import sovereign_state
from server.ui import labels, map_view, market_view, reversals

TEMPLATES_DIR = Path(__file__).with_name("templates")
_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATES_DIR), autoescape=True
)
_environment.globals["labels"] = labels
templates = Jinja2Templates(env=_environment)

router = APIRouter()


def _connection(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.pool.connection() as conn:
        yield conn


def _turn_page(realm_id: int, error: str = "") -> RedirectResponse:
    url = f"/ui/realms/{realm_id}"
    if error:
        url += f"?error={quote(error)}"
    return RedirectResponse(url, status_code=303)


def _not_found(request: Request, what: str) -> HTMLResponse:
    return templates.TemplateResponse(request, "not_found.html", {"what": what}, status_code=404)


# ------------------------------------------------------------- games

@router.get("/", include_in_schema=False)
def home() -> RedirectResponse:
    return RedirectResponse("/ui", status_code=303)


@router.get("/ui", response_class=HTMLResponse)
def games_page(request: Request, conn=Depends(_connection)):
    rows = conn.execute(
        "SELECT g.id, g.status::text, g.created_at, r.id, r.name,"
        " (SELECT number FROM turns t WHERE t.game_id = g.id AND t.status = 'open')"
        " FROM games g JOIN realms r ON r.game_id = g.id ORDER BY g.id DESC"
    ).fetchall()
    game_list = [
        {"id": r[0], "status": r[1], "created_at": r[2], "realm_id": r[3], "realm_name": r[4], "open_turn": r[5]}
        for r in rows
    ]
    return templates.TemplateResponse(request, "games.html", {"games": game_list})


@router.post("/ui/games")
def create_game(request: Request, realm_name: str = Form("Nord"), conn=Depends(_connection)):
    settings = request.app.state.council_settings
    seed = secrets.randbelow(1_000_000)  # a new world each time
    name = realm_name.strip()[:40] or "Nord"
    game_id = games.create_game(conn, load_raw_config(), seed, [name], settings.models,
                                personas=persons.load_catalog(), model_tiers=settings.model_tiers)
    realm_id = games.load_game(conn, game_id)["realms"][0]["id"]
    return _turn_page(realm_id)


# -------------------------------------------------------------- turn

def _council_context(request: Request, conn: psycopg.Connection, realm_id: int, game: dict) -> dict:
    """@brief Everything the council panel shows for the open turn."""
    jobs = request.app.state.council_jobs
    context = {
        "realm_id": realm_id,
        # Only a council round counts here; a private audience has its own page.
        "running": jobs.running_kind(realm_id) in ("meeting", "directive", "debate"),
        # A failed meeting or directive round; audience failures stay on their page.
        "job_error": (jobs.last_error(realm_id, "meeting") or jobs.last_error(realm_id, "directive")
                      or jobs.last_error(realm_id, "debate")),
        "open_turn": game["open_turn"],
        "council": None,
        "messages": [],
        "plan": None,
        "reversals": {},  # plan index -> line: a counsellor changes a recent decision of the sovereign
        "orders": [],
        "rounds": [],
        "people": None,
        "debated": False,
        "names": games.role_names(conn, realm_id),
    }
    if game["open_turn"] is None:
        return context
    context["people"] = people.decision_for_sovereign(conn, realm_id, game["open_turn"])
    settings = request.app.state.council_settings
    context["council"] = meeting.council_state(conn, realm_id, settings)
    context["messages"] = meeting.list_messages(conn, realm_id, game["open_turn"])
    round_numbers = sorted({m["round"] for m in context["messages"]})
    context["rounds"] = [
        {"number": n, "messages": [m for m in context["messages"] if m["round"] == n]}
        for n in round_numbers
    ]
    latest_round = max((m["round"] for m in context["messages"]), default=0)
    context["debated"] = any(m["kind"] == "comment" and m["round"] == latest_round
                             for m in context["messages"])
    summaries = [m for m in context["messages"] if m["kind"] == "summary"]
    if summaries:
        context["plan"] = summaries[-1]["payload"]
        context["reversals"] = reversals.reversal_lines(
            reversals.recent_decisions(conn, realm_id, game["open_turn"]), context["plan"]["plan"], context["names"])
    context["orders"] = games.list_orders(conn, realm_id, game["open_turn"])
    return context


@router.get("/ui/realms/{realm_id}", response_class=HTMLResponse)
def turn_page(request: Request, realm_id: int, error: str = "", conn=Depends(_connection)):
    game_id = games.realm_game_id(conn, realm_id)
    if game_id is None:
        return _not_found(request, f"il regno {realm_id}")
    game = games.load_game(conn, game_id)
    state = games.load_latest_state(conn, realm_id)
    last_month = []
    if state.turn > 1:
        last_month = games.list_events_for_sovereign(conn, game_id, realm_id, state.turn - 1)
    context = {
        "game": game,
        "realm": next(r for r in game["realms"] if r["id"] == realm_id),
        "state": sovereign_state(state),  # never the full state: no mood
        "season": labels.SEASONS[season_of(state.turn)],
        "winter_in": months_until_winter(state.turn),
        "last_month": [e for e in last_month if e["realm_id"] == realm_id],
        "error": error,
        "nav": "turn",
    }
    context.update(_council_context(request, conn, realm_id, game))
    return templates.TemplateResponse(request, "turn.html", context)


@router.get("/ui/realms/{realm_id}/council-panel", response_class=HTMLResponse)
def council_panel(request: Request, realm_id: int, conn=Depends(_connection)):
    """@brief Polled by HTMX every 2 s while the council meets."""
    game_id = games.realm_game_id(conn, realm_id)
    if game_id is None:
        return _not_found(request, f"il regno {realm_id}")
    context = _council_context(request, conn, realm_id, games.load_game(conn, game_id))
    return templates.TemplateResponse(request, "_council.html", context)


def _start_round(request: Request, realm_id: int, kind: str, check, work,
                 back=None) -> RedirectResponse:
    """@brief Reserve the realm, run the cheap checks now, the model work in
    background. One model job per realm at a time: meeting, directive or audience.
    @param back Builds the redirect from an error message ("" = none);
           defaults to the turn page.
    """
    back = back or (lambda error="": _turn_page(realm_id, error))
    jobs = request.app.state.council_jobs
    if not jobs.reserve(realm_id, kind):
        return back("Il consiglio è occupato: aspetta che finisca.")
    try:
        with request.app.state.pool.connection() as conn:
            check(conn)
    except meeting.CouncilError as error:
        jobs.release(realm_id)
        return back(str(error))
    pool, client = request.app.state.pool, request.app.state.llm_client

    def background() -> None:
        with pool.connection() as conn:
            work(conn, client)

    jobs.start(realm_id, background)
    return back()


@router.post("/ui/realms/{realm_id}/meeting")
def start_meeting(request: Request, realm_id: int):
    settings = request.app.state.council_settings
    return _start_round(
        request, realm_id, "meeting",
        lambda conn: meeting.check_meeting_allowed(conn, realm_id),
        lambda conn, client: meeting.hold_meeting(conn, realm_id, client, settings),
    )


@router.post("/ui/realms/{realm_id}/directive")
def give_directive(request: Request, realm_id: int, text: str = Form(...)):
    settings = request.app.state.council_settings
    text = text.strip()[:500]
    if not text:
        return _turn_page(realm_id, "Scrivi la direttiva prima di inviarla.")
    return _start_round(
        request, realm_id, "directive",
        lambda conn: meeting.check_directive_allowed(conn, realm_id, settings),
        lambda conn, client: meeting.give_directive(conn, realm_id, client, settings, text),
    )


@router.post("/ui/realms/{realm_id}/debate")
def ask_debate(request: Request, realm_id: int):
    """@brief The ministers comment on the plan, in the background."""
    settings = request.app.state.council_settings
    return _start_round(
        request, realm_id, "debate",
        lambda conn: debate.check_debate_allowed(conn, realm_id),
        lambda conn, client: debate.hold_debate(conn, realm_id, client, settings),
    )


@router.post("/ui/realms/{realm_id}/approve")
def approve_plan(request: Request, realm_id: int, plan_size: int = Form(...),
                 keep: list[int] = Form(default=[]), conn=Depends(_connection)):
    """@brief The form ticks the orders to KEEP (all ticked at first); the
    engine call wants the ones to remove. A wrong plan_size is caught by
    approve_plan(), which checks every position against the stored plan."""
    if request.app.state.council_jobs.is_running(realm_id):
        return _turn_page(realm_id, "Aspetta che il consiglio finisca.")
    exclude = [index for index in range(plan_size) if index not in keep]
    try:
        meeting.approve_plan(conn, realm_id, exclude)
    except (meeting.CouncilError, ValueError) as error:
        return _turn_page(realm_id, str(error))
    return _turn_page(realm_id)


@router.post("/ui/realms/{realm_id}/resolve")
def resolve_turn(request: Request, realm_id: int, conn=Depends(_connection)):
    if request.app.state.council_jobs.is_running(realm_id):
        return _turn_page(realm_id, "Aspetta che il consiglio finisca prima di chiudere il mese.")
    game_id = games.realm_game_id(conn, realm_id)
    try:
        games.resolve_open_turn(conn, game_id)
    except (games.NoOpenTurnError, games.GamePausedError, games.EngineVersionError) as error:
        return _turn_page(realm_id, str(error))
    return _turn_page(realm_id)


@router.post("/ui/realms/{realm_id}/petition")
def answer_petition(realm_id: int, answer: str = Form(...), conn=Depends(_connection)):
    """@brief The sovereign grants or refuses the people's petition."""
    try:
        people.answer_petition(conn, realm_id, answer)
    except (meeting.CouncilError, ValueError) as error:
        return _turn_page(realm_id, str(error))
    return _turn_page(realm_id)


# ------------------------------------------------------------- government

def _government_page(realm_id: int, error: str = "") -> RedirectResponse:
    url = f"/ui/realms/{realm_id}/government"
    if error:
        url += f"?error={quote(error)}"
    return RedirectResponse(url, status_code=303)


# Months of arrivals on the kingdom page (village block B+C, stage 2): a year,
# long enough to see whether the houses fill with newcomers.
NEWCOMERS_MONTHS = 12


def _arrivals(conn: psycopg.Connection, game_id: int, realm_id: int, now_turn: int, months: int) -> dict:
    """@brief Newcomers of the last months, from the events the sovereign may see:
    {"adults", "children", "from_raids"} summed."""
    total = {"adults": 0, "children": 0, "from_raids": 0}
    for turn in range(max(1, now_turn - months), now_turn):
        for event in games.list_events_for_sovereign(conn, game_id, realm_id, turn):
            if event["realm_id"] == realm_id and event["kind"] == "arrival":
                for key in total:
                    total[key] += event["data"].get(key, 0)
    return total


def _doors_card(conn: psycopg.Connection, game_id: int, realm_id: int, state, config) -> dict | None:
    """@brief The doors on the Gastaldo's card (stage 2); None in games without them."""
    if config.migration is None:
        return None
    in_force = migration.doors_in_force(state, config.migration)
    return {"doors": in_force, "word": labels.DOORS[in_force], "hint": labels.DOORS_HINTS[in_force],
            "not_held": state.doors == "closed" and in_force != "closed",
            "min_guards": config.migration.closed_min_guards,
            "free_beds": migration.free_beds(state, config), "empty_jobs": migration.empty_jobs(state, config),
            "arrived": _arrivals(conn, game_id, realm_id, state.turn, GATE_MEMORY_TURNS)}


def _gate_card(conn: psycopg.Connection, realm_id: int) -> dict:
    """@brief The Gastaldo's card on the government page (village block B+C):
    the guards, the raiders they stop, the last raid and the flights of the
    last months, from the events the sovereign may see. Never the bandits'
    number: nobody can count them."""
    game_id = games.realm_game_id(conn, realm_id)
    state = games.load_latest_state(conn, realm_id)
    config = games.load_game_config(conn, game_id)
    last_raid, flights = None, 0
    for turn in range(state.turn - 1, 0, -1):  # newest first
        own = [e for e in games.list_events_for_sovereign(conn, game_id, realm_id, turn) if e["realm_id"] == realm_id]
        if state.turn - turn <= GATE_MEMORY_TURNS:
            flights += sum(1 for e in own if e["kind"] == "flight")
        if last_raid is None and any(e["kind"] == "raid" for e in own):
            last_raid = labels.month_name(turn)
        if last_raid is not None and state.turn - turn >= GATE_MEMORY_TURNS:
            break
    repel = config.bandits.repel_per_guard if config.bandits else 0
    return {"guards": state.militia, "stops": state.militia * repel, "last_raid": last_raid,
            "flights": flights, "months": GATE_MEMORY_TURNS,
            "doors": _doors_card(conn, game_id, realm_id, state, config)}


def _government_context(request: Request, conn: psycopg.Connection, realm_id: int) -> dict:
    jobs = request.app.state.council_jobs
    kind = jobs.running_kind(realm_id) or ""
    game = games.load_game(conn, games.realm_game_id(conn, realm_id))
    offices = mandates.government(conn, realm_id)
    return {
        "realm_id": realm_id,
        "offices": offices,
        "gate": _gate_card(conn, realm_id) if any(o["role"] == "gastaldo" for o in offices) else None,
        "watch_open": games.load_game_config(conn, game["id"]).bandits is not None,
        "names": games.role_names(conn, realm_id),
        "open_turn": game["open_turn"],
        "running": kind.startswith("mandate:"),
        "running_role": kind.removeprefix("mandate:") if kind.startswith("mandate:") else None,
        "job_errors": {role: jobs.last_error(realm_id, f"mandate:{role}") for role in mandates.MANDATE_ROLES},
        "max_chars": mandates.MAX_REQUEST_CHARS,
    }


@router.get("/ui/realms/{realm_id}/government", response_class=HTMLResponse)
def government_page(request: Request, realm_id: int, error: str = "", conn=Depends(_connection)):
    if games.realm_game_id(conn, realm_id) is None:
        return _not_found(request, f"il regno {realm_id}")
    context = _government_context(request, conn, realm_id)
    context.update({"error": error, "nav": "government"})
    return templates.TemplateResponse(request, "government.html", context)


@router.get("/ui/realms/{realm_id}/government/panel", response_class=HTMLResponse)
def government_panel(request: Request, realm_id: int, conn=Depends(_connection)):
    """@brief Polled by HTMX every 2 s while the chancellery reviews a request."""
    if games.realm_game_id(conn, realm_id) is None:
        return _not_found(request, f"il regno {realm_id}")
    return templates.TemplateResponse(request, "_government.html", _government_context(request, conn, realm_id))


@router.post("/ui/realms/{realm_id}/government/{role}")
def request_mandate(request: Request, realm_id: int, role: str, text: str = Form(...)):
    settings = request.app.state.council_settings
    text = text.strip()
    return _start_round(
        request, realm_id, f"mandate:{role}",
        lambda conn: mandates.check_request(conn, realm_id, role, text),
        lambda conn, client: mandates.review(conn, realm_id, role, text, client, settings),
        back=lambda error="": _government_page(realm_id, error),
    )


@router.get("/ui/realms/{realm_id}/manual", response_class=HTMLResponse)
def manual_page(request: Request, realm_id: int, conn=Depends(_connection)):
    """@brief How the realm works, from this game's own config (the same
    facts the counsellors read, in Italian)."""
    game_id = games.realm_game_id(conn, realm_id)
    if game_id is None:
        return _not_found(request, f"il regno {realm_id}")
    sections = manual.page_sections(games.load_game_config(conn, game_id))
    return templates.TemplateResponse(request, "manual.html",
                                      {"realm_id": realm_id, "sections": sections, "nav": "manual"})


# ------------------------------------------------- kingdom and chronicle

@router.get("/ui/realms/{realm_id}/kingdom", response_class=HTMLResponse)
def kingdom_page(request: Request, realm_id: int, conn=Depends(_connection)):
    game_id = games.realm_game_id(conn, realm_id)
    if game_id is None:
        return _not_found(request, f"il regno {realm_id}")
    game = games.load_game(conn, game_id)
    state = games.load_latest_state(conn, realm_id)
    config = games.load_game_config(conn, game_id)
    buildings = {}
    for building in state.buildings:
        entry = buildings.setdefault(building.kind, {"active": 0, "building": 0})
        entry["active" if building.turns_left == 0 else "building"] += 1
    context = {
        "game": game,
        "realm": next(r for r in game["realms"] if r["id"] == realm_id),
        "state": sovereign_state(state),  # never the full state: no mood
        "food_needed": food_needed(state, config),
        "housing": housing_capacity(state, config),
        "jobs": {sector: jobs_in_sector(state, config, sector) for sector in ("food", "wood", "stone", "trade")},
        # Village block A: the merchants' row only where the market is a building.
        "village_market": config.market is not None and config.market.needs_building,
        "buildings": buildings,
        # On the map the free space is the land, not a count of free tiles.
        "land": ({"owned": owned_count(state), "wild": len(state.clearing_queue)} if state.has_map() else None),
        # Stage 2: the doors among the laws (normal before the watchtower too) and the year's newcomers.
        "doors": (labels.DOORS[migration.doors_in_force(state, config.migration)]
                  if config.migration is not None else None),
        "newcomers": (_arrivals(conn, game_id, realm_id, state.turn, NEWCOMERS_MONTHS)
                      if config.migration is not None else None),
        "newcomers_months": NEWCOMERS_MONTHS,
        "nav": "kingdom",
        "realm_id": realm_id,
    }
    return templates.TemplateResponse(request, "kingdom.html", context)


@router.get("/ui/realms/{realm_id}/map", response_class=HTMLResponse)
def map_page(request: Request, realm_id: int, b: int | None = None, zone: str | None = None,
             zones: int = 0, zoom: int = 0, conn=Depends(_connection)):
    """@brief The realm's land, buildings and town plan (server/ui/map_view.py).
    Every choice is a link: b = building id (0 the square), zone = zone to
    light up, zones = 1 to draw every zone, zoom = 1 for bigger tiles."""
    game_id = games.realm_game_id(conn, realm_id)
    if game_id is None:
        return _not_found(request, f"il regno {realm_id}")
    game = games.load_game(conn, game_id)
    state = games.load_latest_state(conn, realm_id)
    config = games.load_game_config(conn, game_id)
    view = (map_view.map_page(state, config, realm_id, b, zone, bool(zones), bool(zoom))
            if state.has_map() else None)
    context = {
        "game": game,
        "realm": next(r for r in game["realms"] if r["id"] == realm_id),
        "turn": state.turn,
        "map": view,
        "nav": "map",
        "realm_id": realm_id,
    }
    return templates.TemplateResponse(request, "map.html", context)


ICON_AUTHORS = Path(__file__).with_name("static") / "icons" / "AUTHORS.txt"


def icon_credits() -> list[dict]:
    """@brief The icons of the sprite with their authors, from AUTHORS.txt
    (lines "name.svg  author  source (licence)"; lab/build_icon_sprite.py)."""
    credits = []
    for line in ICON_AUTHORS.read_text(encoding="utf-8").splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            credits.append({"icon": parts[0].removesuffix(".svg"), "author": parts[1], "source": parts[2]})
    return credits


@router.get("/ui/credits", response_class=HTMLResponse)
def credits_page(request: Request):
    """@brief Who made the icons of the map (CC BY 3.0 asks for the credit)."""
    return templates.TemplateResponse(request, "credits.html", {"credits": icon_credits()})


@router.get("/ui/realms/{realm_id}/market", response_class=HTMLResponse)
def market_page(request: Request, realm_id: int, conn=Depends(_connection)):
    """@brief The common market as this realm sees it (server/ui/market_view.py):
    public prices and totals, its own goods on sale, the Treasurer's trades.
    Read only: trades go through the council like every other order."""
    game_id = games.realm_game_id(conn, realm_id)
    if game_id is None:
        return _not_found(request, f"il regno {realm_id}")
    game = games.load_game(conn, game_id)
    state = games.load_latest_state(conn, realm_id)
    config = games.load_game_config(conn, game_id)
    history = games.load_market_history(conn, game_id, state.turn, market_view.HISTORY_MONTHS)
    view = None
    if history and config.market is not None:
        summaries = [m for m in meeting.list_messages(conn, realm_id, state.turn) if m["kind"] == "summary"]
        last_events = []
        if state.turn > 1:
            last_events = [e for e in games.list_events_for_sovereign(conn, game_id, realm_id, state.turn - 1)
                           if e["realm_id"] == realm_id]
        view = market_view.market_page(history, state, config, str(realm_id),
                                       summaries[-1]["payload"] if summaries else None, last_events)
    context = {
        "game": game,
        "realm": next(r for r in game["realms"] if r["id"] == realm_id),
        "turn": state.turn,
        "market": view,
        "nav": "market",
        "realm_id": realm_id,
    }
    return templates.TemplateResponse(request, "market.html", context)


@router.get("/ui/realms/{realm_id}/chronicle", response_class=HTMLResponse)
def chronicle_page(request: Request, realm_id: int, conn=Depends(_connection)):
    game_id = games.realm_game_id(conn, realm_id)
    if game_id is None:
        return _not_found(request, f"il regno {realm_id}")
    game = games.load_game(conn, game_id)
    state = games.load_latest_state(conn, realm_id)
    months = []
    for turn in range(state.turn - 1, 0, -1):  # newest first
        events = games.list_events_for_sovereign(conn, game_id, realm_id, turn)
        months.append({"turn": turn, "events": [e for e in events if e["realm_id"] == realm_id]})
    context = {
        "game": game,
        "realm": next(r for r in game["realms"] if r["id"] == realm_id),
        "months": months,
        "nav": "chronicle",
        "realm_id": realm_id,
    }
    return templates.TemplateResponse(request, "chronicle.html", context)


# ---------------------------------------------------------- audiences

def _audience_page(realm_id: int, role: str, error: str = "") -> RedirectResponse:
    url = f"/ui/realms/{realm_id}/audience/{role}"
    if error:
        url += f"?error={quote(error)}"
    return RedirectResponse(url, status_code=303)


def _audience_context(request: Request, conn: psycopg.Connection, realm_id: int, role: str) -> dict:
    settings = request.app.state.council_settings
    jobs = request.app.state.council_jobs
    game = games.load_game(conn, games.realm_game_id(conn, realm_id))
    left = 0
    if game["open_turn"] is not None:
        left = audience.lines_left(conn, realm_id, role, settings)
    lines = audience.dialogue_for_sovereign(conn, realm_id, role)
    running = jobs.running_kind(realm_id) == f"audience:{role}"
    return {
        "realm_id": realm_id,
        "role": role,
        "who": {**labels.ROLES[role], "name": games.role_names(conn, realm_id).get(role, labels.ROLES[role]["name"])},
        "lines": lines,
        "lines_left": left,
        "open_turn": game["open_turn"],
        "running": running,
        "unanswered": bool(lines) and lines[-1]["speaker"] == "sovereign" and not running,
        "job_error": jobs.last_error(realm_id, f"audience:{role}"),
    }


@router.get("/ui/realms/{realm_id}/audience/{role}", response_class=HTMLResponse)
def audience_page(request: Request, realm_id: int, role: str, error: str = "",
                  conn=Depends(_connection)):
    if games.realm_game_id(conn, realm_id) is None or role not in audience.AUDIENCE_ROLES:
        return _not_found(request, "questa udienza")
    context = _audience_context(request, conn, realm_id, role)
    context.update({"error": error, "nav": "turn"})
    return templates.TemplateResponse(request, "audience.html", context)


@router.get("/ui/realms/{realm_id}/audience/{role}/panel", response_class=HTMLResponse)
def audience_panel(request: Request, realm_id: int, role: str, conn=Depends(_connection)):
    """@brief Polled by HTMX every 2 s while the council member answers."""
    if games.realm_game_id(conn, realm_id) is None or role not in audience.AUDIENCE_ROLES:
        return _not_found(request, "questa udienza")
    return templates.TemplateResponse(
        request, "_audience.html", _audience_context(request, conn, realm_id, role)
    )


@router.post("/ui/realms/{realm_id}/audience/{role}")
def speak_in_audience(request: Request, realm_id: int, role: str, text: str = Form(...)):
    settings = request.app.state.council_settings
    text = text.strip()[:audience.MAX_SOVEREIGN_CHARS]
    if not text:
        return _audience_page(realm_id, role, "Scrivi qualcosa prima di inviare.")
    return _start_round(
        request, realm_id, f"audience:{role}",
        lambda conn: audience.check_audience_allowed(conn, realm_id, role, settings),
        lambda conn, client: audience.speak(conn, realm_id, role, text, client, settings),
        back=lambda error="": _audience_page(realm_id, role, error),
    )
