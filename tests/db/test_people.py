"""The people decide: behaviour inside the mood band, petitions, and the
engine applying it all, with exact replays."""

import html
import json
import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from engine import load_config, new_game, resolve_turn
from engine.config import load_raw_config
from engine.people import PeopleChoice
from server.app import create_app
from server.council import meeting, people
from server.council.llm import FakeClient, LLMError
from server.council.settings import load_settings
from server.db.games import create_game, list_orders, load_latest_state, resolve_open_turn
from server.db.replay import replay_game


@pytest.fixture
def settings():
    return replace(load_settings(), provider="fake")  # voice and people included


@pytest.fixture
def realm(db, settings):
    game_id = create_game(db, load_raw_config(), seed=8, realm_names=["Nord"],
                          council_models=settings.models)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    return game_id, realm_id


def _people_reply(effort, births, petition=None, reason="perché sì"):
    return json.dumps({"effort_pct": effort, "birth_pct": births, "petition": petition, "reason": reason})


def _decision(db, realm_id, turn=1):
    return db.execute(
        "SELECT effort_pct, birth_pct, petition, petition_text, source FROM people_decisions"
        " WHERE realm_id = %s AND turn = %s", (realm_id, turn),
    ).fetchone()


# ------------------------------------------------------------------ engine

def test_effort_births_and_petition_change_the_month():
    config = load_config()
    state = new_game(config, seed=1)
    usual = resolve_turn(state, [], config).state
    zeal = resolve_turn(state, [], config, PeopleChoice(effort_pct=10)).state
    assert zeal.food > usual.food and zeal.wood > usual.wood
    granted = resolve_turn(state, [], config, PeopleChoice(petition="granted", petition_weight=15)).state
    refused = resolve_turn(state, [], config, PeopleChoice(petition="refused", petition_weight=15)).state
    assert granted.mood - usual.mood == 15 and usual.mood - refused.mood == 15


def test_petition_weight_follows_the_relief():
    """Half the relief to the people's burdens, between 10 and 30 (game 5)."""
    from engine.people import petition_weight
    config = load_config()
    state = new_game(config, seed=1)  # taxes 10 %, normal ration
    assert petition_weight(state, config, {"action": "set_tax", "rate": 7}) == 15   # -50 -> -20
    assert petition_weight(state, config, {"action": "hold_feast", "gold": 10}) == 10  # +5: the minimum
    state.tax_rate = 5
    assert petition_weight(state, config, {"action": "set_tax", "rate": 4}) == 10  # no relief at all
    state.ration = "reduced"
    assert petition_weight(state, config, {"action": "set_ration", "ration": "normal"}) == 30  # capped


def test_games_saved_with_fixed_petitions_keep_them():
    config = load_config()
    old = replace(config, people=replace(config.people, petition_granted_mood=30, petition_refused_mood=-30,
                                         petition_min_mood=None, petition_max_mood=None))
    state = new_game(old, seed=1)
    usual = resolve_turn(state, [], old).state
    assert resolve_turn(state, [], old, PeopleChoice(petition="granted")).state.mood - usual.mood == 30


def test_neutral_choice_and_old_configs_change_nothing():
    config = load_config()
    state = new_game(config, seed=1)
    assert resolve_turn(state, [], config).state == resolve_turn(state, [], config, PeopleChoice()).state
    old = replace(config, people=None)  # a game saved before the people decided
    assert (resolve_turn(state, [], old, PeopleChoice(effort_pct=10, petition="granted")).state
            == resolve_turn(state, [], old).state)


# ------------------------------------------------------------------ decision

def test_meeting_stores_a_choice_kept_inside_the_mood_band(db, realm, settings):
    _, realm_id = realm
    client = FakeClient({"people": [_people_reply(50, 300)]})  # far beyond the limits
    meeting.hold_meeting(db, realm_id, client, settings)
    roles = [call["role"] for call in client.calls]
    assert roles[:2] == ["square_voice", "people"]  # after the square, before the council
    assert "Allowed this month: effort_pct from -8 to 8" in client.calls[1]["user"]  # mood 500: neutral
    assert _decision(db, realm_id)[:2] == (8, 110)
    assert _decision(db, realm_id)[4] == "model"


def test_silent_model_falls_back_to_the_rules(db, realm, settings):
    _, realm_id = realm
    client = FakeClient({"people": [LLMError("timeout", "too slow")]})
    meeting.hold_meeting(db, realm_id, client, settings)
    assert _decision(db, realm_id)[:2] == (0, 102) and _decision(db, realm_id)[4] == "rules"


@pytest.mark.parametrize("petition", [
    {"order": {"action": "set_tax", "rate": 10}, "text": "Lasciate tutto com'è"},  # changes nothing
    {"order": {"action": "build", "building": "farm"}, "text": "Una fattoria"},     # not theirs to ask
    {"order": {"action": "hold_feast", "gold": 5000}, "text": "Una festa enorme"},   # more gold than there is
    {"order": {"action": "set_tax", "rate": 5}, "text": ""},                         # no words
])
def test_impossible_petitions_are_dropped(db, realm, settings, petition):
    _, realm_id = realm
    meeting.hold_meeting(db, realm_id, FakeClient({"people": [_people_reply(0, 100, petition)]}), settings)
    assert _decision(db, realm_id)[2] is None


def _hold_with_petition(db, realm_id, settings):
    petition = {"order": {"action": "set_tax", "rate": 5}, "text": "Maestà, la gabella ci strangola."}
    client = FakeClient({"people": [_people_reply(-3, 100, petition)]})
    meeting.hold_meeting(db, realm_id, client, settings)
    return client


def test_council_hears_the_people_and_the_petition(db, realm, settings):
    _, realm_id = realm
    client = _hold_with_petition(db, realm_id, settings)
    treasurer = next(c for c in client.calls if c["role"] == "treasurer")["user"]
    assert "## The people this month" in treasurer
    assert "the peasants work reluctantly" in treasurer
    assert '"Maestà, la gabella ci strangola." (not answered yet)' in treasurer
    assert "this order runs first: set_tax 5" in treasurer
    # The harvest estimate counts the people's effort: 405 x 97 % = 392.
    assert "Harvest expected this month if nothing changes: 392 food" in treasurer
    assert "perché sì" not in treasurer  # the model's reason is for the admin only


def test_granting_a_petition_submits_its_order_first(db, realm, settings):
    game_id, realm_id = realm
    _hold_with_petition(db, realm_id, settings)
    people.answer_petition(db, realm_id, "granted")
    meeting.approve_plan(db, realm_id, excluded=[])
    orders = list_orders(db, realm_id, 1)
    assert orders[0]["raw"] == {"action": "set_tax", "rate": 5} and orders[0]["priority"] == -1
    with pytest.raises(people.PetitionError):
        people.answer_petition(db, realm_id, "refused")  # one answer only
    resolve_open_turn(db, game_id)
    assert load_latest_state(db, realm_id).tax_rate == 5
    assert replay_game(db, game_id) is None


def test_unanswered_petition_counts_as_refused(db, realm, settings):
    game_id, realm_id = realm
    _hold_with_petition(db, realm_id, settings)
    resolve_open_turn(db, game_id)
    assert people.recent_decisions(db, realm_id, 1, 1)[0]["answer"] is None
    from server.db.games import load_people_choice
    assert load_people_choice(db, realm_id, 1).petition == "refused"
    assert replay_game(db, game_id) is None
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 2: the square tells it
    facts = next(c for c in client.calls if c["role"] == "square_voice")["user"]
    assert "## What the people did" in facts
    assert '"Maestà, la gabella ci strangola." (refused)' in facts


def test_games_without_people_rules_decide_nothing(db, settings):
    raw = load_raw_config()
    del raw["people"]
    game_id = create_game(db, raw, seed=9, realm_names=["Sud"], council_models=settings.models)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    assert "people" not in [call["role"] for call in client.calls]
    assert _decision(db, realm_id) is None


# ------------------------------------------------------------------ pages

def test_sovereign_sees_the_people_and_answers_the_petition(database_url, settings):
    fake = FakeClient()
    fake.queue("people", _people_reply(-8, 80, {"order": {"action": "hold_feast", "gold": 20},
                                                "text": "Una festa, Maestà, per dimenticare il freddo."},
                                       reason="SEGRETO del modello"))
    with TestClient(create_app(database_url, settings, fake, admin_view=False)) as ui:
        created = ui.post("/ui/games", data={"realm_name": "Valdoro"}, follow_redirects=False)
        realm_id = int(re.search(r"/ui/realms/(\d+)", created.headers["location"]).group(1))
        ui.post(f"/ui/realms/{realm_id}/meeting")
        for _ in range(200):
            panel = ui.get(f"/ui/realms/{realm_id}/council-panel").text
            if "hx-trigger" not in panel:
                break
        page = html.unescape(ui.get(f"/ui/realms/{realm_id}").text)
        assert "I contadini lavorano svogliati; le famiglie rimandano i figli." in page
        assert "Resa di campi, segheria e cava: -8%" in page  # neutral band: kept at -8
        assert "«Una festa, Maestà, per dimenticare il freddo.»" in page and "Esaudisci" in page
        assert "SEGRETO" not in page
        ui.post(f"/ui/realms/{realm_id}/petition", data={"answer": "refused"})
        page = html.unescape(ui.get(f"/ui/realms/{realm_id}").text)
        assert "Supplica respinta." in page and "Esaudisci" not in page
        assert ui.get(f"/realms/{realm_id}/people?turn=1").json()["answer"] == "refused"


def test_granted_petition_keeps_the_plan_from_repeating_its_law(db, realm, settings):
    """Game 5: the plan's set_tax was rejected as a duplicate of the petition's."""
    _, realm_id = realm
    petition = {"order": {"action": "set_tax", "rate": 7}, "text": "Maestà, la gabella pesa."}
    plan = [{"proposer": "treasurer", "order": {"action": "set_tax", "rate": 7}},
            {"proposer": "architect", "order": {"action": "build", "building": "farm"}}]
    client = FakeClient({"people": [_people_reply(0, 100, petition)],
                         "chancellor": [json.dumps({"summary": "Maestà, ecco il piano.", "plan": plan})]})
    meeting.hold_meeting(db, realm_id, client, settings)
    people.answer_petition(db, realm_id, "granted")
    meeting.approve_plan(db, realm_id, excluded=[])
    assert [o["raw"]["action"] for o in list_orders(db, realm_id, 1)] == ["set_tax", "build"]


def test_petition_granted_after_the_plan_links_the_same_order(db, realm, settings):
    _, realm_id = realm
    petition = {"order": {"action": "set_tax", "rate": 7}, "text": "Maestà, la gabella pesa."}
    plan = [{"proposer": "treasurer", "order": {"action": "set_tax", "rate": 7}}]
    client = FakeClient({"people": [_people_reply(0, 100, petition)],
                         "chancellor": [json.dumps({"summary": "Maestà, ecco il piano.", "plan": plan})]})
    meeting.hold_meeting(db, realm_id, client, settings)
    meeting.approve_plan(db, realm_id, excluded=[])
    people.answer_petition(db, realm_id, "granted")
    orders = list_orders(db, realm_id, 1)
    assert len(orders) == 1
    linked = db.execute(
        "SELECT a.order_id FROM petition_answers a JOIN people_decisions d ON d.id = a.decision_id"
        " WHERE d.realm_id = %s", (realm_id,),
    ).fetchone()[0]
    assert linked == orders[0]["id"]


def test_discontented_people_get_their_own_ranges(db, realm, settings):
    """Game 7, turn 15: the first mood below 400 crashed the meeting."""
    _, realm_id = realm
    from engine.people import allowed_ranges
    state = load_latest_state(db, realm_id)
    state.mood = 380
    assert allowed_ranges(state, load_config()) == {"effort_pct": (-25, 0), "birth_pct": (60, 100)}


def test_a_meeting_broken_after_the_square_can_be_held_again(db, realm, settings):
    _, realm_id = realm
    broken = FakeClient({"treasurer": [RuntimeError("crash")]})
    with pytest.raises(RuntimeError):
        meeting.hold_meeting(db, realm_id, broken, settings)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # not stuck
    roles = [call["role"] for call in client.calls]
    assert "square_voice" not in roles and "people" not in roles  # they already spoke
    kinds = [m["kind"] for m in meeting.list_messages(db, realm_id, 1)]
    assert kinds.count("voice") == 1 and kinds.count("summary") == 1
