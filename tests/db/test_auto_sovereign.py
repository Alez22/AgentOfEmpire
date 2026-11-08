"""The automatic sovereign plays a month through the API (server/sovereign/auto.py)."""

import html
from dataclasses import replace

import psycopg
import pytest
from fastapi.testclient import TestClient

from engine.config import load_raw_config
from server.app import create_app
from server.council import meeting
from server.council.llm import FakeClient
from server.council.settings import load_settings
from server.db.games import create_game, list_orders, load_game, resolve_open_turn

COUNCIL = {"chancellor": "m", "treasurer": "m", "architect": "m"}


@pytest.fixture
def api(database_url):
    settings = replace(load_settings(), provider="fake")
    with TestClient(create_app(database_url, settings, FakeClient())) as client:
        yield client


def test_three_automatic_realms_play_a_year(api, database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        game_id = create_game(conn, load_raw_config(), seed=0, realm_names=["Nord", "Est", "Sud"],
                              council_models=COUNCIL)
        realms = [r[0] for r in conn.execute("SELECT id FROM realms WHERE game_id = %s ORDER BY id", (game_id,))]
    for turn in range(1, 13):
        for realm_id in realms:
            response = api.post(f"/realms/{realm_id}/sovereign/auto")
            assert response.status_code == 200, response.text
            assert isinstance(response.json()["lines"], list)
        if turn == 1:
            page = html.unescape(api.get(f"/ui/realms/{realms[0]}").text)
            assert "Il sovrano automatico ha deciso" in page
        with psycopg.connect(database_url, autocommit=True) as conn:
            for realm_id in realms:
                kinds = [m["kind"] for m in meeting.list_messages(conn, realm_id, turn)]
                assert kinds[-1] == "sovereign"
                assert meeting.council_state(conn, realm_id, load_settings()).approved or not list_orders(
                    conn, realm_id, turn)
            resolve_open_turn(conn, game_id)
            assert load_game(conn, game_id)["open_turn"] == turn + 1
    # A second call in the same month is refused: the plan is already approved.
    api.post(f"/realms/{realms[0]}/sovereign/auto")
    assert api.post(f"/realms/{realms[0]}/sovereign/auto").status_code == 409


def test_a_fallen_realm_is_not_played(api, database_url, monkeypatch):
    """Game 27: Brenna fell in month 11; the next month the meeting ran and the
    petition check crashed (500) on the finished realm."""
    from server.db import games
    from server.sovereign import auto
    with psycopg.connect(database_url, autocommit=True) as conn:
        game_id = create_game(conn, load_raw_config(), seed=0, realm_names=["Nord"], council_models=COUNCIL)
        realm_id = conn.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
        fallen = games.load_latest_state(conn, realm_id)
    fallen.game_over = "revolt"
    monkeypatch.setattr(auto.games, "load_latest_state", lambda conn, rid: fallen)
    response = api.post(f"/realms/{realm_id}/sovereign/auto")
    assert response.status_code == 200 and response.json()["lines"] == ["Il popolo si è ribellato: il regno è perduto."]
    with psycopg.connect(database_url, autocommit=True) as conn:
        assert meeting.list_messages(conn, realm_id, 1) == []  # no meeting paid for a fallen realm
