-- 001_init.sql: prototype schema (see "Database" in docs/DESIGN.md).
-- Applied once by server/db/migrate.py inside a single transaction.
-- The database owner (game_admin) writes everything and is not subject to
-- row-level security; agent_reader only reads, and is always filtered.

-- Roles are cluster-wide, not per database: create agent_reader only if a
-- previous database (e.g. an earlier test run) did not create it already.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_reader') THEN
        CREATE ROLE agent_reader NOLOGIN;
    END IF;
END
$$;
GRANT agent_reader TO CURRENT_USER;  -- lets the server SET LOCAL ROLE agent_reader
GRANT USAGE ON SCHEMA public TO agent_reader;

CREATE TYPE visibility_level AS ENUM ('sovereign_secret', 'council', 'court', 'public', 'foreign');
CREATE TYPE game_status AS ENUM ('running', 'paused', 'finished');
CREATE TYPE turn_status AS ENUM ('open', 'resolving', 'resolved');

-- ---------------------------------------------------------------- games

CREATE TABLE games (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at     timestamptz NOT NULL DEFAULT now(),
    seed           bigint NOT NULL,
    config         jsonb NOT NULL,  -- copy of config.toml: tuning never alters a running game
    engine_version text NOT NULL,
    status         game_status NOT NULL DEFAULT 'running'
);

CREATE TABLE players (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text NOT NULL UNIQUE,
    invited_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE realms (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id   bigint NOT NULL REFERENCES games (id),
    name      text NOT NULL,
    player_id bigint REFERENCES players (id),  -- NULL = automatic sovereign
    UNIQUE (game_id, name),
    -- Target of the composite foreign keys below: they guarantee that a row's
    -- realm_id really belongs to its game_id.
    UNIQUE (id, game_id)
);

CREATE TABLE actors (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    realm_id    bigint NOT NULL REFERENCES realms (id),
    role        text NOT NULL CHECK (role IN (
                    'chancellor', 'treasurer', 'architect', 'marshal',
                    'ambassador', 'square_voice', 'tribune')),
    model       text NOT NULL,
    personality jsonb NOT NULL DEFAULT '{}',
    trust       integer NOT NULL DEFAULT 500 CHECK (trust BETWEEN 0 AND 1000),  -- per mille
    UNIQUE (realm_id, role)
);

CREATE TABLE turns (
    game_id     bigint NOT NULL REFERENCES games (id),
    number      integer NOT NULL CHECK (number >= 1),
    status      turn_status NOT NULL DEFAULT 'open',
    deadline    timestamptz,
    resolved_at timestamptz,
    PRIMARY KEY (game_id, number)
);

-- State of a realm at the START of turn `turn` (turn 1 = new game).
-- is_season_end marks snapshots taken right after a season-end turn.
CREATE TABLE snapshots (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id        bigint NOT NULL,
    realm_id       bigint NOT NULL,
    turn           integer NOT NULL CHECK (turn >= 1),
    is_season_end  boolean NOT NULL,
    format_version integer NOT NULL,
    engine_version text NOT NULL,
    state          jsonb NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (realm_id, game_id) REFERENCES realms (id, game_id),
    UNIQUE (realm_id, turn)
);

-- ------------------------------------------------------ append-only logs

-- Raw orders exactly as received (also the ones rejected by parsing).
-- issued_by_actor_id NULL = the sovereign.
CREATE TABLE orders (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id            bigint NOT NULL,
    realm_id           bigint NOT NULL,
    turn               integer NOT NULL,
    issued_by_actor_id bigint REFERENCES actors (id),
    raw                jsonb NOT NULL,
    priority           integer NOT NULL DEFAULT 0,
    submitted_at       timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (realm_id, game_id) REFERENCES realms (id, game_id)
);

-- Verdicts are written at resolution time in their own table, so that
-- orders itself never needs an UPDATE.
CREATE TABLE order_results (
    order_id       bigint PRIMARY KEY REFERENCES orders (id),
    accepted       boolean NOT NULL,
    rejection_code text,
    message        text NOT NULL DEFAULT '',
    CHECK (accepted = (rejection_code IS NULL))
);

CREATE TABLE events (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id           bigint NOT NULL,
    realm_id          bigint NOT NULL,
    turn              integer NOT NULL,
    kind              text NOT NULL,
    data              jsonb NOT NULL DEFAULT '{}',
    visibility        visibility_level NOT NULL,
    audience_realm_id bigint REFERENCES realms (id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (realm_id, game_id) REFERENCES realms (id, game_id),
    CHECK ((visibility = 'foreign') = (audience_realm_id IS NOT NULL))
);

-- ------------------------------------------------- council and memory

-- speaker_actor_id NULL = the sovereign.
CREATE TABLE council_messages (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id           bigint NOT NULL,
    realm_id          bigint NOT NULL,
    turn              integer NOT NULL,
    speaker_actor_id  bigint REFERENCES actors (id),
    content           text NOT NULL,
    visibility        visibility_level NOT NULL,
    audience_realm_id bigint REFERENCES realms (id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (realm_id, game_id) REFERENCES realms (id, game_id),
    CHECK ((visibility = 'foreign') = (audience_realm_id IS NOT NULL))
);

CREATE TABLE memories (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id           bigint NOT NULL,
    realm_id          bigint NOT NULL,
    actor_id          bigint NOT NULL REFERENCES actors (id),
    turn              integer NOT NULL,
    content           text NOT NULL,
    visibility        visibility_level NOT NULL,
    audience_realm_id bigint REFERENCES realms (id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (realm_id, game_id) REFERENCES realms (id, game_id),
    CHECK ((visibility = 'foreign') = (audience_realm_id IS NOT NULL))
);

CREATE TABLE model_calls (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id       bigint NOT NULL REFERENCES games (id),
    realm_id      bigint REFERENCES realms (id),
    actor_id      bigint REFERENCES actors (id),
    turn          integer NOT NULL,
    model         text NOT NULL,
    input_tokens  integer NOT NULL CHECK (input_tokens >= 0),
    output_tokens integer NOT NULL CHECK (output_tokens >= 0),
    cost_usd      numeric(10, 6) NOT NULL,  -- keeps fractions of a cent
    latency_ms    integer NOT NULL CHECK (latency_ms >= 0),
    confidence    integer CHECK (confidence BETWEEN 0 AND 1000),  -- per mille, NULL if none
    status        text NOT NULL,  -- e.g. ok, timeout, invalid_json
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX events_realm_turn ON events (game_id, realm_id, turn);
CREATE INDEX council_messages_realm_turn ON council_messages (game_id, realm_id, turn);
CREATE INDEX memories_actor_turn ON memories (actor_id, turn);
CREATE INDEX orders_realm_turn ON orders (game_id, realm_id, turn);

-- ------------------------------------------------ append-only enforcement

CREATE FUNCTION reject_append_only_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
END
$$;

CREATE TRIGGER orders_append_only BEFORE UPDATE OR DELETE ON orders
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER orders_no_truncate BEFORE TRUNCATE ON orders
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER order_results_append_only BEFORE UPDATE OR DELETE ON order_results
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER order_results_no_truncate BEFORE TRUNCATE ON order_results
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION reject_append_only_change();
CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON events
    FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_change();

-- ------------------------------------------------------ row-level security

-- Reader clearance: 4 sovereign, 3 council, 2 court, 1 outsider.
-- 'foreign' counts as council level, both for the sending realm and for
-- the audience realm.
CREATE FUNCTION visibility_rank(level visibility_level) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE level
        WHEN 'sovereign_secret' THEN 4
        WHEN 'council'          THEN 3
        WHEN 'foreign'          THEN 3
        WHEN 'court'            THEN 2
        WHEN 'public'           THEN 1
    END
$$;

-- current_setting() is called WITHOUT missing_ok on purpose: if the server
-- forgets to set the reader, the query fails instead of silently showing
-- the wrong rows.
CREATE FUNCTION reader_can_see(
    row_game_id bigint, row_realm_id bigint,
    row_visibility visibility_level, row_audience_realm_id bigint
) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT row_game_id = current_setting('app.game_id')::bigint
       AND (
            (row_realm_id = current_setting('app.realm_id')::bigint
                AND visibility_rank(row_visibility) <= current_setting('app.clearance')::integer)
         OR row_visibility = 'public'
         OR (row_visibility = 'foreign'
                AND row_audience_realm_id = current_setting('app.realm_id')::bigint
                AND current_setting('app.clearance')::integer >= 3)
       )
$$;

ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE council_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;

CREATE POLICY agent_read ON events FOR SELECT TO agent_reader
    USING (reader_can_see(game_id, realm_id, visibility, audience_realm_id));
CREATE POLICY agent_read ON council_messages FOR SELECT TO agent_reader
    USING (reader_can_see(game_id, realm_id, visibility, audience_realm_id));
CREATE POLICY agent_read ON memories FOR SELECT TO agent_reader
    USING (reader_can_see(game_id, realm_id, visibility, audience_realm_id));

-- agent_reader can read ONLY the labelled tables; snapshots, orders and the
-- model log stay server-only.
GRANT SELECT ON events, council_messages, memories TO agent_reader;
