[![GitHub issues](https://img.shields.io/github/issues/davewalker5/CricketTracker)](https://github.com/davewalker5/CricketTracker/issues)
[![Releases](https://img.shields.io/github/v/release/davewalker5/CricketTracker.svg?include_prereleases)](https://github.com/davewalker5/CricketTracker/releases)
[![License](https://img.shields.io/badge/License-mit-blue.svg)](https://github.com/davewalker5/CricketTracker/blob/main/LICENSE)
[![Language](https://img.shields.io/badge/language-python-blue.svg)](https://www.python.org)
[![GitHub code size in bytes](https://img.shields.io/github/languages/code-size/davewalker5/CricketTracker)](https://github.com/davewalker5/CricketTracker/)

# Cricket Tracker

## Overview

Cricket Tracker is a local-first desktop application for recording, following and exploring cricket competitions, fixtures, results, innings summaries and league standings.

The initial release focuses on The Hundred men's and women's competitions. It provides structured season records without attempting to act as a live-scoring service or reproduce complete scorecards and ball-by-ball data.

Built using Python, Streamlit and SQLite, the application emphasises a simple, maintainable design backed by a cricket-specific relational data model. Competition rules are modelled explicitly so that standings, points and net run rate can be calculated consistently from recorded match and innings data.

Cricket Tracker is based on the established structure of Rugby Tracker but uses its own independent database, configuration and migration history.

## Competition Tracking

Cricket Tracker currently provides:

### Competition Database

Maintain structured reference data for:

- Countries
- Venues
- Teams
- Competitions

Teams are linked to countries and classified by gender. Venues also reference their host country, providing consistent location and competition data throughout the application.

Competitions are season-specific and define the rules used when calculating league standings.

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

Rounds may be numeric league stages or descriptive knockout stages such as *Eliminator* and *Final*.

Structured result fields support cricket result types including wins by runs or wickets, ties and no-results.

### Innings Summaries

Record innings-level summaries separately from the main match record.

Each innings can include:

- Batting team
- Innings number
- Runs scored
- Wickets lost
- Balls faced

This provides enough information to describe the shape and outcome of a match without requiring complete scorecards or ball-by-ball data.

Future fixtures may contain empty innings records that can be completed after the match has taken place.

### Automatic Match Results

Where sufficient innings data has been recorded, Cricket Tracker can derive the structured match result automatically.

For completed two-innings matches, the application can determine:

- Winning team
- Whether the match was won by runs or wickets
- Winning margin
- Tied result

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

- Points awarded for wins, ties and no-results
- Whether knockout matches contribute to league standings
- Which stages are treated as knockout rounds

Net run rate is calculated from the recorded innings summaries and displayed alongside the competition standings.

## Supported Competitions

The initial release supports:

- The Hundred Men
- The Hundred Women

Men's and women's competitions are modelled separately while sharing the same teams, venues and competition-management structure where appropriate.

Additional competitions can be added as their formats, points systems and standings rules are established.

## Data Exchange

### CSV Import

Import structured data from CSV files for:

- Countries
- Venues
- Teams
- Competitions
- Matches
- Innings

Match and innings data are imported separately.

The match import contains the fixture-level information, including competition, teams, venue, schedule, toss and result details.

The innings import contains the associated batting summaries. Future fixtures may therefore be imported with empty innings shells and completed later as results become available.

Imports resolve related entities using names and other identifying fields while validating the required relationships between competitions, matches, teams and venues.

The same data can be imported from the command line:

```bash
cricket-import --type matches --input matches.csv
```

Supported types are:

- `countries`
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

Export the application's structured data using the same schemas accepted by CSV Import.

Available exports include:

- Countries
- Venues
- Teams
- Competitions
- Matches
- Innings
- Calculated league tables

Match and innings exports remain separate so fixture-level information can be maintained independently from innings summaries.

The same data can be exported from the command line:

```bash
cricket-export --type matches --output matches.csv
```

Supported types are:

- `countries`
- `competitions`
- `venues`
- `teams`
- `matches`
- `innings`

The convenience wrapper accepts the same values:

```bash
./scripts/export.sh matches matches.csv
```

CSV export makes the recorded competition data available for spreadsheets, Jupyter notebooks and other external analysis tools.

### CSV League Table Export

Calculated league tables can be exported in CSV format for offline reference or sharing.

The output is generated from the same dynamically calculated standings displayed in the application.

## Database Configuration

Cricket Tracker uses an independent SQLite database controlled by the `CRICKET_TRACKER_DB` environment variable.

For example:

```bash
export CRICKET_TRACKER_DB=/path/to/cricket-tracker.db
```

If the environment variable is not set, the application uses its configured fallback database location.

## Project Scope

Cricket Tracker is intended as a personal competition and results tracker rather than a comprehensive cricket scoring platform.

The initial release deliberately does not attempt to provide:

- Ball-by-ball scoring
- Batting scorecards
- Bowling figures
- Partnerships
- Fall-of-wicket records
- Player statistics
- Live match feeds
- Automated data collection from external services

The focus is on maintaining a clear, useful and inspectable record of competitions, fixtures, results, innings summaries and standings.

## Feedback

To file issues or suggestions, please use the [Issues](https://github.com/davewalker5/CricketTracker/issues) page for this project on GitHub.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
