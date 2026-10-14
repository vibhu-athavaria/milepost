# milepost Build Plan

Companion to SPEC.md. Each milestone lists the work, the test functions to write first (TDD), and acceptance criteria. Test names follow `test_<what>_when_<condition>_then_<expected>`.

## Status

| Milestone | State |
|---|---|
| M0 to M6, M5a | Done, on `main` |
| M7 Drafting, init, doctor, `.env` | Done, on `main` |
| M8 Review, rehash, hooks, merge driver | Done, on `main` |
| M8a Computed context (outline, impact, sync, L1 purpose) | Done, on `main` |
| M8b Human visibility (status, report, churn, CODEOWNERS) | Done, on `main` |
| M9 MCP server | Done, on `main`. Agent-mode drafting deferred |
| M10 Claude Code plugin | Built, on `main`. The manual test in a live Claude Code session is still to do, so it is not called done |
| M11 Pilot and release | **Not started**. Needs the pass rule agreed first |

Each milestone below was reviewed with the code-review skill before it was merged; fixes are in the commit "Address code review findings" on each PR.

Rules for implementers:
- Write the named tests first, see them fail, then implement.
- A milestone is done only when its acceptance criteria are verified by running the commands, not by inspection.
- Do not add `# type: ignore`. Keep `mypy --strict` clean.
- Imports at file top. No inline imports except the lazy ones listed in SPEC section 13.

Test file paths are under `tests/`. Fixtures are under `tests/fixtures/`.

---

## M0. Project skeleton

Work:
- `pyproject.toml` with `[project.scripts] milepost = "milepost.cli:app"`, Python `>=3.12`, dependencies from SPEC section 13.
- Empty package layout from SPEC section 15.
- `ruff`, `mypy --strict`, `pytest` configured. CI workflow runs all three.
- `LICENSE` (Apache-2.0), `README.md` stub.

Tests (`tests/unit/test_cli_smoke.py`):
- `test_cli_help_when_invoked_then_lists_all_commands`
- `test_cli_version_when_invoked_then_prints_package_version`

Acceptance:
- `uv run milepost --help` lists every command in SPEC section 8 (stubs allowed).
- `uv run pytest`, `uv run ruff check`, `uv run mypy milepost` all pass.

---

## M1. Config and validation

Files: `milepost/config.py`, `tests/unit/test_config.py`, `tests/fixtures/config/*.toml`.

Tests:
- `test_load_config_when_valid_file_then_returns_models`
- `test_load_config_when_module_id_uppercase_then_raises_invalid_config`
- `test_load_config_when_sources_empty_then_raises_invalid_config`
- `test_load_config_when_glob_absolute_then_raises_invalid_config`
- `test_load_config_when_glob_contains_parent_ref_then_raises_invalid_config`
- `test_load_config_when_related_unknown_module_then_raises_invalid_config`
- `test_load_config_when_backend_not_sqlite_then_raises_invalid_config`
- `test_load_config_when_embedding_dim_zero_then_raises_invalid_config`
- `test_load_config_when_structure_root_absolute_then_raises_invalid_config`
- `test_load_config_when_roots_omitted_then_defaults_applied`
- `test_load_config_when_max_detail_notes_negative_then_raises_invalid_config`
- `test_load_config_when_missing_file_then_raises_config_not_found`
- `test_resolve_model_when_env_unset_then_raises_with_variable_name`

Acceptance:
- CLI exits 2 with the field path in the message for each invalid case.

---

## M2. Notes: parse, validate, write

Files: `milepost/core/notes.py`, `tests/unit/test_notes.py`.

Tests:
- `test_parse_note_when_valid_frontmatter_then_returns_note`
- `test_parse_note_when_no_frontmatter_then_raises_note_invalid`
- `test_parse_note_when_yaml_malformed_then_raises_note_invalid`
- `test_validate_note_when_kb_schema_not_one_then_reports_error`
- `test_validate_note_when_status_unknown_then_reports_error`
- `test_validate_note_when_id_mismatches_path_then_reports_error`
- `test_validate_note_when_source_hash_conflict_then_reports_conflict_code`
- `test_write_note_when_round_trip_then_frontmatter_and_body_unchanged`
- `test_write_note_when_keys_written_then_order_is_stable`

Acceptance:
- Writing then parsing a note returns identical data; writing twice produces byte-identical files.

---

## M3. Source hash

Files: `milepost/core/hashing.py`, `milepost/core/glob.py`, `tests/unit/test_hashing.py`, `tests/integration/test_hash_stability.py`.

Tests:
- `test_source_hash_when_same_content_then_same_hash_on_repeat_runs`
- `test_source_hash_when_crlf_and_lf_then_same_hash`
- `test_source_hash_when_file_added_then_hash_changes`
- `test_source_hash_when_file_order_differs_then_hash_same`
- `test_source_hash_when_no_files_match_then_returns_empty_digest_and_warns`
- `test_source_hash_when_ignore_pattern_matches_then_file_excluded`
- `test_source_hash_when_binary_file_then_no_newline_normalization`
- `test_source_hash_when_symlink_then_hashes_target_content_under_link_name`
- `test_source_hash_when_trailing_whitespace_changed_then_hash_changes`

Acceptance:
- A fixed fixture repo produces a hard-coded expected hash (store the expected value in the test; regenerate only with an explicit flag and a commit note).
- Same fixture on Linux and macOS produces the same hash (CI matrix).

---

## M4. Structure scanner

Files: `milepost/structure/python_scanner.py`, `milepost/structure/tree_sitter_scanner.py`, `tests/unit/test_scanners.py`.

Tests:
- `test_python_scanner_when_import_statements_then_returns_module_edges`
- `test_python_scanner_when_relative_import_then_resolves_to_repo_path`
- `test_python_scanner_when_syntax_error_then_reports_file_and_continues`
- `test_ts_scanner_when_import_from_then_returns_module_edges`
- `test_ts_scanner_when_dynamic_import_then_marks_edge_unresolved`
- `test_scan_candidates_when_app_directory_then_proposes_module_per_subdirectory`
- `test_scan_candidates_when_candidates_proposed_then_none_marked_active`
- `test_scan_command_when_run_after_init_then_lists_only_undeclared_candidates`
- `test_scan_command_when_run_then_config_file_unchanged`

Acceptance:
- Scanning `tests/fixtures/sample_repo` returns the expected edges (fixture committed).

---

## M5. Check command

Files: `milepost/services/check.py`, `milepost/services/render.py`, `milepost/services/coverage.py`, `milepost/cli.py` (wiring), `tests/unit/test_check.py`, `tests/unit/test_coverage.py`, `tests/integration/test_check_cli.py`.

Tests:
- `test_check_when_note_hash_matches_then_no_findings`
- `test_check_when_source_changed_then_reports_stale_with_note_id`
- `test_check_when_module_has_no_note_then_reports_warning_not_failure`
- `test_check_when_index_md_drifted_then_reports_failure`
- `test_check_when_source_hash_conflict_then_reports_failure_with_rehash_hint`
- `test_check_when_fail_on_none_then_exit_zero_despite_stale`
- `test_check_ci_when_changed_source_has_stale_note_then_fails`
- `test_check_ci_when_waiver_trailer_present_then_downgrades_to_warning`
- `test_check_ci_when_waiver_without_reason_then_exit_two`
- `test_check_cli_when_json_format_then_output_parses_and_matches_findings`
- `test_check_cli_when_config_invalid_then_exit_two`
- `test_check_when_dir_under_root_matches_no_module_then_warns_uncovered_dir`
- `test_check_when_dir_covered_by_module_then_no_uncovered_warning`
- `test_check_when_l3_sources_match_no_files_then_warns_orphan_note`
- `test_check_ci_when_new_source_dir_uncovered_in_range_then_fails`
- `test_check_ci_when_uncovered_dir_predates_range_then_warning_only`
- `test_check_ci_when_dir_waiver_trailer_present_then_downgrades_uncovered_dir`
- `test_check_ci_when_l3_source_deleted_in_range_then_fails_orphan_note`
- `test_check_when_declared_module_has_no_note_then_still_warning_in_ci`
- `test_check_when_l3_and_l4_count_over_max_then_warns_detail_note_count`
- `test_check_when_l3_and_l4_count_at_max_then_no_warning`

Acceptance:
- Running `milepost check` twice on an unchanged repo gives identical output.
- Integration test runs against a real git repo created in a temp directory, with real commits and trailers.

---

## M5a. Baseline measurement (go/no-go gate)

This milestone needs no milepost code and can start at any time. M6 does not start until it is done, because everything from M6 on is only worth building if the measurement later shows an improvement.

Work:
- Pilot repository: a real repository the maintainer owns (its name and data are kept outside this repository).
- Pick five representative tasks (a feature, a bugfix, a cross-module change, a question about existing behavior, a refactor). Write each as a fixed prompt, kept with the private baseline data (see `PILOT.md` for the protocol).
- Run each with the coding agent and no milepost. Record files read, tokens used, and whether the task outcome was acceptable.

Acceptance:
- The five prompts and the baseline numbers are recorded (privately, outside this repository) before any M6 work; `PILOT.md` holds the public protocol.
- The prompts are frozen: M11 reruns exactly these.

---

## M6. Index and search

Files: `milepost/store/base.py`, `milepost/store/sqlite_store.py`, `milepost/services/index.py`, `milepost/services/search.py`, `tests/unit/test_chunking.py`, `tests/integration/test_index_search.py`.

Tests:
- `test_chunk_note_when_split_on_headings_then_one_chunk_per_section`
- `test_chunk_note_when_section_over_2000_chars_then_split_on_paragraphs`
- `test_index_when_fresh_then_all_notes_embedded`
- `test_index_when_note_unchanged_then_not_reembedded`
- `test_index_when_note_edited_then_only_that_note_reembedded`
- `test_index_when_model_changed_then_requires_rebuild_and_fails_without_it`
- `test_index_rebuild_when_run_then_tables_recreated`
- `test_search_when_keyword_present_then_note_ranks_in_results`
- `test_search_when_paraphrase_then_vector_match_returns_note`
- `test_search_when_level_filter_then_only_that_level_returned`
- `test_search_when_index_missing_then_exit_three_with_hint`
- `test_index_when_note_deleted_then_removed_from_index`
- `test_index_when_note_invalid_then_skipped_and_reported`
- `test_index_when_index_md_stale_then_rewritten_so_check_has_no_drift`
- `test_search_keyword_when_stopwords_shared_with_irrelevant_chunk_then_only_content_match`
- `test_search_keyword_when_query_has_only_stopwords_then_no_hits`
- `test_search_when_query_has_punctuation_then_no_syntax_error`

Acceptance:
- Index of the fixture KB (20 notes) builds in under 30 seconds on a laptop.
- `milepost search` returns the expected note for each of 10 fixture queries (queries committed in `tests/fixtures/search_queries.json`).

---

## M7. Drafting and init

Files: `milepost/services/draft.py`, `milepost/services/init.py`, `milepost/services/doctor.py`, `milepost/llm/client.py`, `milepost/prompts/*.md`, `tests/unit/test_draft.py`, `tests/unit/test_init.py`, `tests/integration/test_init_cli.py`.

Tests:
- `test_collect_sources_when_exclude_matches_env_file_then_file_not_sent`
- `test_collect_sources_when_over_budget_then_truncates_and_notes_truncation`
- `test_secret_scan_when_aws_key_pattern_then_aborts_module_with_file_name_only`
- `test_draft_when_provider_fails_twice_then_retries_and_succeeds`
- `test_draft_when_provider_fails_three_times_then_exit_four_and_progress_saved`
- `test_draft_when_note_reviewed_and_no_force_then_refuses`
- `test_draft_when_run_then_frontmatter_written_by_milepost_not_model`
- `test_init_when_run_twice_then_second_run_creates_nothing`
- `test_init_when_kb_note_exists_then_not_overwritten`
- `test_init_when_dry_run_then_no_files_written_and_no_network_calls`
- `test_init_when_not_git_repo_then_exit_three`
- `test_init_when_scan_runs_then_no_module_activated_automatically`
- `test_init_when_modules_flag_then_declares_only_named_candidates`
- `test_init_when_modules_flag_names_non_candidate_then_exit_two`
- `test_init_when_config_exists_and_modules_flag_then_appends_only_new_module_tables`
- `test_init_when_config_exists_and_modules_flag_then_rest_of_file_byte_identical`
- `test_init_when_yes_flag_then_no_prompt_and_runs_to_completion`
- `test_init_when_ci_workflow_absent_then_written_with_installed_version_pinned`
- `test_init_when_ci_workflow_exists_then_not_overwritten`
- `test_doctor_when_model_env_unset_then_exit_three_naming_variable`
- `test_doctor_when_provider_key_missing_then_exit_three_naming_variable`
- `test_doctor_when_all_present_then_exit_zero`
- `test_doctor_when_json_flag_then_output_parses`
- `test_draft_prompt_when_loaded_then_has_l2_sections_in_order_including_file_map`
- `test_load_env_when_dotenv_present_then_values_available`
- `test_load_env_when_shell_value_set_then_shell_wins`
- `test_load_env_when_no_dotenv_then_nothing_changes`
- `test_doctor_when_dotenv_not_ignored_then_warns`
- `test_init_when_run_then_gitignore_lists_dotenv`

Acceptance:
- Provider calls are mocked in unit tests with a recorded response fixture. One integration test uses a real provider and is skipped unless `MILEPOST_MODEL` and the provider key are set.
- `.env` at the repository root is loaded for `draft`, `init`, `doctor` and `serve`; the shell wins.
- `milepost init --dry-run` on the fixture repo lists the files it would send and the estimated token count, with no network traffic (verified by a socket-blocking test).

---

## M8. Review, rehash, and git integration

Files: `milepost/services/review.py`, `milepost/services/hooks.py`, `milepost/services/merge_driver.py`, `tests/unit/test_review.py`, `tests/unit/test_merge_driver.py`, `tests/integration/test_hooks.py`, `tests/integration/test_merge_conflict.py`.

Tests:
- `test_review_when_draft_then_status_reviewed_and_hash_unchanged`
- `test_review_when_run_then_records_reviewer_and_time_from_git_identity`
- `test_review_when_git_identity_missing_then_exit_three`
- `test_rehash_when_conflict_then_sets_hash_and_prints_manifest_diff`
- `test_rehash_when_non_interactive_and_no_yes_then_exit_two`
- `test_hooks_install_when_fresh_repo_then_hooks_written_with_marker`
- `test_hooks_install_when_foreign_hook_exists_then_prints_snippet_and_writes_nothing`
- `test_hooks_uninstall_when_marker_missing_then_file_untouched`
- `test_merge_driver_when_only_ours_changed_key_then_keeps_ours`
- `test_merge_driver_when_both_changed_source_hash_then_writes_conflict`
- `test_merge_driver_when_body_conflicts_then_leaves_markers_and_exits_nonzero`
- `test_merge_driver_when_ours_reviewed_but_theirs_edited_body_then_draft`
- `test_merge_driver_when_agent_edit_on_one_side_then_draft_wins_over_reviewed`
- `test_merge_driver_when_index_md_then_keeps_ours`
- `test_review_when_note_stale_then_refused_and_unchanged`
- `test_review_when_hash_conflict_then_refused_pointing_at_rehash`
- `test_hooks_install_when_hooks_path_configured_then_snippet_and_nothing_written`
- `test_pre_commit_when_milepost_not_installed_then_hook_exits_zero_with_warning`
- `test_init_when_hooks_requested_then_hooks_installed`
- `test_merge_conflict_when_two_branches_edit_same_module_then_check_fails_until_rehash`
- `test_post_merge_when_index_fails_then_hook_exits_zero_with_warning`

Acceptance:
- `init` also runs `milepost hooks install` (skipped by `--no-hooks`).
- Integration test creates two branches in a temp repo, edits the same module note and source, merges, and asserts the documented outcome (`CONFLICT` sentinel or body markers, never a silently chosen hash).

---

## M8a. Computed context: outline, impact, sync, L1 purpose

Revision of the design (SPEC sections 0, 8.2, 8.3). Per-file detail is computed from source on demand instead of stored in L3 notes. No MCP and no model: pure services plus thin CLI commands, so they can be tested and used before the server exists.

Files: `milepost/services/outline.py`, `milepost/services/impact.py`, `milepost/services/sync.py`, changes to `milepost/services/render.py`, `milepost/config.py` (`verify`; `draft.mode` and `visibility` wait for M9 and M8b), `milepost/structure/*`, `tests/unit/test_outline.py`, `tests/unit/test_impact.py`, `tests/unit/test_sync.py`, `tests/unit/test_render.py`.

Tests:
- `test_outline_when_python_file_then_symbols_with_line_ranges`
- `test_outline_when_class_with_methods_then_methods_listed_with_qualified_names`
- `test_outline_when_typescript_file_then_functions_classes_and_exported_consts_listed`
- `test_outline_when_file_edited_then_new_line_ranges_returned`
- `test_outline_when_over_200_symbols_then_truncated_flag_set`
- `test_outline_when_unsupported_extension_then_usage_error_with_line_count`
- `test_outline_when_path_outside_repo_then_usage_error`
- `test_impact_when_file_imported_then_importers_listed`
- `test_impact_when_test_file_imports_target_then_listed_as_test_via_import`
- `test_impact_when_test_name_contains_stem_then_listed_as_test_via_name`
- `test_impact_when_over_50_importers_then_truncated_flag_set`
- `test_impact_when_path_unknown_then_not_found`
- `test_impact_when_module_has_verify_commands_then_returned`
- `test_sync_when_file_modified_in_module_then_routes_to_l2_with_stale_flag`
- `test_sync_when_file_added_then_routes_to_l2_file_map`
- `test_sync_when_file_deleted_then_routes_to_l2_and_flags_orphan_l3`
- `test_sync_when_file_covered_by_l3_then_l3_also_listed`
- `test_sync_when_path_uncovered_then_uncovered_dir_guidance`
- `test_sync_when_invariant_cites_changed_file_then_bullet_named`
- `test_sync_when_citation_ambiguous_then_skipped`
- `test_sync_when_nothing_changed_then_empty_and_says_so`
- `test_sync_when_base_given_then_uses_range_not_working_tree`
- `test_sync_when_module_has_verify_then_commands_included`
- `test_render_index_when_note_has_purpose_then_row_has_first_sentence_cut_to_160`
- `test_render_index_when_note_missing_then_row_says_no_note_yet`
- `test_render_index_when_no_purpose_section_then_row_says_so`
- `test_check_when_purpose_edited_and_index_not_rewritten_then_index_drift`
- `test_config_when_module_verify_list_then_parsed`
- `test_cli_outline_impact_sync_when_json_flag_then_output_parses`
- `test_sync_when_several_files_change_in_one_module_then_next_steps_has_every_route`
- `test_sync_when_module_has_no_note_then_next_steps_says_to_draft`
- `test_sync_when_note_exists_but_is_invalid_then_not_reported_as_missing`
- `test_sync_when_repo_has_no_commits_then_everything_counts_as_added`
- `test_outline_when_file_has_form_feed_or_bom_then_line_numbers_and_parse_correct`
- `test_outline_when_signature_spans_lines_then_joined_into_one_line`
- `test_outline_when_function_defined_under_if_or_try_then_listed`
- `test_outline_when_typescript_class_decorated_then_signature_is_the_class_line`
- `test_outline_when_line_comment_ends_with_slash_then_not_truncated`
- `test_impact_when_directory_name_contains_stem_then_not_listed_as_test`
- `test_impact_when_stem_shorter_than_three_chars_then_no_name_matches`

Acceptance:
- On a real repository, `milepost outline` on the largest route file (1,779 lines) lists the same 31 top-level definitions as `grep -nE "^(async )?def |^class "`. Whole-command time including `uv` startup was 1.1 s; the parse itself is not separately timed, so the 200 ms target in SPEC section 14 is not yet shown.
- `milepost impact` on a service file of that repository lists its importers and test, checked by hand against `grep` (done for `analytics_service.py`: 2 route importers and 1 test; two other grep hits were docstring mentions, correctly not listed).
- The existing INDEX fixtures and `milepost index` regenerate with the Purpose column and `check` passes.

---

## M8b. Human visibility: status, report, churn

Revision of the design (SPEC sections 4.1, 6 step 9, 8.4, 10.2). Everything here is derived from git and the notes, read-only, and never fails a build.

Files: `milepost/services/status.py`, `milepost/services/report.py`, changes to `milepost/services/check.py` and `milepost/core/notes.py` (`reviewed_by`, `reviewed_at`), `milepost/resources/ci-kb-check.yml`, `templates/CODEOWNERS.snippet`, `tests/unit/test_status.py`, `tests/unit/test_report.py`, `tests/integration/test_status_git.py`.

Tests:
- `test_status_when_note_reviewed_then_counts_lines_changed_since_baseline_commit`
- `test_status_when_note_never_reviewed_then_marked_never_reviewed_and_listed_first`
- `test_status_when_reviewed_note_later_edited_by_agent_then_baseline_is_last_reviewed_commit`
- `test_status_when_history_squashed_then_baseline_still_found`
- `test_status_when_commits_carry_agent_trailer_then_counted_as_agent_commits`
- `test_status_when_trailer_configured_then_custom_pattern_used`
- `test_status_when_json_flag_then_output_parses`
- `test_check_when_reviewed_note_churn_over_threshold_then_warns_unreviewed_churn`
- `test_check_when_note_never_reviewed_then_no_unreviewed_churn_warning`
- `test_check_when_churn_over_threshold_then_still_exit_zero`
- `test_notes_when_reviewed_by_and_at_present_then_round_trip_and_validate`
- `test_report_when_note_changed_then_lists_it_with_status_before_and_after`
- `test_report_when_reviewed_note_flipped_to_draft_then_flip_shown`
- `test_report_when_changed_file_has_stale_note_then_listed`
- `test_report_when_changed_file_uncovered_then_listed`
- `test_report_when_invariant_cites_changed_file_then_bullet_quoted_with_note_id`
- `test_report_when_nothing_needs_attention_then_says_so`
- `test_report_when_format_json_then_parses`
- `test_report_when_run_then_exit_zero_even_with_findings`
- `test_ci_workflow_when_written_then_report_step_writes_to_step_summary`
- `test_codeowners_snippet_when_present_then_names_kb_directory`

Acceptance:
- On the pilot repository, `milepost status` runs in under 2 seconds and ranks the `api` module by unreviewed lines after a deliberate edit to one route file.
- `milepost report --base main` on a branch where an agent edited `routes/db_tools.py` quotes the `db_tools.py` invariant or gotcha bullet if one cites it, and says so plainly if none does.
- The CI template renders the report into the job summary on a pull request in a scratch repository.

---

## M9. MCP server

**MVP scope:** the ten tools in model mode. Agent-mode drafting (`draft.mode = "agent"`, draft packets, `kb_update` creating L2) is deferred past the MVP and its tests were removed from this list; SPEC 9.3 and 11 still describe it.

Files: `milepost/mcp_server.py`, `tests/unit/test_mcp_tools.py`, `tests/integration/test_mcp_stdio.py`.

Tests:
- `test_kb_overview_when_called_then_returns_index_and_stale_count`
- `test_kb_module_when_unknown_id_then_error_not_found`
- `test_kb_module_when_known_id_then_includes_related_summaries`
- `test_kb_file_when_path_matches_sources_then_returns_covering_notes`
- `test_kb_search_when_limit_over_ten_then_capped_at_ten`
- `test_kb_update_when_l2_note_missing_then_rejects_and_points_to_kb_draft_module`
- `test_kb_update_when_body_over_limit_then_rejects`
- `test_kb_update_when_called_then_recomputes_source_hash_from_working_tree`
- `test_kb_update_when_frontmatter_key_other_than_status_then_ignored`
- `test_kb_update_when_read_hash_missing_for_l2_then_invalid_input`
- `test_kb_update_when_read_hash_matches_working_tree_then_writes`
- `test_kb_update_when_source_changed_after_read_then_stale_read_error`
- `test_kb_update_when_body_unchanged_and_read_hash_current_then_refreshes_hash_and_written_at`
- `test_kb_file_when_called_then_each_note_has_source_hash_now_and_stale_flag`
- `test_kb_draft_module_when_module_declared_and_no_note_then_writes_draft_note`
- `test_kb_draft_module_when_module_not_in_config_then_not_found_with_config_hint`
- `test_kb_draft_module_when_note_exists_then_conflict`
- `test_kb_draft_module_when_model_env_unset_then_environment_error_naming_variable`
- `test_kb_draft_module_when_secret_in_sources_then_aborts_with_file_name_only`
- `test_kb_draft_module_when_written_then_frontmatter_set_by_milepost_and_status_draft`
- `test_tool_response_when_any_tool_called_then_next_steps_present_and_deterministic`
- `test_kb_file_when_notes_cover_path_then_next_steps_names_each_note_to_update`
- `test_kb_update_when_purpose_changed_then_index_md_rewritten_so_check_has_no_drift`
- `test_kb_update_when_reviewed_note_updated_then_status_draft_and_review_fields_removed`
- `test_kb_update_when_status_reviewed_requested_then_ignored_stays_draft`
- `test_kb_module_when_called_then_includes_verify_commands`
- `test_kb_outline_when_called_then_matches_outline_service`
- `test_kb_impact_when_called_then_matches_impact_service`
- `test_kb_sync_when_called_then_matches_sync_service_and_next_steps_present`
- `test_kb_outline_when_over_cap_then_truncated_and_response_under_token_budget`
- `test_mcp_stdio_when_client_lists_tools_then_ten_tools_returned`

Acceptance:
- A stdio integration test starts `milepost serve` as a subprocess, calls each of the ten tools, and checks responses against the schema in SPEC section 11.
- Each tool's response, on the fixture KB, is under its token budget in SPEC section 14 (characters divided by 4).

---

## M10. Claude Code plugin

**MVP scope:** the plugin runs the local checkout (`uv run --project ${CLAUDE_PLUGIN_ROOT}/..`), so nothing is published. The PyPI-pinned `uvx milepost==<version>` form and the `plugin/` marketplace entry wait for the release (M11). The hook formats and plugin layout were verified against the Claude Code docs and `claude plugin validate` passes.

Files: `plugin/` (moved from `templates/plugin/`), `templates/AGENTS.md.snippet`, `milepost/services/hook.py`, `tests/integration/test_plugin_manifest.py`, `tests/unit/test_hook.py`.

Tests:
- `test_plugin_manifest_when_parsed_then_has_name_version_and_description`
- `test_plugin_mcp_config_when_parsed_then_starts_milepost_serve`
- `test_plugin_skill_when_present_then_frontmatter_has_name_and_description`
- `test_plugin_commands_when_cli_subcommands_referenced_then_each_exists`
- `test_plugin_commands_when_listed_then_only_kb_init_present`
- `test_plugin_kb_init_command_when_parsed_then_names_doctor_scan_and_init_steps_in_order`
- `test_plugin_hooks_when_parsed_then_session_start_post_edit_and_stop_hooks_present`
- `test_plugin_hooks_when_parsed_then_each_command_is_a_real_milepost_hook`
- `test_hook_stop_when_stale_note_is_old_debt_unrelated_to_this_work_then_no_block`
- `test_hook_stop_when_agent_committed_the_change_then_still_blocks`
- `test_hook_stop_when_failure_is_not_a_stale_note_then_no_block`
- `test_hook_stop_when_stale_l3_note_covers_untouched_file_then_no_block`
- `test_hook_stop_when_changed_file_is_ignored_then_no_block`
- `test_hook_project_root_when_env_dir_set_then_preferred_over_payload_cwd`
- `test_hook_post_edit_when_notebook_path_then_handled`
- `test_hook_post_edit_when_nested_uncovered_dirs_then_most_specific_named`
- `test_hook_post_edit_when_kb_dir_configured_with_dot_slash_then_still_ignored`
- `test_hook_post_edit_when_note_stale_then_marked_stale`
- `test_playbook_when_skill_names_kb_tools_then_every_name_exists_in_mcp_server`
- `test_playbook_when_spec_scenarios_listed_then_each_has_a_section_in_skill`
- `test_hook_session_start_when_kb_present_then_returns_index_cut_to_3000_chars_and_playbook_reminder`
- `test_hook_session_start_when_no_kb_then_prints_nothing`
- `test_hook_session_start_when_milepost_errors_then_exits_zero_with_stderr_warning`
- `test_playbook_when_spec_scenarios_listed_then_each_has_a_section_in_skill`
- `test_hook_post_edit_when_path_covered_then_returns_covering_notes_and_update_instruction`
- `test_hook_post_edit_when_path_under_kb_dir_then_prints_nothing`
- `test_hook_post_edit_when_path_in_uncovered_dir_then_names_uncovered_dir`
- `test_hook_post_edit_when_milepost_errors_then_exits_zero_with_stderr_warning`
- `test_hook_stop_when_check_fails_then_returns_block_with_findings`
- `test_hook_stop_when_stop_hook_already_active_then_exits_zero`
- `test_hook_stop_when_check_passes_then_no_block`

Acceptance:
- Hook JSON field names, matcher syntax, and plugin hook file location are verified against the current Claude Code hooks documentation, and any difference from SPEC section 12.4 is fixed in the spec first.
- Manual test: in a fresh fixture repo with the environment variables set, `/kb-init` alone, with one confirmation, ends with draft notes ready for `milepost review` and no other command needed.
- Manual test: in a Claude Code session on a fixture repo, the index appears at session start, editing a covered file surfaces the covering notes, and ending the turn with a stale note is blocked once.
- Before release, the plugin layout is verified against the current Claude Code plugin documentation (not done in this spec).
- Manual test: install the plugin in a Claude Code session on a fixture repo; `kb_overview` returns the index; `kb_update` writes a note that passes `milepost check`.

---

## M11. Pilot and release

Work:
- Repeat the measurement (PROPOSAL.md section 7 step 6) on the same repository and the same five frozen prompts as the M5a baseline.
- Measure review effort, the second goal (SPEC 0.1). Proposed method, not yet agreed: take three agent-written pull requests from the pilot. Someone who did not write them writes five factual questions each from the code diff (what behavior changed, which module, what invariant is touched). A reviewer answers using only the note diff and `milepost report`, timed; another answers from the code diff alone. Compare correct answers and time.
- Record which tools agents actually called per run (from the logs), since a tool never called saves nothing.
- Publish `0.1.0` to PyPI only if the measurement passes. Otherwise stop and record the result.

Acceptance:
- Baseline (from M5a) and post-milepost numbers recorded side by side, plus the review-effort comparison and the per-run tool-call counts. Go/no-go decision recorded with the private baseline data.
- Pass rule: agreed with the maintainer before the run and written down first, with the protocol in `PILOT.md`. A proposal to start from: at least 30% fewer total fresh tokens after the first turn, and the review-effort comparison at least 80% as many correct answers in at most half the time. Neither number is agreed yet.
- README includes quickstart, the decision record, and the known limitations from SPEC section 16.
