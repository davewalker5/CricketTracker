"""Streamlit user interface for Cricket Tracker."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Callable

import pandas as pd
import streamlit as st

from cricket_tracker.analysis import (
    batting_order_summary,
    competition_teams,
    head_to_head,
    load_analysis_matches,
    rate_label,
    team_summary,
)
from cricket_tracker.config import application_version, is_read_only_domain
from cricket_tracker.database import apply_migrations, connect
from cricket_tracker.exports import DATASETS, export_csv
from cricket_tracker.imports import CricketImporter
from cricket_tracker.services import (
    GENDERS,
    MATCH_STAGES,
    MATCH_STATUSES,
    RESULT_METHODS,
    RESULT_TYPES,
    TOSS_DECISIONS,
    INNINGS_STATUSES,
    CricketService,
    ValidationError,
)
from cricket_tracker.standings import (
    calculate_combined_standings,
    calculate_standings,
    combined_competition_ids,
    table_to_csv,
)


def _queue_success(message: str) -> None:
    """Store a success message for display after the next Streamlit rerun.

    :param message: User-facing confirmation text.
    :return: None.
    """
    # Session state survives the control-flow interruption raised by st.rerun().
    st.session_state["_pending_success"] = message


def _show_pending_success() -> None:
    """Display and consume the success message queued by the previous run.

    :return: None.
    """
    message = st.session_state.pop("_pending_success", None)
    if message:
        # The rendered alert remains on screen until the user's next interaction.
        st.success(message)


def _show_persistent_error(error_key: str) -> None:
    """Display a record-specific validation error without consuming it.

    :param error_key: Session-state key holding the validation message.
    :return: None.
    """
    message = st.session_state.get(error_key)
    if message:
        # Table-selection reruns must not erase an error before the user can read it.
        st.error(str(message))


def _is_read_only_request() -> bool:
    """Return whether the current request is served from a browse-only domain.

    :return: ``True`` when the request host matches the configured domain list.
    """
    headers = st.context.headers
    # The public host may be forwarded by a deployment proxy. Only the first
    # value is relevant when a proxy chain has appended multiple hosts.
    hostname = headers.get("X-Forwarded-Host") or headers.get("Host")
    return is_read_only_domain(hostname.split(",", 1)[0] if hostname else None)


def _options(rows: list[dict[str, Any]], label: str = "name") -> dict[str, int]:
    """Map display names to entity identifiers.

    :param rows: Entity rows.
    :param label: Display-name column.
    :return: Label-to-identifier mapping.
    """
    return {str(row[label]): int(row["id"]) for row in rows}


def _team_options(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Map gender-qualified team labels to identifiers.

    :param rows: Team rows containing name, gender, and identifier fields.
    :return: Unique display labels mapped to team identifiers.
    """
    # Competitions can contain men's and women's teams with identical public names.
    return {
        f"{row['name']} — {row['gender']}": int(row["id"])
        for row in rows
    }


def _competition_team_options(
    teams: list[dict[str, Any]], competition: dict[str, Any]
) -> dict[str, int]:
    """Return teams whose gender matches the selected competition.

    :param teams: Available team rows.
    :param competition: Selected competition row.
    :return: Gender-qualified team labels mapped to identifiers.
    """
    return _team_options(
        [team for team in teams if team.get("gender") == competition.get("gender")]
    )


def _save(
    action: Callable[[], Any],
    message: str,
    connection: sqlite3.Connection,
    read_only: bool = False,
    error_key: str | None = None,
    on_success: Callable[[Any], None] | None = None,
) -> None:
    """Run a UI mutation and show its safe outcome.

    :param action: Zero-argument mutation.
    :param message: Success message.
    :param connection: Open connection containing the mutation transaction.
    :param read_only: Whether the current application domain prohibits mutations.
    :param error_key: Optional session-state key used to persist validation errors.
    :return: None.
    """
    if read_only:
        connection.rollback()
        error_message = "This application is browse only; changes cannot be saved."
        if error_key:
            st.session_state[error_key] = error_message
        st.error(error_message)
        return
    if error_key:
        # A new attempt supersedes the previous validation message for this record.
        st.session_state.pop(error_key, None)
    try:
        result = action()
        # Persist the mutation before Streamlit interrupts execution for its rerun.
        connection.commit()
        if on_success:
            on_success(result)
        _queue_success(message)
        st.rerun()
    except (ValidationError, sqlite3.IntegrityError, LookupError) as error:
        # Discard any writes performed before a multi-step validation failed.
        connection.rollback()
        if error_key:
            st.session_state[error_key] = str(error)
        st.error(str(error))


def _delete(
    action: Callable[[], Any],
    editor_key: str,
    message: str,
    connection: sqlite3.Connection,
    read_only: bool = False,
) -> None:
    """Run a delete action and reset its editor after success.

    :param action: Zero-argument delete mutation.
    :param editor_key: Stable key for the associated selectable table.
    :param message: Success message.
    :param connection: Open connection containing the mutation transaction.
    :return: None.
    """
    if read_only:
        connection.rollback()
        st.error("This application is browse only; records cannot be deleted.")
        return
    try:
        action()
        # Commit before rerunning so closing the interrupted connection cannot undo deletion.
        connection.commit()
        st.session_state[f"{editor_key}_generation"] = (
            st.session_state.get(f"{editor_key}_generation", 0) + 1
        )
        _queue_success(message)
        st.rerun()
    except (ValidationError, sqlite3.IntegrityError, LookupError) as error:
        # Restore the transaction after any expected domain or database failure.
        connection.rollback()
        st.error(str(error))


def _clear_editor(editor_key: str) -> None:
    """Clear a selected row and reset the associated form.

    :param editor_key: Stable key for the selectable table.
    :return: None.
    """
    st.session_state[f"{editor_key}_generation"] = (
        st.session_state.get(f"{editor_key}_generation", 0) + 1
    )
    st.rerun()


def _reset_competition_editor(_saved_id: int | None = None) -> None:
    """Clear competition table selection and all add/edit form values.

    :param _saved_id: Identifier returned by the save action; intentionally unused.
    :return: None.
    """
    st.session_state["competition_editor_generation"] = (
        st.session_state.get("competition_editor_generation", 0) + 1
    )
    form_prefixes = (
        "competition_name_",
        "competition_year_",
        "competition_ruleset_",
        "competition_gender_",
        "competition_format_",
        "competition_country_",
    )
    for key in list(st.session_state):
        if key.startswith(form_prefixes):
            del st.session_state[key]


def _reset_team_editor(_saved_id: int | None = None) -> None:
    """Clear team table selection and all add/edit form values.

    :param _saved_id: Identifier returned by the save action; intentionally unused.
    :return: None.
    """
    st.session_state["team_editor_generation"] = (
        st.session_state.get("team_editor_generation", 0) + 1
    )
    form_prefixes = (
        "team_name_",
        "team_country_",
        "team_gender_",
        "team_venue_",
    )
    for key in list(st.session_state):
        if key.startswith(form_prefixes):
            del st.session_state[key]


def _reset_venue_editor(_saved_id: int | None = None) -> None:
    """Clear venue table selection and all add/edit form values.

    :param _saved_id: Identifier returned by the save action; intentionally unused.
    :return: None.
    """
    st.session_state["venue_editor_generation"] = (
        st.session_state.get("venue_editor_generation", 0) + 1
    )
    form_prefixes = (
        "venue_name_",
        "venue_city_",
        "venue_country_",
        "venue_capacity_",
    )
    for key in list(st.session_state):
        if key.startswith(form_prefixes):
            del st.session_state[key]


def _reset_country_editor(_saved_id: int | None = None) -> None:
    """Clear country table selection and all add/edit form values.

    :param _saved_id: Identifier returned by the save action; intentionally unused.
    :return: None.
    """
    st.session_state["country_editor_generation"] = (
        st.session_state.get("country_editor_generation", 0) + 1
    )
    form_prefixes = (
        "country_name_",
        "country_code_",
    )
    for key in list(st.session_state):
        if key.startswith(form_prefixes):
            del st.session_state[key]


def _selectable_table(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    editor_key: str,
) -> dict[str, Any] | None:
    """Render a display-only table with single-row selection.

    Streamlit supplies the leading selector column. Database identifiers remain
    in the backing rows and are never included in the displayed frame.

    :param rows: Backing entity rows in display order.
    :param columns: Source-column and display-label pairs.
    :param editor_key: Stable widget key for this entity editor.
    :return: Selected backing row, or ``None`` for a blank editor.
    """
    boolean_columns = {
        "active",
        "completed",
        "uses_net_run_rate",
        "include_knockout_matches_in_table",
    }
    frame = pd.DataFrame(
        [
            {
                label: bool(row.get(source)) if source in boolean_columns else row.get(source)
                for source, label in columns
            }
            for row in rows
        ],
        columns=[label for _, label in columns],
    )
    generation = st.session_state.get(f"{editor_key}_generation", 0)
    event = st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"{editor_key}_table_{generation}",
    )
    selected_indices = event.selection.rows
    if not selected_indices:
        return None
    selected_index = int(selected_indices[0])
    return rows[selected_index] if selected_index < len(rows) else None


def _selected_index(options: list[Any], selected: Any) -> int:
    """Return the option index for a stored value.

    :param options: Available option values.
    :param selected: Stored value to locate.
    :return: Matching index, or zero when absent.
    """
    try:
        return options.index(selected)
    except ValueError:
        return 0


def _reset_match_tab() -> None:
    """Clear match selection and form state after the competition changes.

    :return: None.
    """
    # A new table generation prevents the prior competition's selected row index persisting.
    st.session_state["match_editor_generation"] = (
        st.session_state.get("match_editor_generation", 0) + 1
    )
    st.session_state["match_editor_new"] = False
    st.session_state["match_workspace_match_id"] = None
    form_prefixes = (
        "match_date_",
        "match_time_",
        "match_venue_",
        "match_home_",
        "match_away_",
        "match_stage_",
        "match_status_",
        "match_toss_",
        "match_override_",
        "match_winner_",
        "match_result_",
        "match_margin_",
        "match_method_",
        "match_calculated_",
    )
    # Remove every record-specific value while retaining the newly selected competition.
    for key in list(st.session_state):
        if key.startswith(form_prefixes):
            del st.session_state[key]


def _sync_workspace_match(
    match_options: dict[str, int],
    widget_key: str,
) -> None:
    """Copy the innings match selector into shared match-workspace state.

    :param match_options: Match labels mapped to identifiers.
    :param widget_key: Session-state key used by the innings match selector.
    :return: None.
    """
    selected_label = st.session_state.get(widget_key)
    st.session_state["match_workspace_match_id"] = match_options.get(selected_label)
    # Reset any old dataframe selection so it cannot override the dropdown choice.
    st.session_state["match_editor_generation"] = (
        st.session_state.get("match_editor_generation", 0) + 1
    )
    st.session_state["match_editor_new"] = False


def _select_saved_match(saved_id: int) -> None:
    """Select a newly created match and rebuild its table row.

    :param saved_id: Identifier returned by the match save.
    :return: None.
    """
    st.session_state["match_workspace_match_id"] = int(saved_id)
    st.session_state["match_editor_new"] = False
    st.session_state["match_editor_generation"] = (
        st.session_state.get("match_editor_generation", 0) + 1
    )


def _reset_new_innings_form(editor_key: str, generation: int) -> None:
    """Close and reset a new-innings form after saving.

    :param editor_key: Match-specific innings editor key.
    :param generation: Generation used by the form that was just saved.
    :return: None.
    """
    st.session_state[f"{editor_key}_new_form_generation"] = generation + 1
    st.session_state[f"{editor_key}_new"] = False


def _choose_match_selection(
    checked_ids: list[int],
    selected_match_id: int | None,
) -> int | None:
    """Choose one match from checkbox values while supporting row changes.

    :param checked_ids: Match identifiers whose checkboxes are currently selected.
    :param selected_match_id: Previously shared match identifier.
    :return: Newly selected match identifier, or ``None``.
    """
    if not checked_ids:
        return None
    # During a row change, the non-current checked row is the user's new choice.
    changed_ids = [
        match_id for match_id in checked_ids
        if match_id != selected_match_id
    ]
    return changed_ids[0] if changed_ids else checked_ids[0]


def _match_team_cell_styles(
    rows: list[dict[str, Any]],
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Build winner, loser, and neutral styles for match team-name cells.

    :param rows: Enriched match rows corresponding to the display frame.
    :param frame: Match table display frame.
    :return: CSS style strings aligned with the display frame.
    """
    styles = pd.DataFrame("", index=frame.index, columns=frame.columns)
    for index, row in enumerate(rows):
        if index >= len(frame.index):
            break
        result_type = row.get("result_type")
        status = row.get("match_status")
        winner_id = row.get("winning_team_id")
        # Tied and abandoned matches give both teams the same neutral treatment.
        if result_type in {"Tie", "Abandoned"} or status == "Abandoned":
            styles.at[index, "Home team"] = "background-color: #fff3cd"
            styles.at[index, "Away team"] = "background-color: #fff3cd"
        elif winner_id is not None:
            # An ordinary result highlights the winner and the opposing loser.
            home_won = int(winner_id) == int(row["home_team_id"])
            styles.at[index, "Home team"] = (
                "background-color: #dff2e1"
                if home_won
                else "background-color: #f8dddd"
            )
            styles.at[index, "Away team"] = (
                "background-color: #f8dddd"
                if home_won
                else "background-color: #dff2e1"
            )
    return styles


def _selectable_match_table(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    selected_match_id: int | None,
    editor_key: str,
) -> dict[str, Any] | None:
    """Render a match table with a controllable single-selection checkbox.

    :param rows: Enriched match rows.
    :param columns: Source-column and display-label pairs.
    :param selected_match_id: Match selected in either match workspace view.
    :param editor_key: Stable widget key for the match editor.
    :return: Selected backing row, or ``None``.
    """
    frame = pd.DataFrame(
        [
            {
                "Selected": int(row["id"]) == selected_match_id,
                **{label: row.get(source) for source, label in columns},
            }
            for row in rows
        ],
        columns=["Selected", *[label for _, label in columns]],
    )
    generation = st.session_state.get(f"{editor_key}_generation", 0)
    team_styles = _match_team_cell_styles(rows, frame)
    styled_frame = frame.style.apply(
        lambda _frame: team_styles,
        axis=None,
    )
    # Only the checkbox is editable; all persisted match fields remain read-only.
    edited = st.data_editor(
        styled_frame,
        hide_index=True,
        width="stretch",
        disabled=[label for _, label in columns],
        column_config={
            "Selected": st.column_config.CheckboxColumn(
                "Selected",
                help="Select one match to edit.",
            )
        },
        key=f"{editor_key}_table_{generation}",
    )
    checked_ids = [
        int(rows[index]["id"])
        for index, checked in enumerate(edited["Selected"].tolist())
        if checked and index < len(rows)
    ]
    new_match_id = _choose_match_selection(checked_ids, selected_match_id)
    if new_match_id != selected_match_id:
        # Rebuild once so a row change leaves exactly one checkbox selected.
        st.session_state["match_workspace_match_id"] = new_match_id
        st.session_state[f"{editor_key}_generation"] = generation + 1
        st.rerun()
    return next(
        (row for row in rows if int(row["id"]) == new_match_id),
        None,
    )


def _match_editor_tab(service: CricketService, read_only: bool = False) -> None:
    """Render match fixture and result maintenance.

    :param service: Transaction-scoped service.
    :param read_only: Whether controls that mutate cricket data are disabled.
    :return: None.
    """
    competitions = service.list_competitions()
    teams = service.list_teams()
    if not competitions or len(teams) < 2:
        st.info("Add a competition and at least two teams before creating fixtures.")
        return
    competition_options = {
        f"{row['name']} — {row['season']}": int(row["id"]) for row in competitions
    }
    venue_options: dict[str, int | None] = {"Not set": None, **_options(service.list_venues())}
    competition_label = st.selectbox(
        "Competition",
        competition_options,
        key="match_workspace_competition",
        on_change=_reset_match_tab,
    )
    competition_id = competition_options[competition_label]
    competition = next(
        row for row in competitions if int(row["id"]) == competition_id
    )
    team_options = _competition_team_options(teams, competition)
    if len(team_options) < 2:
        st.info(
            "Add at least two teams matching this competition's gender before "
            "creating fixtures."
        )
        return
    matches = service.list_matches(competition_id)
    shared_match_id = st.session_state.get("match_workspace_match_id")
    table_selected = _selectable_match_table(
        matches,
        [
            ("match_date", "Date"), ("start_time", "Start"),
            ("home_team_name", "Home team"), ("away_team_name", "Away team"),
            ("venue_name", "Venue"), ("match_stage", "Stage"),
            ("match_status", "Status"),
            ("effective_delivery_display", "Allocation"),
            ("winning_team_name", "Winning team"),
            ("result_type", "Result"),
        ],
        shared_match_id,
        "match_editor",
    )
    if table_selected:
        # Publish table selections for the innings view.
        st.session_state["match_workspace_match_id"] = int(table_selected["id"])
        shared_match_id = int(table_selected["id"])
    selected = table_selected or next(
        (
            row for row in matches
            if int(row["id"]) == shared_match_id
        ),
        None,
    )
    # Selecting a row always takes precedence over a previously requested blank form.
    if selected:
        st.session_state["match_editor_new"] = False
    add_clicked = st.button(
        "Add match",
        key="match_editor_add",
        disabled=bool(selected) or read_only,
    )
    if add_clicked:
        # Reset the table selection before displaying controls for a new record.
        st.session_state["match_editor_new"] = True
        st.session_state["match_workspace_match_id"] = None
        st.session_state["match_editor_generation"] = (
            st.session_state.get("match_editor_generation", 0) + 1
        )
        st.rerun()
    adding_match = bool(st.session_state.get("match_editor_new", False))
    if not selected and not adding_match:
        st.caption("Select a match to edit it, or choose Add match to create one.")
        st.info("No match selected.")
        return
    st.caption(
        "Editing the selected match."
        if selected
        else "Enter the details for the new match."
    )
    st.subheader("Edit match" if selected else "Add match")
    selected_id = selected["id"] if selected else None
    team_labels = list(team_options)
    venue_labels = list(venue_options)
    selected_venue = next(
        (
            label for label, venue_id in venue_options.items()
            if selected and venue_id == selected.get("venue_id")
        ),
        "Not set",
    )
    selected_home = next(
        (
            label for label, team_id in team_options.items()
            if selected and team_id == selected.get("home_team_id")
        ),
        team_labels[0],
    )
    selected_away = next(
        (
            label for label, team_id in team_options.items()
            if selected and team_id == selected.get("away_team_id")
        ),
        team_labels[1],
    )
    calculated = service.derive_match_result(int(selected_id)) if selected_id else None
    if calculated:
        calculated_winner = next(
            (
                row["name"] for row in teams
                if row["id"] == calculated["winning_team_id"]
            ),
            None,
        )
        calculated_display = {**calculated, "winning_team_name": calculated_winner}
        st.info(f"Calculated result: {service.result_description(calculated_display)}")
    elif selected and selected.get("match_status") == "Completed":
        st.warning("A result cannot yet be calculated from the current innings data.")
    if selected and selected.get("result_source") == "Manual":
        official_result = service.result_description(selected)
        st.warning(
            "The official manual override is active. "
            f"Official result: {official_result}. "
            "Any available calculated result is shown above for comparison."
        )
    # Keep the override switch outside the form so changing it reruns immediately.
    override_result = st.checkbox(
        "Override calculated result",
        value=bool(selected and selected.get("result_source") == "Manual"),
        key=f"match_override_{selected_id}",
    )
    # A record-specific form key prevents values from the previous selection being reused.
    form_identity = selected_id if selected_id is not None else "new"
    match_error_key = f"match_save_error_{form_identity}"
    _show_persistent_error(match_error_key)
    limit_unit = str(competition["limit_unit"])
    balls_per_over = competition.get("balls_per_over")
    unit_size = int(balls_per_over or 1)
    allocation_label = "overs" if limit_unit == "overs" else "balls"
    default_allocation = int(competition["innings_limit"])
    scheduled_value = (
        int(selected["scheduled_balls"]) // unit_size
        if selected and selected.get("scheduled_balls")
        else default_allocation
    )
    revised_value = (
        int(selected["revised_balls"]) // unit_size
        if selected and selected.get("revised_balls")
        else scheduled_value
    )
    st.caption(
        f"Match format: {competition['match_format_name']} — "
        f"{default_allocation} {allocation_label} per innings."
    )
    with st.form(f"match_{form_identity}"):
        fixture_columns = st.columns(3)
        match_date = fixture_columns[0].date_input(
            "Match date *",
            date.fromisoformat(selected["match_date"]) if selected else date.today(),
            key=f"match_date_{selected_id}",
        )
        start_time = fixture_columns[1].text_input(
            "Start time", value=selected.get("start_time") or "" if selected else "",
            placeholder="HH:MM", key=f"match_time_{selected_id}",
        )
        venue = fixture_columns[2].selectbox(
            "Venue",
            venue_labels,
            index=_selected_index(venue_labels, selected_venue),
            key=f"match_venue_{selected_id}",
        )
        participant_columns = st.columns(3)
        home = participant_columns[0].selectbox(
            "Home team *",
            team_labels,
            index=_selected_index(team_labels, selected_home),
            key=f"match_home_{selected_id}",
        )
        away = participant_columns[1].selectbox(
            "Away team *",
            team_labels,
            index=_selected_index(team_labels, selected_away),
            key=f"match_away_{selected_id}",
        )
        stage = participant_columns[2].selectbox(
            "Match stage *",
            MATCH_STAGES,
            index=_selected_index(
                list(MATCH_STAGES), selected.get("match_stage") if selected else "League"
            ),
            key=f"match_stage_{selected_id}",
        )
        allocation_option_columns = st.columns(3)
        use_revised_allocation = allocation_option_columns[2].checkbox(
            "Use reduced allocation",
            value=bool(selected and selected.get("revised_balls")),
            key=f"match_use_revised_allocation_{selected_id}",
        )
        allocation_columns = st.columns(3)
        status = allocation_columns[0].selectbox(
            "Match status *",
            MATCH_STATUSES,
            index=_selected_index(
                list(MATCH_STATUSES), selected.get("match_status") if selected else "Scheduled"
            ),
            key=f"match_status_{selected_id}",
        )
        scheduled_allocation = allocation_columns[1].number_input(
            f"Scheduled {allocation_label} per innings",
            value=scheduled_value,
            key=f"match_scheduled_allocation_{selected_id}",
        )
        revised_allocation = allocation_columns[2].number_input(
            f"Revised {allocation_label} per innings",
            value=revised_value,
            disabled=not use_revised_allocation,
            key=f"match_revised_allocation_{selected_id}",
        )
        # Targets are authoritative inputs; the application never calculates DLS.
        target_option_columns = st.columns(3)
        use_revised_target = target_option_columns[1].checkbox(
            "Use revised target",
            value=bool(selected and selected.get("revised_target_runs")),
            key=f"match_use_revised_target_{selected_id}",
        )
        target_columns = st.columns(3)
        original_target = target_columns[0].number_input(
            "Original target (0 to derive from first innings)",
            value=int(selected.get("target_runs") or 0) if selected else 0,
            key=f"match_original_target_{selected_id}",
        )
        revised_target = target_columns[1].number_input(
            "Revised target",
            value=int(selected.get("revised_target_runs") or 1)
            if selected else 1,
            disabled=not use_revised_target,
            key=f"match_revised_target_{selected_id}",
        )
        calculation_method = target_columns[2].selectbox(
            "Calculation method",
            RESULT_METHODS,
            index=_selected_index(
                list(RESULT_METHODS),
                selected.get("result_method") if selected else "Standard",
            ),
            disabled=not use_revised_target,
            key=f"match_calculation_method_{selected_id}",
        )
        participant_options = {
            "Not recorded": None,
            home: team_options[home],
            away: team_options[away],
        }
        participant_labels = list(participant_options)
        selected_toss = next(
            (
                label for label, team_id in participant_options.items()
                if selected and team_id == selected.get("toss_winner_team_id")
            ),
            "Not recorded",
        )
        match_outcome_columns = st.columns(3)
        toss_winner = match_outcome_columns[0].selectbox(
            "Toss winner",
            participant_labels,
            index=_selected_index(participant_labels, selected_toss),
            key=f"match_toss_winner_{selected_id}",
        )
        toss_choices = ["Not recorded", *TOSS_DECISIONS]
        toss_decision = match_outcome_columns[1].selectbox(
            "Toss decision",
            toss_choices,
            index=_selected_index(
                toss_choices, selected.get("toss_decision") if selected else "Not recorded"
            ),
            key=f"match_toss_decision_{selected_id}",
        )
        selected_winner = next(
            (
                label for label, team_id in participant_options.items()
                if selected and team_id == selected.get("winning_team_id")
            ),
            "Not recorded",
        )
        result_choices = ["Not recorded", *RESULT_TYPES]
        if override_result:
            # Manual mode uses editable fields whose values are explicitly saved.
            winner = match_outcome_columns[2].selectbox(
                "Winning team",
                participant_labels,
                index=_selected_index(participant_labels, selected_winner),
                key=f"match_winner_{selected_id}",
            )
            result_columns = st.columns(3)
            result = result_columns[0].selectbox(
                "Result type",
                result_choices,
                index=_selected_index(
                    result_choices,
                    selected.get("result_type") if selected else "Not recorded",
                ),
                key=f"match_result_{selected_id}",
            )
            margin = result_columns[1].number_input(
                "Result margin",
                value=int(selected.get("result_margin_value") or 0) if selected else 0,
                key=f"match_margin_{selected_id}",
            )
            method = result_columns[2].selectbox(
                "Result method",
                RESULT_METHODS,
                index=_selected_index(
                    list(RESULT_METHODS),
                    selected.get("result_method") if selected else "Standard",
                ),
                key=f"match_method_{selected_id}",
            )
            override_reason = st.text_area(
                "Override reason *",
                value=selected.get("result_override_reason") or "" if selected else "",
                key=f"match_override_reason_{selected_id}",
            )
        else:
            # Value-bearing keys force read-only controls to refresh after innings changes.
            winner = selected_winner
            result = selected.get("result_type") or "Not recorded" if selected else "Not recorded"
            margin = int(selected.get("result_margin_value") or 0) if selected else 0
            method = calculation_method
            override_reason = ""
            result_revision = (
                f"{selected_id}_{selected.get('winning_team_id')}_"
                f"{result}_{margin}_{method}"
                if selected
                else "new"
            )
            match_outcome_columns[2].text_input(
                "Winning team",
                value=selected_winner,
                disabled=True,
                key=f"match_calculated_winner_{result_revision}",
            )
            result_columns = st.columns(3)
            result_columns[0].text_input(
                "Result type",
                value=result,
                disabled=True,
                key=f"match_calculated_result_{result_revision}",
            )
            result_columns[1].number_input(
                "Result margin",
                min_value=0,
                value=margin,
                disabled=True,
                key=f"match_calculated_margin_{result_revision}",
            )
            result_columns[2].text_input(
                "Result method",
                value=method,
                disabled=True,
                key=f"match_calculated_method_{result_revision}",
            )
        save_column, delete_column, clear_column = st.columns(3)
        save_clicked = save_column.form_submit_button(
            "Save", type="primary", disabled=read_only, width="stretch"
        )
        delete_clicked = delete_column.form_submit_button(
            "Delete", disabled=selected is None or read_only, width="stretch"
        )
        clear_clicked = clear_column.form_submit_button("Clear", width="stretch")
    if save_clicked:
        result_value = None if result == "Not recorded" else result
        _save(
            lambda: service.save_match(
                entity_id=selected_id,
                competition_id=competition_id,
                match_date=match_date,
                start_time=start_time,
                venue_id=venue_options[venue],
                home_team_id=team_options[home],
                away_team_id=team_options[away],
                match_stage=stage,
                match_status=status,
                scheduled_balls=int(scheduled_allocation) * unit_size,
                revised_balls=(
                    int(revised_allocation) * unit_size
                    if use_revised_allocation
                    else None
                ),
                target_runs=original_target or None,
                revised_target_runs=(
                    revised_target if use_revised_target else None
                ),
                toss_winner_team_id=participant_options[toss_winner],
                toss_decision=None if toss_decision == "Not recorded" else toss_decision,
                winning_team_id=participant_options[winner] if override_result else None,
                result_type=result_value if override_result else None,
                result_margin_value=(
                    margin if override_result and result in {"Runs", "Wickets"} else None
                ),
                result_margin_type=(
                    result if override_result and result in {"Runs", "Wickets"} else None
                ),
                result_method=method,
                result_source="Manual" if override_result else None,
                result_override_reason=override_reason if override_result else None,
            ),
            "Match saved.",
            service.repo.connection,
            read_only,
            error_key=match_error_key,
            on_success=(
                _select_saved_match
                if selected_id is None
                else None
            ),
        )
    elif delete_clicked and selected_id is not None:
        st.session_state["match_workspace_match_id"] = None
        _delete(
            lambda: service.delete_match(selected_id),
            "match_editor",
            "Match deleted.",
            service.repo.connection,
            read_only,
        )
    elif clear_clicked:
        # Closing the editor returns the tab to its deliberately empty state.
        st.session_state.pop(match_error_key, None)
        st.session_state["match_editor_new"] = False
        st.session_state["match_workspace_match_id"] = None
        _clear_editor("match_editor")


def _innings_editor_tab(service: CricketService, read_only: bool = False) -> None:
    """Render competition, match, and innings maintenance controls.

    :param service: Transaction-scoped service.
    :param read_only: Whether controls that mutate cricket data are disabled.
    :return: None.
    """
    competitions = service.list_competitions()
    if not competitions:
        st.info("Add a competition before entering innings.")
        return
    competition_options = {
        f"{row['name']} — {row['season']}": int(row["id"]) for row in competitions
    }
    workspace_columns = st.columns(2)
    competition_label = workspace_columns[0].selectbox(
        "Competition",
        competition_options,
        key="match_workspace_competition",
        on_change=_reset_match_tab,
    )
    competition_id = competition_options[competition_label]
    matches = service.list_matches(competition_id)
    if not matches:
        st.info("Add a match to this competition before entering innings.")
        return
    match_options = {
        f"{row['match_date']} — {row['home_team_name']} v {row['away_team_name']}": int(row["id"])
        for row in matches
    }
    shared_match_id = st.session_state.get("match_workspace_match_id")
    selected_match_label = next(
        (
            label for label, option_match_id in match_options.items()
            if option_match_id == shared_match_id
        ),
        next(iter(match_options)),
    )
    selected_match_index = _selected_index(
        list(match_options),
        selected_match_label,
    )
    # Include the shared identifier so an externally changed selection rebuilds the widget.
    match_widget_key = (
        f"innings_match_{competition_id}_{shared_match_id or 'default'}"
    )
    match_label = workspace_columns[1].selectbox(
        "Match",
        match_options,
        index=selected_match_index,
        key=match_widget_key,
        on_change=_sync_workspace_match,
        args=(match_options, match_widget_key),
    )
    match_id = match_options[match_label]
    # Initialise shared state when the innings view chooses its first default match.
    st.session_state["match_workspace_match_id"] = match_id
    match = next(row for row in matches if int(row["id"]) == match_id)
    participants = {
        str(match["home_team_name"]): int(match["home_team_id"]),
        str(match["away_team_name"]): int(match["away_team_id"]),
    }
    innings = service.list_innings(match_id)
    selected_innings = _selectable_table(
        innings,
        [
            ("innings_number", "Innings"), ("batting_team_name", "Batting team"),
            ("bowling_team_name", "Bowling team"), ("runs", "Runs"),
            ("wickets", "Wickets"), ("delivery_display", "Progress"),
            ("innings_status", "Status"),
        ],
        f"innings_editor_{match_id}",
    )
    innings_editor_key = f"innings_editor_{match_id}"
    new_innings_key = f"{innings_editor_key}_new"
    # Selecting a row closes any blank form previously opened for this match.
    if selected_innings:
        st.session_state[new_innings_key] = False
    add_innings_clicked = st.button(
        "Add innings",
        key=f"{innings_editor_key}_add",
        disabled=bool(selected_innings) or read_only,
    )
    if add_innings_clicked:
        # Rebuild the innings table so its prior row selection is cleared.
        st.session_state[new_innings_key] = True
        st.session_state[f"{innings_editor_key}_generation"] = (
            st.session_state.get(f"{innings_editor_key}_generation", 0) + 1
        )
        st.rerun()
    adding_innings = bool(st.session_state.get(new_innings_key, False))
    if not selected_innings and not adding_innings:
        st.caption("Select an innings to edit it, or choose Add innings to create one.")
        st.info("No innings selected.")
        return
    st.caption(
        "Editing the selected innings."
        if selected_innings
        else "Enter the details for the new innings."
    )
    st.subheader("Edit innings" if selected_innings else "Add innings")
    st.caption(
        f"Expected allocation: {match['effective_delivery_display']} "
        f"({match['match_format_name']})."
    )
    selected_innings_id = selected_innings["id"] if selected_innings else None
    participant_options: dict[str, int | None] = {
        "Not set": None,
        **participants,
    }
    participant_labels = list(participant_options)
    selected_batting = next(
        (
            label for label, team_id in participants.items()
            if selected_innings and team_id == selected_innings.get("batting_team_id")
        ),
        "Not set",
    )
    # A record-specific form prevents values leaking between selected innings.
    new_form_generation = st.session_state.get(
        f"{innings_editor_key}_new_form_generation", 0
    )
    innings_form_identity = (
        selected_innings_id
        if selected_innings_id is not None
        else f"new_{new_form_generation}"
    )
    innings_error_key = (
        f"innings_save_error_{match_id}_{innings_form_identity}"
    )
    _show_persistent_error(innings_error_key)
    with st.form(f"innings-{match_id}-{innings_form_identity}"):
        innings_detail_columns = st.columns(3)
        number = innings_detail_columns[0].number_input(
            "Innings number",
            value=int(selected_innings.get("innings_number", len(innings) + 1))
            if selected_innings else len(innings) + 1,
            key=f"innings_number_{match_id}_{innings_form_identity}",
        )
        batting = innings_detail_columns[1].selectbox(
            "Batting team",
            participant_labels,
            index=_selected_index(participant_labels, selected_batting),
            key=f"innings_batting_{match_id}_{innings_form_identity}",
        )
        innings_status = innings_detail_columns[2].selectbox(
            "Innings status",
            INNINGS_STATUSES,
            index=_selected_index(
                list(INNINGS_STATUSES),
                selected_innings.get("innings_status")
                if selected_innings else "not_started",
            ),
            key=f"innings_status_{match_id}_{innings_form_identity}",
        )
        score_columns = st.columns(3)
        runs = score_columns[0].number_input(
            "Runs",
            value=int(selected_innings.get("runs") or 0) if selected_innings else 0,
            key=f"innings_runs_{match_id}_{innings_form_identity}",
        )
        wickets = score_columns[1].number_input(
            "Wickets",
            value=int(selected_innings.get("wickets") or 0) if selected_innings else 0,
            key=f"innings_wickets_{match_id}_{innings_form_identity}",
        )
        balls = score_columns[2].number_input(
            "Legal balls",
            value=int(selected_innings.get("balls") or 0) if selected_innings else 0,
            help=(
                "Enter canonical legal balls. Values above the displayed "
                "allocation are rejected when you save."
            ),
            key=f"innings_balls_{match_id}_{innings_form_identity}",
        )
        target_columns = st.columns(3)
        target = target_columns[0].number_input(
            "Target (0 if not applicable)",
            value=int(selected_innings.get("target") or 0)
            if selected_innings else 0,
            key=f"innings_target_{match_id}_{innings_form_identity}",
        )
        save_column, delete_column, clear_column = st.columns(3)
        innings_save = save_column.form_submit_button(
            "Save", type="primary", disabled=read_only, width="stretch"
        )
        innings_delete = delete_column.form_submit_button(
            "Delete", disabled=selected_innings is None or read_only, width="stretch"
        )
        innings_clear = clear_column.form_submit_button("Clear", width="stretch")
    if innings_save:
        batting_team_id = participant_options[batting]
        bowling_team_id = (
            next(
                team_id
                for team_id in participants.values()
                if team_id != batting_team_id
            )
            if batting_team_id is not None
            else None
        )
        _save(
            lambda: service.save_innings(
                entity_id=selected_innings_id,
                match_id=match_id,
                innings_number=number,
                batting_team_id=batting_team_id,
                bowling_team_id=bowling_team_id,
                runs=runs,
                wickets=wickets,
                balls=balls,
                target=target or None,
                innings_status=innings_status,
            ),
            "Innings saved.",
            service.repo.connection,
            read_only,
            error_key=innings_error_key,
            on_success=(
                lambda _saved_id: _reset_new_innings_form(
                    innings_editor_key, new_form_generation
                )
                if selected_innings_id is None
                else None
            ),
        )
    elif innings_delete and selected_innings_id is not None:
        _delete(
            lambda: service.delete_innings(selected_innings_id),
            f"innings_editor_{match_id}",
            "Innings deleted.",
            service.repo.connection,
            read_only,
        )
    elif innings_clear:
        # Closing the editor restores the deliberate no-selection state.
        st.session_state.pop(innings_error_key, None)
        st.session_state[new_innings_key] = False
        _clear_editor(innings_editor_key)


def _matches(service: CricketService, read_only: bool = False) -> None:
    """Render separate match and innings maintenance tabs.

    :param service: Transaction-scoped service.
    :param read_only: Whether controls that mutate cricket data are disabled.
    :return: None.
    """
    st.header("Matches")
    # Unlike st.tabs, a keyed radio retains the active view across selection reruns.
    active_tab = st.radio(
        "Match data view",
        ("Matches", "Innings"),
        horizontal=True,
        label_visibility="collapsed",
        key="matches_active_tab",
    )
    if active_tab == "Matches":
        _match_editor_tab(service, read_only)
    else:
        _innings_editor_tab(service, read_only)


def _standings(service: CricketService) -> None:
    """Render the selected season's league table.

    :param service: Transaction-scoped service.
    :return: None.
    """
    st.header("League table")
    # Knockout-only rulesets remain available elsewhere without a misleading table.
    competitions = [
        row for row in service.list_competitions() if bool(row["has_standings"])
    ]
    if not competitions:
        st.info("No competition is configured to provide a standings table.")
        return
    options: dict[str, tuple[str, int]] = {
        f"{row['name']} — {row['season']}": ("single", int(row["id"]))
        for row in competitions
    }
    seen_combined_groups: set[frozenset[int]] = set()
    for competition in competitions:
        group = combined_competition_ids(
            service.repo.connection,
            int(competition["id"]),
        )
        group_key = frozenset(group)
        if group and group_key not in seen_combined_groups:
            # One combined choice represents every gender competition in the group.
            combined_label = (
                f"{competition['format']} — {competition['season']} — Combined"
            )
            options[combined_label] = ("combined", int(competition["id"]))
            seen_combined_groups.add(group_key)
    label = st.selectbox("Competition", options)
    table_type, competition_id = options[label]
    table = (
        calculate_combined_standings(service.repo.connection, competition_id)
        if table_type == "combined"
        else calculate_standings(service.repo.connection, competition_id)
    )
    columns = ["team", "played", "won", "lost", "tied", "no_result", "points"]
    if any(row.get("net_run_rate") is not None for row in table):
        columns.append("net_run_rate")
        st.caption(
            "Net run rate uses completed, unrevised matches. "
            "Revised-allocation and revised-target matches are excluded."
        )
    st.dataframe(pd.DataFrame(table, columns=columns), hide_index=True, width="stretch")
    # Export the already calculated rows so the download exactly matches this view.
    st.download_button(
        "Download the league table CSV",
        table_to_csv(table),
        file_name="league-table.csv",
        mime="text/csv",
        width="content",
    )


def _analysis_value(value: Any, suffix: str = "") -> str:
    """Format an optional analysis metric consistently.

    :param value: Numeric or textual metric value.
    :param suffix: Optional display suffix.
    :return: Display-ready value or an unavailable marker.
    """
    # Preserve integers while keeping calculated averages compact.
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _analysis_metrics(items: list[tuple[str, Any, str]]) -> None:
    """Render a responsive row of analysis metric cards.

    :param items: Label, value, and suffix tuples.
    :return: None.
    """
    # Batches of at most five cards remain readable on ordinary displays.
    for offset in range(0, len(items), 5):
        batch = items[offset : offset + 5]
        columns = st.columns(len(batch))
        for column, (label, value, suffix) in zip(columns, batch):
            # A bordered container gives each figure the aligned card treatment.
            card = column.container(border=True)
            card.metric(label, _analysis_value(value, suffix))


def _analysis_scope(
    service: CricketService,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Render cascading competition and season selectors.

    :param service: Cricket service providing competition rows.
    :return: Selected competition row and participating teams, or ``None``.
    """
    # Group season-specific database rows behind the human competition name.
    competitions = service.list_competitions()
    if not competitions:
        st.info("Add a competition and fixtures before using analysis.")
        return None
    names = sorted({row["name"] for row in competitions}, key=str.casefold)
    selected_name = st.selectbox("Competition", names, key="analysis_competition")
    seasons = sorted(
        {str(row["season"]) for row in competitions if row["name"] == selected_name},
        reverse=True,
    )
    selected_season = st.selectbox("Season", seasons, key="analysis_season")
    selected = next(
        row
        for row in competitions
        if row["name"] == selected_name and str(row["season"]) == selected_season
    )
    teams = competition_teams(service.repo.connection, int(selected["id"]))
    if not teams:
        st.info("No teams appear in fixtures for the selected competition and season.")
        return None
    return selected, teams


def _team_summary_report(
    matches: list[dict[str, Any]], teams: list[dict[str, Any]]
) -> None:
    """Render the Team Summary analysis report.

    :param matches: Terminal matches for the selected competition-season.
    :param teams: Teams participating in that competition-season.
    :return: None.
    """
    # Team choices are already constrained by the cascading scope selectors.
    options = {row["name"]: int(row["id"]) for row in teams}
    label = st.selectbox("Team", list(options), key="analysis_summary_team")
    report = team_summary(matches, options[label])
    metrics = report["metrics"]
    if not metrics["matches_played"]:
        st.info("No completed, tied, or no-result matches are available for this team.")
        return
    st.caption(
        "Win percentage excludes no-results and abandoned matches. "
        "Score and rate metrics use only innings with the required data."
    )
    _analysis_metrics(
        [
            ("Matches", metrics["matches_played"], ""),
            ("Wins", metrics["wins"], ""),
            ("Losses", metrics["losses"], ""),
            ("Ties", metrics["ties"], ""),
            ("No results", metrics["no_results"], ""),
            ("Win percentage", metrics["win_percentage"], "%"),
            ("Runs scored", metrics["total_runs_scored"], ""),
            ("Runs conceded", metrics["total_runs_conceded"], ""),
            ("Average score", metrics["average_runs_scored"], ""),
            ("Average conceded", metrics["average_runs_conceded"], ""),
            ("Average wickets lost", metrics["average_wickets_lost"], ""),
            ("Average wickets taken", metrics["average_wickets_taken"], ""),
            ("Highest score", metrics["highest_team_innings"], ""),
            ("Lowest completed score", metrics["lowest_team_innings"], ""),
            ("Highest opposition score", metrics["highest_opposition_innings"], ""),
            ("Lowest opposition score", metrics["lowest_opposition_innings"], ""),
            (
                f"Average {rate_label(report['format_code']).lower()}",
                metrics["average_scoring_rate"],
                "",
            ),
            (
                f"Opposition {rate_label(report['format_code']).lower()}",
                metrics["average_opposition_scoring_rate"],
                "",
            ),
        ]
    )
    st.subheader("Batting order record")
    _analysis_metrics(
        [
            ("Wins batting first", metrics.get("won_first", 0), ""),
            ("Losses batting first", metrics.get("lost_first", 0), ""),
            ("Wins chasing", metrics.get("won_chasing", 0), ""),
            ("Losses chasing", metrics.get("lost_chasing", 0), ""),
        ]
    )
    st.subheader("Result margins")
    _analysis_metrics(
        [
            ("Largest win by runs", report["win_margins"]["largest_runs"], ""),
            ("Narrowest win by runs", report["win_margins"]["narrowest_runs"], ""),
            ("Largest win by wickets", report["win_margins"]["largest_wickets"], ""),
            (
                "Narrowest win by wickets",
                report["win_margins"]["narrowest_wickets"],
                "",
            ),
            ("Largest defeat by runs", report["defeat_margins"]["largest_runs"], ""),
            (
                "Largest defeat by wickets",
                report["defeat_margins"]["largest_wickets"],
                "",
            ),
        ]
    )
    st.subheader("Match history")
    history = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in report["history"]
    ]
    st.dataframe(pd.DataFrame(history), hide_index=True, width="stretch")


def _batting_order_report(
    matches: list[dict[str, Any]], teams: list[dict[str, Any]]
) -> None:
    """Render the Batting First vs Chasing report.

    :param matches: Terminal matches for the selected competition-season.
    :param teams: Teams participating in that competition-season.
    :return: None.
    """
    # The blank option switches cleanly between competition and team perspectives.
    options = {"All teams": None, **{row["name"]: int(row["id"]) for row in teams}}
    label = st.selectbox("Team (optional)", list(options), key="analysis_order_team")
    report = batting_order_summary(matches, options[label])
    metrics = report["competition"]
    if not metrics["completed_matches_analysed"]:
        st.info("No matches have two suitable, ordered innings for this report.")
        return
    st.caption(
        "Batting order is determined only from innings numbers. "
        "Ambiguous or incomplete innings pairs are excluded."
    )
    _analysis_metrics(
        [
            ("Matches analysed", metrics["completed_matches_analysed"], ""),
            ("Batting-first wins", metrics["batting_first_wins"], ""),
            ("Chasing wins", metrics["chasing_wins"], ""),
            ("Ties", metrics["ties"], ""),
            ("No results", metrics["no_results"], ""),
            (
                "Batting-first win percentage",
                metrics["batting_first_win_percentage"],
                "%",
            ),
            ("Chasing win percentage", metrics["chasing_win_percentage"], "%"),
            ("Average first innings", metrics["average_first_innings_score"], ""),
            ("Median first innings", metrics["median_first_innings_score"], ""),
            ("Highest first innings", metrics["highest_first_innings_score"], ""),
            (
                "Lowest completed first innings",
                metrics["lowest_completed_first_innings_score"],
                "",
            ),
            ("Highest successful chase", metrics["highest_successful_chase"], ""),
            (
                "Lowest defended total",
                metrics["lowest_successfully_defended_total"],
                "",
            ),
            (
                f"Average first-innings {rate_label(report['format_code']).lower()}",
                metrics["average_first_innings_rate"],
                "",
            ),
            (
                f"Successful-chase {rate_label(report['format_code']).lower()}",
                metrics["average_successful_chase_rate"],
                "",
            ),
            (
                f"Losing-chase {rate_label(report['format_code']).lower()}",
                metrics["average_losing_chase_rate"],
                "",
            ),
        ]
    )
    if report["team"]:
        for role, title in (("batting_first", "Batting first"), ("chasing", "Chasing")):
            role_metrics = report["team"][role]
            st.subheader(title)
            _analysis_metrics(
                [
                    ("Matches", role_metrics["matches"], ""),
                    ("Wins", role_metrics["wins"], ""),
                    ("Losses", role_metrics["losses"], ""),
                    ("Ties", role_metrics["ties"], ""),
                    ("Win percentage", role_metrics["win_percentage"], "%"),
                    ("Average score", role_metrics["average_score"], ""),
                    ("Highest score", role_metrics["highest_score"], ""),
                    (
                        "Lowest completed score",
                        role_metrics["lowest_completed_score"],
                        "",
                    ),
                    ("Lowest winning score", role_metrics["lowest_successful_score"], ""),
                    ("Largest win margin", role_metrics["largest_margin"], ""),
                    ("Narrowest win margin", role_metrics["narrowest_margin"], ""),
                ]
            )
    st.subheader("Match detail")
    st.dataframe(pd.DataFrame(report["detail"]), hide_index=True, width="stretch")


def _head_to_head_report(
    matches: list[dict[str, Any]], teams: list[dict[str, Any]]
) -> None:
    """Render the Head-to-Head report.

    :param matches: Terminal matches for the selected competition-season.
    :param teams: Teams participating in that competition-season.
    :return: None.
    """
    # Filtering the second selector prevents selecting the same team twice.
    options = {row["name"]: int(row["id"]) for row in teams}
    first_label = st.selectbox("First team", list(options), key="analysis_h2h_first")
    second_labels = [label for label in options if label != first_label]
    if not second_labels:
        st.info("At least two teams are required for head-to-head analysis.")
        return
    second_label = st.selectbox(
        "Second team", second_labels, key="analysis_h2h_second"
    )
    report = head_to_head(matches, options[first_label], options[second_label])
    if not report["matches_played"]:
        st.info("These teams have no recorded meetings in the selected season.")
        return
    st.caption(
        "Win percentages exclude no-results and abandoned matches. "
        "Run and wicket margins are reported separately."
    )
    _analysis_metrics(
        [
            ("Matches", report["matches_played"], ""),
            (f"{first_label} wins", report["first_team"]["metrics"]["wins"], ""),
            (f"{second_label} wins", report["second_team"]["metrics"]["wins"], ""),
            ("Ties", report["ties"], ""),
            ("No results", report["no_results"], ""),
            (
                f"{first_label} win percentage",
                report["first_team"]["metrics"]["win_percentage"],
                "%",
            ),
            (
                f"{second_label} win percentage",
                report["second_team"]["metrics"]["win_percentage"],
                "%",
            ),
        ]
    )
    for label, team_report in (
        (first_label, report["first_team"]),
        (second_label, report["second_team"]),
    ):
        metrics = team_report["metrics"]
        st.subheader(label)
        _analysis_metrics(
            [
                ("Runs", metrics["total_runs_scored"], ""),
                ("Average score", metrics["average_runs_scored"], ""),
                ("Average wickets lost", metrics["average_wickets_lost"], ""),
                (
                    f"Average {rate_label(report['format_code']).lower()}",
                    metrics["average_scoring_rate"],
                    "",
                ),
                ("Highest innings", metrics["highest_team_innings"], ""),
                ("Lowest completed innings", metrics["lowest_team_innings"], ""),
                ("Wins batting first", metrics.get("won_first", 0), ""),
                ("Losses batting first", metrics.get("lost_first", 0), ""),
                ("Wins chasing", metrics.get("won_chasing", 0), ""),
                ("Losses chasing", metrics.get("lost_chasing", 0), ""),
            ]
        )
    st.subheader("Notable matches")
    notable = report["notable"]
    _analysis_metrics(
        [
            ("Largest win by runs", notable["largest_runs"], ""),
            ("Narrowest result by runs", notable["narrowest_runs"], ""),
            ("Largest win by wickets", notable["largest_wickets"], ""),
            ("Narrowest result by wickets", notable["narrowest_wickets"], ""),
            ("Highest successful chase", notable["highest_successful_chase"], ""),
            (
                "Lowest defended total",
                notable["lowest_successfully_defended_total"],
                "",
            ),
            ("Highest aggregate", notable["highest_aggregate"], ""),
            ("Lowest completed aggregate", notable["lowest_aggregate"], ""),
        ]
    )
    st.subheader("Match history")
    st.dataframe(pd.DataFrame(report["history"]), hide_index=True, width="stretch")


def _analysis(service: CricketService) -> None:
    """Render all limited-overs analysis reports.

    :param service: Cricket service sharing the current database connection.
    :return: None.
    """
    st.header("Analysis")
    # Shared cascading filters keep every report on one format and season.
    scope = _analysis_scope(service)
    if scope is None:
        return
    competition, teams = scope
    matches = load_analysis_matches(service.repo.connection, int(competition["id"]))
    report_name = st.radio(
        "Report",
        ["Team Summary", "Batting First vs Chasing", "Head-to-Head"],
        horizontal=True,
        key="analysis_report",
    )
    st.caption(
        f"{competition['name']} · {competition['season']} · "
        f"{competition['match_format_name']}"
    )
    if report_name == "Team Summary":
        _team_summary_report(matches, teams)
    elif report_name == "Batting First vs Chasing":
        _batting_order_report(matches, teams)
    else:
        _head_to_head_report(matches, teams)


def _countries(service: CricketService, read_only: bool = False) -> None:
    """Render country maintenance.

    :param service: Transaction-scoped service.
    :return: None.
    """
    st.header("Countries")
    selected = _selectable_table(
        service.list_countries(),
        [("name", "Name"), ("code", "Code")],
        "country_editor",
    )
    st.caption("Select a table row to edit it, or use the blank form to add a new record.")
    st.subheader("Add or edit country")
    selected_id = selected["id"] if selected else None
    country_error_key = f"country_save_error_{selected_id or 'new'}"
    _show_persistent_error(country_error_key)
    with st.form("country"):
        name = st.text_input(
            "Name *", value=selected.get("name", "") if selected else "",
            key=f"country_name_{selected_id}",
        )
        code = st.text_input(
            "Code", value=selected.get("code") or "" if selected else "",
            key=f"country_code_{selected_id}",
        )
        save_column, delete_column, clear_column = st.columns(3)
        save_clicked = save_column.form_submit_button(
            "Save", type="primary", disabled=read_only, width="stretch"
        )
        delete_clicked = delete_column.form_submit_button(
            "Delete", disabled=selected is None or read_only, width="stretch"
        )
        clear_clicked = clear_column.form_submit_button("Clear", width="stretch")
    if save_clicked:
        _save(
            lambda: service.save_country(entity_id=selected_id, name=name, code=code),
            "Country saved.",
            service.repo.connection,
            read_only,
            error_key=country_error_key,
            on_success=_reset_country_editor,
        )
    elif delete_clicked and selected_id is not None:
        _delete(
            lambda: service.delete_country(selected_id),
            "country_editor",
            "Country deleted.",
            service.repo.connection,
            read_only,
        )
    elif clear_clicked:
        st.session_state.pop(country_error_key, None)
        _clear_editor("country_editor")


def _venues(service: CricketService, read_only: bool = False) -> None:
    """Render venue maintenance.

    :param service: Transaction-scoped service.
    :return: None.
    """
    st.header("Venues")
    country_options: dict[str, int | None] = {"Not set": None, **_options(service.list_countries())}
    rows = service.list_venues()
    selected = _selectable_table(
        rows,
        [
            ("name", "Name"), ("city", "City"), ("country_name", "Country"),
            ("capacity", "Capacity"),
        ],
        "venue_editor",
    )
    st.caption("Select a table row to edit it, or use the blank form to add a new record.")
    st.subheader("Add or edit venue")
    selected_id = selected["id"] if selected else None
    venue_error_key = f"venue_save_error_{selected_id or 'new'}"
    _show_persistent_error(venue_error_key)
    country_labels = list(country_options)
    selected_country = next(
        (
            label for label, country_id in country_options.items()
            if selected and country_id == selected.get("country_id")
        ),
        "Not set",
    )
    with st.form("venue"):
        name = st.text_input(
            "Name *", value=selected.get("name", "") if selected else "",
            key=f"venue_name_{selected_id}",
        )
        city = st.text_input(
            "City", value=selected.get("city") or "" if selected else "",
            key=f"venue_city_{selected_id}",
        )
        country = st.selectbox(
            "Country",
            country_labels,
            index=_selected_index(country_labels, selected_country),
            key=f"venue_country_{selected_id}",
        )
        capacity = st.number_input(
            "Capacity",
            value=int(selected.get("capacity") or 0) if selected else 0,
            key=f"venue_capacity_{selected_id}",
        )
        save_column, delete_column, clear_column = st.columns(3)
        save_clicked = save_column.form_submit_button(
            "Save", type="primary", disabled=read_only, width="stretch"
        )
        delete_clicked = delete_column.form_submit_button(
            "Delete", disabled=selected is None or read_only, width="stretch"
        )
        clear_clicked = clear_column.form_submit_button("Clear", width="stretch")
    if save_clicked:
        _save(
            lambda: service.save_venue(
                entity_id=selected_id,
                name=name,
                city=city,
                country_id=country_options[country],
                capacity=capacity or None,
            ),
            "Venue saved.",
            service.repo.connection,
            read_only,
            error_key=venue_error_key,
            on_success=_reset_venue_editor,
        )
    elif delete_clicked and selected_id is not None:
        _delete(
            lambda: service.delete_venue(selected_id),
            "venue_editor",
            "Venue deleted.",
            service.repo.connection,
            read_only,
        )
    elif clear_clicked:
        st.session_state.pop(venue_error_key, None)
        _clear_editor("venue_editor")


def _teams(service: CricketService, read_only: bool = False) -> None:
    """Render team maintenance.

    :param service: Transaction-scoped service.
    :return: None.
    """
    st.header("Teams")
    country_options: dict[str, int | None] = {"Not set": None, **_options(service.list_countries())}
    venue_options: dict[str, int | None] = {"Not set": None, **_options(service.list_venues())}
    gender_filter = st.selectbox("Gender", ["Men and Women", *GENDERS])
    rows = service.list_teams()
    if gender_filter in GENDERS:
        rows = [row for row in rows if row["gender"] == gender_filter]
    selected = _selectable_table(
        rows,
        [
            ("name", "Name"), ("country_name", "Country"), ("gender", "Gender"),
            ("home_venue_name", "Home venue"),
        ],
        "team_editor",
    )
    st.caption("Select a table row to edit it, or use the blank form to add a new record.")
    st.subheader("Add or edit team")
    selected_id = selected["id"] if selected else None
    team_error_key = f"team_save_error_{selected_id or 'new'}"
    _show_persistent_error(team_error_key)
    country_labels = list(country_options)
    venue_labels = list(venue_options)
    selected_country = next(
        (
            label for label, country_id in country_options.items()
            if selected and country_id == selected.get("country_id")
        ),
        "Not set",
    )
    selected_venue = next(
        (
            label for label, venue_id in venue_options.items()
            if selected and venue_id == selected.get("home_venue_id")
        ),
        "Not set",
    )
    with st.form("team"):
        name = st.text_input(
            "Name *", value=selected.get("name", "") if selected else "",
            key=f"team_name_{selected_id}",
        )
        country = st.selectbox(
            "Country",
            country_labels,
            index=_selected_index(country_labels, selected_country),
            key=f"team_country_{selected_id}",
        )
        gender = st.selectbox(
            "Gender *",
            GENDERS,
            index=_selected_index(list(GENDERS), selected.get("gender") if selected else "Men"),
            key=f"team_gender_{selected_id}",
        )
        venue = st.selectbox(
            "Home venue",
            venue_labels,
            index=_selected_index(venue_labels, selected_venue),
            key=f"team_venue_{selected_id}",
        )
        save_column, delete_column, clear_column = st.columns(3)
        save_clicked = save_column.form_submit_button(
            "Save", type="primary", disabled=read_only, width="stretch"
        )
        delete_clicked = delete_column.form_submit_button(
            "Delete", disabled=selected is None or read_only, width="stretch"
        )
        clear_clicked = clear_column.form_submit_button("Clear", width="stretch")
    if save_clicked:
        _save(
            lambda: service.save_team(
                entity_id=selected_id,
                name=name,
                gender=gender,
                country_id=country_options[country],
                home_venue_id=venue_options[venue],
            ),
            "Team saved.",
            service.repo.connection,
            read_only,
            error_key=team_error_key,
            on_success=_reset_team_editor,
        )
    elif delete_clicked and selected_id is not None:
        _delete(
            lambda: service.delete_team(selected_id),
            "team_editor",
            "Team deleted.",
            service.repo.connection,
            read_only,
        )
    elif clear_clicked:
        st.session_state.pop(team_error_key, None)
        _clear_editor("team_editor")


def _competitions(service: CricketService, read_only: bool = False) -> None:
    """Render competition maintenance.

    :param service: Transaction-scoped service.
    :return: None.
    """
    st.header("Competitions")
    country_options: dict[str, int | None] = {"Not set": None, **_options(service.list_countries())}
    ruleset_options = _options(service.list_rulesets())
    rows = service.list_competitions()
    selected = _selectable_table(
        rows,
        [
            ("name", "Name"), ("season", "Season"), ("ruleset_name", "Ruleset"),
            ("gender", "Gender"), ("format", "Format"), ("country_name", "Country"),
        ],
        "competition_editor",
    )
    st.caption("Select a table row to edit it, or use the blank form to add a new record.")
    st.subheader("Add or edit competition")
    if not ruleset_options:
        st.info("Add a ruleset before creating a competition.")
        return
    selected_id = selected["id"] if selected else None
    competition_error_key = f"competition_save_error_{selected_id or 'new'}"
    _show_persistent_error(competition_error_key)
    country_labels = list(country_options)
    ruleset_labels = list(ruleset_options)
    selected_country = next(
        (
            label for label, country_id in country_options.items()
            if selected and country_id == selected.get("country_id")
        ),
        "Not set",
    )
    selected_ruleset = next(
        (
            label for label, ruleset_id in ruleset_options.items()
            if selected and ruleset_id == selected.get("ruleset_id")
        ),
        ruleset_labels[0],
    )
    with st.form("competition"):
        name = st.text_input(
            "Name *", value=selected.get("name", "") if selected else "",
            key=f"competition_name_{selected_id}",
        )
        season = st.text_input(
            "Season *",
            value=selected.get("season", str(date.today().year))
            if selected else str(date.today().year),
            key=f"competition_year_{selected_id}",
        )
        ruleset = st.selectbox(
            "Ruleset *",
            ruleset_labels,
            index=_selected_index(ruleset_labels, selected_ruleset),
            key=f"competition_ruleset_{selected_id}",
        )
        gender = st.selectbox(
            "Gender *",
            GENDERS,
            index=_selected_index(
                list(GENDERS), selected.get("gender") if selected else "Men"
            ),
            key=f"competition_gender_{selected_id}",
        )
        format_name = st.text_input(
            "Format *",
            value=selected.get("format", "The Hundred") if selected else "The Hundred",
            key=f"competition_format_{selected_id}",
        )
        country = st.selectbox(
            "Country",
            country_labels,
            index=_selected_index(country_labels, selected_country),
            key=f"competition_country_{selected_id}",
        )
        save_column, delete_column, clear_column = st.columns(3)
        save_clicked = save_column.form_submit_button(
            "Save", type="primary", disabled=read_only, width="stretch"
        )
        delete_clicked = delete_column.form_submit_button(
            "Delete", disabled=selected is None or read_only, width="stretch"
        )
        clear_clicked = clear_column.form_submit_button("Clear", width="stretch")
    if save_clicked:
        _save(
            lambda: service.save_competition(
                entity_id=selected_id,
                name=name,
                season=season,
                ruleset_id=ruleset_options[ruleset],
                gender=gender,
                format=format_name,
                country_id=country_options[country],
            ),
            "Competition saved.",
            service.repo.connection,
            read_only,
            error_key=competition_error_key,
            on_success=_reset_competition_editor,
        )
    elif delete_clicked and selected_id is not None:
        _delete(
            lambda: service.delete_competition(selected_id),
            "competition_editor",
            "Competition deleted.",
            service.repo.connection,
            read_only,
        )
    elif clear_clicked:
        st.session_state.pop(competition_error_key, None)
        _clear_editor("competition_editor")


def _rulesets(service: CricketService, read_only: bool = False) -> None:
    """Render competition ruleset maintenance.

    :param service: Transaction-scoped service.
    :param read_only: Whether controls that mutate cricket data are disabled.
    :return: None.
    """
    st.header("Rulesets")
    rows = service.list_rulesets()
    selected = _selectable_table(
        rows,
        [
            ("name", "Name"), ("match_format_name", "Match format"),
            ("points_for_win", "Win"), ("points_for_tie", "Tie"),
            ("points_for_no_result", "No result"),
            ("points_for_abandonment", "Abandoned"),
            ("points_for_loss", "Loss"), ("has_standings", "Standings"),
            ("uses_net_run_rate", "Uses NRR"),
            ("include_knockout_matches_in_table", "Includes knockouts"),
            ("balls_per_innings", "Balls"), ("wickets_per_innings", "Wickets"),
            ("balls_per_rate_unit", "Rate unit"),
            ("combine_gender_tables", "Combined table"),
        ],
        "ruleset_editor",
    )
    st.caption("Select a table row to edit it, or use the blank form to add a new record.")
    st.subheader("Add or edit ruleset")
    selected_id = selected["id"] if selected else None
    ruleset_error_key = f"ruleset_save_error_{selected_id or 'new'}"
    _show_persistent_error(ruleset_error_key)
    # New rulesets use active formats; every seeded Phase 1 format is active.
    active_match_formats = service.list_match_formats(active_only=True)
    match_format_options = _options(active_match_formats)
    selected_match_format = next(
        (
            label for label, match_format_id in match_format_options.items()
            if selected and match_format_id == selected.get("match_format_id")
        ),
        next(iter(match_format_options)),
    )
    with st.form("ruleset"):
        name = st.text_input(
            "Name *", value=selected.get("name", "") if selected else "",
            key=f"ruleset_name_{selected_id}",
        )
        match_format = st.selectbox(
            "Match format *",
            list(match_format_options),
            index=_selected_index(
                list(match_format_options), selected_match_format
            ),
            key=f"ruleset_match_format_{selected_id}",
        )
        points = st.columns(5)
        win_points = points[0].number_input(
            "Win points",
            value=int(selected.get("points_for_win", 2)) if selected else 2,
            key=f"ruleset_win_{selected_id}",
        )
        tie_points = points[1].number_input(
            "Tie points",
            value=int(selected.get("points_for_tie", 1)) if selected else 1,
            key=f"ruleset_tie_{selected_id}",
        )
        no_result_points = points[2].number_input(
            "No-result points",
            value=int(selected.get("points_for_no_result", 1)) if selected else 1,
            key=f"ruleset_nr_{selected_id}",
        )
        abandonment_points = points[3].number_input(
            "Abandonment points",
            value=int(selected.get("points_for_abandonment", 1))
            if selected else 1,
            key=f"ruleset_abandoned_{selected_id}",
        )
        loss_points = points[4].number_input(
            "Loss points",
            value=int(selected.get("points_for_loss", 0)) if selected else 0,
            key=f"ruleset_loss_{selected_id}",
        )
        has_standings = st.checkbox(
            "Provide a standings table",
            value=bool(selected.get("has_standings", 1)) if selected else True,
            key=f"ruleset_has_standings_{selected_id}",
        )
        use_nrr = st.checkbox(
            "Use net run rate",
            value=bool(selected.get("uses_net_run_rate", 1)) if selected else True,
            disabled=not has_standings,
            key=f"ruleset_nrr_{selected_id}",
        )
        include_knockouts = st.checkbox(
            "Include knockout matches in table",
            value=bool(selected.get("include_knockout_matches_in_table", 0))
            if selected else False,
            key=f"ruleset_knockouts_{selected_id}",
        )
        combine_genders = st.checkbox(
            "Provide combined gender table",
            value=bool(selected.get("combine_gender_tables", 0))
            if selected else False,
            key=f"ruleset_combined_{selected_id}",
        )
        outcome_options = st.columns(3)
        ties_may_stand = outcome_options[0].checkbox(
            "Ties may stand",
            value=bool(selected.get("ties_may_stand", 1)) if selected else True,
            key=f"ruleset_ties_stand_{selected_id}",
        )
        tie_break_winner_allowed = outcome_options[1].checkbox(
            "Allow tie-break winner",
            value=bool(selected.get("tie_break_winner_allowed", 1))
            if selected else True,
            key=f"ruleset_tie_break_{selected_id}",
        )
        revised_targets_allowed = outcome_options[2].checkbox(
            "Allow revised targets",
            value=bool(selected.get("revised_targets_allowed", 1))
            if selected else True,
            key=f"ruleset_revised_targets_{selected_id}",
        )
        allocation = st.columns(3)
        balls = allocation[0].number_input(
            "Balls per innings",
            value=int(selected.get("balls_per_innings", 100)) if selected else 100,
            key=f"ruleset_balls_{selected_id}",
        )
        wickets = allocation[1].number_input(
            "Wickets per innings",
            value=int(selected.get("wickets_per_innings", 10)) if selected else 10,
            key=f"ruleset_wickets_{selected_id}",
        )
        rate_unit = allocation[2].number_input(
            "Balls per rate unit",
            value=int(selected.get("balls_per_rate_unit", 6)) if selected else 6,
            key=f"ruleset_rate_unit_{selected_id}",
        )
        sort_order = st.text_input(
            "Table sort order *",
            value=selected.get("table_sort_order", "points,net_run_rate,wins")
            if selected else "points,net_run_rate,wins",
            key=f"ruleset_sort_{selected_id}",
        )
        save_column, delete_column, clear_column = st.columns(3)
        save_clicked = save_column.form_submit_button(
            "Save", type="primary", disabled=read_only, width="stretch"
        )
        delete_clicked = delete_column.form_submit_button(
            "Delete", disabled=selected is None or read_only, width="stretch"
        )
        clear_clicked = clear_column.form_submit_button("Clear", width="stretch")
    if save_clicked:
        _save(
            lambda: service.save_ruleset(
                entity_id=selected_id,
                name=name,
                match_format_id=match_format_options[match_format],
                points_for_win=win_points,
                points_for_tie=tie_points,
                points_for_no_result=no_result_points,
                points_for_abandonment=abandonment_points,
                points_for_loss=loss_points,
                has_standings=has_standings,
                uses_net_run_rate=use_nrr,
                include_knockout_matches_in_table=include_knockouts,
                combine_gender_tables=combine_genders,
                ties_may_stand=ties_may_stand,
                tie_break_winner_allowed=tie_break_winner_allowed,
                revised_targets_allowed=revised_targets_allowed,
                balls_per_innings=balls,
                wickets_per_innings=wickets,
                balls_per_rate_unit=rate_unit,
                table_sort_order=sort_order,
            ),
            "Ruleset saved.",
            service.repo.connection,
            read_only,
            error_key=ruleset_error_key,
        )
    elif delete_clicked and selected_id is not None:
        _delete(
            lambda: service.delete_ruleset(selected_id),
            "ruleset_editor",
            "Ruleset deleted.",
            service.repo.connection,
            read_only,
        )
    elif clear_clicked:
        st.session_state.pop(ruleset_error_key, None)
        _clear_editor("ruleset_editor")


def _reset_import_upload() -> None:
    """Reset the CSV uploader after the selected dataset changes.

    :return: None.
    """
    st.session_state["import_upload_generation"] = (
        st.session_state.get("import_upload_generation", 0) + 1
    )


def _reset_export_file_stem() -> None:
    """Reset the export file stem to the newly selected dataset.

    :return: None.
    """
    # Dataset changes intentionally replace any custom stem entered for the prior export.
    st.session_state["export_file_stem"] = st.session_state.get("export", "")


def _csv_import(service: CricketService, read_only: bool = False) -> None:
    """Render CSV import controls.

    :param service: Transaction-scoped service.
    :return: None.
    """
    st.header("CSV Import")
    dataset = st.selectbox(
        "Dataset",
        DATASETS,
        key="import_dataset",
        on_change=_reset_import_upload,
    )
    upload_generation = st.session_state.get("import_upload_generation", 0)
    upload = st.file_uploader(
        "CSV file",
        type="csv",
        key=f"import_upload_{upload_generation}",
        disabled=read_only,
    )
    if upload and st.button("Import CSV", disabled=read_only):
        result = CricketImporter(service.repo.connection).import_csv(dataset, upload.getvalue())
        service.repo.connection.commit()
        st.success(f"Imported {result.imported}; skipped {result.skipped}.")
        for error in result.errors:
            st.error(error)


def _csv_export(service: CricketService) -> None:
    """Render CSV export controls.

    :param service: Transaction-scoped service.
    :return: None.
    """
    st.header("CSV Export")
    dataset = st.selectbox(
        "Dataset",
        DATASETS,
        key="export",
        on_change=_reset_export_file_stem,
    )
    competitions = {
        "All competitions": None,
        **{
            f"{row['name']} — {row['season']}": int(row["id"])
            for row in service.list_competitions()
        },
    }
    competition_label = st.selectbox(
        "Competition",
        competitions,
        key="export_competition",
    )
    competition_id = competitions[competition_label]
    if "export_file_stem" not in st.session_state:
        # The first visit defaults to the selected dataset before rendering the text box.
        st.session_state["export_file_stem"] = dataset
    file_stem = st.text_input(
        "File stem",
        key="export_file_stem",
    )
    file_name = f"{file_stem}.csv"
    st.download_button(
        "Download CSV",
        export_csv(service.repo.connection, dataset, competition_id),
        file_name=file_name,
        mime="text/csv",
    )


def _main_navigation() -> str:
    """Render the primary navigation as a main-panel tab strip.

    :return: Label of the selected application page.
    """
    page_labels = [
        "Analysis",
        "League Table",
        "Matches",
        "Competitions",
        "Teams",
        "Venues",
        "Countries",
        "Rulesets",
        "CSV Import",
        "CSV Export",
    ]
    # Style Streamlit's horizontal radio as the tab strip used by the tracker family.
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"],
        [data-testid="collapsedControl"] {
            display: none;
        }
        .st-key-main_navigation,
        .st-key-main_navigation [data-testid="stRadio"],
        .st-key-main_navigation [data-testid="stRadioGroup"] {
            width: 100% !important;
        }
        div[role="radiogroup"] {
            display: flex;
            gap: 0;
            width: 100%;
            border-bottom: 1px solid rgba(49, 51, 63, 0.2);
            margin: 0 0 1.5rem;
        }
        div[role="radiogroup"] > label {
            flex: 1 1 auto;
            justify-content: center;
            padding: 0.9rem 0.75rem;
            margin: 0;
            border-bottom: 3px solid transparent;
            border-radius: 0.45rem 0.45rem 0 0;
            cursor: pointer;
            white-space: nowrap;
        }
        div[role="radiogroup"] > label:hover {
            background: #f3f3f3;
        }
        div[role="radiogroup"] > label:has(input:checked) {
            color: inherit;
            background: #eeeeee;
            border-bottom-color: #ff4b4b;
            font-weight: 400;
        }
        div[role="radiogroup"] input[type="radio"],
        div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child,
        div[role="radiogroup"] label[data-baseweb="radio"] > span:first-child,
        [data-testid="stRadioOption"] > div > div > div:first-child {
            display: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    return st.radio(
        "Navigation",
        page_labels,
        horizontal=True,
        label_visibility="collapsed",
        key="main_navigation",
    )


def run() -> None:
    """Run the Cricket Tracker Streamlit application.

    :return: None.
    """
    st.set_page_config(
        page_title="Cricket Tracker",
        page_icon="🏏",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    read_only = _is_read_only_request()
    apply_migrations()
    connection = connect()
    service = CricketService(connection)
    st.title(f"🏏 Cricket Tracker v{application_version()}")
    if read_only:
        st.info(
            "Browse-only mode: this hosted application does not allow saving, "
            "deleting, or importing data."
        )
    # Show confirmations queued immediately before the preceding rerun.
    _show_pending_success()
    page = _main_navigation()
    try:
        pages = {
            "League Table": _standings,
            "Analysis": _analysis,
            "Matches": _matches,
            "Competitions": _competitions,
            "Teams": _teams,
            "Venues": _venues,
            "Countries": _countries,
            "Rulesets": _rulesets,
            "CSV Import": _csv_import,
            "CSV Export": _csv_export,
        }
        if page in {
            "Matches",
            "Competitions",
            "Teams",
            "Venues",
            "Countries",
            "Rulesets",
            "CSV Import",
        }:
            pages[page](service, read_only)
        else:
            pages[page](service)
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    run()
