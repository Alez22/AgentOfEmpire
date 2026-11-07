"""Debate on request: the ministers comment on the Chancellor's plan."""

import html
import json
import re
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from engine.config import load_raw_config
from server.app import create_app
from server.council import debate, meeting
from server.council.llm import FakeClient
from server.council.settings import load_settings
from server.db.games import create_game

COUNCIL = {"chancellor": "top-model", "treasurer": "mid-model", "architect": "mid-model"}


@pytest.fixture
def settings():
    loaded = load_settings()
    models = {r: m for r, m in loaded.models.items() if r not in ("square_voice", "people")}
    return replace(loaded, provider="fake", models=models)


@pytest.fixture
def realm(db):
    game_id = create_game(db, load_raw_config(), seed=13, realm_names=["Nord"], council_models=COUNCIL)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    return game_id, realm_id


def _comments(db, realm_id):
    return [m for m in meeting.list_messages(db, realm_id, 1) if m["kind"] == "comment"]


def test_ministers_comment_in_turn_and_the_plan_stays(db, realm, settings):
    _, realm_id = realm
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    plan_before = [m for m in meeting.list_messages(db, realm_id, 1) if m["kind"] == "summary"][-1]["payload"]["plan"]
    objection = json.dumps({"stance": "object", "comment": "Maestà, senza la festa la piazza si inasprirà."})
    client = FakeClient({"treasurer": [objection]})
    debate.hold_debate(db, realm_id, client, settings)
    comments = _comments(db, realm_id)
    assert [(c["speaker"], c["payload"]["stance"]) for c in comments] == [
        ("treasurer", "object"), ("architect", "agree")]
    assert "## The plan" in client.calls[0]["user"] and "1) hold_feast 10 (Il Tesoriere; feasible)" in client.calls[0]["user"]
    assert "Il Tesoriere (object): Maestà, senza la festa" in client.calls[1]["user"]  # the Architect hears him
    plan_after = [m for m in meeting.list_messages(db, realm_id, 1) if m["kind"] == "summary"][-1]["payload"]["plan"]
    assert plan_after == plan_before


def test_one_debate_per_plan_and_a_new_one_after_a_directive(db, realm, settings):
    _, realm_id = realm
    with pytest.raises(meeting.NoMeetingYetError):
        debate.check_debate_allowed(db, realm_id)
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    debate.hold_debate(db, realm_id, FakeClient(), settings)
    with pytest.raises(debate.DebateAlreadyHeldError):
        debate.check_debate_allowed(db, realm_id)
    meeting.give_directive(db, realm_id, FakeClient(), settings, "Più prudenza")
    debate.hold_debate(db, realm_id, FakeClient(), settings)  # new round, new plan
    assert len(_comments(db, realm_id)) == 4
    meeting.approve_plan(db, realm_id, excluded=[])
    with pytest.raises(meeting.AlreadyApprovedError):
        debate.check_debate_allowed(db, realm_id)


def test_chancellor_role_stands_above_the_parties(db, realm, settings):
    _, realm_id = realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    assert "you stand above the parties" in client.calls[2]["system"]


def test_debate_from_the_phone(database_url, settings):
    with TestClient(create_app(database_url, settings, FakeClient(), admin_view=False)) as ui:
        created = ui.post("/ui/games", data={"realm_name": "Valdoro"}, follow_redirects=False)
        realm_id = int(re.search(r"/ui/realms/(\d+)", created.headers["location"]).group(1))

        def settle():
            for _ in range(200):
                if "hx-trigger" not in ui.get(f"/ui/realms/{realm_id}/council-panel").text:
                    return
                time.sleep(0.05)

        ui.post(f"/ui/realms/{realm_id}/meeting")
        settle()
        assert "Chiedi il parere dei ministri sul piano" in ui.get(f"/ui/realms/{realm_id}").text
        ui.post(f"/ui/realms/{realm_id}/debate")
        settle()
        page = html.unescape(ui.get(f"/ui/realms/{realm_id}").text)
        assert "D'accordo con il piano" in page and "approva il piano." in page
        assert "Chiedi il parere dei ministri sul piano" not in page
