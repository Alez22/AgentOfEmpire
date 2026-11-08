"""@brief HTTP API of the prototype (FastAPI).

Run: docker compose up server   ->   http://127.0.0.1:8000/docs

No authentication yet: the server is reachable only from this PC
(127.0.0.1). Accounts and tokens come before friends get access.

Endpoints are plain `def` functions: FastAPI runs them in its thread pool
(40 threads by default) and each request holds one pooled DB connection
for its whole duration.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from contextlib import asynccontextmanager
from dataclasses import asdict

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from engine.market import check_month_plan
from engine.config import load_raw_config
from engine.orders import Order
from server.council import audience, debate, mandates, meeting, people, persons
from server.council.jobs import CouncilJobs
from server.council.llm import FakeClient, OpenRouterClient
from server.council.settings import CouncilSettings, load_settings
from server.db import games
from server.sovereign_view import sovereign_state
from server.admin.routes import router as admin_router
from server.ui.routes import router as ui_router

STATIC_DIR = Path(__file__).with_name("ui") / "static"

POOL_MAX_CONNECTIONS = 10  # well below the PostgreSQL default limit of 100

class DirectiveRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class PetitionAnswer(BaseModel):
    answer: str = Field(pattern="^(granted|refused)$")


class ApproveRequest(BaseModel):
    exclude: list[int] = []  # plan positions (0-based) the sovereign removes


class CreateGameRequest(BaseModel):
    seed: int
    realm_names: list[str] = Field(default=["Nord"], min_length=1)
    # Role -> model. None = the models in server/council.toml. Each game keeps
    # the models it was created with, like it keeps its config copy.
    council_models: dict[str, str] | None = None


def _make_llm_client(settings: CouncilSettings):
    if settings.provider == "fake":
        return FakeClient()
    return OpenRouterClient(
        settings.base_url,
        os.environ.get("OPENROUTER_API_KEY", ""),
        settings.timeout_seconds,
        settings.prices,
        settings.max_output_tokens,
        settings.models_without_json_schema,
        settings.models_without_reasoning,
    )


def create_app(
    database_url: str | None = None,
    council_settings: CouncilSettings | None = None,
    llm_client=None,
    admin_view: bool | None = None,
) -> FastAPI:
    """@brief Build the app; the connection pool lives for the app's lifetime.
    @param database_url Defaults to the DATABASE_URL environment variable.
    @param council_settings Defaults to server/council.toml.
    @param llm_client Defaults to the client of the configured provider
           (tests pass a scripted FakeClient).
    @param admin_view Enables /admin; defaults to ADMIN_VIEW=1 in the environment.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.council_settings = council_settings or load_settings()
        app.state.council_jobs = CouncilJobs()
        app.state.llm_client = llm_client or _make_llm_client(app.state.council_settings)
        url = database_url or os.environ["DATABASE_URL"]
        # autocommit: the db functions open their own transactions.
        with ConnectionPool(
            url, min_size=1, max_size=POOL_MAX_CONNECTIONS, kwargs={"autocommit": True}
        ) as pool:
            app.state.pool = pool
            yield

    app = FastAPI(title="AgentOfEmpire", lifespan=lifespan)
    app.state.admin_view = (os.environ.get("ADMIN_VIEW") == "1") if admin_view is None else admin_view
    _add_routes(app)
    _add_audience_routes(app)
    _add_people_routes(app)
    app.include_router(ui_router)
    app.include_router(admin_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _connection(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.pool.connection() as conn:
        yield conn


def _require_realm_game(conn: psycopg.Connection, realm_id: int) -> int:
    game_id = games.realm_game_id(conn, realm_id)
    if game_id is None:
        raise HTTPException(404, f"realm {realm_id} not found")
    return game_id


def _add_routes(app: FastAPI) -> None:
    @app.post("/games", status_code=201)
    def create_game(body: CreateGameRequest, request: Request, conn=Depends(_connection)):
        council_models = body.council_models or request.app.state.council_settings.models
        # Explicit models (tests, experiments) keep generated traits; otherwise
        # the council is drawn from the catalog of persons.
        catalog = None if body.council_models else persons.load_catalog()
        game_id = games.create_game(
            conn, load_raw_config(), body.seed, body.realm_names, council_models, personas=catalog,
            model_tiers=request.app.state.council_settings.model_tiers,
        )
        return games.load_game(conn, game_id)

    @app.get("/games/{game_id}")
    def get_game(game_id: int, conn=Depends(_connection)):
        game = games.load_game(conn, game_id)
        if game is None:
            raise HTTPException(404, f"game {game_id} not found")
        return game

    @app.get("/realms/{realm_id}/state")
    def get_state(realm_id: int, conn=Depends(_connection)):
        # The sovereign's view: no mood. The full state is in the admin view.
        state = games.load_latest_state(conn, realm_id)
        if state is None:
            raise HTTPException(404, f"realm {realm_id} not found")
        return sovereign_state(state)

    @app.post("/realms/{realm_id}/orders/check")
    def check_orders(realm_id: int, orders: list[Order], conn=Depends(_connection)):
        game_id = _require_realm_game(conn, realm_id)
        state = games.load_latest_state(conn, realm_id)
        report = check_month_plan(state, orders, games.load_market(conn, game_id, state.turn),
                                  games.load_game_config(conn, game_id))
        return {
            "results": [
                {
                    "order": result.order.model_dump(exclude_none=True),
                    "accepted": result.accepted,
                    "code": result.code,
                    "message": result.message,
                }
                for result in report.results
            ],
            "spent": report.spent,
            "remaining": report.remaining,
        }

    @app.post("/realms/{realm_id}/orders", status_code=201)
    def submit_order(realm_id: int, order: Order, conn=Depends(_connection)):
        _require_realm_game(conn, realm_id)
        try:
            order_id = games.submit_order(conn, realm_id, order.model_dump(exclude_none=True), order.priority)
        except games.TurnClosedError as error:
            raise HTTPException(409, str(error)) from error
        return {"id": order_id}

    @app.get("/realms/{realm_id}/orders")
    def get_orders(realm_id: int, turn: int, conn=Depends(_connection)):
        _require_realm_game(conn, realm_id)
        return games.list_orders(conn, realm_id, turn)

    @app.get("/realms/{realm_id}/events")
    def get_events(realm_id: int, turn: int, conn=Depends(_connection)):
        game_id = _require_realm_game(conn, realm_id)
        return games.list_events_for_sovereign(conn, game_id, realm_id, turn)

    @app.post("/games/{game_id}/turns/resolve")
    def resolve_turn(game_id: int, conn=Depends(_connection)):
        if games.load_game(conn, game_id) is None:
            raise HTTPException(404, f"game {game_id} not found")
        try:
            summary = games.resolve_open_turn(conn, game_id)
        except (games.NoOpenTurnError, games.GamePausedError, games.EngineVersionError) as error:
            raise HTTPException(409, str(error)) from error
        return asdict(summary)

    # Council meetings run inside the request: 3 model calls per round,
    # so with real models the answer takes about 20-60 seconds.
    # The JSON endpoints run the round inside the request but take the same
    # per-realm reservation as the web UI, so the two never overlap.
    @app.post("/realms/{realm_id}/council/meeting")
    def hold_meeting(realm_id: int, request: Request, conn=Depends(_connection)):
        _require_realm_game(conn, realm_id)
        jobs = request.app.state.council_jobs
        if not jobs.reserve(realm_id, "meeting"):
            raise HTTPException(409, "the council of this realm is already meeting")
        try:
            meeting.hold_meeting(
                conn, realm_id, request.app.state.llm_client, request.app.state.council_settings
            )
        except meeting.CouncilError as error:
            raise HTTPException(409, str(error)) from error
        finally:
            jobs.release(realm_id)
        return _open_turn_messages(conn, realm_id)

    @app.post("/realms/{realm_id}/council/directives")
    def give_directive(realm_id: int, body: DirectiveRequest, request: Request,
                       conn=Depends(_connection)):
        _require_realm_game(conn, realm_id)
        jobs = request.app.state.council_jobs
        if not jobs.reserve(realm_id, "directive"):
            raise HTTPException(409, "the council of this realm is already meeting")
        try:
            meeting.give_directive(
                conn, realm_id, request.app.state.llm_client,
                request.app.state.council_settings, body.text,
            )
        except meeting.CouncilError as error:
            raise HTTPException(409, str(error)) from error
        finally:
            jobs.release(realm_id)
        return _open_turn_messages(conn, realm_id)

    @app.get("/realms/{realm_id}/mandates")
    def get_mandates(realm_id: int, conn=Depends(_connection)):
        """Each office, its mandate in force and the last request."""
        _require_realm_game(conn, realm_id)
        return mandates.government(conn, realm_id)

    @app.post("/realms/{realm_id}/mandates/{role}", status_code=201)
    def request_mandate(realm_id: int, role: str, body: DirectiveRequest, request: Request,
                        conn=Depends(_connection)):
        """The chancellery reviews the request (runs inside the request)."""
        _require_realm_game(conn, realm_id)
        jobs = request.app.state.council_jobs
        if not jobs.reserve(realm_id, f"mandate:{role}"):
            raise HTTPException(409, "the council of this realm is busy")
        try:
            return mandates.review(conn, realm_id, role, body.text, request.app.state.llm_client,
                                   request.app.state.council_settings)
        except meeting.CouncilError as error:
            raise HTTPException(409, str(error)) from error
        finally:
            jobs.release(realm_id)

    @app.post("/realms/{realm_id}/council/debate", status_code=201)
    def ask_debate(realm_id: int, request: Request, conn=Depends(_connection)):
        """The ministers comment on the latest plan (runs inside the request)."""
        _require_realm_game(conn, realm_id)
        jobs = request.app.state.council_jobs
        if not jobs.reserve(realm_id, "debate"):
            raise HTTPException(409, "the council of this realm is busy")
        try:
            debate.hold_debate(conn, realm_id, request.app.state.llm_client,
                               request.app.state.council_settings)
        except meeting.CouncilError as error:
            raise HTTPException(409, str(error)) from error
        finally:
            jobs.release(realm_id)
        return [m for m in _open_turn_messages(conn, realm_id) if m["kind"] == "comment"]

    @app.get("/realms/{realm_id}/council")
    def get_council(realm_id: int, turn: int, conn=Depends(_connection)):
        _require_realm_game(conn, realm_id)
        return meeting.list_messages(conn, realm_id, turn)

    @app.post("/realms/{realm_id}/council/approve", status_code=201)
    def approve_plan(realm_id: int, body: ApproveRequest, conn=Depends(_connection)):
        _require_realm_game(conn, realm_id)
        try:
            order_ids = meeting.approve_plan(conn, realm_id, body.exclude)
        except meeting.CouncilError as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"order_ids": order_ids}


def _add_audience_routes(app: FastAPI) -> None:
    @app.get("/realms/{realm_id}/council/audiences/{role}")
    def get_audience(realm_id: int, role: str, conn=Depends(_connection)):
        """The sovereign's own private dialogue with one council member."""
        _require_realm_game(conn, realm_id)
        return audience.dialogue_for_sovereign(conn, realm_id, role)

    @app.post("/realms/{realm_id}/council/audiences/{role}")
    def speak_in_audience(realm_id: int, role: str, body: DirectiveRequest, request: Request,
                          conn=Depends(_connection)):
        _require_realm_game(conn, realm_id)
        jobs = request.app.state.council_jobs
        if not jobs.reserve(realm_id, f"audience:{role}"):
            raise HTTPException(409, "the council of this realm is busy")
        try:
            answer = audience.speak(
                conn, realm_id, role, body.text,
                request.app.state.llm_client, request.app.state.council_settings,
            )
        except meeting.CouncilError as error:
            raise HTTPException(409, str(error)) from error
        finally:
            jobs.release(realm_id)
        return {"answer": answer}


def _add_people_routes(app: FastAPI) -> None:
    @app.get("/realms/{realm_id}/people")
    def get_people(realm_id: int, turn: int, conn=Depends(_connection)):
        """What the people decided that turn: behaviour, numbers, petition."""
        _require_realm_game(conn, realm_id)
        decision = people.decision_for_sovereign(conn, realm_id, turn)
        if decision is None:
            raise HTTPException(404, f"the people decided nothing in turn {turn}")
        return decision

    @app.post("/realms/{realm_id}/people/petition", status_code=201)
    def answer_petition(realm_id: int, body: PetitionAnswer, conn=Depends(_connection)):
        _require_realm_game(conn, realm_id)
        try:
            people.answer_petition(conn, realm_id, body.answer)
        except meeting.CouncilError as error:
            raise HTTPException(409, str(error)) from error
        return {"answer": body.answer}


def _open_turn_messages(conn: psycopg.Connection, realm_id: int) -> list[dict]:
    game = games.load_game(conn, games.realm_game_id(conn, realm_id))
    return meeting.list_messages(conn, realm_id, game["open_turn"])


app = create_app()
