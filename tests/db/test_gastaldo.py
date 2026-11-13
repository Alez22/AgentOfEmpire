"""The Gastaldo and the bandits at the council (village block B+C, step 3),
with the fake model client: no network, no cost."""

from dataclasses import replace

import pytest
from psycopg.types.json import Jsonb

from engine.config import load_raw_config
from server.council import audience, mandates, manual, meeting, persons
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
    assert "gastaldo (set_militia, set_doors)" in chancellor["system"]
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
    moderates = {p["id"] for p in persons.load_catalog() if p["role"] == "gastaldo" and p["group"] == "moderate"}
    assert personality["persona"] in moderates
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
    assert "Bandits and arrivals:" in text and "nobody can count" in text
    assert any(section["title"] == "Briganti e arrivi" for section in manual.page_sections(config))
    from dataclasses import replace
    stage_one = replace(config, migration=None)  # games saved before stage 2
    assert "Bandits:" in manual.prompt_text(stage_one) and "doors" not in manual.prompt_text(stage_one)
    assert any(section["title"] == "Briganti" for section in manual.page_sections(stage_one))


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
        # Roads of the world: with bands the guards turn the odds, they stop nobody for sure.
        government = ui.get(f"/ui/realms/{realm_id}/government/panel").text
        assert "Una banda di 8 passa" in government and "100%" in government  # no guards yet
        assert "Bande avvistate in 6 mesi" in government and "Fermano" not in government


def test_the_sovereign_may_give_the_gastaldo_a_mandate(db, settings):
    """Village block B+C, step 4: the Gastaldo takes a mandate like the others,
    and the Chancellor reads it."""
    import json
    _, realm_id = _realm(db)
    with pytest.raises(meeting.CouncilError):
        mandates.check_request(db, realm_id, "gastaldo", "Poche guardie")  # not yet sitting
    _give_watchtower(db, realm_id)
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    text = "Il Gastaldo rimandi metà delle guardie nei campi se il bosco tace da tre mesi."
    review = json.dumps({"decision": "approved", "mandate": text, "reply": "Fatto, Maestà."})
    assert mandates.review(db, realm_id, "gastaldo", "Poche guardie se è tutto calmo",
                           FakeClient({"chancellor": [review]}), settings)["decision"] == "approved"
    client = FakeClient()  # the council already met this month: the audiences read the same prompts
    audience.speak(db, realm_id, "gastaldo", "Quante guardie?", client, settings)
    audience.speak(db, realm_id, "chancellor", "Che dice il Gastaldo?", client, settings)
    assert text in client.calls[0]["system"]
    assert f"Mandate of Il Gastaldo: «{text}»" in client.calls[1]["system"]


def test_the_government_page_shows_the_gate_and_the_chronicle_the_raid(db, database_url, settings):
    from fastapi.testclient import TestClient
    from server.app import create_app
    _, realm_id = _realm(db)
    with TestClient(create_app(database_url, settings, FakeClient())) as ui:
        page = ui.get(f"/ui/realms/{realm_id}/government").text
        assert "siederà in consiglio un Gastaldo" in page and "La porta e la guardia" not in page
    _give_watchtower(db, realm_id)
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    game_id = db.execute("SELECT game_id FROM realms WHERE id = %s", (realm_id,)).fetchone()[0]
    db.execute("INSERT INTO events (game_id, realm_id, turn, kind, data, visibility) VALUES (%s, %s, 1, 'raid', %s, 'public')",
               (game_id, realm_id, Jsonb({"raiders": 9, "guards": 0, "repelled": False, "food": 200, "wood": 25})))
    db.execute("UPDATE snapshots SET state = jsonb_set(state, '{militia}', '3') WHERE realm_id = %s", (realm_id,))
    db.execute("UPDATE snapshots SET turn = 2, state = jsonb_set(state, '{turn}', '2') WHERE realm_id = %s",
               (realm_id,))
    with TestClient(create_app(database_url, settings, FakeClient())) as ui:
        page = ui.get(f"/ui/realms/{realm_id}/government").text
        assert "La porta e la guardia" in page and "siederà in consiglio" not in page
        assert "gennaio" in page  # the last raid
        assert 'action="/ui/realms/%d/government/gastaldo"' % realm_id in page
        chronicle = ui.get(f"/ui/realms/{realm_id}/chronicle").text
        assert 'class="event-alert raid"' in chronicle and "Assalto" in chronicle


def test_the_gastaldo_speaks_in_the_debate(db, settings):
    """Village block B+C: the Gastaldo comments on the plan after the Architect."""
    from server.council import debate
    _, realm_id = _realm(db)
    _give_watchtower(db, realm_id)
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    client = FakeClient()
    debate.hold_debate(db, realm_id, client, settings)
    assert _roles_called(client) == ["treasurer", "architect", "gastaldo"]
    assert "You are the Gastaldo" in client.calls[-1]["system"]
    assert "## Already said in this debate" in client.calls[-1]["user"]


# ---- the doors (village block B+C, stage 2) -------------------------------------------

def _arrival_last_month(db, realm_id):
    game_id = db.execute("SELECT game_id FROM realms WHERE id = %s", (realm_id,)).fetchone()[0]
    db.execute("INSERT INTO events (game_id, realm_id, turn, kind, data, visibility)"
               " VALUES (%s, %s, 0, 'arrival', %s, 'public')",
               (game_id, realm_id, Jsonb({"adults": 3, "children": 1, "from_raids": 2, "grumbled": True})))


def test_the_gastaldo_keeps_the_doors(db, settings):
    _, realm_id = _realm(db)
    _give_watchtower(db, realm_id)
    _arrival_last_month(db, realm_id)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    gastaldo = next(c for c in client.calls if c["role"] == "gastaldo")
    assert '{"action": "set_doors", "doors": "closed" | "normal" | "open"}' in gastaldo["system"]
    assert "at least 2 guards" in gastaldo["system"]
    assert "Also the doors" in gastaldo["system"] and "a bet on growth" in gastaldo["system"]
    assert "- The doors: normal. Free beds: " in gastaldo["user"]
    assert "3 adults and 1 children settled (2 of them stopped raiders); the people grumbled" in gastaldo["user"]


def test_a_game_before_stage_two_has_no_doors(db, settings):
    raw = load_raw_config()
    del raw["migration"]
    game_id = create_game(db, raw, seed=3, realm_names=["Nord"], council_models=COUNCIL)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    _give_watchtower(db, realm_id)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    gastaldo = next(c for c in client.calls if c["role"] == "gastaldo")
    assert "set_doors" not in gastaldo["system"] and "a bet on growth" not in gastaldo["system"]
    assert "The doors:" not in gastaldo["user"]


def test_doors_already_in_force_are_dropped_from_the_plan(config):
    from engine import new_game
    state = new_game(config, seed=1)
    assert meeting._changes_nothing(state, {"action": "set_doors", "doors": "normal"})
    assert not meeting._changes_nothing(state, {"action": "set_doors", "doors": "open"})


def test_the_pages_show_the_doors_and_the_arrivals(db, database_url, settings):
    """Stage 2, step 4: the doors on the Gastaldo's card and among the laws,
    the arrivals in the chronicle and on the kingdom page."""
    from fastapi.testclient import TestClient
    from server.app import create_app
    _, realm_id = _realm(db)
    with TestClient(create_app(database_url, settings, FakeClient())) as ui:
        kingdom = ui.get(f"/ui/realms/{realm_id}/kingdom").text
        assert "<th>Porte</th><td>normali</td>" in kingdom  # before the watchtower too
        assert "Nuovi venuti" not in kingdom  # nobody came yet
    _give_watchtower(db, realm_id)
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    game_id = db.execute("SELECT game_id FROM realms WHERE id = %s", (realm_id,)).fetchone()[0]
    db.execute("INSERT INTO events (game_id, realm_id, turn, kind, data, visibility) VALUES (%s, %s, 1, 'arrival', %s, 'public')",
               (game_id, realm_id, Jsonb({"adults": 5, "children": 1, "from_raids": 4, "grumbled": False})))
    # Closed doors with one guard: they count as normal.
    db.execute("UPDATE snapshots SET turn = 2, state = state || '{\"turn\": 2, \"doors\": \"closed\", \"militia\": 1}'"
               " WHERE realm_id = %s", (realm_id,))
    with TestClient(create_app(database_url, settings, FakeClient())) as ui:
        page = ui.get(f"/ui/realms/{realm_id}/government").text
        assert 'class="doors-box not-held"' in page and "contano come normali" in page
        assert "Letti liberi" in page and "5 adulti, 1 bambini" in page and "4 erano briganti fermati" in page
        chronicle = ui.get(f"/ui/realms/{realm_id}/chronicle").text
        assert 'class="event-alert arrival"' in chronicle and "Sono arrivati a stabilirsi 5 adulti" in chronicle
        kingdom = ui.get(f"/ui/realms/{realm_id}/kingdom").text
        assert "<th>Nuovi venuti in 12 mesi</th><td>5 adulti, 1 bambini</td>" in kingdom
        assert "<th>Porte</th><td>normali</td>" in kingdom
    db.execute("UPDATE snapshots SET state = state || '{\"doors\": \"open\"}' WHERE realm_id = %s", (realm_id,))
    with TestClient(create_app(database_url, settings, FakeClient())) as ui:
        page = ui.get(f"/ui/realms/{realm_id}/government").text
        assert 'class="doors-box"' in page and "anche senza lavoro" in page
        assert "<th>Porte</th><td>aperte</td>" in ui.get(f"/ui/realms/{realm_id}/kingdom").text


def test_a_game_before_stage_two_shows_no_doors(db, database_url, settings):
    from fastapi.testclient import TestClient
    from server.app import create_app
    raw = load_raw_config()
    del raw["migration"]
    game_id = create_game(db, raw, seed=3, realm_names=["Nord"], council_models=COUNCIL)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    _give_watchtower(db, realm_id)
    meeting.hold_meeting(db, realm_id, FakeClient(), settings)
    with TestClient(create_app(database_url, settings, FakeClient())) as ui:
        page = ui.get(f"/ui/realms/{realm_id}/government").text
        assert "La porta e la guardia" in page and "doors-box" not in page and "Letti liberi" not in page
        assert "<th>Porte</th>" not in ui.get(f"/ui/realms/{realm_id}/kingdom").text
