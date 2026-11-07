-- 004_model_call_errors.sql: keep why a model reply was refused.
-- error:         reason of the refusal or of the failed call ('' when ok).
-- reply_excerpt: start of the raw reply, stored ONLY for refused replies
--                (enough to debug, without keeping every normal answer twice).

ALTER TABLE model_calls
    ADD COLUMN error text NOT NULL DEFAULT '',
    ADD COLUMN reply_excerpt text NOT NULL DEFAULT '';
