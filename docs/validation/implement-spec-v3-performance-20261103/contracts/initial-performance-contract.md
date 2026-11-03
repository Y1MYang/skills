# implement-spec-v3 performance contract

Status: public implementation and independent-test contract, 2026-11-03. Authority: the accepted requirement to reduce handoffs, repeated validation, and unrelated-flow waits while preserving independent tests, one-example TDD, dispatch-only main-agent work, and complete evidence history. This document supplements the [runtime contract](implement-spec-v3-runtime-contract.md). It specifies observable behavior, not an internal algorithm. Tests may be authored from these two contracts without production-source access.

## 1. Compatibility and protected boundaries

All existing entry points, schema-1 plan and event shapes, stable IDs, scope ownership, budget accounting, evidence, process containment, recovery rules, and formal-delivery gates remain supported. The additions below do not replace or collapse original events. No operation infers `valid-red` from an exit code, repairs a test, qualifies a test, releases a consumer, or declares delivery without the corresponding existing, authorized event.

The Integrator remains the state writer. Runner supplies a pinned execution prescription before the Integrator invokes the deterministic execution helper, and Runner assesses the observed cause afterward. The helper is mechanical execution delegated by Runner; it does not substitute another model for the selected Runner responsibility. Distinct selected role models retain their separate contexts and authority. Test-side contexts remain implementation blind; model selections, sanitization provenance, and independent-review boundaries are unchanged.

Every mutation boundary, including every batch item and both sides of external execution, retains the existing complete audit of durable history and adopted evidence. Corrupt old requests, receipts, logs, claims, anchor, state, or event chain must be detected before a subsequent transition can use them. A long-lived process, a successful earlier item, unchanged file size, or restored timestamps is not permission to trust cached history. `inspect`, `verify`, replay, and recovery retain their integrity checks.

Repeated captures or receipt validation inside one transition may share already verified values where no external command, write, event boundary, or candidate change intervenes. This permission does not remove Runner's before/after captures, current-candidate checks, or fresh audit at the next transition. No timestamp-based or cross-command evidence cache is introduced.

## 2. Finite event batch

```text
python scripts/cycle.py --state DIR batch --events FILE
```

FILE is a UTF-8 JSON object with exactly these fields:

```json
{"schema":1,"events":[{"schema":1,"op_id":"open-example-a","op":"open","example":"a","light_check":{"source":"REQ-A","observation":"public result","expected_failure":"specified result absent","independent_context":"blind-author-a"}}]}
```

`events` is a nonempty finite JSON array of existing `apply` event objects. Before its first mutation, the command validates the envelope, integer schema 1, common event headers, recognized operation names, and distinct nonempty `op_id` values. Unknown envelope fields and invalid common headers reject the entire input without applying any item. Operation-specific fields and state-dependent prerequisites are checked at each item's normal transition boundary; the batch does not duplicate all event validators in an advance simulation.

Items execute in input order. Every successful item is independently durable before the next item begins. Each retains its original `op_id`, original event content, sequence, result, hash-chain entry, and ordinary idempotency behavior. The batch introduces no aggregate event and makes no all-or-nothing promise. It stops at the first rejection. No later item executes, and no successful prefix is rolled back. It runs no external command and supplies no placeholder/result interpolation language.

Success exits 0 and emits:

```json
{"ok":true,"results":[{"ok":true,"example":"a","state":"open","seq":1}]}
```

An item rejection exits 2 and emits `{"ok":false,"results":[...],"failed_index":N,"error":{"code":"existing-error-code","message":"..."}}`. `results` contains the successful prefix in order, and `failed_index` is its zero-based failing input index. Upfront envelope/header rejection has `results:[]` and `failed_index:null`. A rejection does not consume that item's `op_id`.

Replaying the same batch replays each committed prefix item and attempts the remaining suffix under current conditions. Already committed items neither add history nor charge budget again. Changed content for a committed `op_id` rejects at that item. Replay still audits current durable evidence before returning the old result. Other authorized commands may interleave at event boundaries; batch is not a long reservation of the entire state. Contention may return the existing `busy` rejection with the committed prefix preserved.

Use batches only for decisions already made from available evidence. For example, an authorized `open` and `prepare` can be adjacent; a future execution's predicted result cannot authorize a prewritten judgment. The helper below ends before that semantic decision.

## 3. One prepared execution and its record

```text
python scripts/cycle.py --state DIR execute --request FILE
```

FILE has exactly these fields:

```json
{
  "schema":1,
  "prepare":{"schema":1,"op_id":"probe-a-prepare","op":"prepare","example":"a","purpose":"probe","timeout_seconds":20},
  "record_op_id":"probe-a-record",
  "argv":["python","tests/test_a.py"]
}
```

`prepare` is an ordinary complete `prepare` or `prepare-formal` event; no other operation is accepted. `record_op_id` is nonempty and different from the prepare ID. `argv` is a nonempty array of nonempty strings, passed directly without a shell. Unknown fields reject. Envelope/common validation and conflicting IDs must be checked before a new preparation is committed.

The exact request is durably bound to its preparation before a target can start. The binding includes canonical request SHA-256, the complete prepare event, record ID, and exact argument array. JSON whitespace and object-key order do not change this identity. The binding is part of audited state/provenance; an unbound preparation made through ordinary `apply` or `batch` cannot later be adopted by `execute`. Such adoption rejects with `execution-unbound` and never starts a target. Reuse of an existing execution's prepare ID with a different bound request rejects with `execution-conflict` and preserves the original materials.

On a new request, the helper:

1. Audits and commits the original prepare event and its execution binding, reserving the ordinary attempt/time budget exactly once.
2. Releases the state lock before command execution. It derives cwd, snapshot request, receipt destination, timeout, and formal mode solely from that prepared attempt; callers cannot override them. It uses the existing owned runner, including claim exclusivity, process-tree containment, progress, total deadline, and bounded cleanup.
3. Reacquires the state for a fresh audit and applies the ordinary `record` event with the supplied `record_op_id` and actual attempt ID, reading only the real prepared receipt destination.

The helper must not retain the state lock while waiting for the command or its descendants. An independent state operation during a deliberately waiting target can complete; it need not wait for target exit. This is observable concurrency behavior, not a millisecond latency guarantee.

Exit 0 means the actual receipt was durably recorded, including nonzero, timeout, and snapshot-changed/ineligible results. It does not mean the behavior passed. The final stdout line is:

```json
{
  "ok":true,
  "attempt_id":"attempt-id",
  "execution_sha256":"64 lowercase hexadecimal characters",
  "prepare":{"ok":true,"attempt_id":"attempt-id","request_path":"absolute","receipt_path":"absolute","seq":2},
  "record":{"ok":true,"attempt_id":"attempt-id","outcome":"exited","exit_code":1,"seq":3},
  "outcome":"exited",
  "exit_code":1
}
```

`prepare` and `record` are the original event results, including the existing ineligible record shape where applicable. The root outcome/exit code are the actual receipt facts. Raw target output remains in the existing logs, and progress remains on stderr. The helper returns after record; it never creates a `judge`, `diagnose`, `close`, review, release, or finish event.

Replay and failure rules:

- The same request after its supplied record event committed returns the prior preparation/record facts, with unchanged sequence and accounting, and never starts a command again. Fresh audit still precedes this response.
- If preparation committed and a complete unrecorded receipt exists, the same request may audit and record it once without rerunning the command.
- If an earlier preparation exists but there is no complete receipt, including no claim, a live claim, unknown ownership, or partial logs, replay returns exit 2 with `recovery-required`. It never relaunches, cancels, or guesses ownership. Existing `invocation`/`recover` handles reconciliation and cancellation claims. A concurrent second helper follows this same rule rather than racing to launch.
- If recovery or another event settled the attempt without this supplied record event, replay returns exit 2 with `execution-settled`; it does not fabricate a second settlement or launch. A new attempt needs a new authorized preparation after normal diagnosis/recovery requirements.
- If the helper cannot obtain a complete receipt during its first execution, it exits 2 with `execution-incomplete` and preserves the pending reservation, logs, and claims for recovery. Existing runner errors or evidence-validation errors may instead propagate their specific error code. Existing, corrupt materials remain corruption errors, never a reason to relaunch or relabel them interrupted.
- Failure before preparation commits consumes no preparation or record ID. Failure afterward preserves the durable prefix and budget reservation. Repeated calls cannot replenish limits, overwrite artifacts, silently finish an example, or erase failures.

## 4. Scope-local plan-change boundaries

This section supersedes only the run-wide activity barriers of `extend`, `include`, and `revise`. Event shapes, atomic complete-plan validation, current scope ownership, path safety/equivalence, cycle checks, consumer-started prohibition, historical evidence, invalidation requirements, and budgets are unchanged. In particular, a new gate still cannot retroactively block an already opened consumer.

The runtime computes an affected set; the caller cannot declare unrelated work safe merely by omitting it. Use actual filesystem path identity for overlaps, including ancestor/descendant declarations, case-equivalent paths, and missing paths under the filesystem's naming semantics. Unknown impact or identity fails closed. The dependency closure repeatedly adds ordinary downstream dependents and every gate consumer whose gate has an affected prerequisite. Ancestors are not added solely because an affected new example depends on them.

Operation-specific seeds are:

| Operation | Initial affected examples |
| --- | --- |
| `extend` | Newly added examples and consumers of newly added gates, evaluated against the fully validated resulting graph. |
| `include` | Listed examples, plus every existing example whose declared snapshot paths in any group overlap a newly added dependency path, followed by the downstream closure. |
| `revise` | Explicitly listed examples, plus other existing examples whose current tests/contract captures differ from their applicable adopted, opened, or pending-preparation baseline, followed by the downstream closure. |

For `revise`, do not miss open examples merely because they lack a Red/Green receipt, or pending attempts merely because their receipts do not yet exist. A pending attempt's prepared snapshot and an open example's opening snapshot are applicable baselines. Unchanged shared read dependencies such as `spec.md` do not alone make every operation global. Existing freshness checks still reject stale evidence whenever used.

Affected flows are flows owning affected examples. A pending development attempt blocks the edit if its flow is affected or its example belongs to the closure. A pending formal attempt blocks if its pinned scope intersects the closure. Every pending final attempt blocks these edits, because the final candidate's membership or qualification is being changed. An unsettled attempt cannot be rewritten to match a newer declaration.

`extend` and `include` require affected flows to have no active example and require all affected attempts to be settled. They accept an unrelated active example or pending attempt when these conditions and all existing validation rules pass. `revise` may reset explicitly listed active examples when affected attempts are settled, as before. An active example in an affected flow that was not explicitly listed causes rejection rather than being silently reset; include it in an authoritative revision or bring it to a safe boundary first. Rejections use `active-work` for active-flow barriers and `attempt-pending` for affected unsettled attempts; either may be reported when both apply.

Only explicitly revised examples lose their historical completion eligibility and return to `planned`; affected downstream/shared-dependency examples retain their history but cannot use stale evidence or releases. Refresh their affected proofs and gates before resuming reliance. `include` preserves historical close, marks listed examples' current proof stale, and invalidates qualifications/releases/executions for affected scopes. `extend` invalidates final scope as before and preserves existing gate proofs unless their actual dependencies or affected scope changed. All three revoke final readiness and require current final proof before delivery. Scope invalidation is conservative over the affected closure; it cannot omit a gate containing an affected prerequisite merely because no file bytes changed.

An accepted local edit leaves every unrelated pending request, binding, timeout, reserved amount, identity, prepared snapshot, and receipt destination unchanged. That attempt can subsequently record under its original preparation if its real execution remains eligible. It neither gets cancelled nor needs re-preparation because an unrelated plan entry changed. Full audits remain run-wide; relaxing an activity barrier does not relax integrity verification.

The single authoritative workspace root remains mandatory. Separate flow workcopy bindings and schema migration are deferred. In the shared workspace fallback, parallel admission requires disjoint writes and complete, pinned test/contract/product dependencies. Shared helper/configuration changes require the relevant owner and affected closure to pause. A flow's edits must not change another running command's declared inputs; actual before/after drift remains ineligible. Independent branches are integrated into the authoritative workspace before accepted evidence is collected. This limitation is explicit rather than claiming separate workcopy proofs are already supported.

## 5. Persistent workflow and independent validation

Dispatch a continuing flow assignment, not a fresh model task for every ledger event. An unpolluted blind Test author and its implementation-side partners may remain available across successive examples. Each example still independently passes author/light check → actual probe → Runner judgment → minimal implementation → actual Green and affected regression → optional refactor and refreshed regression. Do not author several unknown behaviors in advance, batch semantic judgments from predicted results, or cross test/implementation context boundaries to save a handoff.

Report at semantic boundaries: a new independently authored example is ready, Runner has a classified observation, implementation is ready to execute, the example is complete, or a real blocker/contract change/checkpoint needs coordination. Mechanical prepare/run/record persistence does not itself require an additional model wakeup. The main agent remains dispatch-only and consumes structured reports. Full independent review remains at the existing critical-contract and final gates with fresh review contexts.

Independent acceptance should cover, at minimum:

- batch success, durable partial prefix, repaired-suffix replay, conflict replay, invalid envelope, and unchanged original event IDs/accounting;
- real nonzero probe recorded without automatic Red, followed by explicit authorized judgment and Green; actual ineligible and failed executions remain failures;
- exact execute replay without a second target side effect, changed request rejection, incomplete execution/recovery, receipt corruption, and concurrent helper exclusion;
- an unrelated state command succeeding while an execute target is still waiting;
- local `extend`, `include`, and `revise` with an unrelated live/prepared attempt that later records unchanged;
- affected pending/active rejection, shared added-path overlap including filesystem aliases, downstream ordinary/gate consumer closure, and pending final rejection;
- old-evidence tampering discovered by the next operation/replay, including same-size content with restored timestamps;
- existing recovery, ownership, formal qualification, full history, budgets, and final same-candidate delivery checks.

## 6. Speed evidence and limits of the claim

Measure the unmodified baseline and candidate in the same environment using equivalent starting workspaces, public behavior scenarios, command work, event semantics, and quality gates. Include ordinary new behavior, failure/repair, and a shared-contract/dependency change. Use multiple paired repetitions and report wall-clock range and median, process invocations, committed events, and whether work genuinely overlapped. Do not add artificial baseline delays or report summed concurrent durations as elapsed time.

Separate target execution from orchestration/ledger overhead where observed timings allow. Use actual complete commands and their real side effects/evidence, not mocked persistence or event-count savings presented as measured time. Record both successful and failed trials. No fixed timing ratio belongs in correctness tests; measurements must identify filesystem, interpreter/platform, scenario size, run count, and unresolved variance.

Report the measured scope honestly: a local CLI benchmark proves runtime/mechanical-path speed, not model generation, model queueing, or full-task speed. Workflow handoff reductions and accepted unrelated live work can be counted and demonstrated, but cannot stand in for an unmeasured end-to-end acceleration claim. Retain the artifacts/commands needed to reproduce the comparison, and report a non-improvement if the measurements show one.
