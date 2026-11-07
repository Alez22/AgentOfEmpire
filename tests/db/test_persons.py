"""Persons: the council drawn from the catalog, names from gender, salaries
paid by the engine."""

from dataclasses import replace

import pytest

from engine import load_config, new_game, resolve_turn
from engine.config import load_raw_config
from server.council import meeting, persons
from server.council.llm import FakeClient
from server.council.settings import load_settings
from server.db.games import create_game, load_latest_state, role_names

CATALOG = persons.load_catalog()


@pytest.fixture
def settings():
    return replace(load_settings(), provider="fake")


def _game(db, settings, seed, realms=("Nord",)):
    game_id = create_game(db, load_raw_config(), seed=seed, realm_names=list(realms),
                          council_models=settings.models, personas=CATALOG, model_tiers=settings.model_tiers)
    realm_ids = [r[0] for r in db.execute("SELECT id FROM realms WHERE game_id = %s ORDER BY id", (game_id,))]
    return game_id, realm_ids


def test_catalog_has_moderates_and_extremes_for_each_role():
    for role in persons.COUNCIL_ROLES:
        groups = [p["group"] for p in CATALOG if p["role"] == role]
        assert groups.count("moderate") >= 2 and groups.count("extreme") >= 2


def test_council_is_drawn_from_moderates_with_its_model_and_salary(db, settings):
    _, (realm_id,) = _game(db, settings, seed=21)
    rows = db.execute("SELECT role, model, personality FROM actors WHERE realm_id = %s", (realm_id,)).fetchall()
    by_id = {p["id"]: p for p in CATALOG}
    salary = 0
    for role, model, personality in rows:
        if role in persons.COUNCIL_ROLES:
            person = by_id[personality["persona"]]
            assert person["group"] == "moderate" and model == settings.model_tiers[person["tier"]]
            assert personality["tier"] == person["tier"]
            assert personality["traits"] == person["traits"] and personality["name"] == person["name"]
            salary += person["salary"]
    assert load_latest_state(db, realm_id).council_salary == salary > 0


def test_same_seed_same_council_and_no_person_in_two_realms(db, settings):
    _, (a,) = _game(db, settings, seed=22)
    _, (b,) = _game(db, settings, seed=22)
    assert role_names(db, a) == role_names(db, b)
    _, two = _game(db, settings, seed=23, realms=("Nord", "Sud"))
    ids = [r[0] for r in db.execute(
        "SELECT personality->>'persona' FROM actors WHERE realm_id = ANY(%s) AND personality ? 'persona'", (two,))]
    assert len(ids) == len(set(ids)) == 6


def test_names_follow_the_gender_of_the_person():
    assert persons.display_name("architect", {"name": "Bertoldo Sassi", "gender": "m"}) == "Bertoldo Sassi, l'Architetto"
    assert persons.display_name("treasurer", {"name": "Brunilde Masi", "gender": "f"}) == "Brunilde Masi, la Tesoriera"
    assert persons.display_name("chancellor", {"name": "Costanza Vieri", "gender": "f"}) == "Costanza Vieri, la Cancelliera"
    assert persons.display_name("architect", {}) == "L'Architetta"  # games created before persons


def test_the_person_reaches_its_own_prompts(db, settings):
    _, (realm_id,) = _game(db, settings, seed=24)
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    names = role_names(db, realm_id)
    by_role = {c["role"]: c for c in client.calls}
    treasurer = db.execute("SELECT personality FROM actors WHERE realm_id = %s AND role = 'treasurer'",
                           (realm_id,)).fetchone()[0]
    assert f"You are {treasurer['name']}" in by_role["treasurer"]["system"]
    assert treasurer["resume"] in by_role["treasurer"]["system"]
    assert names["architect"] in by_role["chancellor"]["system"]
    assert "Council salaries per month:" in by_role["treasurer"]["user"]


def test_engine_pays_salaries_after_upkeep_and_reports_when_it_cannot():
    config = load_config()
    state = new_game(config, seed=1)
    state.council_salary = 10
    paid = resolve_turn(state, [], config)
    unpaid_free = replace(state, council_salary=0)
    assert resolve_turn(unpaid_free, [], config).state.gold - paid.state.gold == 10
    assert not any(e.kind == "salaries_unpaid" for e in paid.events)
    poor = replace(state, gold=0, tax_rate=0)
    events = resolve_turn(poor, [], config).events
    assert any(e.kind == "salaries_unpaid" for e in events)


def test_catalog_names_tiers_never_models():
    for person in CATALOG:
        assert "model" not in person and person["tier"] in ("low", "medium", "high")
