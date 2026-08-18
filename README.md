[![GitHub issues](https://img.shields.io/github/issues/davewalker5/CricketTracker)](https://github.com/davewalker5/CricketTracker/issues)
[![Releases](https://img.shields.io/github/v/release/davewalker5/CricketTracker.svg?include_prereleases)](https://github.com/davewalker5/CricketTracker/releases)
[![License](https://img.shields.io/badge/License-mit-blue.svg)](https://github.com/davewalker5/CricketTracker/blob/main/LICENSE)
[![Language](https://img.shields.io/badge/language-python-blue.svg)](https://www.python.org)
[![GitHub code size in bytes](https://img.shields.io/github/languages/code-size/davewalker5/CricketTracker)](https://github.com/davewalker5/CricketTracker/)

# Cricket Tracker

## Overview

Cricket Tracker is a local-first desktop application for recording, following and exploring cricket competitions, fixtures, results, innings summaries, league standings and match analysis.

The application supports The Hundred, Twenty20 and one-day cricket. It maintains structured season records without attempting to act as a live-scoring service or reproduce complete scorecards or ball-by-ball data.

Built with Python, Streamlit and SQLite, Cricket Tracker uses a cricket-specific relational data model designed to remain simple, maintainable and inspectable. Competition rules are modelled explicitly so that points, standings and net run rate can be calculated consistently from recorded match and innings data.

A dedicated Analysis area uses the same records to provide team summaries, batting-first and chasing comparisons, and head-to-head reports.

Cricket Tracker is based on the established structure of Rugby Tracker, but uses its own independent database, configuration and migration history.

## Competition Tracking

### Competition Database

Maintain structured reference data for:

- Countries
- Venues
- Teams
- Match formats
- Competition rulesets
- Competitions

Teams are linked to countries and classified by gender. Venues also reference their host country, providing consistent location and competition data throughout the application.

Competitions are season-specific and identify the rules used to calculate their league standings.

### Match Recording

Record fixture and result details including:

- Competition
- Round or stage
- Venue
- Date and start time
- Home and away teams
- Toss winner
- Toss decision
- Winning team
- Result type
- Result margin
- Match status
- Scheduled or reduced innings allocation
- Original or externally supplied revised target
- Result method, such as DLS

Rounds may be numeric league stages or descriptive knockout stages such as *Eliminator* and *Final*.

Structured result fields support wins by runs or wickets, ties and no results.

### Innings Summaries

Record innings-level summaries separately from the main match record.

Each innings can include:

- Batting team
- Innings number
- Runs scored
- Wickets lost
- Balls faced
- Innings status
- Chasing target, where applicable

This provides enough information to describe the shape and outcome of a match without requiring complete scorecards or ball-by-ball data.

Future fixtures may contain empty innings records that can be completed after the match has taken place.

Legal deliveries are always stored as whole balls. Over-based formats are displayed using cricket notation, so 83 legal balls is shown as `13.5 overs` rather than treated as a decimal value.

### Automatic Match Results

Where sufficient innings data has been recorded, Cricket Tracker can derive the structured match result automatically.

For completed matches with one innings per team, the application can determine:

- Winning team
- Whether the match was won by runs or wickets
- Winning margin
- A tied result
- A no result or abandonment
- A revised-target result using an externally supplied target

This reduces duplicate manual entry and keeps the recorded result consistent with the innings summaries.

### Automatic League Tables

League standings are calculated dynamically from recorded match and innings data rather than stored in the database.

The tracker calculates:

- Played
- Won
- Lost
- Tied
- No Result
- Points
- Runs For
- Balls Faced
- Runs Against
- Balls Bowled
- Net Run Rate

Competition rules determine:

- Points awarded for wins, ties and no results
- Whether knockout matches contribute to league standings
- Which stages are treated as knockout rounds

Net run rate is calculated from completed innings summaries and displayed where enabled by the ruleset. An all-out team is credited with its applicable full allocation. Matches with revised allocations or revised targets are excluded because their competition-specific NRR treatment cannot be derived reliably from the stored summary data.

## Match Analysis

The Analysis area provides a focused set of reports for reviewing teams and matches within a selected competition and season.

The reports use existing match and innings-summary data. They do not require player statistics, full scorecards or ball-by-ball records.

### Team Summary

Review one team's performance across a competition, including:

- Matches played, wins, losses, ties and no results
- Win percentage
- Runs scored and conceded
- Average innings totals
- Average wickets lost and taken
- Highest and lowest innings totals
- Record when batting first
- Record when chasing
- Largest and narrowest wins and defeats
- Chronological match history

Results are presented from the selected team's perspective.

### Batting First vs Chasing

Compare outcomes when teams set a target with outcomes when they chase one.

The report supports competition-wide and team-specific views, including:

- Batting-first and chasing wins
- Win percentages by innings position
- Average first-innings total
- Highest successful chase
- Lowest successfully defended total
- Team records when setting and chasing targets
- A supporting match-detail table

Batting order is derived from the recorded innings rather than inferred from home and away status, the toss or the result type.

### Head-to-Head

Compare two teams within a selected competition and season, including:

- Matches played
- Wins by each team
- Ties and no results
- Win percentages
- Total and average runs scored
- Average wickets lost
- Highest and lowest innings totals
- Batting-first and chasing records
- Largest and narrowest wins
- Highest successful chase
- Lowest successfully defended total
- Complete meeting history

### Format-Aware Rates

Scoring-rate calculations reflect the selected match format:

- The Hundred uses runs per 100 balls
- T20 and one-day cricket use runs per six-ball over

All rates are calculated from legal deliveries rather than decimal over notation.

Reports use each metric only where the recorded data supports it. A completed result may therefore contribute to a win-loss record even when incomplete innings details prevent it from contributing to score or rate analysis.

## Supported Match Formats

Cricket Tracker supports one innings per team in:

- The Hundred, with innings progress displayed in legal balls
- Twenty20 cricket, normally 20 six-ball overs
- One-day cricket, normally 50 six-ball overs

The default allocation comes from the selected match format and may be shortened for an individual match. Competition rules remain separate from match formats, allowing different T20 or ODI competitions to define their own points, standings, tie-break and revised-target behaviour.

## Data Exchange

### CSV Import

Import structured data from CSV files for:

- Countries
- Venues
- Teams
- Competition rulesets
- Competitions
- Matches
- Innings

Match and innings data are imported separately.

The match import contains fixture-level information, including the competition, teams, venue, schedule, toss and result details.

The innings import contains the associated batting summaries. Future fixtures can therefore be imported with empty innings shells and completed later as results become available.

Imports resolve related entities using names and other identifying fields while validating the required relationships between competitions, matches, teams and venues.

The same data can be imported from the command line:

```bash
cricket-import matches matches.csv
```

Supported dataset types are:

- `countries`
- `competition_rulesets`
- `competitions`
- `venues`
- `teams`
- `matches`
- `innings`

The convenience wrapper accepts the same values:

```bash
./scripts/import.sh matches matches.csv
```

### CSV Export

Export the application's structured data using the same schemas accepted by CSV import.

Available exports include:

- Countries
- Venues
- Teams
- Competition rulesets
- Competitions
- Matches
- Innings
- Calculated league tables

Match and innings exports remain separate so that fixture-level information can be maintained independently from innings summaries.

The same data can be exported from the command line:

```bash
cricket-export matches.csv --dataset matches
```

Supported dataset types are:

- `countries`
- `competition_rulesets`
- `competitions`
- `venues`
- `teams`
- `matches`
- `innings`

The convenience wrapper accepts the same values:

```bash
./scripts/export.sh matches matches.csv
```

CSV export makes recorded competition data available to spreadsheets, Jupyter notebooks and other external analysis tools.

### Limited-Overs CSV Fields

Match CSV files support the optional fields `scheduled_balls`, `revised_balls`, `target_runs`, `revised_target_runs` and `result_method`.

Innings CSV files retain `balls` as the canonical legal-delivery count and add
`innings_status`. The supported values are `not_started`, `in_progress`,
`completed`, and `abandoned`; conclusions such as all out, target reached, and
the innings limit being reached are derived from the score, wickets, target,
and allocation. Overs must not be encoded as decimal numbers.

All new columns are optional, so legacy Hundred CSV files remain importable. Where an allocation is omitted, the default for the selected match format is used.

### Sample Data

Self-contained examples are available in:

- `data/samples/T20-EXAMPLE-2026`
- `data/samples/ODI-EXAMPLE-2026`

Import each folder in dependency order:

1. `countries.csv`
2. `venues.csv`
3. `teams.csv`
4. `competition_rulesets.csv`
5. `competitions.csv`
6. `matches.csv`
7. `innings.csv`

The ODI example records an authoritative revised target and a DLS result method. Cricket Tracker uses the supplied target but does not calculate DLS.

### CSV League Table Export

Calculated league tables can be exported in CSV format for offline reference, sharing or further analysis.

The output is generated from the same dynamically calculated standings displayed in the application.

## Project Scope

Cricket Tracker is intended as a personal competition, results and analysis tool rather than a comprehensive cricket scoring platform.

The application deliberately does not attempt to provide:

- Ball-by-ball scoring
- Batting scorecards
- Bowling figures
- Partnerships
- Fall-of-wicket records
- Player statistics
- Live match feeds
- Automated data collection from external services
- Test or first-class cricket
- Multiple innings per team
- Declarations, follow-ons or innings victories
- Automatic DLS calculations

The focus is on maintaining a clear, useful and inspectable record of competitions, fixtures, results, innings summaries, standings and match-level analysis.

## Feedback

To report an issue or suggest an improvement, please use the project's [GitHub Issues](https://github.com/davewalker5/CricketTracker/issues) page.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
