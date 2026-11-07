"""The manual of the realm: written from the game's config, read by every
counsellor, shown to the sovereign in Italian."""

import html
import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from engine.config import load_config, load_raw_config
from server.app import create_app
from server.council import manual, meeting
from server.council.llm import FakeClient
from server.council.settings import load_settings
from server.db.games import create_game


@pytest.fixture
def settings():
    return replace(load_settings(), provider="fake")


def test_manual_follows_the_config():
    config = load_config()
    text = manual.prompt_text(config)
    assert "- farm: costs wood 40, stone 10, gold 0; built in 2 months; 15 jobs; each worker yields 15 food" in text
    assert "even when not all its jobs are filled" in text
    assert "gold cannot buy food" in text and "It brings no food." in text
    assert "a strike (all production -30%)" in text
    richer = replace(config, buildings={**config.buildings, "farm": replace(config.buildings["farm"], jobs=20)})
    assert "20 jobs" in manual.prompt_text(richer)


def test_manual_leaves_out_the_mood_formulas():
    text = manual.prompt_text(load_config())
    assert "mood" not in text.lower().replace("their mood changes slowly", "")
    assert "per point" not in text and "/1000" not in text


def test_every_counsellor_reads_the_manual(db, settings):
    game_id = create_game(db, load_raw_config(), seed=15, realm_names=["Nord"], council_models=settings.models)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    client = FakeClient()
    meeting.hold_meeting(db, realm_id, client, settings)
    for call in client.calls:
        has_manual = "The manual of the realm" in call["system"]
        assert has_manual == (call["role"] in ("treasurer", "architect", "chancellor")), call["role"]


def test_manual_page_in_italian(database_url, settings):
    with TestClient(create_app(database_url, settings, FakeClient(), admin_view=False)) as ui:
        created = ui.post("/ui/games", data={"realm_name": "Valdoro"}, follow_redirects=False)
        realm_id = int(re.search(r"/ui/realms/(\d+)", created.headers["location"]).group(1))
        page = html.unescape(ui.get(f"/ui/realms/{realm_id}/manual").text)
        assert "Fattoria." in page and "15 posti di lavoro" in page and "anche se non è piena." in page
        assert "l'oro non compra cibo" in page
        assert "Manuale" in ui.get(f"/ui/realms/{realm_id}").text  # the tab
