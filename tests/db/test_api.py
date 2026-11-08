import pytest
from fastapi.testclient import TestClient

from server.app import create_app


@pytest.fixture
def client(database_url):
    # The with block runs the app lifespan, which opens the connection pool.
    with TestClient(create_app(database_url)) as test_client:
        yield test_client


@pytest.fixture
def game(client):
    response = client.post("/games", json={"seed": 42})
    assert response.status_code == 201
    body = response.json()
    return body["id"], body["realms"][0]["id"]


def test_new_game_starts_at_turn_one(client, game):
    game_id, realm_id = game
    assert client.get(f"/games/{game_id}").json()["open_turn"] == 1
    assert client.get(f"/realms/{realm_id}/state").json()["turn"] == 1


def test_unknown_ids_give_404(client):
    assert client.get("/games/999999").status_code == 404
    assert client.get("/realms/999999/state").status_code == 404
    assert client.post("/realms/999999/orders", json={"action": "set_tax", "rate": 5}).status_code == 404
    assert client.post("/games/999999/turns/resolve").status_code == 404


def test_malformed_order_gives_422_and_is_not_stored(client, game):
    _, realm_id = game
    response = client.post(f"/realms/{realm_id}/orders", json={"action": "summon_dragon"})
    assert response.status_code == 422
    assert client.get(f"/realms/{realm_id}/orders", params={"turn": 1}).json() == []


def test_check_is_a_dry_run(client, game):
    _, realm_id = game
    orders = [{"action": "build", "building": "house"} for _ in range(4)]  # 100 stone: three fit
    report = client.post(f"/realms/{realm_id}/orders/check", json=orders).json()
    assert [r["accepted"] for r in report["results"]] == [True, True, True, False]
    assert report["results"][3]["code"] == "INSUFFICIENT_RESOURCES"
    assert report["remaining"]["stone"] == 100 - 3 * 30
    assert client.get(f"/realms/{realm_id}/state").json()["wood"] == 150


def test_full_turn_through_the_api(client, game):
    game_id, realm_id = game
    assert client.post(
        f"/realms/{realm_id}/orders", json={"action": "set_tax", "rate": 12}
    ).status_code == 201
    client.post(f"/realms/{realm_id}/orders", json={"action": "set_tax", "rate": 20})

    summary = client.post(f"/games/{game_id}/turns/resolve").json()

    assert summary == {"turn": 1, "game_finished": False}
    orders = client.get(f"/realms/{realm_id}/orders", params={"turn": 1}).json()
    assert [(o["accepted"], o["rejection_code"]) for o in orders] == [
        (True, None),
        (False, "DUPLICATE_POLICY"),
    ]
    assert client.get(f"/realms/{realm_id}/state").json()["tax_rate"] == 12
    events = client.get(f"/realms/{realm_id}/events", params={"turn": 1}).json()
    assert "demography" in {e["kind"] for e in events}
    assert client.get(f"/games/{game_id}").json()["open_turn"] == 2


def test_order_after_the_game_ended_gives_409(client, game):
    game_id, realm_id = game
    client.post(f"/realms/{realm_id}/orders", json={"action": "set_tax", "rate": 30})
    finished = False
    while not finished:
        finished = client.post(f"/games/{game_id}/turns/resolve").json()["game_finished"]
    response = client.post(f"/realms/{realm_id}/orders", json={"action": "set_tax", "rate": 5})
    assert response.status_code == 409
    assert client.post(f"/games/{game_id}/turns/resolve").status_code == 409
