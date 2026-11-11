-- 016_rhythm.sql: how often the sovereign plays (docs/DESIGN.md, "Seasonal
-- sovereign"). 'monthly': every month, as every game before this migration.
-- 'seasonal': the first month of each season and the months after an alarm;
-- the other months the automatic sovereign approves the council's plan and
-- the laws stay as the sovereign left them.

ALTER TABLE games ADD COLUMN rhythm text NOT NULL DEFAULT 'monthly'
    CHECK (rhythm IN ('monthly', 'seasonal'));
