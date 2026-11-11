"""A seasonal game: the automatic months lock the laws and drop the
petitions (docs/DESIGN.md, "Seasonal sovereign")."""

import html
import json
import time
from dataclasses import replace

import psycopg
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.council import meeting
from server.council.llm import FakeClient
from server.council.settings import load_settings

COUNCIL = {"chancellor": "m", "treasurer": "m", "architect": "m"}
PETITION = {"effort_pct": 0, "birth_pct": 100, "reason": "Test.",
            "petition": {"order": {"action": "set_tax", "rate": 3}, "text": "Meno gabella, Maestà."}}
TAX_UP = {"report": "Maestà, alzo la gabella.", "proposals": [{"action": "set_tax", "rate": 25}]}


@pytest.fixture
def fake():
    return FakeClient()


@pytest.fixture
def api(database_url, fake):
    settings = replace(load_settings(), provider="fake")
    with TestClient(create_app(database_url, settings, fake)) as client:
        yield client


def _new_game(api, rhythm):
    response = api.post("/games", json={"seed": 0, "realm_names": ["Nord"], "council_models": COUNCIL,
                                        "rhythm": rhythm})
    assert response.status_code == 201, response.text
    assert response.json()["rhythm"] == rhythm
    return response.json()["id"], response.json()["realms"][0]["id"]


def _play_and_resolve(api, game_id, realm_id):
    assert api.post(f"/realms/{realm_id}/sovereign/auto").status_code == 200
    assert api.post(f"/games/{game_id}/turns/resolve").status_code == 200


def test_a_monthly_game_is_the_sovereigns_every_month(api):
    _game_id, realm_id = _new_game(api, "monthly")
    assert api.get(f"/realms/{realm_id}/rhythm").json() == {
        "rhythm": "monthly", "turn": 1, "automatic": False, "reason": "Ogni mese"}


def test_an_automatic_month_locks_the_laws_and_drops_the_petition(api, fake, database_url):
    game_id, realm_id = _new_game(api, "seasonal")
    assert api.get(f"/realms/{realm_id}/rhythm").json()["reason"] == "Inizio dell'inverno"
    _play_and_resolve(api, game_id, realm_id)
    assert api.get(f"/realms/{realm_id}/rhythm").json()["automatic"] is True  # February, nothing happened

    fake.queue("people", json.dumps(PETITION))
    fake.queue("treasurer", json.dumps(TAX_UP))
    lines = api.post(f"/realms/{realm_id}/sovereign/auto").json()["lines"]
    assert any("(R12)" in line for line in lines)
    assert api.get(f"/realms/{realm_id}/people?turn=2").json()["petition"] is None
    with psycopg.connect(database_url, autocommit=True) as conn:
        messages = meeting.list_messages(conn, realm_id, 2)
    people_prompt = [c["user"] for c in fake.calls if c["role"] == "people"][-1]
    assert "nobody answers a petition" in people_prompt
    sovereign = [m for m in messages if m["kind"] == "sovereign"][-1]
    assert sovereign["payload"]["automatic"] is True
    plan = [m for m in messages if m["kind"] == "summary"][-1]["payload"]["plan"]
    tax_index = next(i for i, item in enumerate(plan) if item["order"]["action"] == "set_tax")
    assert tax_index in sovereign["payload"]["excluded"]
    orders = api.get(f"/realms/{realm_id}/orders?turn=2").json()
    assert not any(o["raw"]["action"] == "set_tax" for o in orders)


def test_the_sovereigns_month_keeps_the_petition(api, fake):
    game_id, realm_id = _new_game(api, "seasonal")
    fake.queue("people", json.dumps(PETITION))
    assert api.post(f"/realms/{realm_id}/council/meeting").status_code == 200
    assert api.get(f"/realms/{realm_id}/people?turn=1").json()["petition"] == {"action": "set_tax", "rate": 3}


def _wait_for_council(api, realm_id):
    jobs = api.app.state.council_jobs
    for _ in range(200):
        if not jobs.is_running(realm_id):
            return
        time.sleep(0.05)
    raise AssertionError("the automatic month did not finish")


def test_the_turn_page_plays_the_automatic_months_and_sums_them_up(api):
    game_id, realm_id = _new_game(api, "seasonal")
    page = html.unescape(api.get(f"/ui/realms/{realm_id}").text)
    assert "Inizio dell'inverno: decidi tu." in page
    assert "Mese automatico" not in page
    _play_and_resolve(api, game_id, realm_id)
    for _month in ("febbraio", "marzo"):
        page = html.unescape(api.get(f"/ui/realms/{realm_id}").text)
        assert "Mese automatico" in page and "Torni a decidere ad aprile" in page
        _wait_for_council(api, realm_id)
        assert api.app.state.council_jobs.last_error(realm_id, "auto") == ""
        assert api.post(f"/games/{game_id}/turns/resolve").status_code == 200
    page = html.unescape(api.get(f"/ui/realms/{realm_id}").text)
    assert "Inizio della primavera: decidi tu." in page
    assert "Dalla tua ultima udienza" in page
    assert page.index("Febbraio") < page.index("Marzo")


def test_the_new_game_form_takes_the_rhythm(api, database_url):
    response = api.post("/ui/games", data={"realm_name": "Est", "game_rhythm": "seasonal"}, follow_redirects=False)
    assert response.status_code == 303
    with psycopg.connect(database_url, autocommit=True) as conn:
        assert conn.execute("SELECT rhythm FROM games ORDER BY id DESC LIMIT 1").fetchone()[0] == "seasonal"
