WITH data_issues AS (
    SELECT
        'Match home-team gender mismatch' AS issue,
        m.id AS match_id,
        NULL AS innings_id,
        c.name AS competition,
        c.season,
        c.gender AS expected_gender,
        h.id AS team_id,
        h.name AS team,
        h.gender AS actual_gender
    FROM matches AS m
    JOIN competitions AS c ON c.id = m.competition_id
    JOIN teams AS h ON h.id = m.home_team_id
    WHERE h.gender <> c.gender

    UNION ALL

    SELECT
        'Match away-team gender mismatch',
        m.id,
        NULL,
        c.name,
        c.season,
        c.gender,
        a.id,
        a.name,
        a.gender
    FROM matches AS m
    JOIN competitions AS c ON c.id = m.competition_id
    JOIN teams AS a ON a.id = m.away_team_id
    WHERE a.gender <> c.gender

    UNION ALL

    SELECT
        'Innings batting-team gender mismatch',
        m.id,
        i.id,
        c.name,
        c.season,
        c.gender,
        bt.id,
        bt.name,
        bt.gender
    FROM innings AS i
    JOIN matches AS m ON m.id = i.match_id
    JOIN competitions AS c ON c.id = m.competition_id
    JOIN teams AS bt ON bt.id = i.batting_team_id
    WHERE bt.gender <> c.gender

    UNION ALL

    SELECT
        'Innings bowling-team gender mismatch',
        m.id,
        i.id,
        c.name,
        c.season,
        c.gender,
        bw.id,
        bw.name,
        bw.gender
    FROM innings AS i
    JOIN matches AS m ON m.id = i.match_id
    JOIN competitions AS c ON c.id = m.competition_id
    JOIN teams AS bw ON bw.id = i.bowling_team_id
    WHERE bw.gender <> c.gender

    UNION ALL

    SELECT
        'Innings batting team is not a match participant',
        m.id,
        i.id,
        c.name,
        c.season,
        c.gender,
        bt.id,
        bt.name,
        bt.gender
    FROM innings AS i
    JOIN matches AS m ON m.id = i.match_id
    JOIN competitions AS c ON c.id = m.competition_id
    JOIN teams AS bt ON bt.id = i.batting_team_id
    WHERE i.batting_team_id NOT IN (m.home_team_id, m.away_team_id)

    UNION ALL

    SELECT
        'Innings bowling team is not a match participant',
        m.id,
        i.id,
        c.name,
        c.season,
        c.gender,
        bw.id,
        bw.name,
        bw.gender
    FROM innings AS i
    JOIN matches AS m ON m.id = i.match_id
    JOIN competitions AS c ON c.id = m.competition_id
    JOIN teams AS bw ON bw.id = i.bowling_team_id
    WHERE i.bowling_team_id NOT IN (m.home_team_id, m.away_team_id)
)
SELECT *
FROM data_issues
ORDER BY match_id, innings_id, issue;
