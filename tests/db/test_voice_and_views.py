"""Voice of the square, the sovereign's filtered view and the admin view."""

import html
import json
import re
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from engine.config import load_raw_config
from server.app import create_app
from server.council import meeting
from server.council.llm import FakeClient, LLMError
from server.council.settings import load_settings
from server.db.games import create_game, resolve_open_turn

VOICE_TEXT = "Al mercato si brontola per il pane scarso."


@pytest.fixture
def settings():
    return replace(load_settings(), provider="fake")  # Voice of the square included


@pytest.fixture
def realm(db, settings):
    game_id = create_game(db, load_raw_config(), seed=6, realm_names=["Nord"],
                          council_models=settings.models)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    return game_id, realm_id


def _by_role(client, role):
    return [call for call in client.calls if call["role"] == role]


# ------------------------------------------------------ Voice of the square

def test_voice_speaks_first_and_the_council_hears_it(db, realm, settings):
    _, realm_id = realm
    client = FakeClient({"square_voice": [VOICE_TEXT]})
    meeting.hold_meeting(db, realm_id, client, settings)
    assert client.calls[0]["role"] == "square_voice"
    assert client.calls[0]["reasoning_effort"] == settings.reasoning_effort["square_voice"]
    facts = client.calls[0]["user"]
    assert "NEVER say these numbers" in facts and "Taxes: 10%." in facts
    messages = meeting.list_messages(db, realm_id, 1)
    assert (messages[0]["kind"], messages[0]["content"]) == ("voice", VOICE_TEXT)
    for role in ("treasurer", "architect", "chancellor"):
        assert f"## What they say in the square\n{VOICE_TEXT}" in _by_role(client, role)[0]["user"]


def test_voice_is_court_level(db, realm, settings):
    _, realm_id = realm
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    visibility = db.execute(
        "SELECT visibility::text FROM council_messages WHERE realm_id = %s AND kind = 'voice'", (realm_id,)
    ).fetchone()[0]
    assert visibility == "court"


def test_voice_does_not_speak_again_after_a_directive(db, realm, settings):
    _, realm_id = realm
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    client = FakeClient()
    meeting.give_directive(db, realm_id, client, settings, "Prudenza")
    assert _by_role(client, "square_voice") == []
    assert "## What they say in the square" in _by_role(client, "treasurer")[0]["user"]


def test_season_start_gets_the_long_story(db, realm, settings):
    game_id, realm_id = realm
    for _ in range(3):
        meeting.hold_meeting(db, realm_id, FakeClient(), settings)
        meeting.approve_plan(db, realm_id, excluded=[])
        resolve_open_turn(db, game_id)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 4
    voice_call = _by_role(client, "square_voice")[0]
    assert "A season has just ended" in voice_call["system"]
    assert "Decisions of the crown carried out: " in voice_call["user"]
    assert "build farm (January)" in voice_call["user"]
    assert meeting.list_messages(db, realm_id, 4)[0]["payload"] == {"season": True}


def test_silent_voice_does_not_stop_the_meeting(db, realm, settings):
    _, realm_id = realm
    client = FakeClient({"square_voice": [LLMError("timeout", "too slow")]})
    meeting.hold_meeting(db, realm_id, client, settings)
    kinds = [m["kind"] for m in meeting.list_messages(db, realm_id, 1)]
    assert kinds == ["report", "report", "summary"]


def test_older_games_get_a_voice_at_their_next_meeting(db, settings):
    no_voice = {role: model for role, model in settings.models.items() if role != "square_voice"}
    game_id = create_game(db, load_raw_config(), seed=7, realm_names=["Sud"], council_models=no_voice)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    roles = {r[0] for r in db.execute("SELECT role FROM actors WHERE realm_id = %s", (realm_id,))}
    assert "square_voice" in roles


def test_every_call_keeps_its_prompts(db, realm, settings):
    game_id, realm_id = realm
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    rows = db.execute(
        "SELECT prompt_system, prompt_user FROM model_calls WHERE game_id = %s", (game_id,)
    ).fetchall()
    assert len(rows) == 4 and all(system and user for system, user in rows)


# ------------------------------------------------------------------ views

def _wait(ui, realm_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if "hx-trigger" not in ui.get(f"/ui/realms/{realm_id}/council-panel").text:
            return
        time.sleep(0.05)
    raise AssertionError("council still running")


def _play_one_month(ui):
    created = ui.post("/ui/games", data={"realm_name": "Valdoro"}, follow_redirects=False)
    realm_id = int(re.search(r"/ui/realms/(\d+)", created.headers["location"]).group(1))
    ui.post(f"/ui/realms/{realm_id}/meeting")
    _wait(ui, realm_id)
    ui.post(f"/ui/realms/{realm_id}/approve", data={"plan_size": "2", "keep": ["0", "1"]})
    ui.post(f"/ui/realms/{realm_id}/resolve")
    return realm_id


def test_sovereign_never_sees_the_mood(database_url, settings):
    with TestClient(create_app(database_url, settings, FakeClient(), admin_view=False)) as ui:
        realm_id = _play_one_month(ui)
        state = ui.get(f"/realms/{realm_id}/state").json()
        for hidden in ("mood", "low_mood_turns", "birth_acc", "death_acc", "aging_acc", "rng_seed"):
            assert hidden not in state
        for page in ("", "/kingdom", "/chronicle"):
            text = html.unescape(ui.get(f"/ui/realms/{realm_id}{page}").text)
            assert "Umore" not in text and "/ 1000" not in text
        ui.post(f"/ui/realms/{realm_id}/meeting")  # February: the square speaks again
        _wait(ui, realm_id)
        turn_page = html.unescape(ui.get(f"/ui/realms/{realm_id}").text)
        assert "Malcontento" in turn_page and "Si dice in piazza" in turn_page
        assert "Umore" not in turn_page and "/ 1000" not in turn_page


def test_admin_view_is_hidden_when_off(database_url, settings):
    with TestClient(create_app(database_url, settings, FakeClient(), admin_view=False)) as ui:
        assert ui.get("/admin").status_code == 404
        assert "Amministrazione" not in ui.get("/ui").text


def test_admin_sees_everything(database_url, settings):
    fake = FakeClient()
    fake.queue("square_voice", "<i>Grida</i> in piazza")
    with TestClient(create_app(database_url, settings, fake, admin_view=True)) as ui:
        realm_id = _play_one_month(ui)
        game_id = int(re.search(r"Partita (\d+)", ui.get(f"/ui/realms/{realm_id}").text).group(1))
        game_page = html.unescape(ui.get(f"/admin/games/{game_id}").text)
        assert "Umore (nascosto al sovrano)" in game_page and '"mood":' in game_page
        replay = html.unescape(ui.post(f"/admin/games/{game_id}/replay").text)
        assert "Il replay coincide" in replay
        turn_page = ui.get(f"/admin/realms/{realm_id}/turns/1").text
        assert "Briefing inviato" in turn_page and "Prompt di sistema" in turn_page
        assert "&lt;i&gt;Grida&lt;/i&gt;" in turn_page  # model text stays text here too
        assert ui.get(f"/admin/realms/{realm_id}/lessons").status_code == 200
        assert ui.get(f"/admin/realms/{realm_id}/audiences").status_code == 200
        assert "Amministrazione" in ui.get("/ui").text
        assert ui.get("/admin/games/999999").status_code == 404
