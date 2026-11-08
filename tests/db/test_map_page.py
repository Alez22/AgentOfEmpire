"""The sovereign's map page (server/ui/map_view.py, templates/map.html)."""

import re
from dataclasses import replace

import psycopg
import pytest
from fastapi.testclient import TestClient

from engine.config import load_raw_config
from server.app import create_app
from server.council.llm import FakeClient
from server.council.settings import load_settings
from server.db.games import create_game


@pytest.fixture
def ui(database_url):
    settings = replace(load_settings(), provider="fake")
    with TestClient(create_app(database_url, settings, FakeClient())) as client:
        yield client


def _realm(database_url, raw_config) -> int:
    with psycopg.connect(database_url, autocommit=True) as conn:
        game_id = create_game(conn, raw_config, seed=3, realm_names=["Nord"],
                              council_models={"chancellor": "m", "treasurer": "m", "architect": "m"})
        return conn.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]


def _square_raw():
    """The raw config of a game saved on the square grid (before 2026-11-08)."""
    raw = load_raw_config()
    raw["map"].update(grid="square", world_file="world.txt", core_file="core.toml")
    return raw


def test_the_map_shows_the_town_and_its_land(ui, database_url):
    realm_id = _realm(database_url, _square_raw())
    page = ui.get(f"/ui/realms/{realm_id}/map").text
    assert 'aria-current="page">Mappa</a>' in page
    assert page.count('class="map-building') == 13  # the square and the 12 starting buildings
    assert len(re.findall(r'class="t-river-n[ew]"', page)) == 1 and 't-river-sw' in page  # the bend joins up
    assert "Campi" in page and "posto per 2 fattorie" in page
    assert "Casa n. 12" in page and "In uso" in page  # the newest building is described


def test_choices_are_links(ui, database_url):
    realm_id = _realm(database_url, _square_raw())
    page = ui.get(f"/ui/realms/{realm_id}/map", params={"b": 0, "zone": "Campi", "zoom": 1}).text
    assert "Il cuore della città" in page  # the square is chosen
    assert page.count('class="map-zone lit"') == 1  # only the lit zone is drawn
    assert "repeat(16, 34px)" in page  # zoomed in
    assert f'href="/ui/realms/{realm_id}/map?zones=1&amp;zoom=1&amp;zone=Campi"' in page


def test_zone_names_from_the_model_stay_text(ui, database_url):
    realm_id = _realm(database_url, load_raw_config())
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("UPDATE snapshots SET state = jsonb_set(state, '{zones,0,name}', %s::jsonb)"
                     " WHERE realm_id = %s", ('"<b>Centro</b>"', realm_id))
    page = ui.get(f"/ui/realms/{realm_id}/map").text
    assert "<b>Centro</b>" not in page and "&lt;b&gt;Centro&lt;/b&gt;" in page


def test_a_realm_without_a_map_says_so(ui, database_url):
    raw = load_raw_config()
    del raw["map"]
    realm_id = _realm(database_url, raw)
    assert "nato prima della mappa" in ui.get(f"/ui/realms/{realm_id}/map").text


def _hex_raw():
    """The raw config of a hex game (docs/DESIGN.md, "Hex grid")."""
    raw = load_raw_config()
    raw["map"].update(grid="hex", world_file="world_hex.txt", core_file="core_hex.toml")
    return raw


def test_a_hex_realm_gets_the_svg_board(ui, database_url):
    realm_id = _realm(database_url, _hex_raw())
    page = ui.get(f"/ui/realms/{realm_id}/map").text
    assert 'class="hex-board"' in page and 'class="map-grid"' not in page
    assert page.count('class="map-building"') == 13  # the square and the 12 starting buildings, as links
    assert page.count('class="hit"') == 4 + 4 * 7 + 2 + 4 + 6  # square, farms, sawmill, quarry, houses
    assert "/static/icons/sprite.svg#i-barn" in page and 'class="border"' in page
    assert "1 esagono di pianura" in page  # the newest building, a house, is described in hexes
    assert "Crediti delle icone" in page


def test_the_hex_board_lights_a_zone_and_the_chosen_building(ui, database_url):
    realm_id = _realm(database_url, _hex_raw())
    page = ui.get(f"/ui/realms/{realm_id}/map", params={"b": 1, "zone": "Campi", "zoom": 1}).text
    assert page.count('class="zone lit"') == 1 and 'class="chosen"' in page
    assert "Fattoria n. 1" in page and "7 esagoni" in page and "#i-barn" in page
    assert re.search(r'class="hex-board"[^>]*style="width: \d+px"', page)  # zoomed: natural size, scrolling


def test_credits_list_every_icon_author(ui):
    page = ui.get("/ui/credits").text
    assert "CC BY 3.0" in page and "delapouite" in page and "lorc" in page
    assert page.count("sprite.svg#i-") == 15
