# Execution, evidence, and recovery

Read before allocating run resources, executing tests, diagnosing a failure/timeout, releasing resources, or resuming an interrupted v3 run.

Integrator and Runner use the bundled [runtime ledger and command interface](runtime-ledger.md) for plan initialization, evidence events, bounded commands, gates, and recovery. Integrator remains the state writer. Runner specifies the command, limits, expected failure, and scope; Integrator can invoke the bounded mechanical helper with that prescription. Runner owns interpretation of the receipt and logs, including actual Red causality and preparation of neutral test-side facts. Separate selected models retain these authorities even when one tool performs preparation, execution, and recording.

## Evidence and limits

Use v3's run records to bind run/flow/example or checkpoint identity; requirement and contract versions; exact test/helper/fixture/configuration snapshots; product baseline and result versions; command and scope; owner/model; results/log pointers; and resources. Red and Green need distinct immutable product bindings. A mutable workdir or a success flag cannot represent historical evidence. Raw logs stay with Runner; the blind side receives only allowed neutral summaries with provenance.

Before execution, record a finite command deadline, bounded progress/status interval, stop scope, and the run's finite execution budget, using project configuration, comparable runs, or a stated estimate. Agent-defined issue-local diagnostic allocations are separately recorded and [autonomously renewable on new evidence](diagnostic-budgets.md); they are not fixed run limits. Separate harness limits from business SLAs and acceptance assertion deadlines. Include setup, teardown, descendants, and log collection in containment. A command cap establishes containment, not the correctness of timing assertions or complete acceptance.

Return control regularly for progress and communication; do not use unbounded waits. Runner reports observed progress and stale/failed worker or phase when the project exposes it. Verify that the execution mechanism can bound and stop owned work on the actual platform before relying on it for formal acceptance. Platform adapters require their own validation; a Linux `/proc` implementation is not proof of Windows support. If required containment or ownership cannot be established, keep the affected run unverified and report the limitation.

The runtime checks records and version relationships. Human/agent judgments with cited evidence still establish requirement meaning, actual Red causality, and test independence; exit codes and self-declared states cannot prove those semantics.

Use the [execution helper](runtime-ledger.md#execute-and-record-one-attempt) for one prepared command and its actual record, and [batch](runtime-ledger.md#batch-decided-events) for already-supported event decisions. Both preserve the original event history and checks. A successful helper call means the receipt was recorded; Runner still determines what the actual outcome supports. Keep semantic judgment outside a batch until its evidence exists.

## Failure classification and repair

Treat valid expected Red as a normal development result. It consumes declared execution time/resources, not the formal acceptance repair allowance. Every other failure keeps its original evidence and is classified before repair:

| Class | Owner and next step |
| --- | --- |
| Implementation defect | Implementer uses the discriminating evidence to repair product code; rerun affected development checks or the required formal scope. |
| Test/contract defect | Blind Coverage audit assesses the neutral question; blind Test author repairs the tests after authoritative adjudication, then refresh qualification and execution. |
| Fixture/environment | Appropriate test-side or environment owner fixes the demonstrated cause; preserve oracle independence and rerun affected evidence. |
| Ineligible snapshot change | Runner preserves the complete execution facts and charges actual duration, while the owner diagnoses the changing input. Refresh inputs/evidence through the runtime repair path; the attempt cannot prove Red or success. |
| Missing business decision | Architect identifies the exact requirement choice for the user; pause only dependent work. |
| Unknown | Runner/owner performs the next bounded discriminating check. Do not presume the product is defective or retry until green. |

Each repair attempt states the hypothesis, distinguishing check, new evidence, classification, owner, and remaining budget. On timeout/hang, distinguish the business event, evidence wait, harness deadline, and environment. Send sanitized facts to a fresh failure-scoped test-review when the test contract is uncertain; retain implementation diagnostics outside that review.

At an agent-defined local count/time boundary, review the evidence and renew the bounded allocation under [local diagnostic budgets](diagnostic-budgets.md) before the next check. Record preflight-only failures separately; they do not spend a diagnostic-target slot. Preserve their real execution costs and any existing cycle charges. Routine renewal within the authorized task does not require user approval.

If new evidence is insufficient, route a bounded cause review or distinguishing environment check to the appropriate owner or Expert, and continue independent work. Stop an affected execution when a real constraint prevents it: an exhausted run budget, an explicit user cap, unavailable authority/resources, uncertain process ownership, or no executable distinguishing step after that review. Before declaring the whole task blocked, inspect every ready flow and record the actual constraint; a self-imposed local count is insufficient. Contract revisions, replacement agents, renamed slices, new directories, or fresh run identities never erase the same issue's history or spending. Expert help uses the same history and current allocation.

Diagnosis or a budget extension alone does not resolve a failure for delivery: the runtime requires a later-prepared, eligible formal success covering its scope on the current candidate, as detailed in [the final gate](runtime-ledger.md#qualify-and-execute-a-formal-gate). Retain the failure history; an unrelated or older pass cannot erase it.

## Ownership and resource release

Track only resources created for this invocation and verify their concrete identities: workcopy/path/branch, process identity and descendants, log location, and owner. Isolate per-flow workcopies and evidence writes; serialize the actual shared integration target through Integrator. Bound admission by available capacity and declared run budgets. Existing user processes and unowned files are outside the stop/cleanup scope.

Plan/dependency repairs pause the [runtime-computed affected closure](runtime-ledger.md#scope-local-plan-changes); unrelated active work can continue with its original evidence bindings. Shared snapshot inputs, changed public contracts, and frozen final candidates still constrain admission. The single authoritative snapshot workspace remains required; separate workcopies alone do not establish independent accepted run evidence.

For termination, validate ownership and process identity before stopping the owned process tree. For filesystem release, verify the resolved target is the owned path, work is saved, evidence is retained, and no active command or pending repair uses it. Preserve ambiguous or active resources with a reason and recovery pointer. At normal completion release temporary resources with no pending obligation; retain delivery branches/commits, compact evidence, and justified failure scenes.

## Resume v3 in place

Recovery begins from the original v3 run, not a newly empty ledger. Inspect recorded and actual processes, ownership, workcopies, source/test/contract versions, resource activity, pending obligations, and failure/repair history before resuming. Do not start duplicate commands while the original may still be running. Reconcile interrupted writes conservatively; unknown completion is unverified, not success.

Keep committed batch prefixes and replay the same event identities after resolving the rejection. For an execution-helper request, an existing preparation without a complete receipt requires recovery even when no claim exists; replay never launches it again. A complete unrecorded receipt may be recorded once, while a recovery-settled attempt needs a new authorized preparation if further execution is necessary. Retain the original request binding, reservation, claims, and logs throughout.

Reuse evidence only when its immutable inputs and scope still match. Mark affected evidence stale after test/helper/fixture/configuration/contract or product changes and follow the appropriate development, review, or formal revalidation path. Recreate a blind participant only from its [allowed package and supplied reporting routes](dispatch-and-isolation.md#test-side-allowed-inputs); never restore it from implementation-side conversation history. A resumed invocation confirms the run's recorded ten-role model mapping (re-collecting only roles whose model no longer applies) and records the invocation event without resetting the original run's budgets. Restore the same issue's local diagnostic records too; adopt this policy through an appended revision when an older local plan stopped at its own count, as described in [local-budget recovery](diagnostic-budgets.md#preserve-history-and-resume).

The first release supports v3's own interrupted runs only. Keep v2, its adoption flow, and its cleanup records unchanged; do not import v2 state as v3 qualification or give v3 resources to a v2-only cleanup tool. Post-merge cleanup beyond this invocation is separate work.
