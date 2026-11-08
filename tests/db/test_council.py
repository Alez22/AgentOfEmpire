"""Council meeting with the fake model client: no network, no cost."""

import json
from dataclasses import replace

import psycopg
import pytest
from fastapi.testclient import TestClient

from engine.config import load_raw_config
from server.app import create_app
from server.council import audience, meeting, memory
from server.council.llm import FakeClient, LLMError
from server.council.settings import load_settings
from server.db.access import Clearance, agent_context
from server.db import games
from server.db.games import create_game, list_orders, resolve_open_turn

COUNCIL = {"chancellor": "top-model", "treasurer": "mid-model", "architect": "mid-model"}


@pytest.fixture
def settings():
    # Without the Voice of the square and the people, so call positions stay
    # as written here; they have their own tests (test_voice_and_views, test_people).
    loaded = load_settings()
    models = {role: model for role, model in loaded.models.items() if role not in ("square_voice", "people")}
    return replace(loaded, provider="fake", models=models)


@pytest.fixture
def realm(db):
    game_id = create_game(db, load_raw_config(), seed=3, realm_names=["Nord"], council_models=COUNCIL)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    return game_id, realm_id


def _open_market_raw() -> dict:
    """@brief The config with the market open from the first month, as before
    village block A (the council's side of block A comes in its step 4)."""
    raw = load_raw_config()
    raw["market"]["needs_building"] = False
    return raw


@pytest.fixture
def open_realm(db):
    """A realm that can trade from the first month (the market before village block A)."""
    game_id = create_game(db, _open_market_raw(), seed=3, realm_names=["Nord"], council_models=COUNCIL)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    return game_id, realm_id


def _messages(db, realm_id, turn=1):
    return meeting.list_messages(db, realm_id, turn)


def _summary(db, realm_id, turn=1):
    return [m for m in _messages(db, realm_id, turn) if m["kind"] == "summary"][-1]


def _call_statuses(db, game_id):
    return [row[0] for row in db.execute(
        "SELECT status FROM model_calls WHERE game_id = %s ORDER BY id", (game_id,)
    )]


def test_meeting_stores_two_reports_and_a_checked_plan(db, realm, settings):
    game_id, realm_id = realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)

    messages = _messages(db, realm_id)
    assert [(m["kind"], m["speaker"]) for m in messages] == [
        ("report", "treasurer"), ("report", "architect"), ("summary", "chancellor"),
    ]
    plan = messages[2]["payload"]["plan"]
    assert plan == [
        {"proposer": "treasurer", "order": {"action": "hold_feast", "gold": 10}},
        {"proposer": "architect", "order": {"action": "build", "building": "farm"}},
    ]
    assert [v["accepted"] for v in messages[2]["payload"]["check"]["verdicts"]] == [True, True]
    assert _call_statuses(db, game_id) == ["ok", "ok", "ok"]
    assert [call["model"] for call in client.calls] == ["mid-model", "mid-model", "top-model"]
    # Each role gets the reasoning effort configured for it in council.toml.
    expected_efforts = [settings.reasoning_effort.get(r) for r in ("treasurer", "architect", "chancellor")]
    assert [call["reasoning_effort"] for call in client.calls] == expected_efforts


def test_briefings_contain_engine_numbers_and_traits_as_words(db, realm, settings):
    _, realm_id = realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    treasurer_call = client.calls[0]
    assert "Gold: 100." in treasurer_call["user"]
    assert "Food in store: 1600." in treasurer_call["user"]
    assert "Free tiles" not in treasurer_call["user"]  # the architect's section only
    assert any(word in treasurer_call["system"] for word in ("cautious", "bold", "balanced"))
    assert "L'Architetta" in client.calls[1]["system"]
    assert "L'Architetta" in client.calls[2]["system"]


def test_orders_outside_the_role_are_discarded(db, realm, settings):
    _, realm_id = realm
    sneaky = json.dumps({
        "report": "Costruiamo e tassiamo.",
        "proposals": [{"action": "build", "building": "house"}, {"action": "set_tax", "rate": 12}],
    })
    meeting.hold_meeting(db, realm_id, FakeClient({"treasurer": [sneaky]}), settings)
    treasurer = _messages(db, realm_id)[0]
    assert treasurer["payload"]["proposals"] == [{"action": "set_tax", "rate": 12}]
    assert treasurer["payload"]["discarded"][0]["reason"] == "NOT_ROLE_ACTION"


def test_invalid_reply_is_retried_once_then_minister_is_absent(db, realm, settings):
    game_id, realm_id = realm
    client = FakeClient({"treasurer": ["not json", "```json\n[1, 2]\n```"]})
    meeting.hold_meeting(db, realm_id, client, settings)
    treasurer = _messages(db, realm_id)[0]
    assert treasurer["payload"]["absent"] is True
    assert "non si è presentato" in treasurer["content"]
    assert _call_statuses(db, game_id)[:2] == ["invalid_reply", "invalid_reply"]


def test_reply_in_a_code_fence_is_accepted(db, realm, settings):
    _, realm_id = realm
    fenced = "```json\n" + json.dumps({"report": "Ok, Maestà, approvo.", "proposals": []}) + "\n```"
    meeting.hold_meeting(db, realm_id, FakeClient({"treasurer": [fenced]}), settings)
    assert _messages(db, realm_id)[0]["payload"]["absent"] is False


def test_timeout_makes_the_minister_absent_without_retry(db, realm, settings):
    game_id, realm_id = realm
    client = FakeClient({"architect": [LLMError("timeout", "too slow")]})
    meeting.hold_meeting(db, realm_id, client, settings)
    assert _messages(db, realm_id)[1]["payload"]["status"] == "timeout"
    assert _call_statuses(db, game_id).count("timeout") == 1


def test_absent_chancellor_gives_the_fixed_template_plan(db, realm, settings):
    _, realm_id = realm
    client = FakeClient({"chancellor": [LLMError("http_error", "HTTP 503")]})
    meeting.hold_meeting(db, realm_id, client, settings)
    summary = _summary(db, realm_id)
    assert summary["payload"]["absent"] is True
    assert "Il Cancelliere è assente" in summary["content"]
    assert len(summary["payload"]["plan"]) == 2


def test_exhausted_budget_silences_the_council(db, realm, settings):
    game_id, realm_id = realm
    db.execute(
        "INSERT INTO model_calls (game_id, turn, model, input_tokens, output_tokens, cost_usd,"
        " latency_ms, status) VALUES (%s, 0, 'earlier', 0, 0, %s, 0, 'ok')",
        (game_id, settings.budget_usd_per_game),
    )
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    assert client.calls == []
    reports = [m for m in _messages(db, realm_id) if m["kind"] == "report"]
    assert all("fondo per i consiglieri" in r["content"] for r in reports)
    assert _call_statuses(db, game_id)[1:] == ["budget_exhausted"] * 3


def test_second_meeting_in_the_same_turn_is_refused(db, realm, settings):
    _, realm_id = realm
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    with pytest.raises(meeting.MeetingAlreadyHeldError):
        meeting.hold_meeting(db, realm_id, FakeClient(), settings)


def test_directive_runs_a_new_round_and_reaches_the_briefings(db, realm, settings):
    _, realm_id = realm
    client = FakeClient()
    with pytest.raises(meeting.NoMeetingYetError):
        meeting.give_directive(db, realm_id, client, settings, "Risparmiate legno")
    meeting.hold_meeting(db, realm_id, client, settings)
    round_number = meeting.give_directive(db, realm_id, client, settings, "Risparmiate legno")
    assert round_number == 2
    assert "Risparmiate legno" in client.calls[-3]["user"]
    assert _summary(db, realm_id)["round"] == 2


def test_directives_are_limited_per_turn(db, realm, settings):
    _, realm_id = realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    for _ in range(settings.max_directives_per_turn):
        meeting.give_directive(db, realm_id, client, settings, "Ancora")
    with pytest.raises(meeting.TooManyDirectivesError):
        meeting.give_directive(db, realm_id, client, settings, "Basta")


def test_approval_records_each_order_with_its_minister(db, realm, settings):
    game_id, realm_id = realm
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    order_ids = meeting.approve_plan(db, realm_id, excluded=[0])
    assert len(order_ids) == 1
    architect_id = db.execute(
        "SELECT id FROM actors WHERE realm_id = %s AND role = 'architect'", (realm_id,)
    ).fetchone()[0]
    orders = list_orders(db, realm_id, 1)
    assert [(o["raw"], o["issued_by_actor_id"]) for o in orders] == [
        ({"action": "build", "building": "farm"}, architect_id)
    ]
    with pytest.raises(meeting.AlreadyApprovedError):
        meeting.approve_plan(db, realm_id, excluded=[])
    with pytest.raises(meeting.AlreadyApprovedError):
        meeting.give_directive(db, realm_id, FakeClient(), settings, "Troppo tardi")


def test_next_briefing_remembers_what_was_approved(db, realm, settings):
    game_id, realm_id = realm
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    meeting.approve_plan(db, realm_id, excluded=[])
    resolve_open_turn(db, game_id)

    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    architect_briefing = client.calls[1]["user"]
    assert "turn 1 (January): you proposed build farm." in architect_briefing
    assert "Approved: build farm carried out." in architect_briefing
    assert "Also decided that turn: hold_feast 10 (Il Tesoriere)." in architect_briefing
    assert "Afterwards: food 1600 → " in architect_briefing


def test_out_of_range_exclusion_is_refused(db, realm, settings):
    _, realm_id = realm
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    with pytest.raises(ValueError):
        meeting.approve_plan(db, realm_id, excluded=[7])


def test_council_through_the_api(database_url, settings):
    with TestClient(create_app(database_url, settings, FakeClient())) as client:
        game = client.post("/games", json={"seed": 5}).json()
        realm_id = game["realms"][0]["id"]
        messages = client.post(f"/realms/{realm_id}/council/meeting").json()
        # Without council_models in the request, the game takes council.toml's models.
        assert {call["model"] for call in client.app.state.llm_client.calls} == set(settings.models.values())
        assert [m["kind"] for m in messages] == ["report", "report", "summary"]
        assert client.post(f"/realms/{realm_id}/council/meeting").status_code == 409
        directive = client.post(f"/realms/{realm_id}/council/directives", json={"text": "Prudenza"})
        assert directive.status_code == 200
        approved = client.post(f"/realms/{realm_id}/council/approve", json={"exclude": []})
        assert approved.status_code == 201 and len(approved.json()["order_ids"]) == 2
        assert client.post(f"/games/{game['id']}/turns/resolve").json()["turn"] == 1
        assert len(client.get(f"/realms/{realm_id}/council", params={"turn": 1}).json()) == 7


def _play_turns_with_council(db, game_id, realm_id, settings, turns):
    for _ in range(turns):
        meeting.hold_meeting(db, realm_id, FakeClient(), settings)
        meeting.approve_plan(db, realm_id, excluded=[])
        resolve_open_turn(db, game_id)


def _actor_id(db, realm_id, role):
    return db.execute(
        "SELECT id FROM actors WHERE realm_id = %s AND role = %s", (realm_id, role)
    ).fetchone()[0]


def _lesson_texts(db, realm_id, role):
    return [lesson.text for lesson in memory.current_lessons(db, _actor_id(db, realm_id, role))]


def _revision(actions=(), new=()):
    return json.dumps({"actions": list(actions), "new_lessons": list(new)})


def test_no_reflection_before_the_end_of_the_first_season(db, realm, settings):
    game_id, realm_id = realm
    _play_turns_with_council(db, game_id, realm_id, settings, 2)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 3
    assert len(client.calls) == 3
    assert _lesson_texts(db, realm_id, "treasurer") == []


def test_first_meeting_of_a_season_writes_lessons_used_at_once(db, realm, settings):
    game_id, realm_id = realm
    _play_turns_with_council(db, game_id, realm_id, settings, 3)
    lesson = "Le razioni normali tengono calmo il popolo (turno 2)"
    client = FakeClient({"treasurer": [_revision(new=[lesson])]})
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 4

    # Three reflections (ministers and Chancellor) before the usual three calls.
    assert [call["role"] for call in client.calls] == [
        "treasurer", "architect", "chancellor", "treasurer", "architect", "chancellor",
    ]
    reflection = client.calls[0]["user"]
    assert "## What happened this season" in reflection
    assert "turn 3 (March): you proposed hold_feast 10." in reflection
    assert _lesson_texts(db, realm_id, "treasurer") == [lesson]
    assert f"[new in turn 4] {lesson}" in client.calls[3]["user"]  # same meeting
    assert lesson not in client.calls[4]["user"]  # never in a colleague's briefing
    assert lesson not in client.calls[5]["user"]  # nor the Chancellor's


def _treasurer_with_three_lessons(db, game_id, realm_id, settings):
    """Play to turn 7 with lessons A, B, C written at turn 4."""
    _play_turns_with_council(db, game_id, realm_id, settings, 3)
    start = FakeClient({"treasurer": [_revision(new=["A (turno 1)", "B (turno 2)", "C (turno 3)"])]})
    meeting.hold_meeting(db, realm_id, start, settings)  # turn 4
    meeting.approve_plan(db, realm_id, excluded=[])
    resolve_open_turn(db, game_id)
    _play_turns_with_council(db, game_id, realm_id, settings, 2)  # turns 5 and 6


def test_revision_confirms_revises_drops_and_adds(db, realm, settings):
    game_id, realm_id = realm
    _treasurer_with_three_lessons(db, game_id, realm_id, settings)
    answer = _revision(
        actions=[
            {"lesson": 1, "action": "confirm"},
            {"lesson": 2, "action": "revise", "text": "B corretta (turno 5)", "reason": "smentita al turno 5"},
            {"lesson": 3, "action": "drop", "reason": "non serve più"},
        ],
        new=["D (turno 6)"],
    )
    client = FakeClient({"treasurer": [answer]})
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 7

    assert _lesson_texts(db, realm_id, "treasurer") == ["A (turno 1)", "B corretta (turno 5)", "D (turno 6)"]
    history = dict(db.execute(
        "SELECT text, status::text || ':' || status_reason FROM lessons WHERE actor_id = %s",
        (_actor_id(db, realm_id, "treasurer"),),
    ).fetchall())
    assert history["B (turno 2)"] == "revised:smentita al turno 5"
    assert history["C (turno 3)"] == "dropped:non serve più"
    previous = db.execute(
        "SELECT p.text FROM lessons l JOIN lessons p ON p.id = l.previous_lesson_id"
        " WHERE l.text = 'B corretta (turno 5)'"
    ).fetchone()[0]
    assert previous == "B (turno 2)"
    briefing_text = client.calls[3]["user"]
    assert "[confirmed once, last in turn 7] A (turno 1)" in briefing_text
    assert "[revised in turn 7] B corretta (turno 5)" in briefing_text
    assert "C (turno 3)" not in briefing_text
    # The reflection prompt numbered the old lessons with their solidity.
    assert "1. [new in turn 4] A (turno 1)" in client.calls[0]["user"]


def test_malformed_revision_is_retried_then_changes_nothing(db, realm, settings):
    game_id, realm_id = realm
    _treasurer_with_three_lessons(db, game_id, realm_id, settings)
    calls_before = len(_call_statuses_for(db, game_id))
    bad_answer = json.dumps({"new_lessons": ["manca actions"]})  # missing key
    meeting.hold_meeting(db, realm_id, FakeClient({"treasurer": [bad_answer, bad_answer]}), settings)
    assert _lesson_texts(db, realm_id, "treasurer") == ["A (turno 1)", "B (turno 2)", "C (turno 3)"]
    assert _call_statuses_for(db, game_id)[calls_before:calls_before + 2] == ["invalid_reply"] * 2


@pytest.mark.parametrize("bad_action", [
    {"lesson": 9, "action": "confirm"},                # unknown lesson
    {"lesson": 1, "action": "drop"},                   # drop without reason
    {"lesson": 1, "action": "revise", "reason": "x"},  # revise without text
    "not an object",
])
def test_bad_action_is_discarded_and_the_others_apply(db, realm, settings, bad_action):
    game_id, realm_id = realm
    _treasurer_with_three_lessons(db, game_id, realm_id, settings)
    calls_before = len(_call_statuses_for(db, game_id))
    answer = _revision(actions=[bad_action, {"lesson": 3, "action": "drop", "reason": "smentita"}],
                       new=["D (turno 6)"])
    meeting.hold_meeting(db, realm_id, FakeClient({"treasurer": [answer]}), settings)  # turn 7
    assert _lesson_texts(db, realm_id, "treasurer") == ["A (turno 1)", "B (turno 2)", "D (turno 6)"]
    assert _call_statuses_for(db, game_id)[calls_before] == "ok"  # no retry
    error = db.execute(
        "SELECT c.error FROM model_calls c JOIN actors a ON a.id = c.actor_id"
        " WHERE c.game_id = %s AND c.turn = 7 AND a.role = 'treasurer' ORDER BY c.id LIMIT 1",
        (game_id,),
    ).fetchone()[0]
    assert error.startswith("discarded: ")


def test_new_lessons_beyond_the_maximum_are_cut(db, realm, settings):
    game_id, realm_id = realm
    _treasurer_with_three_lessons(db, game_id, realm_id, settings)
    answer = _revision(new=[f"nuova {i}" for i in range(8)])  # 3 + 8 > 10
    meeting.hold_meeting(db, realm_id, FakeClient({"treasurer": [answer]}), settings)
    texts = _lesson_texts(db, realm_id, "treasurer")
    assert len(texts) == 10 and texts[-1] == "nuova 6"


def test_small_format_slips_in_a_revision_are_tolerated(db, realm, settings):
    """Game 7: the Chancellor wrote "reason " with a trailing space."""
    game_id, realm_id = realm
    _treasurer_with_three_lessons(db, game_id, realm_id, settings)
    answer = _revision(actions=[
        {"lesson": "2", "Action": "Revise", "text": "B corretta (turno 6)", "reason ": "smentita"},
    ])
    meeting.hold_meeting(db, realm_id, FakeClient({"treasurer": [answer]}), settings)
    assert _lesson_texts(db, realm_id, "treasurer") == ["A (turno 1)", "C (turno 3)", "B corretta (turno 6)"]


def _call_statuses_for(db, game_id):
    return [row[0] for row in db.execute(
        "SELECT status FROM model_calls WHERE game_id = %s ORDER BY id", (game_id,)
    )]


def test_chancellor_learns_what_the_sovereign_removes_and_asks(db, realm, settings):
    game_id, realm_id = realm
    _play_turns_with_council(db, game_id, realm_id, settings, 1)
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)  # turn 2
    meeting.give_directive(db, realm_id, FakeClient(), settings, "Niente spese inutili")
    meeting.approve_plan(db, realm_id, excluded=[0])  # remove the treasurer's order
    resolve_open_turn(db, game_id)
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)  # turn 3: not approved at all
    resolve_open_turn(db, game_id)

    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 4
    chancellor_reflection = client.calls[2]["user"]
    assert "turn 2 (February): your plan: 1) hold_feast 10 (Il Tesoriere); 2) build farm (L'Architetta)." in chancellor_reflection
    assert 'Directives of the sovereign: "Niente spese inutili".' in chancellor_reflection
    assert "The sovereign approved it, removing 1) hold_feast 10." in chancellor_reflection
    assert "turn 3 (March)" in chancellor_reflection
    assert "The sovereign did not approve the plan." in chancellor_reflection
    assert "what the sovereign tends to approve" in client.calls[2]["system"]


def test_agents_cannot_read_lessons_even_through_row_level_security(db, realm):
    game_id, realm_id = realm
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with agent_context(db, game_id, realm_id, Clearance.SOVEREIGN) as reader:
            reader.execute("SELECT text FROM lessons").fetchall()


def test_lessons_never_reach_the_sovereign(database_url, settings):
    secret = "Il sovrano non capisce nulla di grano (turno 3)"
    client = FakeClient()
    with TestClient(create_app(database_url, settings, client)) as api:
        game = api.post("/games", json={"seed": 8}).json()
        game_id, realm_id = game["id"], game["realms"][0]["id"]
        for _ in range(3):
            api.post(f"/realms/{realm_id}/council/meeting")
            api.post(f"/realms/{realm_id}/council/approve", json={"exclude": []})
            api.post(f"/games/{game_id}/turns/resolve")
        client.queue("treasurer", _revision(new=[secret]))
        api.post(f"/realms/{realm_id}/council/meeting")  # turn 4: reflection
        everything_visible = "".join(
            api.get(path, params=params).text
            for path, params in [
                (f"/realms/{realm_id}/council", {"turn": 4}),
                (f"/realms/{realm_id}/events", {"turn": 3}),
                (f"/realms/{realm_id}/state", {}),
                (f"/games/{game_id}", {}),
            ]
        )
        assert secret not in everything_visible
    # ...while it really exists: otherwise the check above would prove nothing.
    with psycopg.connect(database_url, autocommit=True) as conn:
        stored = [row[0] for row in conn.execute(
            "SELECT text FROM lessons WHERE game_id = %s", (game_id,)
        )]
    assert secret in stored


def test_refused_reply_is_logged_and_the_retry_explains_why(db, realm, settings):
    game_id, realm_id = realm
    no_report_key = json.dumps({"proposals": []})  # "report" is required
    client = FakeClient({"treasurer": ["not json at all", no_report_key]})
    meeting.hold_meeting(db, realm_id, client, settings)

    rows = db.execute(
        "SELECT status, error, reply_excerpt FROM model_calls WHERE game_id = %s ORDER BY id LIMIT 3",
        (game_id,),
    ).fetchall()
    assert rows[0][0] == "invalid_reply" and rows[0][1].startswith("not a JSON object")
    assert rows[0][2] == "not json at all"
    assert rows[1][0] == "invalid_reply" and rows[1][1].startswith("wrong JSON shape: report")
    assert rows[2][0] == "ok" and rows[2][2] == ""  # normal replies are not stored twice
    # First attempt: plain briefing. Retry: same briefing + the refusal reason.
    assert "previous answer was refused" not in client.calls[0]["user"]
    assert "Reason: not a JSON object" in client.calls[1]["user"]
    assert client.calls[1]["user"].startswith(client.calls[0]["user"])


def test_discarded_actions_reach_the_log(db, realm, settings):
    game_id, realm_id = realm
    _treasurer_with_three_lessons(db, game_id, realm_id, settings)
    bad = _revision(actions=[{"lesson": 2, "action": "drop"}])
    meeting.hold_meeting(db, realm_id, FakeClient({"treasurer": [bad]}), settings)  # turn 7
    errors = [row[0] for row in db.execute(
        "SELECT c.error FROM model_calls c JOIN actors a ON a.id = c.actor_id"
        " WHERE c.game_id = %s AND c.turn = 7 AND a.role = 'treasurer' AND c.status = 'ok' ORDER BY c.id",
        (game_id,),
    )]
    assert errors[0] == "discarded: drop of lesson 2 needs a reason"


def test_no_council_prompt_contains_the_mood(db, realm, settings):
    """The council knows the people only from the square, like the sovereign."""
    game_id, realm_id = realm
    _play_turns_with_council(db, game_id, realm_id, settings, 3)
    mood = str(games.load_latest_state(db, realm_id).mood)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # turn 4: reflections + meeting
    audience.speak(db, realm_id, "treasurer", "Come sta il popolo?", client, settings)
    assert len(client.calls) == 7
    for call in client.calls:
        prompt = call["system"] + call["user"]
        assert "/1000" not in prompt and "threshold" not in prompt and "Mood of" not in prompt
        assert f"mood {mood}" not in prompt and f" {mood} " not in prompt
    assert "- Unrest: calm" in client.calls[3]["user"]


def test_briefings_show_the_harvest_and_the_empty_jobs(db, realm, settings):
    _, realm_id = realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)  # January: farms at 50 %
    treasurer, architect = client.calls[0]["user"], client.calls[1]["user"]
    # 53 farmers x 15 x 50 % = 397; 1600 + 397 - 860 eaten = 1137, minus 2 % rot = 1115.
    # (Seed 3: a site with every land level fair, so the yields are the buildings' own.)
    assert ("Harvest expected this month if nothing changes: 397 food (winter: farms yield 50%). "
            "After eating and rot the store would go from 1600 to about 1115: it shrinks.") in treasurer
    assert "Without any harvest it would last about 1.8 months." in treasurer
    assert "Jobs without workers: food 7, wood 6, stone 7, trade 0." in architect  # no market yet: no places
    assert "Expected this month if nothing changes: food +397, wood +24, stone +12." in architect


def test_orders_that_change_nothing_leave_the_plan(db, realm, settings):
    _, realm_id = realm
    plan = [
        {"proposer": "treasurer", "order": {"action": "set_tax", "rate": 10}},        # taxes already 10
        {"proposer": "treasurer", "order": {"action": "set_ration", "ration": "normal"}},
        {"proposer": "architect", "order": {"action": "assign_workers", "food": 53, "wood": 4, "stone": 3}},
        {"proposer": "architect", "order": {"action": "build", "building": "farm"}},
    ]
    chancellor = json.dumps({"summary": "Maestà, ecco il piano.", "plan": plan})
    meeting.hold_meeting(db, realm_id, FakeClient({"chancellor": [chancellor]}), settings)
    payload = _summary(db, realm_id)["payload"]
    assert [item["order"]["action"] for item in payload["plan"]] == ["build"]
    assert [d["reason"] for d in payload["discarded"]] == ["NO_CHANGE"] * 3


def test_prompts_tell_the_market_and_a_feast_brings_no_food(db, open_realm, settings):
    _, realm_id = open_realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    for call in client.calls:
        assert "common market shared with the other realms" in call["system"] and "it brings no food" in call["system"]
        assert "gold cannot buy food" not in call["system"]


def test_prompts_without_a_market_keep_the_old_rule(db, settings):
    raw = load_raw_config()
    del raw["market"]
    game_id = create_game(db, raw, seed=3, realm_names=["Nord"], council_models=COUNCIL)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    for call in client.calls:
        assert "gold cannot buy food" in call["system"] and '"action": "trade"' not in call["system"]
    assert "## The market" not in client.calls[0]["user"]


def test_only_the_treasurer_trades(db, open_realm, settings):
    _, realm_id = open_realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    treasurer, architect, chancellor = (call["system"] for call in client.calls[:3])
    assert "set_tax, set_ration, hold_feast, trade" in treasurer
    assert ", trade" not in architect.split("You may only propose these orders:")[1].split("\n")[0]
    assert "treasurer (set_tax, set_ration, hold_feast, trade)" in chancellor
    assert '"action": "trade"' in treasurer


def test_the_treasurer_reads_the_market(db, open_realm, settings):
    _, realm_id = open_realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    treasurer, chancellor = client.calls[0]["user"], client.calls[2]["user"]
    assert "## The market (shared with the other realms; lots of 50)" in treasurer
    assert "- food: buy 11, sell 9 gold a lot; in the warehouse 100; last month bought 0, put on sale 0." in treasurer
    assert "- Your goods waiting in the warehouse: none." in treasurer
    assert "- Firewood: 50 wood a month in Nov/Dec/Jan/Feb/Mar (50 this month)." in treasurer
    assert "## The market" not in client.calls[1]["user"]  # the Architect sees the needs, not the market
    assert "- Firewood: 50 wood a month" in client.calls[1]["user"]
    assert "- Market prices (buy/sell a lot of 50): food 11/9, wood 17/13, stone 22/18." in chancellor


def test_the_cost_check_counts_the_trades_first(db, settings):
    """Wood bought at the market pays for a house the same month."""
    game_id = create_game(db, _open_market_raw(), seed=3, realm_names=["Nord"], council_models=COUNCIL)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    buy_wood = {"action": "trade", "good": "wood", "side": "buy", "lots": 1}
    treasurer = json.dumps({"report": "Maestà, compriamo un lotto di legno al mercato.", "proposals": [buy_wood]})
    architect = json.dumps({"report": "Maestà, costruiamo una nuova fattoria nei campi.", "proposals": [{"action": "build", "building": "farm"}]})
    client = FakeClient({"treasurer": [treasurer], "architect": [architect]})
    meeting.hold_meeting(db, realm_id, client, settings)
    chancellor = client.calls[2]["user"]
    assert '- treasurer {"action": "trade", "good": "wood", "side": "buy", "lots": 1}: affordable' in chancellor
    assert '- architect {"action": "build", "building": "farm"}: affordable' in chancellor
    # 150 wood + 50 bought - 40 for the farm; 100 gold - 17 for the lot.
    assert "left: {'food': 1600, 'wood': 160, 'stone': 90, 'gold': 83}" in chancellor


def test_chancellor_is_warned_of_workers_beyond_the_jobs(db, realm, settings):
    _, realm_id = realm
    too_many = {"action": "assign_workers", "food": 40, "wood": 15, "stone": 5}  # sawmill: 10 jobs
    architect = json.dumps({"report": "Maestà, più legna.", "proposals": [too_many]})
    client = FakeClient({"architect": [architect]})
    meeting.hold_meeting(db, realm_id, client, settings)
    chancellor_briefing = client.calls[2]["user"]
    assert "WARNING: 5 wood workers beyond the 10 jobs would produce nothing" in chancellor_briefing


def test_chancellor_is_warned_of_adults_left_without_work(db, realm, settings):
    _, realm_id = realm
    as_a_change = {"action": "assign_workers", "food": 0, "wood": 1, "stone": 0}  # read as a change
    architect = json.dumps({"report": "Maestà, un uomo alla segheria.", "proposals": [as_a_change]})
    client = FakeClient({"architect": [architect]})
    meeting.hold_meeting(db, realm_id, client, settings)
    adults = games.load_latest_state(db, realm_id).adults
    assert f"WARNING: {adults - 1} adults would be left without work" in client.calls[2]["user"]


def test_jobs_at_harvest_count_sites_finishing_this_month(db, realm, settings):
    from engine.turn import jobs_at_harvest
    game_id, realm_id = realm
    state = games.load_latest_state(db, realm_id)
    config = games.load_game_config(db, game_id)
    assert jobs_at_harvest(state, config)["food"] == 60
    state.buildings[0].turns_left = 1  # a farm site that finishes this month
    assert jobs_at_harvest(state, config)["food"] == 60
    state.buildings[1].turns_left = 2  # still building at harvest time
    assert jobs_at_harvest(state, config)["food"] == 45


def test_treasurer_sees_the_coming_seasons(db, realm, settings):
    _, realm_id = realm
    client = FakeClient()
    # January, 53 farmers: 397 this month, so about 794 at full yield (the line
    # scales this month's rounded harvest).
    meeting.hold_meeting(db, realm_id, client, settings)
    assert ("- Coming seasons, with today's farmers: spring 100% (about 794 a month); "
            "summer 120% (about 952 a month); autumn 130% (about 1032 a month). "
            "Months left in this season: 3.") in client.calls[0]["user"]


def test_counsellors_must_quote_only_their_briefing_numbers(db, realm, settings):
    """Game 6: the Chancellor invented "ten idle workers" and a rule in force."""
    _, realm_id = realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    audience.speak(db, realm_id, "chancellor", "Quanti sono gli oziosi?", client, settings)
    for call in client.calls:
        assert "Quote only numbers that appear in your briefing" in call["system"]
        assert "as a rule or a decision already in force" in call["system"]
    assert "the total cannot exceed the adults" in client.calls[2]["system"]  # the Chancellor


def test_briefing_lists_the_jobs_of_each_building(db, realm, settings):
    """Game 7: "a farm creates two jobs" (it has 15), so no farm was built."""
    _, realm_id = realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    architect = client.calls[1]["user"]
    assert "farm: wood 40, stone 10, gold 0, 2 turns, 15 jobs" in architect
    assert "house: wood 30, stone 30, gold 20, 3 turns, houses 20 people" in architect
    assert "Empty jobs are not a problem in themselves" in client.calls[1]["system"]  # the Architect's craft


def test_a_reply_that_ran_up_to_the_cap_is_retried_without_reasoning(db, realm, settings):
    _, realm_id = realm
    runaway = "{" + "x" * (settings.max_output_tokens * 4)  # fake tokens = len // 4
    client = FakeClient({"treasurer": [runaway]})
    meeting.hold_meeting(db, realm_id, client, settings)
    treasurer_calls = [c for c in client.calls if c["role"] == "treasurer"]
    assert treasurer_calls[0]["reasoning_effort"] == settings.reasoning_effort["treasurer"]
    assert treasurer_calls[1]["reasoning_effort"] == "none"


def test_a_model_that_must_reason_is_retried_at_the_lowest_level(db, realm, settings):
    """Game 20: GLM 5.3 Flash answers reasoning "none" with HTTP 400."""
    _, realm_id = realm
    runaway = "{" + "x" * (settings.max_output_tokens * 4)
    client = FakeClient({"treasurer": [runaway]})
    meeting.hold_meeting(db, realm_id, client, replace(settings, models_reasoning_required=("mid-model",)))
    treasurer_calls = [c for c in client.calls if c["role"] == "treasurer"]
    assert treasurer_calls[1]["reasoning_effort"] == "low"


def test_an_ordinary_refusal_keeps_the_reasoning_level(db, realm, settings):
    _, realm_id = realm
    client = FakeClient({"treasurer": ["not json at all"]})
    meeting.hold_meeting(db, realm_id, client, settings)
    treasurer_calls = [c for c in client.calls if c["role"] == "treasurer"]
    assert treasurer_calls[1]["reasoning_effort"] == settings.reasoning_effort["treasurer"]



def test_each_role_has_its_own_craft(db, realm, settings):
    _, realm_id = realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    treasurer, architect, chancellor = (c["system"] for c in client.calls[:3])
    assert "granary, treasury and registry" in treasurer and "works and labour" not in treasurer
    assert "works and labour" in architect and "granary, treasury and registry" not in architect
    assert "What your training taught you (government)" in chancellor
    for system in (treasurer, architect, chancellor):
        assert "good practice, not laws" in system and "as your own outlook leads you" in system


def test_treasurer_reads_every_ration_and_the_registry(db, realm, settings):
    _, realm_id = realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    treasurer = client.calls[0]["user"]
    assert "- Eaten per month at each ration: reduced 602, normal 860, abundant 1118." in treasurer
    assert "children will come of age in the next three months" in treasurer
    assert "Housing: 100 people, 120 places, 20 free." in treasurer
    assert "Registry" not in client.calls[1]["user"]  # the Architect has to ask


def test_a_report_far_over_its_length_is_asked_again(db, realm, settings):
    """Game 21: a report of over a thousand words, repeating its signature."""
    _, realm_id = realm
    endless = json.dumps({"report": "Maestà, firmato la Tesoriera. " * 120, "proposals": []})
    client = FakeClient({"treasurer": [endless]})
    meeting.hold_meeting(db, realm_id, client, settings)
    treasurer_calls = [c for c in client.calls if c["role"] == "treasurer"]
    assert len(treasurer_calls) == 2 and "far over the limit" in treasurer_calls[1]["user"]
    report = next(m for m in _messages(db, realm_id) if m["speaker"] == "treasurer")
    assert report["content"].startswith("Maestà, le casse reggono")  # the retry's answer


def test_a_summary_of_three_dots_is_asked_again(db, realm, settings):
    """Game 21: the Chancellor answered "..." with an empty plan."""
    _, realm_id = realm
    client = FakeClient({"chancellor": [json.dumps({"summary": "...", "plan": []})]})
    meeting.hold_meeting(db, realm_id, client, settings)
    assert _summary(db, realm_id)["content"] == "Maestà, ecco il piano del consiglio."
    assert len(_summary(db, realm_id)["payload"]["plan"]) == 2


# ---- Village block A: the market as a building (docs/DESIGN.md, step 4) ----

def test_a_realm_without_its_market_is_told_so_and_cannot_trade(db, realm, settings):
    _, realm_id = realm
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    by_role = {c["role"]: c for c in client.calls if c["role"] in ("treasurer", "architect", "chancellor")}
    treasurer, architect, chancellor = by_role["treasurer"], by_role["architect"], by_role["chancellor"]
    assert "The realm has no market yet" in treasurer["system"]
    assert '"action": "trade"' not in treasurer["system"] and '"action": "set_merchant_tax"' not in treasurer["system"]
    assert "You may only propose these orders: set_tax, set_ration, hold_feast. Any" in treasurer["system"]
    assert "## The market\n- The realm has no market yet: no trade, and no news of the prices" in treasurer["user"]
    assert "buy 11" not in treasurer["user"]  # no prices without the market
    assert '"building": "market"' in architect["system"] and '"trade": <int>' in architect["system"]
    assert "What your training taught you about the market building" in architect["system"]
    assert "The realm has no market yet: any trade would be refused." in chancellor["user"]


def _play(db, game_id, realm_id, orders_by_turn):
    for orders in orders_by_turn:
        for order in orders:
            games.submit_order(db, realm_id, order)
        resolve_open_turn(db, game_id)


def test_a_finished_market_with_merchants_reaches_the_council_and_the_square(db, realm, settings):
    game_id, realm_id = realm
    staff = {"action": "assign_workers", "food": 50, "wood": 4, "stone": 3, "trade": 3}
    _play(db, game_id, realm_id, [[{"action": "build", "building": "market"}], [], [staff]])
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    treasurer = next(c for c in client.calls if c["role"] == "treasurer")
    assert '"action": "trade"' in treasurer["system"] and '"action": "set_merchant_tax"' in treasurer["system"]
    assert "What your training taught you about the merchants" in treasurer["system"]
    assert "- Your merchants: 3 at the market (6 places); this month they can handle 9 lots in all" in treasurer["user"]
    assert "- Merchants' tax: 10% of the gold value of the month's trades" in treasurer["user"]
    assert "buy 11" in treasurer["user"]
    # The council's test settings have no Voice: read its facts directly.
    from server.council import voice
    facts = voice.facts_for_the_square(meeting.load_context(db, realm_id, None, None), season=False)
    assert "## The merchants" in facts and "Mood of the merchants (0-1000; NEVER say it): " in facts
