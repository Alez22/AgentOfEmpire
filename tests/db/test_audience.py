"""Private audiences with the fake model client."""

import html
import time
from dataclasses import replace

import psycopg
import pytest
from fastapi.testclient import TestClient

from engine.config import load_raw_config
from server.app import create_app
from server.council import audience, meeting
from server.council.llm import FakeClient, LLMError
from server.council.settings import load_settings
from server.db.access import Clearance, agent_context
from server.db.games import create_game, list_events_for_sovereign, resolve_open_turn

COUNCIL = {"chancellor": "top-model", "treasurer": "mid-model", "architect": "mid-model"}
SECRET = "Diffido della prudenza del Cancelliere"


@pytest.fixture
def settings():
    # Without the Voice of the square, so call positions stay as written
    # here; the voice has its own tests in test_voice.py.
    loaded = load_settings()
    models = {role: model for role, model in loaded.models.items() if role not in ("square_voice", "people")}
    return replace(loaded, provider="fake", models=models)


@pytest.fixture
def realm(db):
    game_id = create_game(db, load_raw_config(), seed=4, realm_names=["Nord"], council_models=COUNCIL)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    return game_id, realm_id


def test_dialogue_is_stored_and_answered_in_plain_text(db, realm, settings):
    _, realm_id = realm
    client = FakeClient({"treasurer": ["Maestà, le casse sono più vuote di quanto dica in consiglio."]})
    answer = audience.speak(db, realm_id, "treasurer", "Come stanno davvero le casse?", client, settings)
    assert answer.startswith("Maestà, le casse")
    assert client.calls[0]["system"].count("private audience") >= 1
    assert "Gold: 100." in client.calls[0]["user"]  # the usual numbers
    assert "«Come stanno davvero le casse?»" in client.calls[0]["user"]
    lines = audience.dialogue_for_sovereign(db, realm_id, "treasurer")
    assert [(line["speaker"], line["turn"]) for line in lines] == [("sovereign", 1), ("actor", 1)]


def test_audience_shapes_that_member_only_and_others_see_the_fact(db, realm, settings):
    _, realm_id = realm
    audience.speak(db, realm_id, "architect", SECRET, FakeClient(), settings)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    treasurer, architect, chancellor = (call["user"] for call in client.calls)
    assert SECRET in architect
    assert SECRET not in treasurer and SECRET not in chancellor
    assert "The sovereign received L'Architetta in private." in treasurer
    assert "The sovereign received L'Architetta in private." in chancellor
    assert "received L'Architetta" not in architect  # its own audience is in its dialogue


def test_fact_reaches_the_chronicle_but_not_the_content(db, realm, settings):
    game_id, realm_id = realm
    audience.speak(db, realm_id, "chancellor", SECRET, FakeClient(), settings)
    audience.speak(db, realm_id, "chancellor", "E ancora una cosa", FakeClient(), settings)
    resolve_open_turn(db, game_id)
    events = [e for e in list_events_for_sovereign(db, game_id, realm_id, 1) if e["kind"] == "audience"]
    assert [e["data"] for e in events] == [{"role": "chancellor"}]  # once per member per turn
    assert SECRET not in str(events)


def test_season_reflection_rereads_the_audiences(db, realm, settings):
    game_id, realm_id = realm
    audience.speak(db, realm_id, "treasurer", SECRET, FakeClient(), settings)
    for _ in range(3):
        meeting.hold_meeting(db, realm_id, FakeClient(), settings)
        meeting.approve_plan(db, realm_id, excluded=[])
        resolve_open_turn(db, game_id)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 4: reflections first
    treasurer_reflection = client.calls[0]["user"]
    assert "## Your private audiences with the sovereign this season" in treasurer_reflection
    assert SECRET in treasurer_reflection
    assert SECRET not in client.calls[1]["user"]  # the architect's reflection


def test_line_limit_per_member_and_turn(db, realm, settings):
    _, realm_id = realm
    small = replace(settings, max_audience_messages_per_turn=2)
    audience.speak(db, realm_id, "architect", "uno", FakeClient(), small)
    audience.speak(db, realm_id, "architect", "due", FakeClient(), small)
    with pytest.raises(audience.AudienceLimitError):
        audience.speak(db, realm_id, "architect", "tre", FakeClient(), small)
    audience.speak(db, realm_id, "treasurer", "uno", FakeClient(), small)  # other member: own limit


def test_missing_answer_keeps_the_line_and_the_next_one_covers_both(db, realm, settings):
    game_id, realm_id = realm
    client = FakeClient({"treasurer": [LLMError("timeout", "too slow")]})
    assert audience.speak(db, realm_id, "treasurer", "Prima domanda", client, settings) == ""
    audience.speak(db, realm_id, "treasurer", "Seconda domanda", client, settings)
    second_prompt = client.calls[1]["user"]
    assert "«Prima domanda»" in second_prompt and "«Seconda domanda»" in second_prompt
    statuses = [r[0] for r in db.execute(
        "SELECT status FROM model_calls WHERE game_id = %s ORDER BY id", (game_id,))]
    assert statuses == ["timeout", "ok"]


def test_unknown_member_is_refused(db, realm, settings):
    _, realm_id = realm
    with pytest.raises(audience.UnknownCounsellorError):
        audience.speak(db, realm_id, "marshal", "Ciao", FakeClient(), settings)


def test_agents_cannot_read_audiences(db, realm):
    game_id, realm_id = realm
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with agent_context(db, game_id, realm_id, Clearance.SOVEREIGN) as reader:
            reader.execute("SELECT content FROM audiences").fetchall()


def test_audiences_are_append_only(db, realm, settings):
    _, realm_id = realm
    audience.speak(db, realm_id, "treasurer", "Parole al vento", FakeClient(), settings)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("UPDATE audiences SET content = 'altro'")


def test_audience_from_the_phone(database_url, settings):
    fake = FakeClient()
    fake.queue("architect", "<b>Maestà</b>, costruirei una casa.")
    with TestClient(create_app(database_url, settings, fake)) as ui:
        created = ui.post("/ui/games", data={"realm_name": "Valdoro"}, follow_redirects=False)
        realm_id = int(created.headers["location"].rsplit("/", 1)[1])
        assert "Udienze private" in html.unescape(ui.get(f"/ui/realms/{realm_id}").text)

        sent = ui.post(f"/ui/realms/{realm_id}/audience/architect", data={"text": "Che ne pensi?"},
                       follow_redirects=False)
        assert sent.headers["location"] == f"/ui/realms/{realm_id}/audience/architect"
        deadline = time.monotonic() + 10
        panel = ""
        while time.monotonic() < deadline:
            panel = ui.get(f"/ui/realms/{realm_id}/audience/architect/panel").text
            if "hx-trigger" not in panel:
                break
            time.sleep(0.05)
        assert "&lt;b&gt;Maestà&lt;/b&gt;" in panel  # model text stays text
        assert "Che ne pensi?" in panel and "5 battute rimaste" in panel

        # The council panel is not disturbed by an audience, and vice versa.
        turn_page = html.unescape(ui.get(f"/ui/realms/{realm_id}").text)
        assert "Il consiglio discute" not in turn_page
        assert ui.get(f"/realms/{realm_id}/council/audiences/architect").json()[1]["speaker"] == "actor"
        assert ui.get(f"/ui/realms/{realm_id}/audience/marshal").status_code == 404
