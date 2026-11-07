-- 010_debate_comments.sql: on request, the ministers comment on the
-- Chancellor's plan before the sovereign approves it (server/council/debate.py).
-- New council message kind 'comment', council level like the reports.

ALTER TABLE council_messages DROP CONSTRAINT council_messages_kind_check;
ALTER TABLE council_messages ADD CONSTRAINT council_messages_kind_check
    CHECK (kind IN ('directive', 'report', 'summary', 'voice', 'comment'));
