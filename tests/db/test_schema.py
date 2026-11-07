import psycopg
import pytest

from server.db.migrate import MIGRATIONS_DIR, apply_migrations


def _new_game_with_realm(db) -> tuple[int, int]:
    game_id = db.execute(
        "INSERT INTO games (seed, config, engine_version) VALUES (1, '{}', 'test') RETURNING id"
    ).fetchone()[0]
    realm_id = db.execute(
        "INSERT INTO realms (game_id, name) VALUES (%s, 'Nord') RETURNING id", (game_id,)
    ).fetchone()[0]
    return game_id, realm_id


def test_second_run_applies_nothing(db):
    assert apply_migrations(db) == []
    applied = sorted(row[0] for row in db.execute("SELECT filename FROM schema_migrations"))
    assert applied == sorted(path.name for path in MIGRATIONS_DIR.glob("*.sql"))


@pytest.mark.parametrize("statement", ["UPDATE events SET kind = 'x'", "DELETE FROM events"])
def test_events_are_append_only(db, statement):
    game_id, realm_id = _new_game_with_realm(db)
    db.execute(
        "INSERT INTO events (game_id, realm_id, turn, kind, visibility)"
        " VALUES (%s, %s, 1, 'famine', 'council')",
        (game_id, realm_id),
    )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute(statement)


def test_orders_are_append_only(db):
    game_id, realm_id = _new_game_with_realm(db)
    db.execute(
        "INSERT INTO orders (game_id, realm_id, turn, raw) VALUES (%s, %s, 1, '{}')",
        (game_id, realm_id),
    )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("UPDATE orders SET priority = 5")


def test_realm_must_belong_to_the_game_of_the_row(db):
    _, realm_id = _new_game_with_realm(db)
    other_game_id, _ = _new_game_with_realm(db)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute(
            "INSERT INTO events (game_id, realm_id, turn, kind, visibility)"
            " VALUES (%s, %s, 1, 'famine', 'council')",
            (other_game_id, realm_id),
        )


def test_foreign_rows_need_an_audience(db):
    game_id, realm_id = _new_game_with_realm(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO events (game_id, realm_id, turn, kind, visibility)"
            " VALUES (%s, %s, 1, 'treaty', 'foreign')",
            (game_id, realm_id),
        )
