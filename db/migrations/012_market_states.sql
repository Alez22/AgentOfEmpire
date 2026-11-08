-- 012_market_states.sql: the common market of a game (engine/market.py).
--
-- One row per game and turn: the warehouse at the START of that turn (turn 1
-- = new game), like the realms' snapshots. Games without a market have no
-- rows. Append-only, so the replay can check every month.
-- No grant to agent_reader: the state says who has goods on sale, which is
-- never public. Pages and briefings get only prices, stock and totals,
-- built by the server.

CREATE TABLE market_states (
    game_id  bigint NOT NULL REFERENCES games (id),
    turn     integer NOT NULL CHECK (turn >= 1),
    state    jsonb NOT NULL,
    PRIMARY KEY (game_id, turn)
);

CREATE TRIGGER market_states_append_only BEFORE UPDATE OR DELETE ON market_states
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER market_states_no_truncate BEFORE TRUNCATE ON market_states
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_change();
