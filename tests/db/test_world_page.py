"""The world view (server/ui/world_view.py, templates/world.html): the admin
sees every realm, a player only their own."""

import html
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
def client(database_url):
    settings = replace(load_settings(), provider="fake")
    with TestClient(create_app(database_url, settings, FakeClient(), admin_view=True)) as client:
        yield client


def _game(database_url, raw_config, names=("Nord", "Sud", "Est")) -> tuple[int, list[int]]:
    with psycopg.connect(database_url, autocommit=True) as conn:
        game_id = create_game(conn, raw_config, seed=3, realm_names=list(names),
                              council_models={"chancellor": "m", "treasurer": "m", "architect": "m"})
        realms = [r[0] for r in conn.execute("SELECT id FROM realms WHERE game_id = %s ORDER BY id", (game_id,))]
        return game_id, realms


def test_a_player_sees_only_their_own_realm(client, database_url):
    _, realms = _game(database_url, load_raw_config())
    page = html.unescape(client.get(f"/ui/realms/{realms[0]}/world").text)
    assert 'aria-current="page">Mondo</a>' in page
    assert page.count('<use href="#wh"') == 64 * 64  # the whole world's terrain
    assert page.count('class="realm-border"') == 1
    assert ">Nord</text>" in page and "Sud" not in page and "Est" not in page
    assert page.count('<text class="wl') == 13  # the square and the 12 starting buildings


def test_the_admin_sees_every_realm(client, database_url):
    game_id, _ = _game(database_url, load_raw_config())
    page = html.unescape(client.get(f"/admin/games/{game_id}/world").text)
    assert page.count('class="realm-border"') == 3
    assert all(f">{name}</text>" in page for name in ("Nord", "Sud", "Est"))
    assert page.count('<text class="wl') == 3 * 13
    assert f'href="/admin/games/{game_id}/world?zoom=1"' in page


def test_realm_names_stay_text(client, database_url):
    game_id, realms = _game(database_url, load_raw_config(), names=("<b>Nord</b>",))
    for url in (f"/ui/realms/{realms[0]}/world", f"/admin/games/{game_id}/world"):
        page = client.get(url).text
        assert "<b>Nord</b>" not in page and "&lt;b&gt;Nord&lt;/b&gt;" in page


def test_a_game_without_the_hex_world_says_so(client, database_url):
    raw = load_raw_config()
    raw["map"].update(grid="square", world_file="world.txt", core_file="core.toml")
    game_id, realms = _game(database_url, raw, names=("Nord",))
    assert "non ha la mappa a esagoni" in client.get(f"/ui/realms/{realms[0]}/world").text
    assert "non ha la mappa a esagoni" in client.get(f"/admin/games/{game_id}/world").text
