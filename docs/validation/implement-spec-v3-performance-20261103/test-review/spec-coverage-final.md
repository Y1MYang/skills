# Performance-contract final test review — Spec/coverage axis

Version 1, 2026-11-03. This continues the same full qualification through a direct, test-only delta from 37 to 43 cases.

**Spec fidelity: pass. Spec/coverage reconciliation for the bounded final correctness packet: pass, with the declared nonblocking scenario limits below. No material new test-contract defect found.** The four actionable findings from the prior review are resolved by the six additions and the recorded E06 correction. This is not a claim of exhaustive branch coverage or a passing product run. The Validity/standards axis and coordinator reconciliation remain separate. Actual §5 workflow compliance, §6 speed, and independently observed final product execution remain **unverified** here; this axis alone does not grant whole-spec blessing.

## Exact comparison and carried evidence

Candidate HEAD remains owner-pinned `996eb268bf0cf3c31b19cbe2c1445f1cff06cb1d`. The comparison was direct file-to-file, not merge-base or three-dot:

| Snapshot | SHA-256 |
| --- | --- |
| Base: `docs/validation/implement-spec-v3-performance-20261103/independent-tests/37-case-test-cycle-performance.py` | `f23993b2dabc2c907b2d5b461fe95674b280df66a8014c426a12fa146c841dda` |
| Candidate: `docs/validation/implement-spec-v3-performance-20261103/independent-tests/43-case-test-cycle-performance.py` | `5b726580139693d62bd0ee2021473a2e14e0e30d6d19d42dbeb6ea0e294c22f1` |

Both hashes were independently checked. The allowed test-only diff adds exactly six methods at the end of the same class; the 37 earlier methods, imports, and shared helpers are unchanged. No production diff was read. The current main candidate was not needed: the coordinator reports its bytes match the immutable candidate.

The prior [Spec/coverage report, version 2](spec-coverage.md) contains the complete 37-ID mapping, inherited compatibility mapping, standards inventory, numeric analysis, and retained version-1/correction history. Its original full-coverage failure is **not** reused as a qualification. Only its matching, unaffected source-level mappings are retained; the unresolved material findings were re-adjudicated against the six new methods in this report.

The following public contracts and shared tests were rehashed and match the prior report exactly:

| Input | SHA-256 |
| --- | --- |
| Performance contract revision 1 | `b6ede11f51d5c3a0f509d97e9026a0caadcb2900fb8cc14d10c223c5d2a48d0b` |
| Runtime contract | `0a6e2285afd62fc3789bd23874ebcf6c415a5b873901e3e5bec61c19af59f1fb` |
| Runtime ledger reference | `88491ab095eee1b1c89d9a4a898f40c8a67aff37b72a72d7b1440c307a54309f` |
| `test_cycle.py` | `c6c7a3ff20fa75ed8c51a6fe677a3e24ca3a43a2cd216ce1b07bcdc6d1debd53` |
| `test_cycle_proofs.py` | `5c611692402cc915ae5000a4a64b101249b0f3f672691bbf7061cb02a3696deb` |
| `test_cycle_recovery.py` | `a6ef2b3a81b20499cc8f16aa61de3a38ef869101253e4413ab2e0b5616519245` |
| `test_cycle_safety.py` | `b1c1fcdb4f14bfc4d1981ea8f1abcd8dd2434282b255b736381260d2123e0744` |
| `test_run_command.py` | `12f9afdcb6523d4dfefa7034204b466410f1734d52f8499b512434a7b92445b5` |

Full paths for these unchanged inputs are in the prior report. The dependency closure remains the same test-owned CLI/setup, toy fixture, standalone-runner, and native identity helpers. The six additions introduce no new dependency module, private observation seam, or changed helper behavior. The new direct dependencies are public filesystem hardlink identity, genuine receipts, existing socket acknowledgment, and public CLI results.

Independence is unchanged: no production source, production diff, raw runtime log, private review, imports, test collection, or execution was read or performed. This review uses source reasoning only. No new child reviewer was dispatched.

## Six added requirement-to-test mappings

Line numbers refer to the immutable 43-case candidate named above.

| ID and named test | Requirement and observable evidence | Assessment |
| --- | --- | --- |
| **S15**, line 1136: `test_formal_refresh_with_hardlink_equivalent_test_paths_preserves_unrelated_next_work` | §4 actual filesystem identity and applicable refreshed formal baselines. Two test paths at different depths are verified by `os.path.samefile` to name the same file. Both examples obtain genuine completion; the deeper declaration gains a stable helper; a real formal run covers the gate and is recorded/released. After a new deeper attempt is prepared, unrelated revision succeeds, keeps the older deeper example closed, preserves the exact pending request bytes/list/budget and active flow, and allows the original preparation to run and record without a new attempt. | Pass. Tests a public identity distinction and accepted-proof baseline, not an internal projection algorithm. Complements S06/S14. |
| **E17**, line 1224: `test_execute_unknown_envelope_field_rejects_before_preparation_and_leaves_ids_usable` | §3 exact outer envelope and validation before preparation. Unknown outer field produces exit 2, `ok:false`, a structured error, no target marker, and identical inspect state. The corrected request reuses the same prepare/record IDs, actually launches, records exit 0, advances exactly two sequences, and uses one attempt. | Pass. Closes representative precommit validation with a positive corrected retry. |
| **E18**, line 1254: `test_execute_records_a_real_timeout_and_replays_without_relaunch` | §3 exit 0 means actual receipt recorded, including timeout. A target writes its launch marker then deliberately waits beyond its three-second allowance. `execute` returns exit 0/`ok:true`, timeout/null exit facts; its actual receipt agrees and reports complete cleanup. Inspect shows the original two events, settled reservation, actual receipt-duration charge, and unresolved unclassified failure. Replay returns identical facts/state and one launch marker. | Pass. Closes timeout propagation through the new helper; does not infer it from standalone runner tests. |
| **H02**, line 1295: `test_execute_reaudits_old_receipt_bytes_after_the_acknowledged_target_finishes` | §1 full audit across external execution and §3 fresh audit before record. After a prior real receipt is recorded, the new target acknowledges live execution through the existing socket. The test changes only the older receipt's bytes by appending JSON whitespace, then releases the target. A real successful new receipt exists, but the helper returns exit 2/error. Restoring old bytes leaves inspect equal to the pre-record state; replay records the already completed attempt with exactly one new event, no new attempt, and no relaunch. | Pass. Causally distinguishes post-target audit from entry-only audit, verifies an actual adopted-receipt byte change, and proves preserved durable prefix. |
| **S16**, line 1339: `test_revise_propagates_through_an_ordinary_then_gate_edge_to_pending_terminal_work` | §4 repeatedly computed closure over ordinary and gate edges. Completed upstream → completed middle → legitimately released gate → pending terminal is built with actual public events. Revising only upstream returns `active-work` or `attempt-pending` and leaves inspect unchanged. Current declared bytes were not changed, so a changed-file seed is not the intended explanation for the far-end barrier. | Pass. Distinguishes direct-only impact expansion from the required mixed-edge closure. |
| **S17**, line 1376: `test_accepted_revision_preserves_downstream_history_but_requires_new_gate_proof_at_unchanged_bytes` | §4 accepted revision resets only explicitly named completion and invalidates affected downstream gate reliance independently of file drift. After a legitimate middle gate proof/release, upstream-only revision succeeds; upstream returns to planned while unlisted middle keeps state/mode/attempt history, budget and old receipt bytes. Upstream is genuinely re-completed without changing clean HEAD. Old release reuse and terminal open both reject without mutation. New qualification, real formal run/record and release allow the same terminal open; middle history and old receipt remain. | Pass. Closes accepted unchanged-byte downstream gate invalidation with a valid refreshed-proof positive control. |

The complete current mapping is the unchanged 37 rows in the prior report plus these six rows: B01–B06, E01–E18, H01–H02, S01–S17, totaling 43 named examples. These counts identify the reviewed set, not execution results.

## Prior finding reconciliation

| Prior finding | Final adjudication |
| --- | --- |
| **SC-1: new input/reserved identity boundaries** | The actionable missing representative execute-envelope/precommit case is resolved by E17. Original B03/B05, B01/B06 and E14–E16 remain valid coverage of batch rejection/replay and protected record identity across all three entry mechanisms. Duplicate batch-ID, wrong-attempt reserved-record, and additional parser variants remain declared nonblocking scenario limits; no matrix is requested. |
| **SC-2: execute timeout / incomplete / no-claim paths** | Timeout settlement and replay are resolved by E18. The prior version-2 correction stands: the existing dirty-formal helper already observes representative initial receipt failure with exit 2, `ok:false`, absent receipt/target, and retained preparation. E06 is unchanged and remains forced-death/recovery evidence; no JSON is demanded from a process the test deliberately killed. No-claim replay remains a declared nonblocking partial branch. |
| **SC-3: fresh post-target audit** | Resolved by H02's acknowledgment → old receipt byte change → target completion → rejected record → restored evidence → record-only replay chain. H01 separately retains same-size/restored-mtime tamper coverage at new entry/replay boundaries. Deterministic proof of a fresh audit between two items in the same batch remains a declared nonblocking observation limit; no flaky race or private hook is required. |
| **SC-4: repeated closure and accepted invalidation** | Resolved for the actionable guarantees by S16 and S17. S15 strengthens the actual-identity/refreshed-formal-baseline coverage. S01–S14 and inherited compatibility mappings remain unchanged. Other scope combinations remain sampled, as explicitly recorded below, rather than becoming new mandatory cases. |

The move from the prior failure to this qualified pass is based on new discriminating public observations, not on reported Green results, a reset of the previous findings, or an assumption that the old full review passed. No unresolved missing business decision was discovered for these six cases.

## Whole public-contract reconciliation

| Contract area | Final source-level coverage conclusion |
| --- | --- |
| §1 compatibility, original events, budgets and semantic boundaries | Existing mapping retained: B01/B02/B06 and E01/E13 distinguish original event/accounting semantics and semantic judgment from execution. Inherited CLI, stale criterion, scope ownership, formal same-candidate, recovery and process tests still map to their public observations. Actual model/context authority is separate §5 evidence. |
| §1 audit freshness and adopted evidence | H01 plus H02 now cover both new entry/replay tamper detection and the previously missing deterministic external-execution boundary. Audit of every material type and every internal batch boundary is not claimed exhaustively. |
| §2 ordered finite batch and replay | B01–B06 plus E15 retain successful original events, durable partial prefix, repaired suffix, changed-content conflict, unknown envelope/header rejection, unchanged accounting and reserved-ID rejection. Additional header permutations and batch-specific contention/interleaving are nonblocking limits. |
| §3 validated bound execution and exact identity | E17 closes representative precommit envelope validation; E02/E03/E09 retain canonical request and immutable argv identity; E04 retains unbound apply rejection; E14–E16 retain record identity protection across apply/batch/execute. |
| §3 real execution, failures, recovery and replay | E01/E13/E18 cover nonzero, ineligible and timeout settlement. E02/E08 cover completed and complete-unrecorded replay; E05/E07 cover live/unknown exclusion; corrected E06 covers forced interruption and settled replay; the dirty-formal helper covers representative initial receipt failure; E10–E12 reject wrong-command evidence. No-claim replay remains partial. |
| §3 concurrent state operation and fresh record | E05 proves independent state mutation returns while the acknowledged target is waiting, with no duplicate launch. H02 proves a fresh post-target audit before settlement. These are causal concurrency/integrity observations, not millisecond SLA or speedup assertions. |
| §3 existing runner behavior and derived execution inputs | Existing standalone runner coverage retains actual argv/cwd, logs/snapshots, progress, formal state, deadlines, containment and ownership. New execution cases observe genuine prepared work and formal preflight. Wrapper propagation is directly tested for the newly material outcomes; every standalone property is not separately re-exercised through execute. |
| §4 local edit admission and applicable baselines | S01–S08/S14 retain unrelated development preparation preservation, active/pending/open/formal baseline detection, ancestor exclusion, existing-path overlap and refreshed proof behavior. S15 adds hardlink-equivalent path-depth formal refresh with later recordable original preparation. |
| §4 affected closure and barriers | S09/S10 retain direct ordinary/gate barriers; S16 adds repeated mixed-edge closure; S11–S13 retain pending-final rejection for all three edits; S07 retains affected pending formal protection. |
| §4 accepted edits, historical completion and stale gates | S17 adds accepted upstream revision with preserved unlisted downstream history, stale unchanged-byte gate reliance, and current proof restoring consumer admission. Inherited include/extend/revise tests retain direct final invalidation and re-completion semantics. |
| §4 plan/path/root safeguards and workflow workspace discipline | Existing tests retain complete-plan examples, cycles, atomic include, scope anchors and actual-path alias checks. Runtime tests do not establish that real agents declared every dependency, used disjoint writes, integrated branches before evidence, or maintained the candidate freeze. Those remain agent evidence responsibilities, not assertions silently supplied by fixture strings. |
| §5 persistent workflow and independent validation | Mechanical ordering, explicit judgments, first-Green mode and independent acceptance scenarios are mapped. Actual continuing assignments, one-example chronology, selected-model dispatch, context isolation, semantic reports, dispatch-only main work and fresh independent review contexts remain **unverified by this axis**. |
| §6 speed evidence and claim limits | **Unverified**. No paired baseline/candidate benchmark artifacts or workflow elapsed measurements were reviewed. The correctness suite does not assert a fixed ratio and cannot prove acceleration. |

## Declared limits and numbers

The bounded packet resolves the actionable material gaps; it does not make untested variants covered. Remaining nonblocking limits include parser/record-collision permutations, batch-created unbound adoption, no-claim replay, audit between items of one batch, additional tamper carriers, and further combinations of scope seeds, missing-path identity, unlisted affected flows, and disjoint pending gate-formal admission. These product guarantees remain binding. The coordinator explicitly retained these as declared limits for this final packet; this report does not request more tests or convert them into observed success.

No new business timing requirement appears. E18's **3 seconds** is the selected fixture execution allowance; **30 seconds** is a deliberately longer target wait that forces the timeout outcome. The inherited **15-second** whole-CLI harness cap accommodates that allowance, the contract's maximum **5-second** cleanup, and startup/observation margin. Its accounting equality uses the actual public receipt duration, not a claimed performance measurement. H02 uses the existing acknowledgment/collection bounds and verifies order through a socket signal, not a guessed delay. Other new numbers count the test's concrete events, attempts or byte changes. Exact error/result/count assertions follow the unchanged public contract and fixture actions; no unsupported extra restriction was found on this axis.

## Execution facts and next gate

Owner-supplied neutral facts for this delta: S15 reportedly had actual Red (exit 2 when success was expected), then Green, with six affected checks in 14.673 seconds; E17 first-Green in 0.878 seconds; E18 first-Green in 3.661 seconds; H02 first-Green in 1.374 seconds; S16 first-Green in 4.431 seconds; S17 first-Green in 7.238 seconds. These are runner reports, not independently observed results here and not speed-comparison evidence. No final whole-43 or full-suite execution result was supplied to this reviewer at this report version. The earlier 127-case run belongs to the older snapshot and is not substituted for the final candidate run.

Next action: coordinator reconciles this qualified Spec/coverage pass with the separate Validity/standards result, then records the neutral final-candidate execution checkpoint. Actual workflow compliance and any acceleration claim require their own authorized evidence. No further test additions are requested by this axis for the agreed packet.

## Coordinator neutral execution addendum

After this axis completed, the root/runtime owner supplied final43 results: 43 pass, zero skips/failures/errors in 78.799 seconds, with candidate SHA `5b726580139693d62bd0ee2021473a2e14e0e30d6d19d42dbeb6ea0e294c22f1` unchanged before/after. The owner also reported its runtime identity unchanged. Only neutral counts/pins were supplied; no raw log was opened. This fills the supplied final43-result gap above without changing the source-level verdict or claiming independently observed execution, a broader inherited-suite rerun, or performance acceleration. See the coordinator's `qualification-final.md` for full reconciliation and evidence provenance.
