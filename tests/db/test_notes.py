"""Secret notes between council members: one a month, one recipient,
delivered at the next meeting, unknown to everyone else."""

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from engine.config import load_raw_config
from server.app import create_app
from server.council import audience, meeting
from server.council.llm import FakeClient
from server.council.settings import load_settings
from server.db.games import create_game, resolve_open_turn

COUNCIL = {"chancellor": "top-model", "treasurer": "mid-model", "architect": "mid-model"}
NOTE = "Sostieni la mia fattoria e io non toccherò la tua festa."


@pytest.fixture
def settings():
    loaded = load_settings()
    models = {r: m for r, m in loaded.models.items() if r not in ("square_voice", "people")}
    return replace(loaded, provider="fake", models=models)


@pytest.fixture
def realm(db):
    game_id = create_game(db, load_raw_config(), seed=12, realm_names=["Nord"], council_models=COUNCIL)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    return game_id, realm_id


def _architect_with_note(note):
    return json.dumps({"report": "Maestà, una fattoria.", "proposals": [{"action": "build", "building": "farm"}],
                       "note": note})


def _send_and_next_month(db, game_id, realm_id, settings, note):
    meeting.hold_meeting(db, realm_id, FakeClient({"architect": [_architect_with_note(note)]}), settings)
    meeting.approve_plan(db, realm_id, excluded=[])
    resolve_open_turn(db, game_id)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 2
    return {call["role"]: call["user"] for call in client.calls}


def test_note_reaches_only_its_recipient_the_month_after(db, realm, settings):
    game_id, realm_id = realm
    briefings = _send_and_next_month(db, game_id, realm_id, settings, {"to": "treasurer", "text": NOTE})
    assert f"January: L'Architetta wrote to you: «{NOTE}»" in briefings["treasurer"]
    assert f"January: you wrote to Il Tesoriere: «{NOTE}»" in briefings["architect"]
    assert NOTE not in briefings["chancellor"]


def test_nothing_records_that_a_note_was_sent(db, realm, settings):
    game_id, realm_id = realm
    _send_and_next_month(db, game_id, realm_id, settings, {"to": "treasurer", "text": NOTE})
    assert NOTE not in json.dumps([list(r) for r in db.execute(
        "SELECT kind, data::text FROM events WHERE realm_id = %s", (realm_id,))])
    assert db.execute("SELECT count(*) FROM events WHERE realm_id = %s AND kind LIKE '%%note%%'",
                      (realm_id,)).fetchone()[0] == 0
    payloads = json.dumps([r[0] for r in db.execute(
        "SELECT payload FROM council_messages WHERE realm_id = %s", (realm_id,))])
    assert NOTE not in payloads and '"note"' not in payloads


@pytest.mark.parametrize("bad_note", [
    {"to": "architect", "text": NOTE},  # to oneself
    {"to": "square_voice", "text": NOTE},  # not a council member
    {"to": "treasurer", "text": "  "},  # empty
    "just a string",
])
def test_bad_notes_are_dropped_and_the_reply_stays(db, realm, settings, bad_note):
    _, realm_id = realm
    meeting.hold_meeting(db, realm_id, FakeClient({"architect": [_architect_with_note(bad_note)]}), settings)
    assert db.execute("SELECT count(*) FROM counsel_notes WHERE realm_id = %s", (realm_id,)).fetchone()[0] == 0
    report = [m for m in meeting.list_messages(db, realm_id, 1) if m["speaker"] == "architect"][0]
    assert report["payload"]["proposals"] == [{"action": "build", "building": "farm"}]


def test_one_note_a_month_even_after_a_directive(db, realm, settings):
    _, realm_id = realm
    first = _architect_with_note({"to": "treasurer", "text": "Primo"})
    second = _architect_with_note({"to": "chancellor", "text": "Secondo"})
    meeting.hold_meeting(db, realm_id, FakeClient({"architect": [first]}), settings)
    meeting.give_directive(db, realm_id, FakeClient({"architect": [second]}), settings, "Prudenza")
    rows = db.execute("SELECT content FROM counsel_notes WHERE realm_id = %s", (realm_id,)).fetchall()
    assert rows == [("Primo",)]


def test_audience_knows_the_notes_and_the_choice_to_tell(db, realm, settings):
    game_id, realm_id = realm
    _send_and_next_month(db, game_id, realm_id, settings, {"to": "treasurer", "text": NOTE})
    client = FakeClient()
    audience.speak(db, realm_id, "treasurer", "Qualcuno ti ha scritto?", client, settings)
    assert NOTE in client.calls[0]["user"]
    assert "you may tell, deny or keep silent" in client.calls[0]["system"]


def test_season_review_rereads_the_notes(db, realm, settings):
    game_id, realm_id = realm
    meeting.hold_meeting(db, realm_id, FakeClient({"architect": [_architect_with_note(
        {"to": "treasurer", "text": NOTE})]}), settings)
    for _ in range(3):
        meeting.approve_plan(db, realm_id, excluded=[])
        resolve_open_turn(db, game_id)
        if _ < 2:
            meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 4: reviews first
    treasurer_review = client.calls[0]["user"]
    assert "## What happened this season" in treasurer_review and NOTE in treasurer_review


def test_only_the_admin_sees_the_notes(database_url, settings, db, realm):
    game_id, realm_id = realm
    meeting.hold_meeting(db, realm_id, FakeClient({"architect": [_architect_with_note(
        {"to": "treasurer", "text": "Segreto <b>tra noi</b>"})]}), settings)
    with TestClient(create_app(database_url, settings, FakeClient(), admin_view=True)) as ui:
        sovereign_pages = "".join(ui.get(f"/ui/realms/{realm_id}{page}").text
                                  for page in ("", "/kingdom", "/chronicle"))
        assert "Segreto" not in sovereign_pages
        admin = ui.get(f"/admin/realms/{realm_id}/turns/1").text
        assert "Biglietti segreti" in admin and "&lt;b&gt;tra noi&lt;/b&gt;" in admin
