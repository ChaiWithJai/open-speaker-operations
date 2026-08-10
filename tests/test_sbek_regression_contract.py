"""Auditable ownership contract for the SessionBoard Eval Kit rubric.

The authoritative inventory is SBEK commit d99935c3, specs/01..07. This file
intentionally does not pretend that a Django test replaces browser or manual
evidence. Every direct claim names a real pytest node; everything else remains
owned by the browser/manual evidence stage.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]

AREA_COUNTS = {
    "CFP": 16,
    "ABS": 14,
    "SPK": 16,
    "CNT": 14,
    "AIA": 8,
    "EMB": 16,
    "CRM": 12,
}
OPTIONAL_AREAS = {"CRM"}


def _ids(prefix, count):
    return {f"{prefix}-{number:02d}" for number in range(1, count + 1)}


ALL_CRITERIA = set().union(*(_ids(prefix, count) for prefix, count in AREA_COUNTS.items()))
MANDATORY_CRITERIA = {
    criterion for criterion in ALL_CRITERIA if criterion.split("-", 1)[0] not in OPTIONAL_AREAS
}

# Existing integration tests that directly exercise the essential server-side
# behavior. Repeated nodes are intentional when one end-to-end test proves a
# tightly related group of rubric rules.
DIRECT_EVIDENCE = {
    "CFP-01": (
        "tests/test_cfp_evaluation_fields.py",
        "test_organizer_builder_fields_render_and_validate_on_public_form",
    ),
    "CFP-02": (
        "tests/test_cfp_evaluation_fields.py",
        "test_workshop_prerequisites_render_only_for_workshops_and_are_required",
    ),
    "CFP-04": ("tests/test_cfp.py", "test_cfp_close_date_blocks_new_submission_and_existing_edit"),
    "CFP-06": (
        "tests/test_cfp.py",
        "test_seeded_cfp_renders_accepts_all_p0_field_types_and_resumes_draft",
    ),
    "CFP-07": (
        "tests/test_cfp.py",
        "test_seeded_cfp_renders_accepts_all_p0_field_types_and_resumes_draft",
    ),
    "CFP-10": (
        "tests/test_cfp_reviewer_provisioning.py",
        "test_reviewer_invite_creates_usable_scoped_account",
    ),
    "CFP-11": (
        "tests/test_screens.py",
        "test_reviewer_screen_saves_scores_comments_and_recommendation",
    ),
    "CFP-12": (
        "tests/test_program_decisions.py",
        "test_explicit_wave_release_applies_staged_acceptance",
    ),
    "CFP-13": (
        "tests/test_program_decisions.py",
        "test_applied_decisions_reach_speaker_dashboard_and_native_mail_history",
    ),
    "CFP-15": (
        "tests/test_program_decisions.py",
        "test_acceptance_handoff_preserves_metadata_in_wip_agenda",
    ),
    "CFP-16": ("tests/test_cfp.py", "test_cfp_close_date_blocks_new_submission_and_existing_edit"),
    "ABS-01": (
        "tests/test_abstract_management.py",
        "test_rounds_persist_distinct_dates_scorecards_and_pools",
    ),
    "ABS-02": (
        "tests/test_abstract_management.py",
        "test_rounds_persist_distinct_dates_scorecards_and_pools",
    ),
    "ABS-03": (
        "tests/test_abstract_management.py",
        "test_mixed_scorecard_roundtrip_weighted_aggregate_sort_and_csv",
    ),
    "ABS-04": (
        "tests/test_abstract_management.py",
        "test_mixed_scorecard_roundtrip_weighted_aggregate_sort_and_csv",
    ),
    "ABS-05": (
        "tests/test_abstract_management.py",
        "test_exact_assignments_cap_progress_reminder_and_reviewer_isolation",
    ),
    "ABS-06": (
        "tests/test_abstract_management.py",
        "test_exact_assignments_cap_progress_reminder_and_reviewer_isolation",
    ),
    "ABS-07": (
        "tests/test_abstract_management.py",
        "test_exact_assignments_cap_progress_reminder_and_reviewer_isolation",
    ),
    "ABS-08": (
        "tests/test_abstract_management.py",
        "test_exact_assignments_cap_progress_reminder_and_reviewer_isolation",
    ),
    "ABS-09": (
        "tests/test_abstract_management.py",
        "test_exact_assignments_cap_progress_reminder_and_reviewer_isolation",
    ),
    "ABS-10": (
        "tests/test_abstract_management.py",
        "test_mixed_scorecard_roundtrip_weighted_aggregate_sort_and_csv",
    ),
    "ABS-11": (
        "tests/test_presenter_roles.py",
        "test_presenter_roles_survive_reload_and_render_for_speaker_and_organizer",
    ),
    "ABS-12": ("tests/test_abstract_management.py", "test_recusal_is_scoped_and_auditable"),
    "ABS-13": (
        "tests/test_abstract_management.py",
        "test_mixed_scorecard_roundtrip_weighted_aggregate_sort_and_csv",
    ),
    "SPK-02": (
        "tests/test_speaker_operations.py",
        "test_spk02_single_speaker_profile_crud_is_event_scoped",
    ),
    "SPK-03": (
        "tests/test_speaker_operations.py",
        "test_csv_speaker_import_previews_maps_validates_and_persists",
    ),
    "SPK-04": (
        "tests/test_speaker_operations.py",
        "test_workflow_logistics_filters_and_multi_speaker_action_roundtrip",
    ),
    "SPK-05": (
        "tests/test_speaker_operations.py",
        "test_workflow_logistics_filters_and_multi_speaker_action_roundtrip",
    ),
    "SPK-06": (
        "tests/test_speaker_operations.py",
        "test_spk06_spk11_invitation_is_sent_logged_and_assignments_show_in_both_views",
    ),
    "SPK-07": ("tests/test_onboarding_operations.py", "test_roles_are_scoped_to_surfaces"),
    "SPK-08": (
        "tests/test_speaker_operations.py",
        "test_speaker_portal_profile_roundtrips_to_organizer",
    ),
    "SPK-09": ("tests/test_onboarding_operations.py", "test_completion_uses_executor_and_evidence"),
    "SPK-10": (
        "tests/test_content_operations.py",
        "test_organiser_download_comments_and_latest_version_zip_are_scoped",
    ),
    "SPK-11": (
        "tests/test_speaker_operations.py",
        "test_spk06_spk11_invitation_is_sent_logged_and_assignments_show_in_both_views",
    ),
    "SPK-13": (
        "tests/test_speaker_operations.py",
        "test_spk13_spk14_selected_bulk_email_previews_personalizes_and_logs_each_outcome",
    ),
    "SPK-14": (
        "tests/test_speaker_operations.py",
        "test_spk13_spk14_selected_bulk_email_previews_personalizes_and_logs_each_outcome",
    ),
    "SPK-15": (
        "tests/test_speaker_operations.py",
        "test_workflow_logistics_filters_and_multi_speaker_action_roundtrip",
    ),
    "CNT-01": (
        "tests/test_content_operations.py",
        "test_organiser_creates_file_request_and_assigns_multiple_speakers",
    ),
    "CNT-02": (
        "tests/test_uploads.py",
        "test_validated_uploads_complete_through_http",
    ),
    "CNT-03": (
        "tests/test_content_operations.py",
        "test_speaker_cannot_comment_on_another_speakers_file",
    ),
    "CNT-04": (
        "tests/test_uploads.py",
        "test_replacement_upload_keeps_version_history_and_is_retry_safe",
    ),
    "CNT-05": (
        "tests/test_content_operations.py",
        "test_organiser_download_comments_and_latest_version_zip_are_scoped",
    ),
    "CNT-06": (
        "tests/test_uploads.py",
        "test_upload_ui_explains_recovery_and_completed_file_identity",
    ),
    "CNT-08": (
        "tests/test_onboarding_operations.py",
        "test_bulk_reminder_targets_selected_outstanding_deliverables",
    ),
    "CNT-09": (
        "tests/test_content_operations.py",
        "test_session_and_speaker_edits_are_attributed_and_restorable",
    ),
    "CNT-10": (
        "tests/test_content_operations.py",
        "test_session_and_speaker_edits_are_attributed_and_restorable",
    ),
    "CNT-11": (
        "tests/test_content_operations.py",
        "test_session_restore_removes_second_edit_but_keeps_first",
    ),
    "CNT-12": (
        "tests/test_content_operations.py",
        "test_explicit_session_approval_controls_public_widgets",
    ),
    "CNT-14": (
        "tests/test_content_operations.py",
        "test_organiser_download_comments_and_latest_version_zip_are_scoped",
    ),
    "AIA-02": (
        "tests/test_conflict_resolution.py",
        "test_organizer_creates_rooms_and_tracks_from_agenda_setup",
    ),
    "AIA-03": (
        "tests/test_conflict_resolution.py",
        "test_assisted_agenda_previews_then_applies_conflict_free_plan",
    ),
    "AIA-04": (
        "tests/test_conflict_resolution.py",
        "test_conflict_rows_name_context_and_link_native_editors",
    ),
    "AIA-05": (
        "tests/test_conflict_resolution.py",
        "test_conflict_rows_name_context_and_link_native_editors",
    ),
    "AIA-06": (
        "tests/test_conflict_resolution.py",
        "test_return_to_gate_reports_cleared_conflict",
    ),
    "AIA-07": (
        "tests/test_schedule_publication.py",
        "test_successful_release_hands_exact_schedule_to_public_agenda",
    ),
    "AIA-08": (
        "tests/test_conflict_resolution.py",
        "test_assisted_agenda_previews_then_applies_conflict_free_plan",
    ),
    "EMB-02": (
        "tests/test_public_widgets.py",
        "test_sessions_widget_server_filters_title_speaker_track_format_and_room",
    ),
    "EMB-03": (
        "tests/test_public_widgets.py",
        "test_sessions_widget_server_filters_title_speaker_track_format_and_room",
    ),
    "EMB-05": (
        "tests/test_public_widgets.py",
        "test_rich_session_search_and_speaker_detail_use_public_released_data",
    ),
    "EMB-07": (
        "tests/test_public_widgets.py",
        "test_agenda_day_query_selects_exact_initial_tab_and_panel",
    ),
    "EMB-09": (
        "tests/test_public_widgets.py",
        "test_itinerary_is_grouped_and_server_navigable_by_day",
    ),
    "EMB-11": (
        "tests/test_public_widgets.py",
        "test_selected_calendar_exports_only_released_requested_sessions",
    ),
    "EMB-14": (
        "tests/test_public_widgets.py",
        "test_five_public_widget_modes_are_released_only_and_cross_origin",
    ),
    "EMB-15": (
        "tests/test_public_widgets.py",
        "test_embed_builder_is_organizer_only_and_exposes_required_controls",
    ),
    "EMB-16": (
        "tests/test_schedule_publication.py",
        "test_successful_release_hands_exact_schedule_to_public_agenda",
    ),
    "CRM-01": (
        "tests/test_crm.py",
        "test_crm_contact_filters_pipeline_handoff_and_outreach_round_trip",
    ),
    "CRM-02": (
        "tests/test_crm.py",
        "test_crm_contact_filters_pipeline_handoff_and_outreach_round_trip",
    ),
    "CRM-03": (
        "tests/test_crm.py",
        "test_crm_contact_filters_pipeline_handoff_and_outreach_round_trip",
    ),
    "CRM-04": (
        "tests/test_crm.py",
        "test_crm_contact_filters_pipeline_handoff_and_outreach_round_trip",
    ),
    "CRM-05": (
        "tests/test_crm.py",
        "test_crm_csv_validation_explicit_merge_and_organiser_isolation",
    ),
    "CRM-06": (
        "tests/test_crm.py",
        "test_crm_csv_validation_explicit_merge_and_organiser_isolation",
    ),
    "CRM-07": (
        "tests/test_crm.py",
        "test_crm_contact_filters_pipeline_handoff_and_outreach_round_trip",
    ),
    "CRM-08": (
        "tests/test_crm.py",
        "test_crm_contact_filters_pipeline_handoff_and_outreach_round_trip",
    ),
    "CRM-09": (
        "tests/test_crm.py",
        "test_crm_contact_filters_pipeline_handoff_and_outreach_round_trip",
    ),
    "CRM-10": (
        "tests/test_crm.py",
        "test_crm_contact_filters_pipeline_handoff_and_outreach_round_trip",
    ),
    "CRM-11": (
        "tests/test_crm.py",
        "test_crm_contact_filters_pipeline_handoff_and_outreach_round_trip",
    ),
}

# A pytest node proves only the behavior that it actually asserts. Criteria
# whose rubric also requires browser state, multi-role UI evidence, reloads, or
# a real side effect stay partial even when useful server coverage exists.
DIRECT_PARTIAL = {
    "CFP-06",
    "CFP-07",
    "CFP-11",
    "CFP-12",
    "ABS-07",
    "ABS-09",
    "ABS-13",
    "SPK-06",
    "SPK-07",
    "SPK-10",
    "SPK-13",
    "CNT-08",
    "CNT-14",
    "AIA-03",
    "EMB-07",
    "EMB-09",
    "EMB-11",
    "EMB-15",
    "EMB-16",
    "CRM-03",
    "CRM-06",
    "CRM-07",
    "CRM-08",
    "CRM-09",
    "CRM-11",
}
DIRECT_FULL = set(DIRECT_EVIDENCE) - DIRECT_PARTIAL
MANUAL_REQUIRED = {"CFP-08", "SPK-16"}
CONDITIONAL = {"ABS-14"}  # AI triage is graded only when the product claims it.
BROWSER_REQUIRED = ALL_CRITERIA - DIRECT_FULL - DIRECT_PARTIAL - MANUAL_REQUIRED - CONDITIONAL

# Manual criteria may still have deterministic supporting coverage. This node
# proves scheduling/idempotency, not that a message reached a real inbox.
SUPPORTING_EVIDENCE = {
    "SPK-16": (
        "tests/test_speaker_operations.py",
        "test_scheduled_reminder_worker_handles_general_tasks_and_is_daily_idempotent",
    ),
}


def _node_id(evidence):
    return "::".join(evidence)


EVIDENCE_MANIFEST = {
    criterion: _node_id(evidence)
    for criterion, evidence in sorted({**DIRECT_EVIDENCE, **SUPPORTING_EVIDENCE}.items())
}

CLASSIFICATION_BY_CRITERION = {
    criterion: classification
    for classification, criteria in (
        ("DIRECT_FULL", DIRECT_FULL),
        ("DIRECT_PARTIAL", DIRECT_PARTIAL),
        ("BROWSER_REQUIRED", BROWSER_REQUIRED),
        ("MANUAL_REQUIRED", MANUAL_REQUIRED),
        ("CONDITIONAL", CONDITIONAL),
    )
    for criterion in sorted(criteria)
}

AREA_OWNERS = {
    "CFP": (
        "tests/test_cfp.py",
        "tests/test_cfp_evaluation_fields.py",
        "tests/test_cfp_reviewer_provisioning.py",
        "tests/test_cfp_routing.py",
        "tests/test_program_decisions.py",
    ),
    "ABS": ("tests/test_abstract_management.py", "tests/test_presenter_roles.py"),
    "SPK": (
        "tests/test_speaker_operations.py",
        "tests/test_onboarding_operations.py",
        "tests/test_uploads.py",
    ),
    "CNT": ("tests/test_content_operations.py", "tests/test_uploads.py"),
    "AIA": ("tests/test_conflict_resolution.py", "tests/test_schedule_publication.py"),
    "EMB": ("tests/test_public_widgets.py",),
    "CRM": ("tests/test_crm.py", "tests/test_conference_memory.py"),
}


def test_sbek_authoritative_inventory_is_complete_and_unique():
    assert len(ALL_CRITERIA) == 96
    assert len(MANDATORY_CRITERIA) == 84
    classifications = (
        DIRECT_FULL,
        DIRECT_PARTIAL,
        BROWSER_REQUIRED,
        MANUAL_REQUIRED,
        CONDITIONAL,
    )
    assert set().union(*classifications) == ALL_CRITERIA
    for index, classification in enumerate(classifications):
        later = classifications[index + 1 :]
        if later:
            assert not classification & set().union(*later)
    assert set(DIRECT_EVIDENCE) == DIRECT_FULL | DIRECT_PARTIAL
    assert set(SUPPORTING_EVIDENCE) <= MANUAL_REQUIRED
    assert set(CLASSIFICATION_BY_CRITERION) == ALL_CRITERIA


def test_known_partial_and_manual_criteria_are_not_overpromoted():
    assert {"CFP-06", "CFP-07", "CFP-11", "CFP-12", "EMB-09"} <= DIRECT_PARTIAL
    assert "SPK-16" in MANUAL_REQUIRED
    assert not ({"CFP-06", "CFP-07", "CFP-11", "CFP-12", "SPK-16", "EMB-09"} & DIRECT_FULL)


def test_every_sbek_area_has_repository_regression_owners():
    assert set(AREA_OWNERS) == set(AREA_COUNTS)
    for paths in AREA_OWNERS.values():
        assert paths
        for path in paths:
            assert (ROOT / path).is_file(), path


def test_evidence_manifest_is_deterministic_and_collectable_by_pytest():
    assert list(EVIDENCE_MANIFEST) == sorted(EVIDENCE_MANIFEST)
    requested = sorted(set(EVIDENCE_MANIFEST.values()))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *requested],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    collected = {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("tests/") and "::" in line
    }
    missing = {
        node_id
        for node_id in requested
        if not any(
            collected_id == node_id or collected_id.startswith(f"{node_id}[")
            for collected_id in collected
        )
    }
    assert not missing, f"pytest did not collect mapped nodes: {sorted(missing)}"


def test_issue_41_differentiator_has_owned_regressions():
    required = {
        "tests/test_conference_memory.py",
        "tests/test_history_coverage.py",
        "tests/test_history_sources.py",
        "tests/test_crm.py",
        "tests/test_operations_contract.py",
    }
    assert all((ROOT / path).is_file() for path in required)
