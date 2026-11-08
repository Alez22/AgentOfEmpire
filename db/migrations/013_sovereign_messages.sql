-- 013_sovereign_messages.sql: the automatic sovereign's decisions and their
-- reasons (server/sovereign/auto.py). New council message kind 'sovereign'.

ALTER TABLE council_messages DROP CONSTRAINT council_messages_kind_check;
ALTER TABLE council_messages ADD CONSTRAINT council_messages_kind_check
    CHECK (kind IN ('directive', 'report', 'summary', 'voice', 'comment', 'sovereign'));
