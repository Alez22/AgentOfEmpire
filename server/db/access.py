"""@brief The only way the server reads data on behalf of an agent.

Inside agent_context() every query runs as agent_reader, so row-level
security filters events, council messages and memories by the reader's
game, realm and clearance. The filter lives in the database, not in the
prompt: an agent cannot leak what it never received.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from enum import IntEnum

import psycopg


class Clearance(IntEnum):
    """Reader grade; must match visibility_rank() in 001_init.sql."""

    OUTSIDER = 1  # other realms: public only
    COURT = 2  # Voice of the square, Tribune
    COUNCIL = 3  # Chancellor and ministers
    SOVEREIGN = 4


@contextmanager
def agent_context(
    conn: psycopg.Connection, game_id: int, realm_id: int, clearance: Clearance
) -> Iterator[psycopg.Connection]:
    """@brief Open a read-only, filtered transaction for one reader.
    @param conn Connection in autocommit mode, so that transaction() opens a
           real transaction and not a savepoint inside an outer one.
    @param game_id Game the reader belongs to.
    @param realm_id Realm the reader belongs to.
    @param clearance Reader grade.
    @return The same connection, usable only inside the with block.

    SET LOCAL and set_config(..., true) last until the end of the
    transaction, so nothing leaks into later queries on this connection.
    """
    if not conn.autocommit:
        raise ValueError("agent_context needs an autocommit connection")
    with conn.transaction():
        # READ ONLY must come before any query of the transaction.
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL ROLE agent_reader")
        conn.execute(
            "SELECT set_config('app.game_id', %s, true),"
            " set_config('app.realm_id', %s, true),"
            " set_config('app.clearance', %s, true)",
            (str(game_id), str(realm_id), str(int(clearance))),
        )
        yield conn
