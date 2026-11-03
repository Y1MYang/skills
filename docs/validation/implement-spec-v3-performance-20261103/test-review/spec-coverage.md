# Performance-contract test review — Spec/coverage axis

Review version: 2, 2026-11-03. Scope: **full qualification of the new performance contract**, including inherited compatibility coverage. This is a fresh, implementation-blind, read-only review; it is not a production review or a delta qualification. Version 2 makes the narrow public-contract correction recorded below; it adds no candidate tests or execution evidence.

**Spec fidelity of the assertions reviewed: pass. Full correctness coverage: fail (material coverage omissions below). Workflow compliance (§5): unverified. Speed claim (§6): unverified. Observed product success: unverified by this reviewer.** The separate Validity/standards axis and coordinator reconciliation remain necessary. There is no whole-spec blessing.

## Pinned inputs and boundary

Candidate HEAD supplied by the input owner: `996eb268bf0cf3c31b19cbe2c1445f1cff06cb1d`. No base comparison was requested or used; this assessment maps the complete current test snapshot to the contract, rather than inferring coverage from a production diff. No previous qualification is reused.

The following SHA-256 values were checked from the allowed files:

| Input | SHA-256 |
| --- | --- |
| `docs/plans/implement-spec-v3-performance-contract.md`, revision 1 | `b6ede11f51d5c3a0f509d97e9026a0caadcb2900fb8cc14d10c223c5d2a48d0b` |
| `docs/plans/implement-spec-v3-runtime-contract.md` | `0a6e2285afd62fc3789bd23874ebcf6c415a5b873901e3e5bec61c19af59f1fb` |
| `skills/engineering/implement-spec-v3/references/runtime-ledger.md` | `88491ab095eee1b1c89d9a4a898f40c8a67aff37b72a72d7b1440c307a54309f` |
| `tests/test_cycle_performance.py` | `f23993b2dabc2c907b2d5b461fe95674b280df66a8014c426a12fa146c841dda` |
| `tests/test_cycle.py` | `c6c7a3ff20fa75ed8c51a6fe677a3e24ca3a43a2cd216ce1b07bcdc6d1debd53` |
| `tests/test_cycle_proofs.py` | `5c611692402cc915ae5000a4a64b101249b0f3f672691bbf7061cb02a3696deb` |
| `tests/test_cycle_recovery.py` | `a6ef2b3a81b20499cc8f16aa61de3a38ef869101253e4413ab2e0b5616519245` |
| `tests/test_cycle_safety.py` | `b1c1fcdb4f14bfc4d1981ea8f1abcd8dd2434282b255b736381260d2123e0744` |
| `tests/test_run_command.py` | `12f9afdcb6523d4dfefa7034204b466410f1734d52f8499b512434a7b92445b5` |

All `tests/` paths above are under `skills/engineering/implement-spec-v3/`. Also read: `skills/engineering/test-review/SKILL.md`, its `references/acceptance-contract.md`, `skills/engineering/tdd/{SKILL.md,tests.md,mocking.md}`, and the approved pstack index, test-behavior, and explain-the-number principles.

Dependency closure: the new test class borrows test-owned CLI/setup/fixture methods from `test_cycle.py`, a standalone-runner helper from `test_cycle_proofs.py`, and native Windows identity observation from `test_cycle_recovery.py`. Those dependencies and the inherited public-CLI tests were inspected as test text. Standard-library filesystem, sockets, subprocesses, Git fixture commands, and native process identity are the observation boundaries. Toy fee programs written by the fixtures are test data. The qualification declarations in fixtures explicitly do not claim actual independent review of production.

No production source, production diff, private review, raw runtime log, test import, collection, or execution was used. No isolated executable mechanism experiment was performed. Reasoning here is based on contract and test source. The owner later reported **127 full-suite cases: 126 pass, one POSIX skip**, and previously reported 37 new cases Green, 17 genuine Red→Green, 20 first-Green, and a corrected E07 test defect. These are labeled owner/runner facts, not independently observed execution or proof of the development chronology. An announced later 38th test is outside this exact snapshot and is not assessed.

## Material findings

These are **confirmed test-set coverage defects**, not findings that production violates the contract. Ownership: independent test author / coverage coordinator. No spec change is needed for the stated guarantees.

### SC-1 — New envelope and reserved-identity boundaries are only partially covered

Sources: performance §2 upfront common validation and distinct IDs; §3 exact envelope, allowed prepare operations, precommit validation, and revision-1 bound record identity. Locations: B03 at line 307, B05 at 1048, E14–E16 at 857–935 of `test_cycle_performance.py`.

B03 rejects an unknown later operation before the first mutation; B05 rejects an unknown batch envelope field; B04 correctly distinguishes operation-specific rejection after a committed prefix. None exercises duplicate IDs within a batch, so a batch that silently treats its duplicate as ordinary replay can satisfy every current test while violating the upfront distinct-ID rule. The inherited malformed-`apply` matrix is a different entry boundary.

There is no negative `execute` envelope case. The helpers always produce the allowed operation, valid argv, and distinct preparation/record IDs. Consequently, accepting an invalid execution request or committing preparation before rejecting it is undetected. E14/E15 collide using `invocation`, and E16 collides through another `execute`; none submits `op:"record"` with the reserved ID but another attempt ID. A reservation check that protects only the operation name could pass these assertions.

Smallest immediate discriminating addition: one representative invalid execution envelope that would otherwise prepare successfully, asserting no target effect or consumed IDs/budget and successful corrected retry. The duplicate batch-ID and wrong-attempt record-ID cases remain explicit coverage limitations for reconciliation; they do not imply a parser or collision permutation matrix is required.

### SC-2 — Execute timeout propagation is missing; no-claim replay remains partial

Sources: performance §3 exit semantics and replay/failure rules. Locations: E01 at 347, E06 at 493–525, `leave_bound_formal_preparation_before_launch` at 179–217, E08 at 618–638.

E01 covers a real nonzero receipt and E13 covers ineligible recording. No test drives `execute` to a real timeout receipt and checks exit 0, `outcome:"timeout"`, null target exit code, durable settlement, retained failure, and replay without another launch. The inherited runner timeout test proves standalone exit 124 and containment, not the new helper's required recording/return semantics.

The dirty formal fixture already covers a representative initial inability to obtain a complete receipt: `execute` must return exit 2 and `ok:false`; the target marker and receipt remain absent; replay of the original prepare exposes the same retained pending preparation. Section 3 permits a specific runner/evidence error rather than requiring `execution-incomplete`, so this is valid initial-error coverage. E08 then resumes a genuine complete unrecorded receipt.

E06 deliberately terminates the native process identified by the claim. The public contract does not require that process to differ from the outer `execute` process, so a final JSON response cannot be mandatory after that forced death. E06 validly supplies narrower evidence: later `recovery-required`, interrupted recovery accounting, and `execution-settled`. No assertion replays a bound preparation with **no complete receipt and no claim**; that distinct replay branch remains partial, and the dirty formal fixture must not be assumed to establish its claim state.

Smallest immediate discriminating addition: one real timed-out execution with durable failure/replay assertions. The version-1 recommendation to strengthen E06's first-helper response is retracted. No additional initial-error test is required by this finding. No-claim replay remains a limitation unless a stable public seam establishes it; it is not a new test-case demand in this correction.

### SC-3 — The fresh audit after external execution is not distinguished from an entry-only audit

Sources: performance §1 and §3 step 3; §5 minimum old-evidence/receipt-corruption acceptance. Location: H01 at 708–739; E10–E12 at 661–706.

H01 is valuable: it changes a real adopted log without changing its size or mtime, then checks execute replay, batch replay, apply, verify, and inspect rejection. All corruptions occur **before a new process enters**. A helper that audits only before launching its target, then reuses that result after the target completes, could pass. E10–E12 exercise a genuine receipt for the wrong argv; that is command-binding rejection, not corruption of an adopted receipt. No supplied test corrupts an adopted receipt and asserts rejection.

Smallest discriminating addition: start a waiting execution after an earlier genuine receipt is adopted; after the target acknowledges live execution, corrupt that old receipt (same-size/restored-mtime if practical), then release the target. Require the helper's final record transition to reject without settling through corrupted history, restore only test-owned bytes for cleanup, and verify the durable prefix/accounting. This one controlled public scenario can establish both the post-target audit and actual receipt-corruption boundary.

The stronger requirement to audit **every item inside one batch process** also remains unverified by H01. B01/B02 establish item identity and durable prefixes, not fresh evidence audit between items. A deterministic public observation/synchronization seam is needed to distinguish that boundary; do not introduce a flaky timing race or require a private hook merely to fill the row.

### SC-4 — Scope-local closure and invalidation have only direct-barrier examples

Source: performance §4. Locations: S01–S04 at 557–616; S05–S10 at 770–1006; inherited `test_include_shared_helper_preserves_closed_history_and_refreshes_formal_proof` at `test_cycle_proofs.py:201`.

S09 and S10 prove one direct ordinary-dependent and one direct gate-consumer pending barrier. They do not distinguish a one-hop expansion from the required repeatedly computed closure. S04 proves an existing-file ancestor/descendant overlap across snapshot groups, with a case alias on Windows; inherited missing-path alias tests validate snapshots, not scope-local edit impact. S07 proves that a changed pending formal baseline blocks revision. Positive scope-local cases preserve an unrelated development preparation, not a pending gate-formal scope.

More critically, all closure examples reject the edit. No accepted edit demonstrates that an **unlisted affected downstream/shared-dependency example keeps historical completion while its current gate qualification/release/formal evidence becomes unusable even when its own bytes did not change**. The inherited include test invalidates the directly listed example's final scope, and the inherited extend test invalidates final membership. Neither observes the new closure-based gate invalidation rule. A runtime that computes direct barriers but invalidates only explicitly named examples can pass the current suite.

Smallest immediate discriminating additions: a short mixed dependency chain (ordinary edge followed by a gate edge) with pending work at the far end, requiring rejection; then a settled version with a legitimate existing gate proof, an accepted edit upstream, and an attempted reliance on unchanged-byte downstream proof that must reject while historical close remains. An unrelated gate proof is a useful positive control if available in the same scenario. Disjoint pending gate-formal admission, missing-path identity, and new-gate-consumer seeding remain explicitly partial coverage; the coordinator should select scope cases for their distinct guarantees, not expand into a Cartesian product of operations and graph shapes.

## Requirement reconciliation

`Covered` below means the test has source-level assertions for the stated behavior, subject to the independent validity axis. It does not mean this reviewer observed a passing run. `Partial` explicitly limits the claim.

| Requirement group | Coverage and observable evidence |
| --- | --- |
| §1 original events, identities, budgets, semantic authority | Covered by B01/B02/B06 and E01/E13: sequential original results, replay via original IDs, one reservation, no automatically valid Red, explicit judgment before actual Green, ineligible result cannot become existing. Inherited close/formal/recovery examples retain prior entry paths. Actual actor/context authority remains §5 evidence. |
| §1 complete audit at every transition; reuse only within unchanged transition | Partial: H01 detects same-size/restored-time old log tamper at entry/replay; inherited changed cancellation claim rejects verify/recover. Post-target, intra-batch, and complete artifact-integrity coverage are incomplete (SC-3). |
| §2 finite batch envelope/common validation | Partial: B03/B05 cover recognized operation and exact outer field set; B04 covers item-specific validation timing. Duplicate-ID/upfront common validation remains SC-1. Finite/nonempty/schema constraints have no new batch-negative example. |
| §2 ordered original durable items, stop at first rejection, replay/accounting | Covered by B01/B02/B04/B06/E15: exact prefix/result sequence, suffix models not applied, no rollback or duplicate reservation, repaired suffix and changed committed content. Batch-specific contention/interleaving is unverified; ordinary apply contention is inherited. No aggregate event is supported by sequence increments and original-ID replay. |
| §3 valid execution, pinned canonical binding, one reservation and real record | Covered for real zero/nonzero/ineligible and genuine formal-receipt resumption by E01/E02/E08/E09/E13. E02 independently calculates the documented canonical request digest; E03 rejects changed argv; E04 rejects adoption of ordinary apply preparation. Batch-created unbound preparation is not separately exercised. |
| §3 reserved record ID through apply/batch/execute | Partial: E14/E15/E16 cover all three entry mechanisms, prefix preservation and original eventual record; wrong-attempt record content remains SC-1. |
| §3 lock release and concurrent helper exclusion | Covered by E05: target sends `R`, an independent mutation returns before target release, duplicate returns `recovery-required`, marker remains one launch, original helper settles after release. This is causal overlap evidence, not a latency SLA. |
| §3 replay, partial prefixes, recovery, corruption | Partial: E02/E08 replay completed/complete-unrecorded paths; E05/E07 live/unknown paths; E06 forced-death recovery and settled replay; E10–E12 real wrong-command evidence. The dirty formal helper covers a representative initial no-complete-receipt rejection and retained pending preparation. No-claim replay remains partial and timeout propagation remains missing (SC-2); corrupted-receipt and post-target audit remain SC-3. |
| §3 derived invocation settings and output channels | Actual fixture execution from the prepared workspace, E08's formal dirty preflight, and genuine bound receipt argv provide partial evidence. Standalone runner covers direct argv, progress, logs and containment. The execute wrapper does not independently exercise literal shell metacharacters, progress/raw-log separation, or timeout derivation; do not infer these from standalone success. |
| §4 affected seeds and actual path identity | Partial: S01 avoids pulling an ancestor in; S02/S04 cover added-path impact; S05/S07/S08 cover pending/open/formal baselines; S06/S14 cover adopted regression/formal refresh. New-gate-consumer seeds, missing-path edit impact and repeated closure lack distinguishing cases (SC-4). |
| §4 affected active/pending/final barriers | Covered for the named concrete cases: S03 explicitly resets active work, S08 rejects omitted open work, S04/S05/S09/S10 reject affected work, S07 blocks relevant pending formal, S11–S13 block pending final for each edit. Multi-hop and disjoint pending formal admission remain partial (SC-4). |
| §4 unrelated work preservation | Covered for development preparations by S01–S03/S06/S14: exact pending list, budget, request bytes, identity/state and active flow survive; original prepared command subsequently records with no reprepare. Execute-bound/live and pending gate-formal preservation are not all established; the latter is SC-4. |
| §4 history, stale proofs, affected gate invalidation and final readiness | Partial: S03 resets only named active work; S06/S14 retain closed history. Inherited include/extend/revise tests cover direct history/final invalidation and required re-completion. Downstream/shared closure invalidation and unchanged-byte gates remain SC-4. |
| §4 complete plan/path/cycle/ownership validation and one authoritative root | Inherited tests cover scope anchors, case-equivalent scope/write paths, indirect graph cycles, atomic include, and original lifecycle. There is no new claim that separate workcopies are supported. Complete dependency admission, workspace integration, and freeze discipline require agent evidence; caller-supplied declarations are not proof of dependency completeness. |
| §5 continuing assignments, one-example TDD, dispatch-only main, separate role authority and fresh reviews | Unverified by runtime tests. E01 and inherited first-Green tests prove mechanical ordering/modes, not real author chronology, model/context separation, semantic reports, Runner prescription, or actual independent reviews. Owner counts do not close this evidence requirement. |
| §5 minimum independent acceptance list | Substantial direct coverage across B/E/S/H mappings below. Receipt-corruption/post-target audit and full execute failure/replay paths are partial; inherited compatibility is mapped below. |
| §6 paired benchmark/workflow-speed evidence | Unverified, intentionally not converted into a correctness ratio. No allowed input supplies equivalent baseline/candidate trials, multiple paired repetitions, elapsed ranges/medians, real command work, process/event counts, overlap observations, environment, failed trials, or reproducible benchmark artifacts. Correctness success cannot establish acceleration. |

## All 37 new examples

Names and line numbers refer to the pinned `test_cycle_performance.py`. Each row describes the specific observed boundary rather than treating a filename or test title as proof.

| ID | Test / line | Observable assertion |
| --- | --- | --- |
| B01 | `test_batch_open_prepare_replay_keeps_original_events_and_single_reservation` :227 | Two consecutive sequences; original prepare replay matches; repeat batch leaves inspect/budget unchanged. |
| B02 | `test_batch_state_rejection_keeps_prefix_and_retries_repaired_suffix` :266 | Index 1 rejection keeps open, does not run invocation; repaired suffix commits once under same IDs. |
| B03 | `test_batch_unknown_later_operation_rejects_before_any_mutation` :307 | Unknown later op gives empty results/null index and identical inspect; original open ID remains usable. |
| B04 | `test_batch_operation_field_failure_preserves_the_successful_prefix` :325 | Boolean timeout rejects at item 1 after open; valid timeout retries suffix without a second prefix. |
| B05 | `test_batch_unknown_envelope_field_rejects_without_consuming_any_event` :1048 | Unknown outer field rejects before any item; valid same open ID succeeds afterward. |
| B06 | `test_batch_changed_committed_event_rejects_at_its_index_and_keeps_new_prefix` :1065 | Changed committed content gets `op-id-conflict`; new prefix stays, later model change does not execute. |
| E01 | `test_execute_records_real_nonzero_probe_without_automatic_red` :347 | Actual exit 1 records unclassified failure; premature Green rejects; explicit judgment then actual Green succeeds. |
| E02 | `test_execute_canonical_replay_returns_original_facts_without_a_second_launch` :389 | Public canonical digest matches; reformatted request returns identical facts, one marker and unchanged state. |
| E03 | `test_execute_changed_argv_cannot_reuse_a_bound_preparation` :421 | Changed argv gets `execution-conflict`, no replacement side effect, original request still replays. |
| E04 | `test_execute_cannot_adopt_an_unbound_apply_preparation` :443 | Preexisting ordinary preparation gives `execution-unbound`, no target marker or state change. |
| E05 | `test_waiting_execute_releases_state_and_excludes_concurrent_duplicate_launch` :465 | Independent mutation completes while target waits; duplicate refuses; one launch and one final settlement. |
| E06 | `test_interrupted_execute_requires_recovery_and_cannot_relaunch_after_settlement` :493 | Windows identity-checked interruption; replay refuses, recover consumes 90 reserved seconds once, settled replay refuses. |
| E07 | `test_execute_unknown_ownership_preserves_live_work_and_requires_recovery` :527 | Missing claim birth identity causes ownership-unknown; replay refuses without ending live work; restored evidence permits finish. |
| E08 | `test_execute_adopts_a_matching_complete_receipt_without_relaunch` :618 | Real complete receipt is recorded with one new sequence and no second target marker or attempt charge. |
| E09 | `test_execute_replay_distinguishes_canonical_integer_and_decimal_requests` :640 | Canonically distinct `5` / `5.0` request rejects as conflict; original replay/state preserved. |
| E10 | `test_execute_refuses_a_real_unrecorded_receipt_with_different_argv` :661 | Actual successful different-command receipt is rejected; bound target marker remains absent. |
| E11 | `test_record_cannot_settle_a_bound_execution_using_a_real_different_command` :677 | Ordinary record rejects genuine evidence whose argv differs from bound execution. |
| E12 | `test_recover_cannot_adopt_a_bound_execution_receipt_from_different_argv` :692 | Recovery rejects genuine wrong-command receipt and does not launch bound target. |
| E13 | `test_execute_records_actual_snapshot_drift_as_ineligible_and_replays_the_failure` :741 | Target changes product bytes; record says ineligible, clears reservation, retains failure, rejects existing judgment. |
| E14 | `test_apply_cannot_consume_the_record_identity_of_a_waiting_execution` :857 | Wrong operation on bound record ID rejects without mutation; authorized record later replays original result. |
| E15 | `test_batch_record_identity_conflict_preserves_prefix_and_original_execution` :883 | Collision at item 1 preserves invocation prefix/reservation and excludes suffix; original target records once. |
| E16 | `test_another_execute_cannot_reserve_an_already_bound_record_identity` :909 | Competing execution's record ID collision rejects before preparation/side effect; original executes once. |
| H01 | `test_same_size_restored_timestamp_log_tampering_is_reaudited_on_every_entry` :708 | Old log byte flip with restored size/time rejects five new entry/replay operations; restored bytes restore original facts. |
| S01 | `test_extend_allows_an_unrelated_pending_ancestor_and_preserves_its_preparation` :557 | New dependent is planned while ancestor preparation/request/reservation survives and later records. |
| S02 | `test_include_allows_unrelated_pending_work_and_preserves_its_preparation` :571 | Disjoint helper addition succeeds; original unrelated preparation remains identical and recordable. |
| S03 | `test_revise_resets_only_the_named_active_flow_while_unrelated_attempt_records` :585 | Named active example becomes planned/released; other pending work survives unchanged and records. |
| S04 | `test_include_overlapping_cross_group_dependency_blocks_affected_pending_flow` :601 | Actual file alias/parent overlap added to another snapshot group rejects with barrier and unchanged state. |
| S05 | `test_revise_detects_changed_criterion_in_an_unlisted_pending_preparation` :770 | Unlisted prepared criterion change rejects revision and preserves pending accounting. |
| S06 | `test_revise_uses_refreshed_adopted_inputs_before_preserving_an_unrelated_next_attempt` :787 | After include and real regression refresh, unrelated revise keeps closed history and next preparation recordable. |
| S07 | `test_revise_checks_a_pending_formal_baseline_even_when_historical_inputs_match_again` :826 | Restoring historical criterion bytes still differs from pending formal baseline; revise gets attempt-pending. |
| S08 | `test_revise_detects_changed_inputs_of_an_unlisted_open_example_without_receipts` :937 | Changed opening criterion without any receipt makes omitted active example block revision. |
| S09 | `test_revise_blocks_a_pending_ordinary_downstream_dependent` :958 | Direct ordinary dependent's pending work blocks prerequisite revision; inspect unchanged. |
| S10 | `test_revise_blocks_a_pending_gate_consumer_without_an_ordinary_dependency` :977 | Real released gate consumer's pending work blocks direct prerequisite revision; inspect unchanged. |
| S11 | `test_extend_cannot_change_scope_while_a_final_attempt_is_pending` :1008 | Disjoint new member still gets attempt-pending while final prepared; no mutation. |
| S12 | `test_include_cannot_change_dependencies_while_a_final_attempt_is_pending` :1022 | Dependency addition during pending final gets attempt-pending; no mutation. |
| S13 | `test_revise_cannot_reset_completion_while_a_final_attempt_is_pending` :1036 | Revision during pending final gets attempt-pending; no mutation. |
| S14 | `test_revise_uses_a_successful_formal_refresh_before_preserving_unrelated_next_work` :1092 | Real adopted formal refresh supersedes old baseline; unrelated revision keeps next preparation recordable. |

## Inherited compatibility evidence

These are current test-source mappings, not carried-forward historical passes. They establish meaningful compatibility examples, but cannot silently close new-wrapper or new-scope behavior gaps.

| Protected contract | Named inherited tests and evidence |
| --- | --- |
| Original CLI/schema/models/idempotency and shared budgets | `test_init_preserves_this_runs_explicit_ten_role_choices` reads the exact model table; `test_repeated_identical_init_preserves_the_original_run` checks created=false and identical state; `test_invalid_event_schema_returns_json_without_consuming_sequence_or_budget` checks malformed apply rejection plus a valid retry; `test_concurrent_flows_cannot_both_spend_the_final_attempt` checks one reservation; `test_independent_concurrent_successes_and_busy_retries_are_never_lost` checks unique attempts, ordered counts and retries. |
| TDD identities and stale criteria | `test_matching_real_green_closes_the_behavior_and_releases_its_flow` observes mode/attempt history/budget; `test_first_green_uses_the_existing_capability_exit_without_a_fake_red` observes existing mode; `test_changed_test_bytes_cannot_reuse_the_previous_valid_red` and `test_changed_criterion_cannot_use_old_green_for_its_first_close` reject stale pairing; rejudging-old-probe tests preserve historical completion. |
| Scope ownership, identity and plan validation | `test_new_run_and_state_cannot_reset_the_existing_scope_budget`, `test_windows_spec_case_alias_cannot_start_a_new_scope_budget`, and `test_windows_duplicate_source_aliases_cannot_mint_another_scope_budget` reject alternate active scope identities; `test_windows_case_alias_does_not_hide_parent_child_write_overlap` rejects overlapping writes; `test_init_rejects_an_indirect_cycle_through_a_gate_consumer` rejects the graph; `test_include_existing_and_new_dependency_rejects_without_partial_append` proves atomic include rejection and corrected retry. |
| Historical close and direct scope invalidation | `test_extend_adds_the_next_example_without_resetting_completed_history` compares history/failures/budget; `test_extend_invalidates_old_final_scope_even_after_new_existing_example_closes` rejects old final despite identical HEAD/bytes; `test_include_shared_helper_preserves_closed_history_and_refreshes_formal_proof` rejects old qualification/final, then observes helper in new request/captures and current final success; `test_revise_with_new_qualification_still_requires_completing_the_changed_behavior` rejects formal preparation before re-completion. |
| Gates, formal qualification and same candidate | `test_current_formal_gate_evidence_releases_the_declared_consumer` observes released consumer admission; `test_new_consumer_test_outside_gate_inputs_can_open_on_the_released_head` admits unrelated dirty consumer tests; `test_final_execution_and_both_review_heads_finish_the_same_candidate` reaches ready at the tested HEAD; `test_another_commit_cannot_reuse_the_previous_final_execution` rejects old final; `test_historical_gate_survives_consumer_commit_and_final_uses_the_new_head` audits historical release and uses new full-scope formal evidence. |
| Failure retention, ineligible receipts and recovery | `test_record_settles_real_snapshot_change_without_granting_existing` checks actual duration settlement, immutable receipt, retained ineligible failure and rejected judgment; `test_later_formal_failure_requires_diagnosis_and_new_success_before_finish` rejects old success/explanation-only and preserves failure through new proof; `test_finish_cannot_ignore_another_pending_final_attempt` rejects pending final. Native recovery cases check live reservation, dead-controller conservative settlement once, complete receipt reconciliation once, unknown ownership preservation, and `test_cancelled_formal_attempt_consumes_the_formal_failure_limit` checks refusal when the formal allowance is exhausted. |
| Real execution, logs, snapshots, ownership and deadline | `test_real_success_publishes_exit_receipt` observes actual target marker/argv/cwd/receipt; `test_real_nonzero_keeps_target_code_and_returns_failure` preserves target 7 behind wrapper 1; `test_binary_logs_preserve_bytes_and_publish_independent_hashes` compares real binary bytes/digests and output separation; `test_snapshot_hashes_actual_files_directories_and_missing_paths` checks independent canonical captures; `test_timeout_stops_owned_tree_and_preserves_unrelated_process` checks actual owned descendants exit, unrelated process lives, timeout receipt; `test_target_arguments_keep_shell_metacharacters_literal` compares argv and absent shell side effect. Progress, formal clean/HEAD drift, native birth identity, controller death, bootstrap-result, and bounded Git-helper tests remain standalone runner coverage. |
| Evidence integrity | `test_record_rejects_a_real_receipt_whose_log_bytes_were_changed` rejects a tampered real log without settlement; `test_verify_and_recover_reject_a_changed_cancellation_claim` rejects changed historical claim. These do not prove every old request/receipt/anchor/state/hash-chain corruption branch; SC-3 limits the full audit claim. |

## Numbers, acceptance sources, and limits

No fixed speedup ratio appears in the new correctness tests. Exit 0/2, schema integer 1, sequence increments of one per original event, zero-based failed index, exact original/replayed state, and expected error codes come directly from the public contracts. One/two/three event or attempt counts follow the concrete operations in each scenario, not a performance goal. The fee values 0/10/20 are independently specified toy fixture outcomes. The E02 SHA uses the public canonical JSON rule; E09's `5` versus `5.0` distinction follows that same serialized identity rule and adds no business deadline.

The five-second execution reservation is an explicit fixture input, so equality to five and conservative charging are accounting assertions. The inherited defaults (12 attempts, two formal failures, 60 seconds) and the waiting scenario's 180-second run budget are fixture capacity, not acceptance SLAs. `start_waiting_execute` uses a 90-second real reservation to contain a socket-waiting target while bounded control CLI calls execute; E06's seconds-used=90 is the specified interrupted-reservation accounting rule. No actual 90-second wait is required for success.

The ten-second monotonic startup interval bounds accept plus the target's `R` acknowledgment. Its start is after process creation, so it is an evidence wait rather than measured end-to-end launch latency. The inherited `cycle()` 15-second subprocess limit is a whole CLI harness cap, including new execute commands called synchronously. The waiting helper's separate 15-second collection limit starts after the release signal; its 10/5-second cleanup waits bound controller cleanup. E06's native `5000` ms wait is a five-second evidence bound after terminating the identity-checked test-owned controller. These limits do not prove §6 speed. Their scheduling sufficiency and failure cleanup are the other review axis's responsibility; no new unsupported business timing requirement was found on this axis.

Next action: the coordinator should retain the passing source-level mappings, route SC-1 through SC-4 to the independent test author, and qualify the revised snapshot plus its dependency closure after the separate validity review and neutral execution checkpoint. §5 requires authorized workflow/context evidence; §6 requires the specified paired measurements. Neither can be replaced by the reported Green count.

## Correction history

Version 1 adjudicated the initial incomplete-helper response as missing and recommended observing E06's first response after killing its claim controller. It also recognized the dirty formal preflight seam but did not credit its existing exit-2 / `ok:false` / absent-target / absent-receipt / retained-pending assertions as representative initial failure coverage.

Version 2 retracts that portion of SC-2. On a narrow correction request, this reviewer reread only the immutable `docs/validation/implement-spec-v3-performance-20261103/independent-tests/37-case-test-cycle-performance.py`, lines 179–217 and 493–525, and verified its SHA-256 is the original `f23993b2dabc2c907b2d5b461fe95674b280df66a8014c426a12fa146c841dda`. The public contract permits a specific runner/evidence error and does not require a separate surviving outer process. Requiring JSON from E06 after the forcibly terminated process could impose an extra process architecture. The initial failure case is therefore covered by the existing dirty-formal helper; E06 remains recovery evidence only. Timeout propagation is still missing, no-claim replay remains partial, and all other version-1 findings and the overall full-coverage verdict are unchanged. No current edited candidate, production source, or new execution evidence was read.
