-- 006_square_voice_and_prompts.sql
-- 1. The Voice of the square speaks in the council: new message kind 'voice'.
-- 2. Every model call keeps the prompts it was sent (admin view, debugging),
--    cut to 20,000 characters each by the server: about 10 MB per
--    120-turn game.

ALTER TABLE council_messages DROP CONSTRAINT council_messages_kind_check;
ALTER TABLE council_messages ADD CONSTRAINT council_messages_kind_check
    CHECK (kind IN ('directive', 'report', 'summary', 'voice'));

ALTER TABLE model_calls
    ADD COLUMN prompt_system text NOT NULL DEFAULT '',
    ADD COLUMN prompt_user text NOT NULL DEFAULT '';
