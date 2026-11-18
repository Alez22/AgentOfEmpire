"""The sovereign's map page (server/ui/map_view.py, templates/map.html)."""

import html
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
    assert re.search(r'aria-current="page">\s*<svg[^>]*>.*?</svg>Regno</a>', page, re.S)  # the tab
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
    page = ui.get(f"/ui/realms/{realm_id}/map", params={"b": 12}).text  # redirected to the realm's first page
    assert 'class="hex-board realm-board"' in page and 'class="map-grid"' not in page
    assert page.count('class="map-building"') == 13  # the square and the 12 starting buildings, as links
    assert page.count('class="hit"') == 4 + 4 * 7 + 2 + 4 + 6  # square, farms, sawmill, quarry, houses
    assert "/static/icons/sprite.svg#i-barn" in page and 'class="border"' in page
    assert "1 esagono di pianura" in page  # the chosen building, a house, is described in hexes


def test_the_hex_board_lights_a_zone_and_the_chosen_building(ui, database_url):
    realm_id = _realm(database_url, _hex_raw())
    page = ui.get(f"/ui/realms/{realm_id}/map", params={"b": 1, "zone": "Campi"}).text
    assert page.count('class="zone lit"') == 1 and 'class="chosen"' in page
    assert "Fattoria n. 1" in page and "7 esagoni" in page and "#i-barn" in page
    assert 'class="sheet-card"' in page and '<details class="sheet-more">' in page  # the card, the map in view


def test_credits_list_every_icon_author(ui):
    page = ui.get("/ui/credits").text
    assert "CC BY 3.0" in page and "delapouite" in page and "lorc" in page
    assert page.count("sprite.svg#i-") == 17  # 16 until the watchtower (village block B+C)


def test_a_watchtower_on_the_map_and_its_card(ui, database_url):
    """Village block B+C: the page draws a finished watchtower and describes it
    in its own slate hex with the game-icons watchtower (step 4)."""
    realm_id = _realm(database_url, _hex_raw())
    tower = {"kind": "watchtower", "turns_left": 0, "id": 13, "x": 0, "y": 0}
    with psycopg.connect(database_url, autocommit=True) as conn:
        state = conn.execute("SELECT state FROM snapshots WHERE realm_id = %s", (realm_id,)).fetchone()[0]
        zone = next(z for z in state["zones"] if z["purpose"] == "watch")
        tower.update(x=zone["x1"], y=zone["y1"])
        conn.execute("UPDATE snapshots SET state = jsonb_set(jsonb_set(state, '{buildings}', state->'buildings' || %s::jsonb),"
                     " '{next_building_id}', '14') WHERE realm_id = %s", (psycopg.types.json.Jsonb([tower]), realm_id))
    page = ui.get(f"/ui/realms/{realm_id}/map", params={"b": 13}).text
    assert "Torre di guardia n. 1" in page and "Torre di guardia" in page
    assert 'class="h-watch' in page and "#i-watchtower" in page


def test_the_realm_opens_on_its_map(ui, database_url):
    """docs/DESIGN.md, "The map as the realm's first page": HUD, sheet, tab bar."""
    realm_id = _realm(database_url, _hex_raw())
    page = html.unescape(ui.get(f"/ui/realms/{realm_id}").text)
    assert 'class="hex-board realm-board"' in page and 'class="hud"' in page
    assert re.search(r'aria-current="page">\s*<svg[^>]*>.*?</svg>Regno</a>', page, re.S)
    assert "Gennaio è aperto" in page or "è aperto" in page
    assert f'action="/ui/realms/{realm_id}/meeting"' in page and ">Convoca<" in page
    assert "Nessuna notizia: è il primo mese." in page
    assert '<details class="sheet-more">' in page
    assert page.count('class="sheet-card"') == 13  # only the hidden cards for the script, none shown
    assert "Il piano della città" in page and "Le terre del regno" in page


def test_the_old_map_link_lands_on_the_realm_page(ui, database_url):
    realm_id = _realm(database_url, _hex_raw())
    moved = ui.get(f"/ui/realms/{realm_id}/map", params={"b": 3, "zoom": 1}, follow_redirects=False)
    assert moved.status_code == 303 and moved.headers["location"] == f"/ui/realms/{realm_id}?b=3"


def test_a_square_realm_opens_on_the_council(ui, database_url):
    realm_id = _realm(database_url, _square_raw())
    moved = ui.get(f"/ui/realms/{realm_id}", follow_redirects=False)
    assert moved.headers["location"] == f"/ui/realms/{realm_id}/council"


def test_closing_the_month_opens_the_new_month_on_the_map(ui, database_url):
    realm_id = _realm(database_url, _hex_raw())
    closed = ui.post(f"/ui/realms/{realm_id}/resolve", follow_redirects=False)
    assert closed.headers["location"] == f"/ui/realms/{realm_id}"
    page = html.unescape(ui.get(closed.headers["location"]).text)
    assert "Febbraio è aperto" in page or "è aperto" in page
    assert 'class="hud-delta' in page  # the change since the previous month


def test_the_more_tab_links_the_other_pages(ui, database_url):
    realm_id = _realm(database_url, _hex_raw())
    page = ui.get(f"/ui/realms/{realm_id}/more").text
    for path in ("kingdom", "government", "world", "manual"):
        assert f'href="/ui/realms/{realm_id}/{path}"' in page
    assert re.search(r'aria-current="page">\s*<svg[^>]*>.*?</svg>Altro</a>', page, re.S)


def test_the_board_moves_where_people_live_and_work(ui, database_url):
    """Phase 3 (B): smoke over the 6 start houses, the wheat sways on the 4
    worked farms, the saw turns and the pick strikes; snow in January."""
    realm_id = _realm(database_url, _hex_raw())
    page = ui.get(f"/ui/realms/{realm_id}").text
    assert page.count('r="2.6" style="animation-delay') == 6 * 3
    assert page.count("i-wheat sway") == 4 * 6
    assert "i-building spin" in page and "i-building pick" in page
    assert 'data-season="winter"' in page and 'class="snow"' in page


def test_the_script_gets_every_card_and_the_frame(ui, database_url):
    """Phase 5 (G): static/map.js shows a card without a reload, frames the
    realm and puts the Voice's scroll over the square."""
    realm_id = _realm(database_url, _hex_raw())
    page = ui.get(f"/ui/realms/{realm_id}").text
    assert re.search(r'<script src="/static/map.js\?v=\d+" defer></script>', page)  # a new file, a new URL
    assert page.count('<template id="card-') == 13  # the square and the 12 starting buildings
    assert re.search(r'data-realm="\d+ \d+ \d+ \d+" data-square="\d+ \d+"', page)
    assert page.count('class="map-building" data-b=') == 13
    assert ui.get("/static/map.js").status_code == 200
