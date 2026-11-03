# Final performance-test validity and standards axis

Version 1, 2026-11-03. **Verdict: PASS for the reviewed 43-case assertion mechanisms. No confirmed invalid predicate or new material test defect was found.** This completes the validity delta within the same ongoing full qualification. Spec/coverage reconciliation and final product execution remain separate conclusions; this report alone does not grant whole-spec blessing or establish performance acceleration.

## Pinned scope and continuity

The direct base-to-candidate comparison used these immutable test snapshots, with both hashes independently verified:

| Snapshot | SHA-256 |
| --- | --- |
| `independent-tests/37-case-test-cycle-performance.py` | `f23993b2dabc2c907b2d5b461fe95674b280df66a8014c426a12fa146c841dda` |
| `independent-tests/43-case-test-cycle-performance.py` | `5b726580139693d62bd0ee2021473a2e14e0e30d6d19d42dbeb6ea0e294c22f1` |

Paths are relative to `docs/validation/implement-spec-v3-performance-20261103/`. The candidate HEAD remains `996eb268bf0cf3c31b19cbe2c1445f1cff06cb1d`. Comparison was an explicit test-only `git diff --no-index`, not a merge-base comparison. It adds exactly six methods, S15, E17, E18, H02, S16 and S17, at candidate lines 1136–1453; it changes no old method, helper or import. The coordinator independently reported that the current main test file has the candidate digest; this reviewer read the immutable archive.

Public inputs independently rechecked unchanged:

| Input | SHA-256 |
| --- | --- |
| Performance contract revision 1 | `b6ede11f51d5c3a0f509d97e9026a0caadcb2900fb8cc14d10c223c5d2a48d0b` |
| Runtime contract | `0a6e2285afd62fc3789bd23874ebcf6c415a5b873901e3e5bec61c19af59f1fb` |
| Public runtime ledger | `88491ab095eee1b1c89d9a4a898f40c8a67aff37b72a72d7b1440c307a54309f` |
| Shared `test_cycle.py` | `c6c7a3ff20fa75ed8c51a6fe677a3e24ca3a43a2cd216ce1b07bcdc6d1debd53` |
| Shared `test_cycle_proofs.py` | `5c611692402cc915ae5000a4a64b101249b0f3f672691bbf7061cb02a3696deb` |
| Shared `test_cycle_recovery.py` | `a6ef2b3a81b20499cc8f16aa61de3a38ef869101253e4413ab2e0b5616519245` |

Carry-forward is limited to the matching unaffected **mechanism evidence** in [standards-validity.md](standards-validity.md), version 2, including its E06 correction. The earlier failed full coverage reconciliation supplies no inherited full qualification. The same test-review acceptance rules, TDD testing/mocking standards and pstack behavior/measurement principles apply. Shared CLI, real runner, temporary-workspace, socket and native-identity helpers were already read in that review; their unchanged digests and unchanged call semantics preserve that evidence.

This reviewer remained implementation blind. Only the bounded test snapshots, approved public contracts, prior own report and supplied neutral runner facts were used. No production source/diff, raw runtime logs, test collection/import or product execution was accessed. Assessment used source inspection and counterfactual reasoning, with no executable mechanism model needed. Only this report was written for this delta.

## New mechanism decisions

Line references below use the immutable 43-case candidate.

| Case and contract source | Observation and counterfactual assessment | Result |
| --- | --- | --- |
| **S15, 1136–1222; §4 actual path identity, refreshed adopted proof, unrelated pending preservation** | Creates real hardlinks at different depths and checks `samefile` before and after the fixture commit. Both example paths first have real execution history; a later formal proof covers the declared scope after dependency inclusion. An unrelated revision must preserve the deeper example's historical close, pending request bytes, reservation and active work, followed by a real execution/record under that original preparation. This catches a false affected-flow rejection caused by retaining an obsolete or incorrectly projected baseline. The test depends on a filesystem supporting these real hardlinks; it does not claim other filesystem behavior. | **Pass** |
| **E17, 1224–1252; §3 exact execute envelope and pre-commit validation** | Adds only an unknown envelope field to an otherwise valid request. Rejection requires exit 2, structured failure, no target marker and unchanged public ledger state. Removing that field with the same IDs then produces one real launch and exactly two events/one attempt. This positive control distinguishes schema rejection from an unusable command fixture, and exposes ID consumption or premature preparation. No exact error code is invented where the contract does not prescribe one. | **Pass** |
| **E18, 1254–1293; §3 actual timeout receipt, accounting and replay** | A target writes an append marker then deliberately waits beyond its prepared allowance. Execute must succeed as a recording operation while both root result and actual receipt report timeout/null exit, complete cleanup, unresolved failure and released reservation. The ledger charge must equal that receipt's public duration; this is a public accounting relationship, not an expected value generated by the tested accounting calculation. Exact replay preserves state and one marker. A helper that treats a published timeout as an unrecorded error, reports target success, loses the failure or relaunches fails these assertions. | **Pass** |
| **H02, 1295–1337; §1/§3 fresh audit after external execution** | First adopts a real receipt in another flow. A second actual target acknowledges that it is waiting; only then does the test append whitespace to the old adopted receipt bytes. After release, the target must have a real zero-exit receipt, while execute rejects and leaves the pending transition unrecorded. Exact-byte restoration permits the same execution to record with one sequence increment and no second marker. Thus malformed target execution, an early pre-launch failure, an old marker, and unconditional rejection cannot satisfy the combined assertions. The changed JSON remains semantically equivalent, making this specifically an adopted-byte integrity check. Restoration is in `finally`. | **Pass** |
| **S16, 1339–1374; §4 repeated ordinary/gate downstream closure** | Establishes completed upstream and middle examples, a current middle gate release, and a pending terminal consumer. Only the upstream ID is revised. The public affected-work rejection and unchanged ledger are required across an ordinary edge followed by a gate edge. No file change or active middle example is needed to create the pending terminal barrier. This supplies the mixed-chain example without inspecting how the closure is computed. | **Pass** |
| **S17, 1376–1453; §4 selective historical reset and conservative gate invalidation** | An accepted upstream revision returns only the named example to planned while retaining middle state/mode/attempt history, budget and old receipt bytes. The upstream is completed again through explicit existing judgment and real regression, and unchanged HEAD/clean worktree are confirmed before testing stale gate reuse. Both old release reuse and consumer open fail; after new qualification/formal proof/release, the same consumer open succeeds. This excludes an incomplete-upstream or dirty-candidate explanation for rejection and proves that unchanged bytes alone cannot preserve the affected gate. | **Pass** |

The new tests retain real public effects rather than private helper calls: target markers, actual receipts, persisted request bytes, current public state, and consumer admission. Test-owned review declarations remain mechanical fixture inputs, not claims that the product received an independent review. Assertions are derived from the public contracts and fixture requirements, not production behavior.

## Timing, cleanup and remaining limits

E18's **3-second execution allowance** begins at runner preflight and covers launch/execution; the deliberately longer **30-second target sleep** creates the timeout condition rather than an evidence-polling delay. The inherited **15-second command wall cap** contains the allowance, the contractual maximum **5-second cleanup window**, and local wrapper/audit margin. It is not a measured business SLA or speed threshold. The marker requires actual target launch, so a preflight-only timeout cannot falsely satisfy the test. A severely delayed environment could fail that fixture condition; the supplied small-workload result supplies no indication of that problem, and no allowance change is warranted.

H02 reuses the bounded live-target handshake: monotonic 10-second acknowledgement wait, 90-second prepared reservation, and 15-second post-release result collection. There is no polling or progress-based deadline renewal. The mutation is ordered after the actual target acknowledgement and before release, so scheduling luck is not used to place the corruption around execution. Shared cleanup releases the test connection and bounds helper collection; receipt bytes are restored even if assertions fail. The scope cases have finite sequences of existing 15-second CLI/Git caps and 20-second standalone runner caps, with 5-second fixture execution reservations.

The prior E07 aggregate-cap arithmetic remains a **nonblocking harness-fit risk**, not an observed defect, performance failure or reason to increase budgets. The prior E06 finding stays withdrawn: the claimed controller may be execute itself, so forcibly terminating it cannot require final JSON. The unchanged dirty-formal-preflight helper still supplies a representative initial no-receipt error response case.

These finite scenarios do not prove every possible corruption material, filesystem mode, failure variation or interleaving. H02 adds a deterministic post-target receipt-byte audit observation; it does not claim exhaustive audit-boundary coverage. This bounded delta found no confirmed invalid predicate or new material bug requiring matrix expansion. Whole-contract coverage belongs to the coordinator's separate full reconciliation.

## Execution facts and caller gate

The coordinator supplied the following neutral facts: S15 genuine Red (exit 2 where 0 was expected) followed by Green and six affected checks in 14.673 seconds; E17 first-Green in 0.878 seconds; E18 first-Green in 3.661 seconds; H02 first-Green in 1.374 seconds; S16 first-Green in 4.431 seconds; S17 first-Green in 7.238 seconds. These are **supplied observations, not independently executed or inspected by this reviewer**. They are not comparable baseline/candidate speed evidence and do not establish end-to-end acceleration.

No final whole-43-case or full-suite result was supplied for this snapshot. **Observed final product success: unverified here. Spec/coverage axis: not performed by this reviewer.** The coordinator may use this passing validity axis with its current pinned coverage reconciliation, then complete the separate final execution and comparative performance gates.

## Coordinator neutral execution addendum

After this axis completed, the root/runtime owner supplied final43 results: 43 pass, zero skips/failures/errors in 78.799 seconds, with candidate SHA `5b726580139693d62bd0ee2021473a2e14e0e30d6d19d42dbeb6ea0e294c22f1` unchanged before/after. The owner also reported its runtime identity unchanged. No raw log was opened; only these neutral facts were consumed. This fills the supplied final43-result gap above while retaining the distinction from independently observed execution, a broader inherited-suite rerun, and comparative speed evidence. The validity verdict is unchanged.
