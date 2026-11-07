-- 009_counsel_notes.sql: secret notes between council members.
--
-- Once a month a counsellor may write one short note to one colleague,
-- inside its usual council reply. The note is delivered at the next
-- meeting. Entirely SECRET (approved 2026-11-07): not even the fact that
-- a note was sent is recorded anywhere else (no event, no chronicle, no
-- square). The sovereign can only ask in a private audience, and the
-- counsellor answers according to its honesty. No grant to agent_reader.

CREATE TABLE counsel_notes (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id            bigint NOT NULL,
    realm_id           bigint NOT NULL,
    turn               integer NOT NULL,  -- the turn it was written in
    sender_actor_id    bigint NOT NULL REFERENCES actors (id),
    recipient_actor_id bigint NOT NULL REFERENCES actors (id),
    content            text NOT NULL CHECK (length(content) > 0),
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sender_actor_id, turn),  -- one note a month per counsellor
    CHECK (sender_actor_id <> recipient_actor_id),
    FOREIGN KEY (realm_id, game_id) REFERENCES realms (id, game_id)
);

CREATE INDEX counsel_notes_by_recipient ON counsel_notes (recipient_actor_id, turn);

CREATE TRIGGER counsel_notes_append_only BEFORE UPDATE OR DELETE ON counsel_notes
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER counsel_notes_no_truncate BEFORE TRUNCATE ON counsel_notes
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_change();
