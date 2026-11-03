# Local diagnostic budgets

Read when planning a failure investigation, reaching a local limit, distinguishing a preflight failure from a diagnostic result, or restoring an investigation stopped by an older local plan.

## Separate the limits

The runtime's `max_attempts`, `max_formal_failures`, and `max_seconds` belong to the whole run. This policy does not change those fields, refund recorded charges, extend explicit user limits, or relax ownership and acceptance gates. Local allocations are Integrator-owned supporting records outside `cycle.py` state; there are no new plan fields or `apply` operations. Never edit a live ledger to implement a local extension.

For each issue, choose a finite allocation of checks and command seconds from the next distinguishing investigation, with a rationale. Use separate allocations and cumulative totals for environment preflight and diagnostic-target execution. There is no default of two checks, and no fixed lifetime count for an agent-defined local investigation. A local limit is a review point before the next launch, not permission to terminate the task.

## Renew autonomously on evidence

The coordinator initiates renewal; the responsible owner assesses the evidence, Integrator persists the decision, and Runner executes the next bounded check. Preserve the dispatch-only main-agent boundary and the blind side's allowed inputs.

1. Reconcile all prior checks, pending ownership, outcomes, cumulative spending, and the remaining run budget before allocating more work.
2. Identify material new evidence since the previous allocation decision: a measured observation, a verified environment change, a newly established contract fact, or an inspected finding that changes the causal account or next check. Record the concrete difference and its source. A new log name, timestamp, agent, directory, restated hypothesis, or unchanged repeat failure is not new evidence.
3. State the next hypothesis, the check and outcomes that distinguish it, and why the additional finite checks/seconds are enough for that step. Add only this bounded allocation; keep the original limit, cumulative use, and every earlier extension in history.
4. Persist the revision before launch and proceed without requesting routine permission. Renew again when later evidence warrants another bounded step. Elapsed allocation or a previous `2/2` label does not veto a justified renewal.

When there is no material new evidence, do not launch the same diagnostic again just to obtain a new artifact. First assign a bounded review of the existing evidence to the relevant owner or Expert. Inspection can establish a previously unrecorded fact or a new causal deduction with cited premises and distinct predicted outcomes; label a deduction as an inference, not an observed cause. This documented analysis can support a finite evidence-gathering allocation even when both local allocations are exhausted. Integrator records that extension before Runner performs the distinguishing check; the check's result is not a prerequisite for allocating the check itself. A proposed command without this additional evidential basis, or a restated old hypothesis, does not qualify.

Environmental investigations use the same review and renewal path. If the review establishes neither new evidence nor a supported distinguishing check, document that substantive blocker and its affected dependencies; continue other ready work. Whole-task blocking requires actual exhausted run/user constraints or an evidenced lack of any actionable frontier, not merely agent-authored local limits.

## Count what actually ran

Keep a stable `check_id` for each logical execution and distinguish the diagnostic target from its runner, shell, Git helper, and setup processes. Runner supplies launch/outcome evidence; Integrator records the phase and counters. Serialize admission of checks for the same issue and reserve the bounded allocation before launch, so concurrent owners cannot spend the same allowance twice.

| Observed result | Local accounting and next step |
| --- | --- |
| Environment check or failed admission, with evidence that the diagnostic target did not start | Record a preflight check and its actual cost; increment `preflight_failures` on failure. Spend no diagnostic-target slot. Correct the demonstrated environment/hand-off cause and recheck within the preflight allocation, renewing on new evidence when necessary. |
| Diagnostic target started, including timeout, assertion failure, or later collection/cleanup failure | Consume one diagnostic check. Record measured costs; if completion or cost remains unknown, retain the unsettled time/ownership reservation while preserving the known start and used check. Reconcile it before another launch. Target execution cannot be relabeled preflight-only or launch-unknown because later collection failed. |
| Whether the diagnostic target started cannot be established | Record `launch_unknown`, preserve the reservation, and reconcile real ownership before another launch. Missing evidence is neither a free retry nor proof that the target ran. |

Preflight failures provide no product Red/Green or acceptance conclusion. A precreated temporary directory incorrectly handed off as unused is an environment/coordination failure, not a consumed product-diagnostic slot. Verify ownership and repair the hand-off through its owner; an unused-slot classification grants no authority to delete or reuse unowned paths.

For a cycle-bound command, `prepare` and `record`/`recover` still determine all global attempt, time, and formal-failure charges. Local phase accounting never cancels those charges. Standalone diagnostics retain their real receipts/logs and local costs but confer no cycle qualification; do not use them to bypass a refused cycle execution, pending ownership, or a global/user stop condition. An `unknown` or `business-decision` failure still needs the permitted classification/decision before its blocked cycle execution can resume.

## Preserve history and resume

Integrator is the single writer of the issue's audit record. Keep immutable, ordered event files under the run's evidence directory, outside product/test snapshots. A readable current summary is derived from these records and never substitutes for them. Use the same `run_id` and `issue_id` across retries, agents, worktrees, and contract revisions; link related issues instead of renaming the failed one to obtain fresh credit.

Every event has a stable `event_id`, sequence/previous-event reference, timestamp, owner/model, and event kind. Retrying a write with the same identity and content is a replay, not another charge or allocation; conflicting content requires an appended correction. Reconcile existing records before recovering an interrupted write. An incomplete/unpublished decision grants no additional allocation.

| Record kind | Required facts |
| --- | --- |
| Allocation or extension | Previous allocation reference; old and new cumulative limits for each affected phase; use/reservations carried forward; material evidence references and fixed versions/hashes; what was learned; next hypothesis/check and distinguishing outcomes; added finite checks/seconds and rationale; remaining global budget and authority/ownership checks. |
| Check admission and outcome | `check_id`; allocation reference; intended phase and reserved deadline; command/workcopy and evidence pointers; observed target-start status (`true`, `false`, or `unknown`); outcome/failure stage; actual measured costs or unresolved reservation; before/after derived counters. Link a cycle attempt when one exists. |
| Correction or policy adoption | Original record/artifact and fixed version; reason/evidence for correction; old and new interpretation and derived counts; unchanged raw execution facts and global charges. Never overwrite the original record. |

A known preflight failure historically charged to diagnostics can be corrected in the derived phase totals through a linked append-only correction. Preserve the original recorded totals and explain the difference; do not silently zero use. If the old artifacts cannot establish launch status, keep it unknown until reconciled. One physical check is projected once, even when its record is replayed or later clarified.

For an existing run stopped at an agent-defined local limit, retain its old plans, stop reports, failures, and counters. Append policy adoption referencing this policy's version and the old artifacts; reconstruct the phase totals; then record any evidence-supported extension and continue on the same run. Do not require the user to repeat authorization already covering the repair. A local extension changes only the available investigation work: it does not erase a failure, refresh a qualification, or release a blocked consumer.
