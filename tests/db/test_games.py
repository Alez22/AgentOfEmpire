import pytest

from engine import load_config, new_game
from engine.config import load_raw_config
from engine.snapshot import state_from_dict
from server.db import games
from server.db.games import (
    EngineVersionError,
    GamePausedError,
    NoOpenTurnError,
    TurnClosedError,
    UnknownEventKindError,
    create_game,
    resolve_open_turn,
    submit_order,
)
from server.db.replay import replay_game

COUNCIL = {"chancellor": "test-top", "treasurer": "test-mid", "architect": "test-mid"}


@pytest.fixture
def game(db):
    game_id = create_game(db, load_raw_config(), seed=42, realm_names=["Nord"], council_models=COUNCIL)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    return game_id, realm_id


def _open_turns(db, game_id):
    return [r[0] for r in db.execute(
        "SELECT number FROM turns WHERE game_id = %s AND status = 'open'", (game_id,)
    )]


def _results_by_order(db, realm_id):
    return {
        order_id: (accepted, code)
        for order_id, accepted, code in db.execute(
            "SELECT o.id, r.accepted, r.rejection_code FROM orders o"
            " JOIN order_results r ON r.order_id = o.id WHERE o.realm_id = %s",
            (realm_id,),
        )
    }


def test_create_game_writes_realm_council_turn_and_first_snapshot(db, game):
    game_id, realm_id = game
    roles = {r[0] for r in db.execute("SELECT role FROM actors WHERE realm_id = %s", (realm_id,))}
    assert roles == set(COUNCIL)
    assert _open_turns(db, game_id) == [1]
    stored = db.execute("SELECT state FROM snapshots WHERE realm_id = %s", (realm_id,)).fetchone()[0]
    assert state_from_dict(stored) == new_game(load_config(), 42)


def test_resolution_stores_verdicts_events_and_next_snapshot(db, game):
    game_id, realm_id = game
    house = submit_order(db, realm_id, {"action": "build", "building": "house"})
    unknown = submit_order(db, realm_id, {"action": "summon_dragon"})
    tax_first = submit_order(db, realm_id, {"action": "set_tax", "rate": 12})
    tax_again = submit_order(db, realm_id, {"action": "set_tax", "rate": 20})

    summary = resolve_open_turn(db, game_id)

    assert summary.turn == 1 and not summary.game_finished
    assert _results_by_order(db, realm_id) == {
        house: (True, None),
        unknown: (False, "UNKNOWN_ACTION"),
        tax_first: (True, None),
        tax_again: (False, "DUPLICATE_POLICY"),
    }
    visibility = dict(db.execute(
        "SELECT kind, visibility::text FROM events WHERE realm_id = %s AND turn = 1", (realm_id,)
    ).fetchall())
    assert visibility["demography"] == "court"  # births and deaths are seen by all
    state = state_from_dict(db.execute(
        "SELECT state FROM snapshots WHERE realm_id = %s AND turn = 2", (realm_id,)
    ).fetchone()[0])
    assert state.tax_rate == 12
    assert state.buildings[-1].kind == "house"
    assert _open_turns(db, game_id) == [2]


def test_priority_column_decides_the_order(db, game):
    game_id, realm_id = game
    feast = submit_order(db, realm_id, {"action": "hold_feast", "gold": 100}, priority=1)
    house = submit_order(db, realm_id, {"action": "build", "building": "house"}, priority=0)
    resolve_open_turn(db, game_id)
    results = _results_by_order(db, realm_id)
    assert results[house] == (True, None)
    assert results[feast] == (False, "INSUFFICIENT_RESOURCES")


def test_finished_game_refuses_orders_and_resolutions(db, game):
    game_id, realm_id = game
    submit_order(db, realm_id, {"action": "set_tax", "rate": 30})
    summary = resolve_open_turn(db, game_id)
    while not summary.game_finished:
        summary = resolve_open_turn(db, game_id)
    status = db.execute("SELECT status::text FROM games WHERE id = %s", (game_id,)).fetchone()[0]
    assert status == "finished"
    with pytest.raises(TurnClosedError):
        submit_order(db, realm_id, {"action": "set_tax", "rate": 5})
    with pytest.raises(NoOpenTurnError):
        resolve_open_turn(db, game_id)


def test_unknown_event_kind_stops_and_writes_nothing(db, game, monkeypatch):
    game_id, realm_id = game
    submit_order(db, realm_id, {"action": "set_tax", "rate": 12})
    visibility_without_demography = dict(games.EVENT_VISIBILITY)
    del visibility_without_demography["demography"]
    monkeypatch.setattr(games, "EVENT_VISIBILITY", visibility_without_demography)

    with pytest.raises(UnknownEventKindError):
        resolve_open_turn(db, game_id)

    assert _open_turns(db, game_id) == [1]
    assert db.execute("SELECT count(*) FROM snapshots WHERE realm_id = %s", (realm_id,)).fetchone()[0] == 1
    assert _results_by_order(db, realm_id) == {}


def test_paused_game_is_not_resolved(db, game):
    game_id, _ = game
    db.execute("UPDATE games SET status = 'paused' WHERE id = %s", (game_id,))
    with pytest.raises(GamePausedError):
        resolve_open_turn(db, game_id)


def test_other_engine_version_is_refused(db, game):
    game_id, _ = game
    db.execute("UPDATE games SET engine_version = '0.0.1' WHERE id = %s", (game_id,))
    with pytest.raises(EngineVersionError):
        resolve_open_turn(db, game_id)


def _play_year(db, game_id, realm_id):
    orders_by_turn = {
        1: [{"action": "build", "building": "farm"}],
        2: [{"action": "set_tax", "rate": 15}, {"action": "not_an_action"}],
        5: [{"action": "hold_feast", "gold": 60}],
        7: [{"action": "assign_workers", "food": 50, "wood": 8, "stone": 4}],
    }
    for turn in range(1, 13):
        for raw in orders_by_turn.get(turn, []):
            submit_order(db, realm_id, raw)
        resolve_open_turn(db, game_id)


def test_season_end_snapshots_are_marked(db, game):
    game_id, realm_id = game
    _play_year(db, game_id, realm_id)
    marked = [r[0] for r in db.execute(
        "SELECT turn FROM snapshots WHERE realm_id = %s AND is_season_end ORDER BY turn", (realm_id,)
    )]
    assert marked == [4, 7, 10, 13]


def test_replay_of_a_full_year_matches(db, game):
    game_id, realm_id = game
    _play_year(db, game_id, realm_id)
    assert replay_game(db, game_id) is None


def test_replay_detects_an_altered_snapshot(db, game):
    game_id, realm_id = game
    _play_year(db, game_id, realm_id)
    db.execute(
        "UPDATE snapshots SET state = jsonb_set(state, '{gold}', '9999')"
        " WHERE realm_id = %s AND turn = 8",
        (realm_id,),
    )
    mismatch = replay_game(db, game_id)
    assert mismatch is not None
    assert mismatch.turn == 8


def test_each_realm_of_a_game_starts_on_its_own_site(db):
    """Before the market every realm of a game started on the seed's site."""
    game_id = create_game(db, load_raw_config(), seed=6, realm_names=["Nord", "Est", "Sud"], council_models=COUNCIL)
    states = [state_from_dict(row[0]) for row in db.execute(
        "SELECT s.state FROM snapshots s JOIN realms r ON r.id = s.realm_id"
        " WHERE r.game_id = %s ORDER BY r.id", (game_id,))]
    config = load_config()
    assert [s.square for s in states] == [new_game(config, 6, site_index=i).square for i in (6, 7, 8)]
    assert len({tuple(s.land_levels.values()) for s in states}) == 3
    assert states[0].square == new_game(config, 6).square  # the first realm keeps the seed's site


def _three_realm_game(db):
    # The market open from the first month, as before village block A
    # (tests/test_village_market.py covers the market building).
    raw = load_raw_config()
    raw["market"]["needs_building"] = False
    game_id = create_game(db, raw, seed=0, realm_names=["Nord", "Est", "Sud"], council_models=COUNCIL)
    realm_ids = [r[0] for r in db.execute("SELECT id FROM realms WHERE game_id = %s ORDER BY id", (game_id,))]
    return game_id, realm_ids


def _market_rows(db, game_id):
    return dict(db.execute("SELECT turn, state FROM market_states WHERE game_id = %s", (game_id,)).fetchall())


def test_a_game_with_three_realms_trades_at_one_market(db):
    game_id, (nord, est, sud) = _three_realm_game(db)
    assert list(_market_rows(db, game_id)) == [1]  # the warehouse at game start
    submit_order(db, nord, {"action": "trade", "good": "food", "side": "sell", "lots": 4})
    submit_order(db, est, {"action": "trade", "good": "food", "side": "buy", "lots": 9})  # 6 lots of start stock + 4
    submit_order(db, sud, {"action": "trade", "good": "stone", "side": "buy", "lots": 1})
    resolve_open_turn(db, game_id)
    markets = _market_rows(db, game_id)
    assert sorted(markets) == [1, 2]
    food = markets[2]["goods"]["food"]
    assert food["last_sold"] == 200 and food["last_bought"] == 450
    sellers = {c["seller"] for c in food["queue"]}
    assert sellers == {str(nord)}  # the start stock went first, the rest of Nord's food waits
    est_result = db.execute(
        "SELECT r.accepted, r.message FROM order_results r JOIN orders o ON o.id = r.order_id"
        " WHERE o.realm_id = %s", (est,)).fetchone()
    assert est_result == (True, "filled 9 of 9 lots of food asked this month")
    kinds = {row[0] for row in db.execute("SELECT kind FROM events WHERE realm_id = %s", (nord,))}
    assert {"trade_on_sale", "trade_paid"} <= kinds  # Nord's first lots were bought at once


def test_a_game_with_a_market_replays_exactly(db):
    game_id, (nord, est, sud) = _three_realm_game(db)
    for turn in range(1, 7):
        submit_order(db, nord, {"action": "trade", "good": "food", "side": "sell", "lots": 2})
        submit_order(db, est, {"action": "trade", "good": "food", "side": "buy", "lots": 3})
        submit_order(db, sud, {"action": "trade", "good": "wood", "side": "buy", "lots": 1})
        resolve_open_turn(db, game_id)
    assert replay_game(db, game_id) is None


def test_the_replay_notices_an_altered_market(db):
    game_id, (nord, _, _) = _three_realm_game(db)
    for turn in range(1, 4):
        submit_order(db, nord, {"action": "trade", "good": "food", "side": "sell", "lots": 2})
        resolve_open_turn(db, game_id)
    db.execute("ALTER TABLE market_states DISABLE TRIGGER market_states_append_only")
    db.execute("UPDATE market_states SET state = jsonb_set(state, '{goods,food,price}', '99')"
               " WHERE game_id = %s AND turn = 3", (game_id,))
    mismatch = replay_game(db, game_id)
    assert mismatch is not None and mismatch.realm_id is None and mismatch.turn == 3


def test_a_game_without_a_market_refuses_trades(db):
    raw = load_raw_config()
    del raw["market"]
    game_id = create_game(db, raw, seed=1, realm_names=["Nord"], council_models=COUNCIL)
    realm_id = db.execute("SELECT id FROM realms WHERE game_id = %s", (game_id,)).fetchone()[0]
    submit_order(db, realm_id, {"action": "trade", "good": "food", "side": "sell", "lots": 1})
    resolve_open_turn(db, game_id)
    assert _market_rows(db, game_id) == {}
    assert _results_by_order(db, realm_id).popitem()[1] == (False, "NO_MARKET")
    assert replay_game(db, game_id) is None
