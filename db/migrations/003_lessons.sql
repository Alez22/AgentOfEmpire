-- 003_lessons.sql: lessons learned by each council member, with their history.
--
-- SECRET: lessons are private to the actor who wrote them. There is no
-- visibility column and NO grant to agent_reader, so even a filtered agent
-- query cannot read them. Only the server reads them, by actor_id, to build
-- that same actor's briefing.
--
-- A revision never overwrites text: the old row becomes 'revised' and a new
-- row points back to it through previous_lesson_id.

CREATE TYPE lesson_status AS ENUM ('active', 'revised', 'dropped');

CREATE TABLE lessons (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id             bigint NOT NULL,
    realm_id            bigint NOT NULL,
    actor_id            bigint NOT NULL REFERENCES actors (id),
    text                text NOT NULL CHECK (length(text) > 0),
    origin_turn         integer NOT NULL,  -- turn this version was written
    confirmations       integer NOT NULL DEFAULT 0 CHECK (confirmations >= 0),
    last_confirmed_turn integer,           -- NULL = never confirmed yet
    status              lesson_status NOT NULL DEFAULT 'active',
    status_turn         integer,           -- when it was revised or dropped
    status_reason       text NOT NULL DEFAULT '',
    previous_lesson_id  bigint REFERENCES lessons (id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (realm_id, game_id) REFERENCES realms (id, game_id),
    CHECK ((status = 'active') = (status_turn IS NULL))
);

CREATE INDEX lessons_active_by_actor ON lessons (actor_id) WHERE status = 'active';

-- Carry over the lessons already written in memories (latest list of each
-- actor) as new, never confirmed lessons. The memories rows stay untouched.
INSERT INTO lessons (game_id, realm_id, actor_id, text, origin_turn)
SELECT m.game_id, m.realm_id, m.actor_id, m.content, m.turn
FROM memories m
WHERE m.turn = (SELECT max(latest.turn) FROM memories latest WHERE latest.actor_id = m.actor_id)
ORDER BY m.id;
