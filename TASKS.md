# kbmap Build Plan

Companion to SPEC.md. Each milestone lists the work, the test functions to write first (TDD), and acceptance criteria. Test names follow `test_<what>_when_<condition>_then_<expected>`.

Rules for implementers:
- Write the named tests first, see them fail, then implement.
- A milestone is done only when its acceptance criteria are verified by running the commands, not by inspection.
- Do not add `# type: ignore`. Keep `mypy --strict` clean.
- Imports at file top. No inline imports except the lazy ones listed in SPEC section 13.

Test file paths are under `tests/`. Fixtures are under `tests/fixtures/`.

---

## M0. Project skeleton

Work:
- `pyproject.toml` with `[project.scripts] kbmap = "kbmap.cli:app"`, Python `>=3.12`, dependencies from SPEC section 13.
- Empty package layout from SPEC section 15.
- `ruff`, `mypy --strict`, `pytest` configured. CI workflow runs all three.
- `LICENSE` (Apache-2.0), `README.md` stub.

Tests (`tests/unit/test_cli_smoke.py`):
- `test_cli_help_when_invoked_then_lists_all_commands`
- `test_cli_version_when_invoked_then_prints_package_version`

Acceptance:
- `uv run kbmap --help` lists every command in SPEC section 8 (stubs allowed).
- `uv run pytest`, `uv run ruff check`, `uv run mypy kbmap` all pass.

---

## M1. Config and validation

Files: `kbmap/config.py`, `tests/unit/test_config.py`, `tests/fixtures/config/*.toml`.

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

Files: `kbmap/core/notes.py`, `tests/unit/test_notes.py`.

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

Files: `kbmap/core/hashing.py`, `kbmap/core/glob.py`, `tests/unit/test_hashing.py`, `tests/integration/test_hash_stability.py`.

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

Files: `kbmap/structure/python_scanner.py`, `kbmap/structure/tree_sitter_scanner.py`, `tests/unit/test_scanners.py`.

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

Files: `kbmap/services/check.py`, `kbmap/services/render.py`, `kbmap/services/coverage.py`, `kbmap/cli.py` (wiring), `tests/unit/test_check.py`, `tests/unit/test_coverage.py`, `tests/integration/test_check_cli.py`.

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
- Running `kbmap check` twice on an unchanged repo gives identical output.
- Integration test runs against a real git repo created in a temp directory, with real commits and trailers.

---

## M5a. Baseline measurement (go/no-go gate)

This milestone needs no kbmap code and can start at any time. M6 does not start until it is done, because everything from M6 on is only worth building if the measurement later shows an improvement.

Work:
- Pilot repository: Kaihle.
- Pick five representative tasks (a feature, a bugfix, a cross-module change, a question about existing behavior, a refactor). Write each as a fixed prompt in `PILOT.md`.
- Run each with the coding agent and no kbmap. Record files read, tokens used, and whether the task outcome was acceptable.

Acceptance:
- `PILOT.md` in the kbmap repository holds the five prompts and the baseline numbers, committed before any M6 work.
- The prompts are frozen: M11 reruns exactly these.

---

## M6. Index and search

Files: `kbmap/store/base.py`, `kbmap/store/sqlite_store.py`, `kbmap/services/index.py`, `kbmap/services/search.py`, `tests/unit/test_chunking.py`, `tests/integration/test_index_search.py`.

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

Acceptance:
- Index of the fixture KB (20 notes) builds in under 30 seconds on a laptop.
- `kbmap search` returns the expected note for each of 10 fixture queries (queries committed in `tests/fixtures/search_queries.json`).

---

## M7. Drafting and init

Files: `kbmap/services/draft.py`, `kbmap/services/init.py`, `kbmap/services/doctor.py`, `kbmap/llm/client.py`, `kbmap/prompts/*.md`, `tests/unit/test_draft.py`, `tests/unit/test_init.py`, `tests/integration/test_init_cli.py`.

Tests:
- `test_collect_sources_when_exclude_matches_env_file_then_file_not_sent`
- `test_collect_sources_when_over_budget_then_truncates_and_notes_truncation`
- `test_secret_scan_when_aws_key_pattern_then_aborts_module_with_file_name_only`
- `test_draft_when_provider_fails_twice_then_retries_and_succeeds`
- `test_draft_when_provider_fails_three_times_then_exit_four_and_progress_saved`
- `test_draft_when_note_reviewed_and_no_force_then_refuses`
- `test_draft_when_run_then_frontmatter_written_by_kbmap_not_model`
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

Acceptance:
- Provider calls are mocked in unit tests with a recorded response fixture. One integration test uses a real provider and is skipped unless `KBMAP_MODEL` and the provider key are set.
- `kbmap init --dry-run` on the fixture repo lists the files it would send and the estimated token count, with no network traffic (verified by a socket-blocking test).

---

## M8. Review, rehash, and git integration

Files: `kbmap/services/review.py`, `kbmap/services/hooks.py`, `kbmap/services/merge_driver.py`, `tests/unit/test_review.py`, `tests/unit/test_merge_driver.py`, `tests/integration/test_hooks.py`, `tests/integration/test_merge_conflict.py`.

Tests:
- `test_review_when_draft_then_status_reviewed_and_hash_unchanged`
- `test_rehash_when_conflict_then_sets_hash_and_prints_manifest_diff`
- `test_rehash_when_non_interactive_and_no_yes_then_exit_two`
- `test_hooks_install_when_fresh_repo_then_hooks_written_with_marker`
- `test_hooks_install_when_foreign_hook_exists_then_prints_snippet_and_writes_nothing`
- `test_hooks_uninstall_when_marker_missing_then_file_untouched`
- `test_merge_driver_when_only_ours_changed_key_then_keeps_ours`
- `test_merge_driver_when_both_changed_source_hash_then_writes_conflict`
- `test_merge_driver_when_body_conflicts_then_leaves_markers_and_exits_nonzero`
- `test_merge_conflict_when_two_branches_edit_same_module_then_check_fails_until_rehash`
- `test_post_merge_when_index_fails_then_hook_exits_zero_with_warning`

Acceptance:
- Integration test creates two branches in a temp repo, edits the same module note and source, merges, and asserts the documented outcome (`CONFLICT` sentinel or body markers, never a silently chosen hash).

---

## M9. MCP server

Files: `kbmap/mcp_server.py`, `tests/unit/test_mcp_tools.py`, `tests/integration/test_mcp_stdio.py`.

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
- `test_kb_draft_module_when_written_then_frontmatter_set_by_kbmap_and_status_draft`
- `test_tool_response_when_any_tool_called_then_next_steps_present_and_deterministic`
- `test_kb_file_when_notes_cover_path_then_next_steps_names_each_note_to_update`
- `test_mcp_stdio_when_client_lists_tools_then_seven_tools_returned`

Acceptance:
- A stdio integration test starts `kbmap serve` as a subprocess, calls each tool, and checks responses against the schema in SPEC section 11.

---

## M10. Claude Code plugin

Files: `plugin/` (from `templates/plugin/`), `kbmap/services/hook.py`, `tests/integration/test_plugin_manifest.py`, `tests/unit/test_hook.py`, `tests/unit/test_playbook.py`.

Tests:
- `test_plugin_manifest_when_parsed_then_has_name_version_and_description`
- `test_plugin_mcp_config_when_parsed_then_pins_kbmap_version_matching_package`
- `test_plugin_skill_when_present_then_frontmatter_has_name_and_description`
- `test_plugin_commands_when_present_then_each_maps_to_existing_cli_command`
- `test_plugin_commands_when_listed_then_only_kb_init_present`
- `test_plugin_kb_init_command_when_parsed_then_names_doctor_scan_and_init_steps_in_order`
- `test_plugin_hooks_when_parsed_then_post_edit_and_stop_hooks_pin_matching_version`
- `test_playbook_when_skill_names_kb_tools_then_every_name_exists_in_mcp_server`
- `test_playbook_when_spec_scenarios_listed_then_each_has_a_section_in_skill`
- `test_hook_post_edit_when_path_covered_then_returns_covering_notes_and_update_instruction`
- `test_hook_post_edit_when_path_under_kb_dir_then_prints_nothing`
- `test_hook_post_edit_when_path_in_uncovered_dir_then_names_uncovered_dir`
- `test_hook_post_edit_when_kbmap_errors_then_exits_zero_with_stderr_warning`
- `test_hook_stop_when_check_fails_then_returns_block_with_findings`
- `test_hook_stop_when_stop_hook_already_active_then_exits_zero`
- `test_hook_stop_when_check_passes_then_no_block`

Acceptance:
- Hook JSON field names, matcher syntax, and plugin hook file location are verified against the current Claude Code hooks documentation, and any difference from SPEC section 12.4 is fixed in the spec first.
- Manual test: in a fresh fixture repo with the environment variables set, `/kb-init` alone, with one confirmation, ends with draft notes ready for `kbmap review` and no other command needed.
- Manual test: in a Claude Code session on a fixture repo, editing a covered file surfaces the covering notes, and ending the turn with a stale note is blocked once.
- Before release, the plugin layout is verified against the current Claude Code plugin documentation (not done in this spec).
- Manual test: install the plugin in a Claude Code session on a fixture repo; `kb_overview` returns the index; `kb_update` writes a note that passes `kbmap check`.

---

## M11. Pilot and release

Work:
- Repeat the measurement (PROPOSAL.md section 7 step 6) on the same Kaihle repository and the same five frozen prompts as the M5a baseline.
- Publish `0.1.0` to PyPI only if the measurement passes. Otherwise stop and record the result.

Acceptance:
- Baseline (from M5a) and post-kbmap numbers recorded side by side. Go/no-go decision written into `PILOT.md` in the kbmap repository.
- README includes quickstart, the decision record, and the known limitations from SPEC section 16.
