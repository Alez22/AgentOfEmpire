-- 008_petition_weight.sql: the mood at stake in a petition, computed when the
-- people decide (half the relief the asked order brings, within limits) and
-- read by the resolution and the replay. NULL = the fixed values of the first
-- version (games saved before), so their results do not change.

ALTER TABLE people_decisions ADD COLUMN petition_weight integer;
