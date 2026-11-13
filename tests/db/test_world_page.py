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


def _seen_last_month(database_url, realm_id, game_id, x, y):
    """Move the realm to month 2 and give it a sighting in month 1."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("UPDATE snapshots SET state = jsonb_set(state, '{turn}', '2') WHERE realm_id = %s", (realm_id,))
        conn.execute("INSERT INTO events (game_id, realm_id, turn, kind, data, visibility)"
                     " VALUES (%s, %s, 1, 'band_seen', %s, 'court')",
                     (game_id, realm_id, psycopg.types.json.Jsonb(
                         {"band": 1, "adults": 9, "week": 2, "x": x, "y": y, "tower": False})))


def test_a_player_sees_only_the_bands_seen_last_month(client, database_url):
    game_id, realms = _game(database_url, load_raw_config())
    page = html.unescape(client.get(f"/ui/realms/{realms[0]}/world").text)
    assert 'class="band-mark"' not in page  # month 1: nothing seen yet, the start bands stay hidden
    _seen_last_month(database_url, realms[0], game_id, 18, 8)
    page = html.unescape(client.get(f"/ui/realms/{realms[0]}/world").text)
    assert page.count('class="band-mark"') == 1
    assert "Avvistata una banda di una decina di briganti" in page and ">9<" not in page


def test_the_admin_sees_every_band_with_its_size(client, database_url):
    game_id, _ = _game(database_url, load_raw_config())
    with psycopg.connect(database_url, autocommit=True) as conn:
        bands = conn.execute("SELECT state->'bands' FROM bandit_pools WHERE game_id = %s", (game_id,)).fetchone()[0]
    page = html.unescape(client.get(f"/admin/games/{game_id}/world").text)
    assert bands and page.count('class="band-mark"') == len(bands)
    assert f"Banda {bands[0]['id']}: {bands[0]['adults']} adulti" in page
