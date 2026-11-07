-- 011_mandates.sql: the sovereign's standing guidelines for each counsellor.
--
-- The sovereign asks; the Chancellor reviews the request against the role
-- and the rules of the realm, and either rewrites it as an official mandate
-- or refuses it with a reason. Only the approved, rewritten text ever
-- reaches a counsellor's prompt, never the sovereign's raw words.
-- Each request is a row (append-only); the active mandate of a counsellor
-- is its latest approved one. No grant to agent_reader.

CREATE TABLE mandates (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id            bigint NOT NULL,
    realm_id           bigint NOT NULL,
    turn               integer NOT NULL,
    actor_id           bigint NOT NULL REFERENCES actors (id),  -- the counsellor it is for
    reviewer_actor_id  bigint REFERENCES actors (id),           -- the Chancellor
    request            text NOT NULL CHECK (length(request) > 0),
    decision           text NOT NULL CHECK (decision IN ('approved', 'rejected')),
    mandate            text,                                    -- the rewritten text, if approved
    reply              text NOT NULL DEFAULT '',                -- the chancellery's words to the sovereign
    created_at         timestamptz NOT NULL DEFAULT now(),
    CHECK ((decision = 'approved') = (mandate IS NOT NULL AND length(mandate) > 0)),
    FOREIGN KEY (realm_id, game_id) REFERENCES realms (id, game_id)
);

CREATE INDEX mandates_by_actor ON mandates (actor_id, id);

CREATE TRIGGER mandates_append_only BEFORE UPDATE OR DELETE ON mandates
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER mandates_no_truncate BEFORE TRUNCATE ON mandates
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_change();
