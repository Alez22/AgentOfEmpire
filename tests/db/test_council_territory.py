"""The council on the map (docs/DESIGN.md, "Territory"): briefings, prompts, the town plan retry."""

import json
from dataclasses import replace

import pytest

from engine.config import load_raw_config
from server.council import meeting
from server.council.llm import FakeClient
from server.council.settings import load_settings
from server.db import games
from server.db.games import create_game

COUNCIL = {"chancellor": "top-model", "treasurer": "mid-model", "architect": "mid-model"}


@pytest.fixture
def settings():
    loaded = load_settings()
    models = {role: model for role, model in loaded.models.items() if role not in ("square_voice", "people")}
    return replace(loaded, provider="fake", models=models)


def _realm(db, raw_config):
    game_id = create_game(db, raw_config, seed=3, realm_names=["Nord"], council_models=COUNCIL)
    return game_id, db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]


@pytest.fixture
def realm(db):
    return _realm(db, load_raw_config())


def _calls(client, role):
    return [call for call in client.calls if call["role"] == role]


def _architect_report(db, realm_id):
    return next(m for m in meeting.list_messages(db, realm_id, 1) if m["speaker"] == "architect")


def _zones(state):
    return [{"name": z.name, "purpose": z.purpose, "x1": z.x1, "y1": z.y1, "x2": z.x2, "y2": z.y2}
            for z in state.zones]


def test_each_counsellor_sees_the_territory_at_its_own_depth(db, realm, settings):
    _, realm_id = realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    architect = _calls(client, "architect")[0]
    assert "## The town and its land" in architect["user"]
    assert "Campi (fields)" in architect["user"] and "room for 2 farm" in architect["user"]
    assert "set_zones" in architect["system"] and "claim_tiles" in architect["system"]
    assert "Territory:" in architect["system"]  # the manual's territory rules
    assert "Keep the town in order" in architect["system"]  # the town-planning craft
    chancellor = _calls(client, "chancellor")[0]
    assert "- Territory: 144 tiles owned" in chancellor["user"]
    assert "## The town and its land" not in chancellor["user"]
    treasurer = _calls(client, "treasurer")[0]
    assert "The next tile costs 20 gold" in treasurer["user"]


def test_games_without_a_map_keep_the_old_prompts(db, settings):
    raw = load_raw_config()
    del raw["map"]
    _, realm_id = _realm(db, raw)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    architect = _calls(client, "architect")[0]
    assert "- Free tiles for new buildings: 7." in architect["user"]
    assert "set_zones" not in architect["system"] and "Territory:" not in architect["system"]


def test_a_refused_town_plan_is_asked_again(db, realm, settings):
    game_id, realm_id = realm
    state = games.load_latest_state(db, realm_id)
    bad = [z for z in _zones(state) if z["name"] != "Campi"]  # the farms would stand outside
    good = _zones(state)
    client = FakeClient()
    client.queue("architect",
                 json.dumps({"report": "Maestà, un piano nuovo.", "proposals": [{"action": "set_zones", "zones": bad}]}),
                 json.dumps({"report": "Maestà, il piano corretto.", "proposals": [{"action": "set_zones", "zones": good}]}))
    meeting.hold_meeting(db, realm_id, client, settings)
    report = _architect_report(db, realm_id)
    assert report["content"] == "Maestà, il piano corretto."
    assert [o["action"] for o in report["payload"]["proposals"]] == ["set_zones"]
    retry = _calls(client, "architect")[1]["user"]
    assert "your town plan (set_zones) would be refused" in retry and "farm 1" in retry


def test_a_town_plan_refused_twice_is_dropped_and_the_rest_stays(db, realm, settings):
    _, realm_id = realm
    state = games.load_latest_state(db, realm_id)
    bad = [z for z in _zones(state) if z["name"] != "Campi"]
    reply = json.dumps({"report": "Maestà, ecco.", "proposals": [
        {"action": "set_zones", "zones": bad}, {"action": "build", "building": "house", "zone": "Centro"}]})
    client = FakeClient()
    client.queue("architect", reply, reply)
    meeting.hold_meeting(db, realm_id, client, settings)
    payload = _architect_report(db, realm_id)["payload"]
    assert payload["proposals"] == [{"action": "build", "building": "house", "zone": "Centro"}]
    assert [d["reason"] for d in payload["discarded"]] == ["BAD_ZONES"]


def test_the_cost_check_warns_of_clearing_hands_with_nothing_to_clear(db, realm, settings):
    _, realm_id = realm
    client = FakeClient()
    client.queue("architect", json.dumps({"report": "Maestà.", "proposals": [
        {"action": "assign_workers", "food": 50, "wood": 4, "stone": 2, "clearing": 4}]}))
    meeting.hold_meeting(db, realm_id, client, settings)
    chancellor = _calls(client, "chancellor")[0]["user"]
    assert "4 clearing workers but nothing is queued for clearing" in chancellor
