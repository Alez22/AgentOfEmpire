"""The sovereign's market page (server/ui/market_view.py, templates/market.html)."""

import html
from dataclasses import replace

import psycopg
import pytest
from fastapi.testclient import TestClient

from engine.config import load_raw_config
from server.app import create_app
from server.council.llm import FakeClient
from server.council.settings import load_settings
from server.db.games import create_game, resolve_open_turn, submit_order

COUNCIL = {"chancellor": "m", "treasurer": "m", "architect": "m"}


@pytest.fixture
def ui(database_url):
    settings = replace(load_settings(), provider="fake")
    with TestClient(create_app(database_url, settings, FakeClient())) as client:
        yield client


def _game(database_url, raw_config, names=("Nord",)) -> tuple[int, list[int]]:
    with psycopg.connect(database_url, autocommit=True) as conn:
        game_id = create_game(conn, raw_config, seed=0, realm_names=list(names), council_models=COUNCIL)
        realms = [r[0] for r in conn.execute("SELECT id FROM realms WHERE game_id = %s ORDER BY id", (game_id,))]
        return game_id, realms


def _page(ui, realm_id) -> str:
    return html.unescape(ui.get(f"/ui/realms/{realm_id}/market").text)


def test_the_market_page_shows_the_prices(ui, database_url):
    raw = load_raw_config()
    raw["market"]["needs_building"] = False  # open from the first month, as before village block A
    _, (realm_id,) = _game(database_url, raw)
    page = _page(ui, realm_id)
    assert 'aria-current="page">Mercato</a>' in page
    assert "Prezzi del mese" in page and "oro per lotto da 50" in page
    assert "Compri a</div><div class=\"value\">11" in page and "Vendi a</div><div class=\"value\">9" in page
    assert "Nel magazzino 100." in page  # the start stock of one realm
    assert "Nessuna merce in vendita." in page and "Il consiglio non si è ancora riunito questo mese." in page
    assert "Legna da ardere: 50 al mese da novembre a marzo (questo mese 50)." in page


def test_own_goods_on_sale_are_shown_and_no_one_else_s(ui, database_url):
    raw = load_raw_config()
    raw["market"]["needs_building"] = False  # trade from the first month, as before village block A
    game_id, (nord, est) = _game(database_url, raw, ("Nord", "Est"))
    with psycopg.connect(database_url, autocommit=True) as conn:
        submit_order(conn, nord, {"action": "trade", "good": "wood", "side": "sell", "lots": 2})
        submit_order(conn, est, {"action": "trade", "good": "stone", "side": "buy", "lots": 1})
        resolve_open_turn(conn, game_id)
    nord_page, est_page = _page(ui, nord), _page(ui, est)
    assert "La tua merce in attesa" in nord_page and "<strong>100</strong>" in nord_page
    assert "Messi in vendita al mercato 2 lotti di legno." in nord_page
    assert "Nessuna merce in vendita." in est_page  # Nord's wood is not Est's business
    assert "Comprati al mercato 1 lotto di pietra" in est_page
    assert "messi in vendita 100" in est_page  # the totals are public
    # Wood: Nord's 100 on sale and nobody asked, so the price fell; stone: the
    # one lot asked was there, so it held.
    assert "scende: resta invenduto" in nord_page and "stabile" in nord_page
    assert nord_page.count('class="bar now"') == 3 and nord_page.count('class="bar"') == 3  # two months each


def test_a_world_without_a_market_says_so(ui, database_url):
    raw = load_raw_config()
    del raw["market"]
    _, (realm_id,) = _game(database_url, raw)
    assert "In questo mondo non c'è mercato" in _page(ui, realm_id)


def test_pages_hold_with_a_market_building_on_the_map(ui, database_url):
    """Village block A: a realm that built its market; the pages must not break
    (the market's own look on the map and its page come with the UI step)."""
    game_id, (realm_id,) = _game(database_url, load_raw_config())
    with psycopg.connect(database_url, autocommit=True) as conn:
        submit_order(conn, realm_id, {"action": "build", "building": "market"})
        resolve_open_turn(conn, game_id)
        resolve_open_turn(conn, game_id)
    for page in ("", "/kingdom", "/map", "/market", "/chronicle", "/manual"):
        response = ui.get(f"/ui/realms/{realm_id}{page}")
        assert response.status_code == 200, page
    assert "Completato un mercato" in html.unescape(ui.get(f"/ui/realms/{realm_id}/chronicle").text)


def test_a_realm_without_its_market_sees_no_price(ui, database_url):
    """Village block A (decided 2026-11-08): no prices before the market."""
    game_id, (realm_id,) = _game(database_url, load_raw_config())
    page = _page(ui, realm_id)
    assert "Il regno non ha ancora un mercato" in page and "80 legno" in page
    assert "Prezzi del mese" not in page and "Compri a" not in page
    with psycopg.connect(database_url, autocommit=True) as conn:
        submit_order(conn, realm_id, {"action": "build", "building": "market"})
        resolve_open_turn(conn, game_id)
    page = _page(ui, realm_id)
    assert "Il mercato è in costruzione" in page and "Sarà finito tra 1 mese" in page
    assert "Compri a" not in page


def test_an_open_market_shows_its_merchants(ui, database_url):
    game_id, (realm_id,) = _game(database_url, load_raw_config())
    staff = {"action": "assign_workers", "food": 50, "wood": 4, "stone": 3, "trade": 3}
    with psycopg.connect(database_url, autocommit=True) as conn:
        submit_order(conn, realm_id, {"action": "build", "building": "market"})
        resolve_open_turn(conn, game_id)
        resolve_open_turn(conn, game_id)
        submit_order(conn, realm_id, staff)
        resolve_open_turn(conn, game_id)
    page = _page(ui, realm_id)
    assert "Prezzi del mese" in page and "I mercanti" in page
    assert "su 6 posti" in page and "Tassa dei mercanti" in page and "calmi" in page
    map_page = html.unescape(ui.get(f"/ui/realms/{realm_id}/map").text)
    assert "#i-shop" in map_page and "h-market" in map_page
    kingdom = html.unescape(ui.get(f"/ui/realms/{realm_id}/kingdom").text)
    assert "Al mercato (mercanti)" in kingdom and "Malcontento dei mercanti" in kingdom
