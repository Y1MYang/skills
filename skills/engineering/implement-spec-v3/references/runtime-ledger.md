# Runtime ledger and command interface

Read with [execution and recovery](execution-and-recovery.md) when initializing a v3 run, recording an example, executing a formal gate, or recovering. Integrator owns state mutation; Runner supplies the execution prescription and interprets receipts. Integrator can invoke the mechanical helper with that prescription under the [role authority rules](dispatch-and-isolation.md#persistent-flow-assignments). Resolve the two bundled scripts relative to this skill, not the project cwd:

Use Python 3.12 or later for the bundled tools, including Windows junction checks, and Git on `PATH` for committed candidates and formal acceptance. Native Windows validation used Python 3.12.10; consult the run's platform evidence before relying on another platform's process containment.

```text
python <skill>/scripts/cycle.py --state <state-dir> init --plan <plan.json>
python <skill>/scripts/cycle.py --state <state-dir> apply --event <event.json>
python <skill>/scripts/cycle.py --state <state-dir> batch --events <events.json>
python <skill>/scripts/cycle.py --state <state-dir> execute --request <execution.json>
python <skill>/scripts/cycle.py --state <state-dir> inspect
python <skill>/scripts/cycle.py --state <state-dir> verify
python <skill>/scripts/run_command.py --receipt <receipt.json> --cwd <worktree> --timeout <seconds> --snapshot <request.json> [--formal] -- <argv...>
```

Replace angle-bracket values with actual paths/values. Store state, request/event files, receipts, and logs outside the tested worktree. Command arguments are an argv sequence; the runner does not add a shell. Supply a shell explicitly only when the project command requires it, preserving quoting and ownership of descendants.

## Common encoding and paths

Plans, snapshots, and events are UTF-8 JSON with integer `schema: 1`. The schemas below list required fields unless stated otherwise; unknown input fields are rejected. Use nonempty strings and finite numbers. IDs are case-sensitive. Every `apply` event includes `schema`, `op_id`, and `op`. Successfully persisted events enter replay history: identical replay returns the original result, while different content is rejected. `execute` also reserves its bound record ID as described below. Busy or validation/precondition rejection consumes neither the rejected event's ID nor sequence/budget, so the identical event can retry after conditions are fixed. Recorded ineligible results and blocked/running recovery observations are persisted facts; use new IDs to observe later changes.

Every mutation boundary, including each batch item and both sides of external execution, audits complete durable history and adopted evidence. Replay, `inspect`, `verify`, and recovery retain their integrity checks. Reuse of a verified capture or receipt check is confined to one unchanged transition; an intervening command, write, event boundary, or candidate change requires fresh checks. A prior success, unchanged size, or restored timestamp cannot replace this audit.

CLI paths resolve from the caller's cwd. Snapshot paths resolve from their absolute `root`. Each of `tests`, `contract`, and `product` is a nonempty array of unique relative files/directories within that root: no globs, parent traversal, absolute entries, symlinks, or directory junctions. Directory capture includes recursively enumerated file bytes and directory entries; explicitly missing paths are recorded. Include all test helper, fixture, and configuration dependencies in `tests` and all authoritative behavior contracts in `contract`. Agents remain responsible for complete dependency inventories.

Path identity follows the actual filesystem for scope ownership, duplicate paths, and overlapping write ranges. In a case-insensitive Windows directory, `Spec.md`/`spec.md` identify the same source and `src`/`SRC/module.py` overlap; equivalent drive or separator spellings also confer no isolation. Missing paths inherit naming semantics from their nearest existing ancestor. Preserve real distinctions on case-sensitive filesystems, and reject a plan when equivalence cannot be established reliably. Business IDs remain case-sensitive and display paths need not be lowercased.

Standalone snapshot shape:

```json
{"schema":1,"root":"/absolute/worktree","tests":["tests"],"contract":["spec.md"],"product":["src"],"binding":null}
```

Use actual project paths. A command without `--snapshot` can execute, but its receipt cannot advance the cycle. For cycle attempts, pass the exact generated request instead of constructing its binding manually.

Keep generated caches and temporary outputs outside every selected snapshot directory. Otherwise the before/after capture changes and the attempt is ineligible; formal runs must also leave the frozen Git worktree clean. Configure the command before taking its snapshot: for Python tests use `-B` or `PYTHONDONTWRITEBYTECODE=1`; for pytest, disable its cache with `-p no:cacheprovider` or direct `cache_dir` outside both the snapshot roots and frozen worktree. Apply the same rule to coverage files, build outputs, test artifacts, and project-specific caches where needed. Preserve all real helper/fixture/configuration dependencies in the snapshot; narrowing the inventory merely to hide generated changes is not evidence of stable inputs.

## Batch decided events

`batch` accepts `{"schema":1,"events":[...existing apply events...]}`, with a nonempty finite event array. Use it for an ordered set of decisions already supported by available evidence. It executes no external command and cannot interpolate a future result. Common headers and distinct operation IDs are checked before the first mutation; operation-specific fields and prerequisites are checked at each transition.

Each successful item keeps its original event, sequence, result, and hash-chain record and is durable before the next item. On success, exit 0 returns `ok:true` and `results`. On rejection, exit 2 returns `ok:false`, the successful-prefix `results`, zero-based `failed_index`, and `error`; an envelope/header rejection has an empty prefix and null index. Later items do not execute and the prefix is not rolled back. Replay the same batch after fixing the rejected condition: committed items return their existing results without extra charges, and the remaining suffix is attempted. Other commands can interleave between items; `busy` preserves any committed prefix.

## Execute and record one attempt

`execute` accepts these four fields:

```json
{"schema":1,"prepare":{"schema":1,"op_id":"probe-a-prepare","op":"prepare","example":"a","purpose":"probe","timeout_seconds":20},"record_op_id":"probe-a-record","argv":["python","tests/test_a.py"]}
```

Use a complete ordinary `prepare` or `prepare-formal` event; record and prepare IDs must differ. `argv` is a nonempty array of nonempty strings, passed without an implicit shell. The envelope and conflicting IDs are checked before a new preparation commits. Runner provides the exact argv, expected failure, limits, and scope before Integrator submits it. The helper durably binds the complete request to preparation, releases the state lock while the owned runner executes, and applies the ordinary `record` after a fresh audit. It derives cwd, snapshot, receipt path, timeout, and formal mode from preparation. It never judges Red or creates a diagnosis, close, qualification, release, or finish.

Once preparation and its binding commit, `record_op_id` is reserved for exactly the ordinary `record` event naming that bound attempt. Any other `apply`, batch item, or execution using it, including a record for another attempt, is rejected with `op-id-conflict` without consuming the ID. The authorized record still requires verifiable receipt evidence and follows normal replay rules; reserving its ID neither records a result nor establishes evidence eligibility.

Exit 0 means a real receipt was recorded, including a nonzero, timeout, or ineligible result. The result includes `attempt_id`, `execution_sha256`, original `prepare` and `record` results, and actual `outcome`/`exit_code`. Runner still inspects and classifies the outcome. Target output stays in its logs and progress stays on stderr. The helper preserves both original events and ordinary accounting; it does not hold the state lock while waiting for the target.

Replay the identical request to retrieve an existing record or adopt a complete unrecorded receipt without rerunning. JSON whitespace/key order do not change the binding; changed request content returns `execution-conflict`. A preparation made through `apply` or `batch` is unbound and cannot be adopted by `execute` (`execution-unbound`); finish that attempt through the low-level runner/record path. If a prior bound preparation has no complete receipt, replay returns `recovery-required`, including when no claim exists. Use normal recovery; it cannot safely relaunch. An attempt already settled without the supplied record event returns `execution-settled`.

If initial execution cannot produce a complete receipt, `execution-incomplete` or the specific runner/evidence error leaves the pending reservation and available materials for recovery. Corrupt materials remain errors. A later new attempt needs a new authorized preparation after the existing recovery/diagnosis requirements; changing IDs does not erase the old attempt. Keep the exact execution request with its evidence. The low-level `apply`, `run_command.py`, and `record` commands remain supported for separate operation and recovery.

## Initialize once

The plan has these fields:

| Field | Value |
| --- | --- |
| `schema`, `run_id`, `workspace` | `1`, stable run identity, absolute project worktree |
| `spec_sources` | Nonempty array of authoritative spec paths used to identify this scope |
| `models` | Explicit nonempty values for `exploration`, `architect`, `test_author`, `implementer`, `runner`, `integrator`, `coverage_audit`, `spec_reviewer`, `standards_reviewer`, `expert` |
| `budget` | Positive integer `max_attempts`, positive integer `max_formal_failures`, and positive finite `max_seconds`; derive finite values for this project and record their rationale |
| `flows` | Nonempty array of `{id, write_paths}`; parallel flows have disjoint normalized write paths without parent/child overlap |
| `examples` | Nonempty array of `{id, flow, requirement, depends_on, snapshot}`; `depends_on` lists prerequisite example IDs; snapshot uses the shape above |
| `gates` | Array of `{id, prerequisites, consumers}` containing example IDs; the array may be empty when no gate is required |

Plan examples and their coverage before `init`, but author each test only when its example is current. Existing identities remain stable; independent findings add missing examples through `extend` or omitted snapshot dependencies through `include` below. Flow, example, and gate IDs are unique within each respective collection; `final` is reserved and cannot be a gate ID. `requirement` identifies the specific requirement/example and is unique in the plan, so different examples have distinct identities even when they exercise one business rule. All example snapshot roots must normalize to `workspace`; merge external worktrees into that authoritative workspace before recording integrated evidence. Git worktrees and merges remain agent-owned operations.

The scope anchor binds the repository and normalized `spec_sources` to the original run/state. Reopening the same active scope under another run ID or state directory is refused; it does not reset budgets. Repeating `init` for the same state and identical normalized original plan returns `created:false` without overwriting history, including after an extension. A genuinely new requirement run using the same spec paths requires a verifiable historical finish, fixed HEAD and audit materials from the old run, changed spec content, and an explicit new run ID; the old qualification need not remain current against the new spec. Preserve the old anchor history. Keep all invocation model maps as historical audit data. Runtime model configuration verifies a complete table, not that an actual dispatch used it; retain dispatch evidence as well.

## Scope-local plan changes

`extend`, `include`, and `revise` use the runtime's affected closure instead of requiring unrelated flows to stop. The runtime seeds `extend` with new examples and new-gate consumers; `include` with listed examples and existing examples whose snapshot paths overlap an added dependency; and `revise` with listed examples plus examples whose current tests/contracts differ from their applicable adopted, opening, or pending-preparation baseline. It repeatedly adds ordinary downstream dependents and consumers of gates with an affected prerequisite. An unchanged shared read dependency alone does not make every flow affected; unknown impact or path identity cannot establish safety.

For `revise`, an eligible later regression that refreshed an example supplies its adopted baseline; an older superseded Red/Green snapshot alone cannot mark that refreshed proof changed. Opening snapshots count before a Red/Green receipt exists. Pending formal attempts contribute their prepared scope snapshots even without an example ID or completed receipt; changed tests/contracts in those snapshots enter the affected scope before checking pending-attempt barriers.

Affected flows own any affected example. A pending development attempt blocks a mutation when its flow or example is affected; a pending formal attempt blocks when its pinned scope intersects the closure. Every pending final attempt blocks these plan changes. `extend` and `include` also require affected flows to have no active example. `revise` may reset explicitly listed active examples after affected attempts settle, but rejects any other active example in an affected flow. Bring that work to a safe boundary or include it in an authoritative revision. `active-work` and `attempt-pending` identify these barriers.

Use actual filesystem path identity, including parent/child overlap and equivalent spellings. Runtime validation covers the complete resulting plan; the caller cannot omit dependencies to declare another flow unrelated. A successful local mutation preserves unrelated pending requests, bindings, snapshots, receipt destinations, reservations, and accounting exactly. Those attempts may record under their original preparations if actual execution remains eligible. Full integrity audits and the common authoritative workspace requirement remain in force.

## Append missing examples at a safe boundary

For independent coverage findings, apply `extend` with nonempty authoritative `source` and `reason`, plus explicit `examples`, `flows`, and `gates` arrays. `examples` must contain at least one new example; `flows` and `gates` may be empty. Entries use the corresponding init shapes. Satisfy the [affected-flow boundary](#scope-local-plan-changes) and retain ownership of the scope anchor. Unrelated active/pending work and unstarted planned examples do not themselves block extension.

Extension only appends. Existing IDs are rejected even when the supplied entry is identical; old entries, gate membership, run identity, workspace, spec sources, models, history, and all budget limits/use remain unchanged. New examples may reference existing or newly added flows/dependencies. A new gate may reference existing or new examples, but every consumer must still be unopened. The tool revalidates the entire merged plan for unique IDs/requirements, path boundaries, write isolation, valid references, and acyclic dependencies, rejecting the whole event on any failure.

The original init plan and accepted `extend`/`include` events determine the effective plan. New examples enter `planned` and still follow their own independent test-first loops; do not hide them inside an old example or create another run to gain budget. Previously closed examples retain their historical completion, failures, attempts, and review records.

An extension expands final scope membership, invalidating the current effect of all earlier final qualifications, formal runs, and ready status even when file hashes are unchanged. Reconcile full coverage and perform complete formal acceptance for the enlarged scope before finishing. Both final `qualify` and `prepare-formal` must follow the latest accepted `extend`; replaying an old record or finish cannot restore readiness. Qualifications and attempts bind their example-ID set as well as content digests. Existing gate evidence may carry forward only where its membership and inputs remain unchanged.

## Include omitted snapshot dependencies

Apply `include` with nonempty `source`, `reason`, and `items`. Each item is `{example, tests, contract, product}`: reference one existing example, explicitly provide all three path arrays, and add at least one path across them. Items cannot repeat an example; normalized paths cannot duplicate an existing declaration or another path in the same group. The original snapshot path rules apply. `include` only appends dependency paths; it cannot change roots, IDs, behavior, flow, or prerequisite edges.

As with `extend`, satisfy the [affected-flow boundary](#scope-local-plan-changes) and retain scope ownership. Runtime validates every item before accepting the whole event. Historical close, attempts, failures, and budget use remain. The listed examples' current execution evidence and qualifications, releases, and formal runs over the affected closure become stale; current final readiness is revoked even if file hashes happen to match.

The blind test side reviews whether the completed dependency inventory is sufficient. Obtain affected dual-axis qualification and formal evidence after that scope's latest `include`; closed examples refresh through regression or a covering formal run without new Red. If a currently active example needs dependency repair, settle its attempt and diagnose the cause, then use `revise` to release its flow before `include → open/probe`.

## Record a development example

Construct event files with the common fields and the operation-specific fields below. Commands return their structured result as the final stdout JSON line; send progress/diagnostics to the owner, not directly to the blind side.

| `op` | Additional fields and use |
| --- | --- |
| `open` | `example`, `light_check:{source,observation,expected_failure,independent_context}`; all check values are nonempty strings. Open after the current test and its lightweight check exist, against the intended product baseline. |
| `prepare` | `example`, `purpose`, `timeout_seconds`; purpose is `probe`, `green`, or `regression`. Result supplies `attempt_id`, `request_path`, `receipt_path`; save these exact values. |
| `record` | `attempt_id`; consumes only the prepared path's real receipt, including request/log/snapshot checks. Do not provide a caller-written exit code or digest. |
| `judge` | `attempt_id`, `classification`, `reason`, `evidence`; reason is nonempty and evidence is a nonempty array of material identifiers. Classification is `valid-red`, `existing`, `implementation`, `test-defect`, `environment`, `business-decision`, or `unknown`. |
| `close` | `example`, `regression_attempt_id`; requires current Green or verified existing capability plus current passing regression. When one `green` attempt also proves regressions, add nonempty `regression_scope` describing that command's actual coverage. |

The continuous path is `open → execute(probe) → judge(valid-red) → implementation → execute(green) → passing regression → close`. Each `execute` persists the same preparation and actual record as the low-level `prepare → run_command → record` path. A separate regression uses `purpose:"regression"`; a Green command covering the affected regressions can supply both proofs via `regression_scope`. In the first-run Green path use `judge(existing)` with a reason establishing test validity, then actual regression and `close`; record completion as `existing`, not Red → Green. These are persistent-owner operations, not separate agent assignments.

Run the prepared command with the returned receipt/request paths and the exact prepared timeout. The request contains the run, example/gate, attempt, purpose, sequence, and prepare time. Only a real nonzero probe can support valid Red; only the first valid zero-exit probe can support existing capability. Those facts still require Runner's semantic judgment. A valid Red must be recorded before green preparation, with matching test/contract identity; product bytes may change for the implementation.

Each receipt path and its `.stdout.log`, `.stderr.log`, and `.claim.json` must be unused. Never overwrite a failed attempt. Runner captures before/after file bytes, actual argv/cwd/timing, target outcome/exit status, process ownership, cleanup result, and log hashes. `exited` requires the target's own completed result; a bootstrap/supervisor exit cannot stand in for it. Incomplete cleanup cannot support success.

When the full receipt, request, logs, binding, timing, sequence, and ownership cleanup verify but before/after snapshots differ, `record` settles the real result as `ineligible` with reason `snapshot-changed`. It clears pending, charges actual duration, releases the reservation, and retains outcome/exit code/logs unchanged; a formal attempt also consumes one formal-failure credit. This successful recording returns `eligible:false` and never supports Red, existing, Green, regression, or formal success. It does not close the active example. Diagnose and repair before a fresh attempt; `judge` cannot make this receipt eligible. Corrupt hashes, binding, or history are rejected rather than being downgraded into this settlement path.

`run_command.py` exits `0` for a zero-exit target, `1` for a nonzero target, `124` for timeout, and `2` for launch/ownership/receipt failure. Nonzero is not automatically a test failure classification. `cycle.py` exits `0` on success or `2` for input/evidence/state rejection, returning `{"ok":false,"error":{"code":"...","message":"..."}}` on rejection. Rejected transitions do not establish a completed gate.

Runner's deadline covers preflight, including Git and initial snapshots, plus launch and execution; it is not renewed per substep. Runner-created helpers, including formal preflight/final Git commands and their descendants, obey the same ownership, total timeout, and shared termination bound as the target. All termination/collection after timeout shares at most five additional seconds. Preflight exhaustion prevents target launch and may return a structured timeout error without a receipt. A final stdout object with `ok:true` says the receipt was published, not that the target passed.

Read progress only from stderr lines parsing as JSON with `event:"progress"`, finite nonnegative `elapsed_seconds`, and absolute `receipt_path`; ignore unrelated diagnostics and tolerate extra progress fields. Elapsed time starts at preflight; integer truncation is allowed with representation error under one second. The one-second publication interval is a best-effort target, not a strict delivery deadline or business SLA. Long commands should expose progress before completion; commands shorter than a period may emit none. Raw target output stays in its logs.

## Refresh evidence without rewriting history

Historical `closed` records survive added examples, product evolution, and changed shared-file digests. Current Red/Green pairing, regression, review qualification, and checkpoint proofs can become stale independently of that history. Never reopen an unchanged completed behavior merely to manufacture a new Red.

To refresh a historically closed example on new inputs, finish any other active example in that flow, then use `prepare` with `purpose:"regression"`, actual execution, and `record`. A successful current formal run also refreshes cumulative regression evidence for its entire scope. Tests/helper/fixture/configuration/contract changes still require affected independent requalification; a refreshed execution does not supply that qualification.

For test-side refactoring after Green, follow [the TDD Refactor phase](tdd-loop.md#5-refactor-if-useful-then-finish-the-cycle): preserve historical close before changing the test snapshot, keep the same cycle scheduled, and refresh through closed-example regression before advancing.

For changed behavior semantics or evidence-backed test/dependency repair, apply `revise` with `examples:["example-id", ...]`, authoritative `source`, and `reason`, after satisfying the [affected-flow boundary](#scope-local-plan-changes). It returns only explicitly listed examples to `planned`, releases their active flows, and revokes their current completion while retaining history and budgets. Other affected examples keep historical completion but require current proofs before relying on stale evidence or releases. Complete any required `include`, then run new `open/probe` loops. Judge first-run Green honestly as existing capability; a repair does not require manufacturing Red. Runtime rechecks declared dependencies and marks shared proofs stale across examples; agent impact analysis establishes the repair's authority and closure.

## Qualify and execute a formal gate

Use `scope: {"gate":"gate-id"}` for a checkpoint or `scope: {"final":true}` for final acceptance. A gate's acceptance scope is exactly its explicit `prerequisites`; list ancestor examples there if they need acceptance too, because dependency edges alone do not expand the scope. Final scope contains every example, including accepted extensions.

1. After real independent review, apply `qualify` with `scope`, `spec_review`, and `standards_review`. Each review object has `review_id`, `source`, `independent_context`, and `verdict:"pass"`. `source` points to the pinned report establishing scope, dependencies, and the corresponding axis; a passing string is not a substitute for that work. Test qualification may precede example completion; formal preparation separately requires close.
2. Freeze a clean, committed candidate, then use `execute` with a `prepare-formal` event containing `scope` and `timeout_seconds`, plus Runner's argv and a distinct record ID. All scope examples must have historical completion not revoked by `revise`, and qualification must be current. The helper prepares the combined snapshot scope, executes in formal mode, and records the actual receipt. The low-level alternative is separate `prepare-formal`, `run_command.py --formal`, and `record` operations using the returned paths.
3. Runner assesses the recorded outcome and stable HEAD/snapshots before the release or finish decision. Keep the candidate frozen throughout; endpoint checks alone cannot detect a mid-run edit that was later restored.
4. For a checkpoint, apply `release` with `gate` and `attempt_id`. Release binds the actual successful formal receipt, current HEAD, and current inputs. A stale receipt cannot open consumers.
5. For final delivery, apply `finish` with `attempt_id` and `code_reviews`. The latter is `{"spec":{"head":"SHA","review_id":"ID","verdict":"pass"},"standards":{"head":"SHA","review_id":"ID","verdict":"pass"}}`. Both real reviews, complete acceptance, and current clean HEAD must match. No flow or scope may retain a pending attempt or unexplained/unresolved failure. The tool's `status:"ready"` establishes its mechanical gates; actual whole-spec coverage and review conclusions still require agent evidence.

For every non-Red execution failure, diagnosis supplies an explanation and repair basis, not resolution. An eligible formal run prepared after that diagnosis must pass on the current candidate and cover the failure's scope: its example for a development attempt, or the entire original scope for a formal attempt. Old success cannot override later failure. Keep original failures and charges; new evidence may mark them resolved, but an ineligible receipt itself never becomes eligible. A new pending attempt or unresolved failure prevents reuse of an older final success.

Consumer `open` revalidates the gate's HEAD and declared dependency snapshots, not whole-worktree cleanliness. Newly written consumer tests or other dirty files outside that gate's dependency closure do not alone revoke its release. Changes to its actual dependencies or HEAD still require current evidence. A release that validly admitted an earlier consumer remains historical evidence after a later commit, but cannot admit new consumers at the changed HEAD. Keep formal execution, `release`, and `finish` clean; do not require replaying obsolete gates merely to audit their valid history.

## Diagnose and recover

`diagnose` takes `attempt_id`, nonempty `reason`, a nonempty `evidence` array, and nonempty `next_action`. At least one evidence identifier must be new for that failure. Preserve classification and its real supporting facts; a new identifier without new evidence is not a new diagnosis. Unknown causes and missing business decisions remain blocked until resolved. Diagnostic records do not replenish budgets.

The three runtime budget fields are run-wide limits. Agent-defined local diagnostic allocations and preflight counters use the separate [local diagnostic budget policy](diagnostic-budgets.md), with evidence-based autonomous extensions and append-only history. These records add no `cycle.py` plan field or event and do not modify its global accounting. Reaching a local count triggers that policy's review/renewal path, not an automatic whole-task stop.

Each new skill invocation resuming the run first collects all ten explicit model selections, then applies `invocation` with `kind:"resume"` and a complete `models` object using the plan's role keys. That event's `op_id` is its `invocation_id`; `inspect.models` returns the current invocation's choices while prior choices, run ID, failures, and budgets remain in history. A separate CLI command within the same skill invocation does not require a new questionnaire.

Apply `recover` with `invocation_id` referencing that latest invocation event. Replay an identical recovery `op_id` only to retrieve its idempotent prior result. To observe changed process or receipt state within the same skill invocation, use a new recovery `op_id` and the same `invocation_id`; this does not repeat settled charges. Recovery verifies the anchor/history and available requests, claims, receipts, and logs, settling a complete unrecorded receipt once under the same rules as `record`, including snapshot-changed `ineligible` results. A live owned attempt remains blocked/running; uncertain ownership remains blocked/ownership-unknown. Confirmed termination without a verifiable complete receipt becomes interrupted. Existing corrupt hashes, binding, or history remain rejected, never relabeled interrupted. Do not launch a duplicate or guess a PID to kill.

When prepare is durable but no claim exists, recovery atomically and exclusively creates a cancellation claim at the reserved claim path. That claim prevents a delayed runner from starting; recovery settles the interrupted reservation conservatively once. If another runner/recovery wins the claim race, reread its claim and follow the observed ownership state. A check-then-unconditional-write is unsafe. Partial, damaged, or insufficiently identified claims remain ownership-unknown. Leave claim creation and reconciliation to the runtime; a missing claim alone is not permission to free the reservation or start another command.

Every prepare consumes an attempt and reserves its timeout; recording settles actual duration, including complete ineligible results. Interrupted attempts lacking verifiable complete receipts conservatively consume the reservation. Formal nonzero, timeout, interrupted, or ineligible results consume one formal-failure credit per attempt even if several conditions apply. Expected development Red is exempt only from that formal allowance, not attempts/time. `inspect` exposes active examples/gates, pending attempts, failures, models, budget use, and last sequence; `verify` checks history and adopted evidence rather than trusting the reported status.

Runner provides owned process containment: Windows uses a Job Object established before allowing the target to start; POSIX uses a separate session/process group. The first POSIX adapter does not claim containment of deliberately escaped sessions or automatic cleanup after the supervisor receives SIGKILL. Keep platform support tied to actual validation and preserve unknown ownership for explicit recovery.
