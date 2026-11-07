"""Council meeting with the fake model client: no network, no cost."""

import json
from dataclasses import replace

import psycopg
import pytest
from fastapi.testclient import TestClient

from engine.config import load_raw_config
from server.app import create_app
from server.council import meeting, memory
from server.council.llm import FakeClient, LLMError
from server.council.settings import load_settings
from server.db.access import Clearance, agent_context
from server.db.games import create_game, list_orders, resolve_open_turn

COUNCIL = {"chancellor": "top-model", "treasurer": "mid-model", "architect": "mid-model"}


@pytest.fixture
def settings():
    # Without the Voice of the square, so call positions stay as written
    # here; the voice has its own tests in test_voice.py.
    loaded = load_settings()
    models = {role: model for role, model in loaded.models.items() if role != "square_voice"}
    return replace(loaded, provider="fake", models=models)


@pytest.fixture
def realm(db):
    game_id = create_game(db, load_raw_config(), seed=3, realm_names=["Nord"], council_models=COUNCIL)
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
        {"proposer": "treasurer", "order": {"action": "set_ration", "ration": "normal"}},
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
    assert "Food in store: 2000." in treasurer_call["user"]
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
    fenced = "```json\n" + json.dumps({"report": "Ok.", "proposals": []}) + "\n```"
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
    assert "Also decided that turn: set_ration normal (Il Tesoriere)." in architect_briefing
    assert "Afterwards: food 2000 → " in architect_briefing


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
    assert "turn 3 (March): you proposed set_ration normal." in reflection
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


@pytest.mark.parametrize("bad_answer", [
    _revision(actions=[{"lesson": 9, "action": "confirm"}]),                # unknown lesson
    _revision(actions=[{"lesson": 1, "action": "drop"}]),                   # drop without reason
    _revision(actions=[{"lesson": 1, "action": "revise", "reason": "x"}]),  # revise without text
    _revision(new=[f"nuova {i}" for i in range(8)]),                        # 3 + 8 > 10 lessons
    json.dumps({"new_lessons": ["manca actions"]}),                          # missing key
])
def test_invalid_revision_is_retried_then_changes_nothing(db, realm, settings, bad_answer):
    game_id, realm_id = realm
    _treasurer_with_three_lessons(db, game_id, realm_id, settings)
    calls_before = len(_call_statuses_for(db, game_id))
    meeting.hold_meeting(db, realm_id, FakeClient({"treasurer": [bad_answer, bad_answer]}), settings)
    assert _lesson_texts(db, realm_id, "treasurer") == ["A (turno 1)", "B (turno 2)", "C (turno 3)"]
    assert _call_statuses_for(db, game_id)[calls_before:calls_before + 2] == ["invalid_reply"] * 2


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
    assert "turn 2 (February): your plan: 1) set_ration normal (Il Tesoriere); 2) build farm (L'Architetta)." in chancellor_reflection
    assert 'Directives of the sovereign: "Niente spese inutili".' in chancellor_reflection
    assert "The sovereign approved it, removing 1) set_ration normal." in chancellor_reflection
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


def test_revision_rule_errors_reach_the_log(db, realm, settings):
    game_id, realm_id = realm
    _treasurer_with_three_lessons(db, game_id, realm_id, settings)
    bad = _revision(actions=[{"lesson": 2, "action": "drop"}])
    meeting.hold_meeting(db, realm_id, FakeClient({"treasurer": [bad, bad]}), settings)  # turn 7
    errors = [row[0] for row in db.execute(
        "SELECT error FROM model_calls WHERE game_id = %s AND turn = 7 AND status = 'invalid_reply'",
        (game_id,),
    )]
    assert errors == ["drop of lesson 2 needs a reason"] * 2
