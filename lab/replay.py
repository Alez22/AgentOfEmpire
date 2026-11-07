"""@brief Check that a stored game replays identically.

Usage: docker compose run --rm tests python lab/replay.py <game_id>
Exit code 0 = every snapshot matches, 1 = mismatch (details printed).
"""

import os
import sys

import psycopg

from server.db.replay import replay_game


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    game_id = int(sys.argv[1])
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        try:
            mismatch = replay_game(conn, game_id)
        except ValueError as error:
            print(error)
            return 2
    if mismatch is None:
        print(f"game {game_id}: replay matches every snapshot")
        return 0
    print(f"game {game_id}: realm {mismatch.realm_id} differs at turn {mismatch.turn}")
    print(f"stored:   {mismatch.stored}")
    print(f"replayed: {mismatch.replayed}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
