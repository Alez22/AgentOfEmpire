"""Web UI with the fake council: pages render, forms act, the meeting runs
in the background and the page finds it again."""

import html
import json
import re
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.council.llm import FakeClient
from server.council.settings import load_settings


@pytest.fixture
def fake():
    return FakeClient()


@pytest.fixture
def ui(database_url, fake):
    settings = replace(load_settings(), provider="fake")
    with TestClient(create_app(database_url, settings, fake)) as client:
        yield client


def _new_realm(ui) -> int:
    response = ui.post("/ui/games", data={"realm_name": "Valdoro"}, follow_redirects=False)
    assert response.status_code == 303
    return int(re.search(r"/ui/realms/(\d+)", response.headers["location"]).group(1))


def _wait_for_council(ui, realm_id, timeout_s=10.0, raw=False):
    """The round runs in a thread: poll like the page does.
    @return The panel as the player reads it (entities decoded), or raw HTML."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        panel = ui.get(f"/ui/realms/{realm_id}/council-panel").text
        if "hx-trigger" not in panel:
            return panel if raw else html.unescape(panel)
        time.sleep(0.05)
    raise AssertionError("council still running")


def test_games_page_and_new_game(ui):
    assert ui.get("/", follow_redirects=False).headers["location"] == "/ui"
    realm_id = _new_realm(ui)
    page = ui.get("/ui").text
    assert "Valdoro" in page and f"/ui/realms/{realm_id}" in page


def test_turn_page_before_the_council(ui):
    realm_id = _new_realm(ui)
    page = html.unescape(ui.get(f"/ui/realms/{realm_id}").text)
    assert "Valdoro, gennaio" in page
    assert "Convoca il consiglio" in page
    assert "Il consiglio non si è riunito" in page


def test_full_month_from_the_phone(ui):
    realm_id = _new_realm(ui)
    assert ui.post(f"/ui/realms/{realm_id}/meeting", follow_redirects=False).status_code == 303
    panel = _wait_for_council(ui, realm_id)
    # The council is drawn from the catalog of persons: a name and the office.
    for office in ("Tesorier", "Architett", "Cancellier"):
        assert office in panel
    assert "Festa per il popolo: 10 oro" in panel and "Costruire: fattoria" in panel
    assert "Approva il piano" in panel and "2 rimaste" in panel

    # Keep only the second order of the plan (the farm).
    approved = ui.post(f"/ui/realms/{realm_id}/approve",
                       data={"plan_size": "2", "keep": ["1"]}, follow_redirects=False)
    assert approved.status_code == 303
    page = html.unescape(ui.get(f"/ui/realms/{realm_id}").text)
    assert "Ordini approvati" in page and "Costruire: fattoria" in page

    ui.post(f"/ui/realms/{realm_id}/resolve", follow_redirects=False)
    page = html.unescape(ui.get(f"/ui/realms/{realm_id}").text)
    assert "Valdoro, febbraio" in page
    assert "Il mese scorso" in page and "Andato a male nei granai" in page
    chronicle = ui.get(f"/ui/realms/{realm_id}/chronicle").text
    assert "Turno 1 · gennaio" in chronicle
    kingdom = ui.get(f"/ui/realms/{realm_id}/kingdom").text
    assert "1 in costruzione" in kingdom


def test_second_meeting_is_refused_with_a_message(ui):
    realm_id = _new_realm(ui)
    ui.post(f"/ui/realms/{realm_id}/meeting")
    _wait_for_council(ui, realm_id)
    response = ui.post(f"/ui/realms/{realm_id}/meeting", follow_redirects=False)
    assert "error=" in response.headers["location"]
    assert "already met" in html.unescape(ui.get(response.headers["location"]).text)


def test_directive_runs_a_second_round(ui, fake):
    realm_id = _new_realm(ui)
    ui.post(f"/ui/realms/{realm_id}/meeting")
    _wait_for_council(ui, realm_id)
    ui.post(f"/ui/realms/{realm_id}/directive", data={"text": "Prudenza col legno"})
    panel = _wait_for_council(ui, realm_id)
    assert "«Prudenza col legno»" in panel
    assert "Prima riunione" in panel  # the first round is folded away
    assert "1 rimasta" in panel
    assert "Prudenza col legno" in fake.calls[-1]["user"]


def test_model_text_cannot_inject_html(ui, fake):
    realm_id = _new_realm(ui)
    fake.queue("treasurer", json.dumps({"report": "<script>alert('x')</script>", "proposals": []}))
    ui.post(f"/ui/realms/{realm_id}/meeting")
    panel = _wait_for_council(ui, realm_id, raw=True)
    assert "<script>alert" not in panel
    assert "&lt;script&gt;" in panel


def test_unknown_realm_gives_404_page(ui):
    response = ui.get("/ui/realms/999999")
    assert response.status_code == 404 and "Non trovato" in response.text


def test_static_files_are_served(ui):
    assert ui.get("/static/style.css").status_code == 200
    assert ui.get("/static/htmx-2.0.11.min.js").status_code == 200
