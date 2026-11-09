"""The Gastaldo and the bandits at the council (village block B+C, step 3),
with the fake model client: no network, no cost."""

from dataclasses import replace

import pytest
from psycopg.types.json import Jsonb

from engine.config import load_raw_config
from server.council import audience, manual, meeting, persons
from server.council.llm import FakeClient
from server.council.settings import load_settings
from server.db.games import create_game, list_orders

COUNCIL = {"chancellor": "top-model", "treasurer": "mid-model", "architect": "mid-model"}


@pytest.fixture
def settings():
    loaded = load_settings()
    models = {role: model for role, model in loaded.models.items() if role not in ("square_voice", "people")}
    return replace(loaded, provider="fake", models=models)


def _realm(db, personas=None, settings=None):
    game_id = create_game(db, load_raw_config(), seed=3, realm_names=["Nord"], council_models=COUNCIL,
                          personas=personas, model_tiers=settings.model_tiers if settings else None)
    return game_id, db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]


def _give_watchtower(db, realm_id, raid=False):
    """@brief A finished watchtower in its zone (and, if asked, a raid last month)."""
    state = db.execute("SELECT state FROM snapshots WHERE realm_id = %s ORDER BY turn DESC LIMIT 1",
                       (realm_id,)).fetchone()[0]
    zone = next(z for z in state["zones"] if z["purpose"] == "watch")
    tower = {"kind": "watchtower", "turns_left": 0, "id": state["next_building_id"], "x": zone["x1"], "y": zone["y1"]}
    state["buildings"].append(tower)
    state["next_building_id"] += 1
    db.execute("UPDATE snapshots SET state = %s WHERE realm_id = %s", (Jsonb(state), realm_id))
    if raid:
        game_id = db.execute("SELECT game_id FROM realms WHERE id = %s", (realm_id,)).fetchone()[0]
        db.execute("INSERT INTO events (game_id, realm_id, turn, kind, data, visibility)"
                   " VALUES (%s, %s, 0, 'raid', %s, 'public')",
                   (game_id, realm_id, Jsonb({"raiders": 9, "guards": 0, "repelled": False, "food": 200, "wood": 25})))


def _roles_called(client):
    return [call["role"] for call in client.calls]


def test_no_gastaldo_before_the_watchtower(db, settings):
    _, realm_id = _realm(db)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    assert "gastaldo" not in _roles_called(client)
    assert db.execute("SELECT count(*) FROM actors WHERE realm_id = %s AND role = 'gastaldo'",
                      (realm_id,)).fetchone()[0] == 0
    architect = next(c for c in client.calls if c["role"] == "architect")
    assert '"building": "watchtower"' in architect["system"]  # it can be built
    assert "set_militia" not in architect["system"]  # but no militia yet
    assert '"to" is "treasurer", "architect" or "chancellor"' in architect["system"]  # wording unchanged


def test_the_gastaldo_joins_when_the_watchtower_is_finished(db, settings):
    _, realm_id = _realm(db)
    _give_watchtower(db, realm_id, raid=True)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    assert _roles_called(client) == ["treasurer", "architect", "gastaldo", "chancellor"]
    gastaldo = next(c for c in client.calls if c["role"] == "gastaldo")
    assert "You are the Gastaldo" in gastaldo["system"] and "set_militia" in gastaldo["system"]
    assert "## The gate and the guard" in gastaldo["user"]
    assert "carried away 200 food and 25 wood" in gastaldo["user"]
    chancellor = next(c for c in client.calls if c["role"] == "chancellor")
    assert '"Il Gastaldo" (a man)' in chancellor["system"]
    assert "gastaldo (set_militia)" in chancellor["system"]
    assert "## The gate and the guard" in chancellor["user"]
    plan = [m for m in meeting.list_messages(db, realm_id, 1) if m["kind"] == "summary"][-1]["payload"]["plan"]
    assert {"proposer": "gastaldo", "order": {"action": "set_militia", "guards": 2}} in plan
    meeting.approve_plan(db, realm_id, [])
    militia = [o for o in list_orders(db, realm_id, 1) if o["raw"]["action"] == "set_militia"]
    assert len(militia) == 1


def test_a_gastaldo_of_the_catalogue_in_a_game_with_persons(db, settings):
    _, realm_id = _realm(db, personas=persons.load_catalog(), settings=settings)
    _give_watchtower(db, realm_id)
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    model, personality = db.execute("SELECT model, personality FROM actors WHERE realm_id = %s AND role = 'gastaldo'",
                                    (realm_id,)).fetchone()
    assert personality["persona"] in ("guidalberto", "ermengarda", "lanfranco")
    assert model == settings.model_tiers[personality["tier"]]


def test_the_sovereign_may_hear_the_gastaldo_in_private(db, settings):
    _, realm_id = _realm(db)
    _give_watchtower(db, realm_id)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    audience.speak(db, realm_id, "gastaldo", "Quanti uomini servono alla porta?", client, settings)
    assert "## The gate and the guard" in client.calls[-1]["user"]


def test_the_manual_tells_the_bandits_but_not_their_number(db):
    from engine.config import config_from_dict
    config = config_from_dict(load_raw_config())
    text = manual.prompt_text(config)
    assert "Bandits:" in text and "nobody can count" in text
    assert any(section["title"] == "Briganti" for section in manual.page_sections(config))


def test_the_pages_show_the_gastaldo(db, database_url, settings):
    from fastapi.testclient import TestClient
    from server.app import create_app
    _, realm_id = _realm(db)
    _give_watchtower(db, realm_id, raid=True)
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    with TestClient(create_app(database_url, settings, FakeClient())) as ui:
        for page in ("", "/council-panel", "/government", "/government/panel", "/manual", "/kingdom",
                     "/map", "/chronicle", "/audience/gastaldo"):
            response = ui.get(f"/ui/realms/{realm_id}{page}")
            assert response.status_code == 200, page
        assert "Il Gastaldo" in ui.get(f"/ui/realms/{realm_id}/council-panel").text
        assert "Briganti" in ui.get(f"/ui/realms/{realm_id}/manual").text
