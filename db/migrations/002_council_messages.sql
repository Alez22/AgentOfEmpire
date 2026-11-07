-- 002_council_messages.sql: structure for the LLM council meeting.
-- kind:    directive (from the sovereign), report (from a minister),
--          summary (from the Chancellor, carries the plan).
-- round:   1 = the meeting, 2.. = a new round after each directive.
-- payload: proposed orders, discarded orders with reasons, or the plan.

ALTER TABLE council_messages
    ADD COLUMN kind text NOT NULL DEFAULT 'report'
        CHECK (kind IN ('directive', 'report', 'summary')),
    ADD COLUMN round integer NOT NULL DEFAULT 1 CHECK (round >= 1),
    ADD COLUMN payload jsonb NOT NULL DEFAULT '{}';

-- The defaults only exist to fill rows written before this migration.
ALTER TABLE council_messages ALTER COLUMN kind DROP DEFAULT;

CREATE INDEX council_messages_round ON council_messages (realm_id, turn, round);
