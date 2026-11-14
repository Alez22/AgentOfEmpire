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


def test_the_fair_is_on_the_world_view_with_caravans(client, database_url):
    """Roads of the world, phase 2: the fair in the empty middle, for players and admin alike."""
    game_id, realms = _game(database_url, load_raw_config())
    for url in (f"/ui/realms/{realms[0]}/world", f"/admin/games/{game_id}/world"):
        page = html.unescape(client.get(url).text)
        assert page.count('class="fair-mark"') == 1 and "La fiera: il magazzino del mercato" in page
    raw = load_raw_config()
    raw.pop("caravans")
    _, old_realms = _game(database_url, raw)
    assert 'class="fair-mark"' not in client.get(f"/ui/realms/{old_realms[0]}/world").text


def _play_months(database_url, game_id, months):
    """Resolve `months` turns with no orders: snapshots 2..months+1 appear."""
    from server.db.games import resolve_open_turn
    with psycopg.connect(database_url, autocommit=True) as conn:
        for _ in range(months):
            resolve_open_turn(conn, game_id)


def test_the_admin_timelapse_shows_a_past_month(client, database_url):
    game_id, _ = _game(database_url, load_raw_config())
    _play_months(database_url, game_id, 2)
    page = html.unescape(client.get(f"/admin/games/{game_id}/world?turn=2").text)
    assert "Turno 2 di 3: il mondo all'inizio di febbraio, anno 1." in page
    assert page.count('class="realm-border"') == 3
    assert "Nel mese di gennaio" in page
    assert f'href="/admin/games/{game_id}/world?zoom=0&turn=1"' in page  # back
    assert f'href="/admin/games/{game_id}/world?zoom=0&turn=3"' in page  # forward
    assert 'http-equiv="refresh"' not in page  # paused


def test_the_timelapse_plays_with_a_meta_refresh_and_stops_at_the_end(client, database_url):
    game_id, _ = _game(database_url, load_raw_config())
    _play_months(database_url, game_id, 2)
    page = html.unescape(client.get(f"/admin/games/{game_id}/world?turn=1&play=1").text)
    assert f'content="2;url=/admin/games/{game_id}/world?zoom=0&turn=2&play=1"' in page
    assert "❚❚ Pausa" in page
    last = html.unescape(client.get(f"/admin/games/{game_id}/world?turn=3&play=1").text)
    assert 'http-equiv="refresh"' not in last and "▶ Riproduci" in last
    beyond = html.unescape(client.get(f"/admin/games/{game_id}/world?turn=99").text)
    assert "Turno 3 di 3" in beyond  # clamped to the last frame


def test_a_player_world_has_no_timelapse(client, database_url):
    game_id, realms = _game(database_url, load_raw_config())
    _play_months(database_url, game_id, 1)
    assert "Timelapse" not in client.get(f"/ui/realms/{realms[0]}/world?turn=1").text


def _month_one_on_the_roads(database_url, game_id, realms):
    """Play January, then give it a robbed caravan (realm 0, out), an arrived
    one (realm 1, back) and a repelled raid on realm 2 (no band raided it in
    the stored pool, append-only: no arrow, test_raid_arrows covers them).
    @return The hex where realm 0's caravan was robbed."""
    from engine.bands import RoadMap
    from engine.caravans import road_home_to_fair
    from server.db.games import load_game_config, load_state_at
    _play_months(database_url, game_id, 1)
    with psycopg.connect(database_url, autocommit=True) as conn:
        config = load_game_config(conn, game_id)
        states = {str(r): load_state_at(conn, r, 2) for r in realms}
        robbed_at = road_home_to_fair(RoadMap(config, states), str(realms[0]))[3]
        rows = [(realms[0], "caravan_robbed", {"leg": "out", "goods": {"food": 100}, "band": 1, "adults": 9,
                                               "week": 2, "x": robbed_at[0], "y": robbed_at[1]}),
                (realms[1], "caravan_arrived", {"leg": "back", "goods": {"wood": 50}, "week": 4}),
                (realms[2], "raid", {"raiders": 9, "guards": 6, "repelled": True, "food": 0, "wood": 0,
                                     "stayed": 1})]
        for realm_id, kind, data in rows:
            conn.execute("INSERT INTO events (game_id, realm_id, turn, kind, data, visibility)"
                         " VALUES (%s, %s, 1, %s, %s, 'court')", (game_id, realm_id, kind, psycopg.types.json.Jsonb(data)))
    return robbed_at


def test_the_timelapse_draws_the_month_caravans_and_raids(client, database_url):
    from server.ui.world_view import centre
    game_id, realms = _game(database_url, load_raw_config())
    robbed_at = _month_one_on_the_roads(database_url, game_id, realms)
    page = html.unescape(client.get(f"/admin/games/{game_id}/world?turn=2").text)
    assert page.count('class="caravan-road"') == 2
    x, y = centre(*robbed_at)
    assert f'<text class="caravan-robbed" x="{x:.1f}" y="{y:.1f}">✕</text>' in page  # where the band met it
    assert page.count('class="caravan-end"') == 1  # the arrived one
    assert "Sud: La carovana è tornata dalla fiera con 50 legno." in page
    assert "<b>Est</b>: Una banda di 9 briganti è stata respinta" in page  # the line, not an arrow
    # The latest view and the first frame draw no month's moves.
    for url in (f"/admin/games/{game_id}/world", f"/admin/games/{game_id}/world?turn=1"):
        assert 'class="caravan-road"' not in client.get(url).text


def test_raid_arrows_go_from_the_camp_to_the_raided_realm(database_url):
    """Pure: a band that raided points at the nearest hex of its target; a
    band that only walked draws nothing; outcome from the raid event."""
    from engine.bandits import Band
    from server.db.games import load_game_config, load_state_at
    from server.ui.world_view import centre, raid_arrows
    game_id, realms = _game(database_url, load_raw_config())
    with psycopg.connect(database_url, autocommit=True) as conn:
        config = load_game_config(conn, game_id)
        states = {str(r): load_state_at(conn, r, 1) for r in realms}
    key = str(realms[1])
    events = [{"key": key, "realm": "Sud", "kind": "raid",
               "data": {"raiders": 5, "guards": 0, "repelled": False, "food": 125, "wood": 0}}]
    raider = Band(7, 30, 30, 30, 30, 5, target=key, raided=True)
    walker = Band(8, 10, 10, 10, 10, 5, target=key, raided=False)
    arrows = raid_arrows(config, states, events, [raider, walker])
    assert len(arrows) == 1 and not arrows[0]["repelled"]
    assert arrows[0]["x1"] == f"{centre(30, 30)[0]:.1f}" and arrows[0]["title"].startswith("Banda 7 su Sud:")
