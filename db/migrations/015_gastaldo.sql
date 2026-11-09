-- 015_gastaldo.sql: the Gastaldo, the first counsellor who joins a council
-- during the game, when the realm's watchtower is finished (village block B+C,
-- server/council/meeting.py ensure_gastaldo).

ALTER TABLE actors DROP CONSTRAINT actors_role_check;
ALTER TABLE actors ADD CONSTRAINT actors_role_check CHECK (role IN (
    'chancellor', 'treasurer', 'architect', 'marshal',
    'ambassador', 'square_voice', 'tribune', 'people', 'gastaldo'));
