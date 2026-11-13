"""Every combination of visibility level and reader clearance from the
"Visibility" table of docs/DESIGN.md. Row-level security filters silently,
so these tests are the only thing that proves the filter is right."""

import psycopg
import pytest

from server.db.access import Clearance, agent_context


@pytest.fixture
def world(db):
    """Two realms (north, south) in one game, plus a second game.
    Each event's kind names its label, so the assertions read clearly."""
    game_id = db.execute(
        "INSERT INTO games (seed, config, engine_version) VALUES (1, '{}', 'test') RETURNING id"
    ).fetchone()[0]
    other_game_id = db.execute(
        "INSERT INTO games (seed, config, engine_version) VALUES (2, '{}', 'test') RETURNING id"
    ).fetchone()[0]

    def add_realm(game, name):
        return db.execute(
            "INSERT INTO realms (game_id, name) VALUES (%s, %s) RETURNING id", (game, name)
        ).fetchone()[0]

    north = add_realm(game_id, "north")
    south = add_realm(game_id, "south")
    elsewhere = add_realm(other_game_id, "elsewhere")

    def add_event(game, realm, kind, visibility, audience=None):
        db.execute(
            "INSERT INTO events (game_id, realm_id, turn, kind, visibility, audience_realm_id)"
            " VALUES (%s, %s, 1, %s, %s, %s)",
            (game, realm, kind, visibility, audience),
        )

    add_event(game_id, north, "north_secret", "sovereign_secret")
    add_event(game_id, north, "north_council", "council")
    add_event(game_id, north, "north_court", "court")
    add_event(game_id, north, "north_public", "public")
    add_event(game_id, north, "north_to_south", "foreign", audience=south)
    add_event(game_id, south, "south_council", "council")
    add_event(game_id, south, "south_public", "public")
    add_event(other_game_id, elsewhere, "other_game_public", "public")
    return {"game": game_id, "north": north, "south": south}


def _visible_kinds(db, game_id, realm_id, clearance):
    with agent_context(db, game_id, realm_id, clearance) as conn:
        return {row[0] for row in conn.execute("SELECT kind FROM events")}


PUBLIC = {"north_public", "south_public"}


@pytest.mark.parametrize(
    ("reader_realm", "clearance", "expected"),
    [
        ("north", Clearance.SOVEREIGN,
         {"north_secret", "north_council", "north_court", "north_to_south"} | PUBLIC),
        ("north", Clearance.COUNCIL, {"north_council", "north_court", "north_to_south"} | PUBLIC),
        ("north", Clearance.COURT, {"north_court"} | PUBLIC),
        ("north", Clearance.OUTSIDER, PUBLIC),
        ("south", Clearance.SOVEREIGN, {"south_council", "north_to_south"} | PUBLIC),
        ("south", Clearance.COUNCIL, {"south_council", "north_to_south"} | PUBLIC),
        ("south", Clearance.COURT, PUBLIC),
    ],
)
def test_reader_sees_exactly_its_levels(db, world, reader_realm, clearance, expected):
    assert _visible_kinds(db, world["game"], world[reader_realm], clearance) == expected


def test_forgotten_settings_fail_instead_of_filtering(db, world):
    with pytest.raises(psycopg.Error):
        with db.transaction():
            db.execute("SET LOCAL ROLE agent_reader")
            db.execute("SELECT kind FROM events").fetchall()


def test_agent_reader_cannot_read_server_only_tables(db, world):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with agent_context(db, world["game"], world["north"], Clearance.SOVEREIGN) as conn:
            conn.execute("SELECT * FROM snapshots").fetchall()


def test_agent_context_is_read_only(db, world):
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with agent_context(db, world["game"], world["north"], Clearance.SOVEREIGN) as conn:
            conn.execute(
                "INSERT INTO events (game_id, realm_id, turn, kind, visibility)"
                " VALUES (%s, %s, 1, 'forged', 'public')",
                (world["game"], world["north"]),
            )


def test_settings_do_not_survive_the_context(db, world):
    _visible_kinds(db, world["game"], world["north"], Clearance.SOVEREIGN)
    current_user = db.execute("SELECT current_user").fetchone()[0]
    assert current_user == "game_admin"
    # The setting exists now but is empty, so using it fails loudly.
    assert db.execute("SELECT current_setting('app.realm_id', true)").fetchone()[0] in ("", None)


def test_a_neighbour_s_public_event_carries_its_name(db, world):
    """Game 41: after Corvara's revolt four councils read its game_over as their own."""
    from server.council.briefing import events_lines
    from server.db.games import list_visible_events
    events = list_visible_events(db, world["game"], world["north"], 1, Clearance.COUNCIL)
    south = next(e for e in events if e["kind"] == "south_public")
    assert south["realm"] == "south" and not south["own"]
    assert next(e for e in events if e["kind"] == "north_public")["own"]
    text = "\n".join(events_lines(events))
    mine, news = text.split("## News from the other realms")
    assert "north_public" in mine and "south_public" not in mine
    assert "- south: south_public" in news
