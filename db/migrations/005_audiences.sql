-- 005_audiences.sql: private audiences between the sovereign and one council member.
--
-- SECRET: only the sovereign (on the audience page) and that council member
-- (in its own briefing) ever read these rows. No visibility column and NO
-- grant to agent_reader, as for lessons. The FACT that an audience took
-- place is recorded separately as an 'audience' event at council level.

CREATE TABLE audiences (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id    bigint NOT NULL,
    realm_id   bigint NOT NULL,
    actor_id   bigint NOT NULL REFERENCES actors (id),
    turn       integer NOT NULL,
    speaker    text NOT NULL CHECK (speaker IN ('sovereign', 'actor')),
    content    text NOT NULL CHECK (length(content) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (realm_id, game_id) REFERENCES realms (id, game_id)
);

CREATE INDEX audiences_by_actor_turn ON audiences (actor_id, turn);

-- What was said stays said.
CREATE TRIGGER audiences_append_only BEFORE UPDATE OR DELETE ON audiences
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER audiences_no_truncate BEFORE TRUNCATE ON audiences
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_change();
