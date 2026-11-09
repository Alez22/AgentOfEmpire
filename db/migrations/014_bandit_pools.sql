-- 014_bandit_pools.sql: the world's bandits of a game (engine/bandits.py,
-- village block B+C).
--
-- One row per game and turn: the pool at the START of that turn (turn 1 =
-- new game), like the market's warehouse. Games without bandits have no
-- rows. Append-only, so the replay can check every month.
-- No grant to agent_reader: the size of the pool is never shown to anyone
-- (docs/DESIGN.md: it is felt in the raids and heard in the square).

CREATE TABLE bandit_pools (
    game_id  bigint NOT NULL REFERENCES games (id),
    turn     integer NOT NULL CHECK (turn >= 1),
    state    jsonb NOT NULL,
    PRIMARY KEY (game_id, turn)
);

CREATE TRIGGER bandit_pools_append_only BEFORE UPDATE OR DELETE ON bandit_pools
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER bandit_pools_no_truncate BEFORE TRUNCATE ON bandit_pools
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_change();
