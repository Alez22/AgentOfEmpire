-- 007_people_decisions.sql: what the people decide each month.
--
-- At the meeting, after the Voice of the square, a cheap model (or the
-- fixed rules) chooses the people's behaviour for the open turn. The row is
-- an INPUT of the resolution, like an order: resolve_open_turn and the
-- replay read it, so the engine stays deterministic.
--
-- No grant to agent_reader: the server reads these rows itself and tells
-- the council and the square what is public (behaviour, petition).

-- The people decide through their own actor (model and call log).
ALTER TABLE actors DROP CONSTRAINT actors_role_check;
ALTER TABLE actors ADD CONSTRAINT actors_role_check CHECK (role IN (
    'chancellor', 'treasurer', 'architect', 'marshal',
    'ambassador', 'square_voice', 'tribune', 'people'));

CREATE TABLE people_decisions (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id       bigint NOT NULL,
    realm_id      bigint NOT NULL,
    turn          integer NOT NULL,
    actor_id      bigint REFERENCES actors (id),
    effort_pct    integer NOT NULL,  -- already clamped to the mood band
    birth_pct     integer NOT NULL,
    petition      jsonb,             -- an order from the catalogue, or NULL
    petition_text text NOT NULL DEFAULT '',  -- the people's words, game language
    reason        text NOT NULL DEFAULT '',  -- why, for the admin view
    source        text NOT NULL CHECK (source IN ('model', 'rules')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (realm_id, turn),
    FOREIGN KEY (realm_id, game_id) REFERENCES realms (id, game_id)
);

-- The sovereign's answer to a petition; none at resolution = refused.
CREATE TABLE petition_answers (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    decision_id bigint NOT NULL UNIQUE REFERENCES people_decisions (id),
    answer      text NOT NULL CHECK (answer IN ('granted', 'refused')),
    order_id    bigint REFERENCES orders (id),  -- the order granted, if any
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER people_decisions_append_only BEFORE UPDATE OR DELETE ON people_decisions
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER people_decisions_no_truncate BEFORE TRUNCATE ON people_decisions
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER petition_answers_append_only BEFORE UPDATE OR DELETE ON petition_answers
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER petition_answers_no_truncate BEFORE TRUNCATE ON petition_answers
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_change();
