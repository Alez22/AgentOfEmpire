"""Voice of the square, the sovereign's filtered view and the admin view."""

import html
import json
import re
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
        square = f"## What they say in the square\n- At the start of January (turn 1): {VOICE_TEXT}"
        assert square in _by_role(client, role)[0]["user"]


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


def test_admin_agents_page_shows_the_prompts_that_are_sent(database_url, settings):
    with TestClient(create_app(database_url, settings, FakeClient(), admin_view=True)) as ui:
        realm_id = _play_one_month(ui)
        page = html.unescape(ui.get(f"/admin/realms/{realm_id}/agents").text)
        for label in ("Riunione del consiglio", "Revisione delle lezioni (fine stagione)",
                      "Udienza privata", "Racconto del mese", "Racconto di inizio stagione"):
            assert label in page
        assert "prudence " in page and "deepseek/deepseek-v4.1-flash" in page
        assert "Ultimo briefing inviato" in page and "Turno 1" in page
    with psycopg.connect(database_url) as conn:
        sent = conn.execute(
            "SELECT c.prompt_system FROM model_calls c JOIN actors a ON a.id = c.actor_id"
            " WHERE c.realm_id = %s AND a.role IN ('treasurer', 'chancellor', 'square_voice')",
            (realm_id,),
        ).fetchall()
    assert len(sent) == 3 and all(system in page for (system,) in sent)


def test_admin_agents_page_is_hidden_when_off(database_url, settings):
    with TestClient(create_app(database_url, settings, FakeClient(), admin_view=False)) as ui:
        assert ui.get("/admin/realms/1/agents").status_code == 404


def test_council_hears_the_square_of_the_last_three_months(db, realm, settings):
    game_id, realm_id = realm
    for month in range(1, 5):
        meeting.hold_meeting(db, realm_id, FakeClient({"square_voice": [f"Voce {month}"]}), settings)
        meeting.approve_plan(db, realm_id, excluded=[])
        resolve_open_turn(db, game_id)
    client = FakeClient({"square_voice": ["Voce 5"]})
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 5
    treasurer = _by_role(client, "treasurer")[-1]["user"]
    assert "Voce 1" not in treasurer and "Voce 2" not in treasurer
    for month, name in ((3, "March"), (4, "April"), (5, "May")):
        assert f"- At the start of {name} (turn {month}): Voce {month}" in treasurer


def test_season_review_rereads_the_square(db, realm, settings):
    game_id, realm_id = realm
    for month in range(1, 4):
        meeting.hold_meeting(db, realm_id, FakeClient({"square_voice": [f"Voce {month}"]}), settings)
        meeting.approve_plan(db, realm_id, excluded=[])
        resolve_open_turn(db, game_id)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 4: reviews first
    review = client.calls[0]["user"]
    assert "## What happened this season" in review
    assert all(f"Voce {month}" in review for month in (1, 2, 3))


def _play_months_with_voices(db, game_id, realm_id, settings, months):
    for month in range(1, months + 1):
        meeting.hold_meeting(db, realm_id, FakeClient({"square_voice": [f"Voce {month}"]}), settings)
        meeting.approve_plan(db, realm_id, excluded=[])
        resolve_open_turn(db, game_id)


def test_voice_keeps_the_thread_of_its_last_two_turns(db, realm, settings):
    game_id, realm_id = realm
    _play_months_with_voices(db, game_id, realm_id, settings, 4)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 5
    facts = _by_role(client, "square_voice")[0]["user"]
    assert "## What you said before" in facts
    assert "- March: Voce 3" in facts and "- April: Voce 4" in facts and "Voce 2" not in facts


def test_voice_knows_only_what_is_evident(db, realm, settings):
    game_id, realm_id = realm
    db.execute(  # a council-only fact the square must never hear
        "INSERT INTO events (game_id, realm_id, turn, kind, data, visibility)"
        " VALUES (%s, %s, 1, 'upkeep_unpaid', '{}', 'council')", (game_id, realm_id))
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    audience.speak(db, realm_id, "architect", "Parliamo", FakeClient(), settings)
    meeting.approve_plan(db, realm_id, excluded=[])
    resolve_open_turn(db, game_id)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 2
    facts = _by_role(client, "square_voice")[0]["user"]
    assert "upkeep_unpaid" not in facts
    assert "demography" in facts and "audience {'role': 'architect'}" in facts
    assert "granar" not in facts.lower() and "per person" not in facts  # only guessed by the people
    assert "Ration: normal." in facts
    assert "Parliamo" not in facts  # never the words of an audience


def test_audience_fact_is_public(db, realm, settings):
    _, realm_id = realm
    audience.speak(db, realm_id, "treasurer", "Due parole", FakeClient(), settings)
    visibility = db.execute(
        "SELECT visibility::text FROM events WHERE realm_id = %s AND kind = 'audience'", (realm_id,)
    ).fetchone()[0]
    assert visibility == "public"


def test_season_story_covers_exactly_the_season(db, realm, settings):
    game_id, realm_id = realm
    _play_months_with_voices(db, game_id, realm_id, settings, 3)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 4: January-March told
    facts = _by_role(client, "square_voice")[0]["user"]
    mood_line = next(line for line in facts.splitlines() if line.startswith("- Mood"))
    assert "January" in mood_line and "April" in mood_line and "December" not in mood_line
    values = mood_line.split("oldest first: ")[1].split(", ")
    assert len(values) == 4  # start of the season + its three months


def test_voice_hears_why_the_people_feel_so(db, realm, settings):
    """Game 1: the square blamed hunger while the taxes weighed most."""
    _, realm_id = realm
    from server.council import voice
    ctx = meeting.load_context(db, realm_id, FakeClient(), settings)
    ctx.state.tax_rate, ctx.state.ration = 30, "reduced"
    line = voice.feelings_line(ctx)
    assert line.startswith("- What weighs on the people, heaviest first: the taxes (crushing); the short ration (heavy).")
    assert "What cheers them: nothing in particular." in line
    ctx.state.tax_rate, ctx.state.ration = 5, "abundant"
    assert voice.feelings_line(ctx).endswith("What cheers them: the generous ration (strong).")


def test_voice_never_hears_the_reserve_bonus(db, realm, settings):
    _, realm_id = realm
    from server.council import voice
    ctx = meeting.load_context(db, realm_id, FakeClient(), settings)
    ctx.state.tax_rate, ctx.state.food = 5, 100_000  # a huge stock: reserve bonus on
    assert "nothing in particular. What cheers them: nothing in particular." in voice.feelings_line(ctx)
