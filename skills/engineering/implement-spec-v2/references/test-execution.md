# Acceptance execution protocol

Read this protocol when designing execution contracts, preparing formal acceptance, handling an execution alert, or recovering an interrupted test. It applies to every acceptance test: runner startup, fixtures/setup, execution, teardown, descendant processes and log collection. Use the bundled process-external supervisor through [resources.md](resources.md); a project adapter or equivalent native runner supplies the project's lifecycle and progress evidence. The adapter is trusted infrastructure, subject to the execution gate and the test side's neutral-input boundary.

The resolved test-review acceptance-contract reference remains authoritative for business deadlines, evidence waits, harness caps and failure semantics. This protocol provides execution containment and qualification; it does not create or relax business SLAs. Independent test blessing, execution qualification and observed product results are separate conclusions.

## Prepare the execution contract

Before formal acceptance, record the following in the approved test-safe package:

- A stable attempt, worker and case identity; worker and case start/end events; setup, run and cleanup phase start/end events. Suite fixtures and command startup must be represented within these boundaries. A case can run as an independent command when the native runner cannot expose its boundaries. A whole-command cap without these observations is insufficient for formal acceptance.
- Finite budgets for the whole attempt, each case and each phase, with named test-category profiles or explicit long-case exceptions where justified. Record each threshold's source, clock, start/end events, included work and fixture/environment assumptions. Suitable sources are project requirements, comparable immutable historical runs, or a bounded preflight measurement. If none exist, propose and record a reasoned provisional harness cap before running; missing business semantics remain unresolved requirements.
- Declared progress kinds for required work and their public observation/injection seams. Progress must belong to the current attempt, worker and case and carry fresh evidence. Internal progress may be unknown while case/phase boundaries and finite caps remain available.
- The isolated process scope, termination capability and repeatability assumptions, including external effects, owned descendants and any shared GUI, service, device or fixture. Record the adapter/configuration/environment inputs the execution gate must bind.

Formal acceptance runs against a committed, clean worktree. Save/commit the candidate before launch and keep its source immutable under the run owner's exclusive control for the entire attempt. Record temporary outputs in allocated data resources. At completion, a bounded source check must confirm the same HEAD and a clean worktree before qualification; a changed or unverifiable source leaves the result unverified even when the test process passed. Before/after clean checks are a defense, not proof that a concurrent temporary edit never occurred. If exclusive immutable-source use cannot be established, retain that qualification gap. Throwaway checks of uncommitted work remain nonformal.

Use monotonic time for enforcement. Set a fixed supervised-command horizon before launch, including a reserved shutdown window: active execution has `total - shutdown` seconds, followed by at most the remaining shutdown window for capture, termination and pipe/log finalization. Case and phase deadlines are fixed from their start events; progress does not renew them or the total horizon. If delayed observation finds several expired deadlines, report the earliest absolute deadline across workers and the total active window. End evidence first observed after an already established deadline cannot erase that timeout; classify any observation delay before attributing a business failure. A timeout inside a callback or GUI event loop is insufficient: supervision runs outside that loop and process. Final ledger registration has a separate finite lock-acquisition allowance bounded by the declared shutdown budget; report registration delay separately from command elapsed time rather than extending the command's horizon.

A stall threshold requests investigation; it does not prove deadlock or business-time failure. Only fresh evidence for a predeclared progress kind from the relevant active worker/case refreshes its progress clock. Heartbeats, CPU usage, arbitrary log growth, duplicate evidence and activity from another worker are diagnostic clues. They do not establish required progress. With no internal observation, report progress **unknown** and use the fixed case/phase/attempt caps. Healthy progress from one worker cannot conceal another worker's missing boundaries or exceeded deadline.

Global agent inactivity rules and the 30-minute resource watch serve their existing purposes. Agent/tool events do not refresh test progress, and the resource watch is not a test supervisor.

## Prove the execution gate

Before the first formal acceptance run, the run owner executes and records a gate using the actual supervisor, project adapter, runner command/configuration and relevant environment. A timer declaration or an isolated decision model does not prove that the real execution path can return. The evidence must cover these failure classes and the healthy counterfactual:

| Injected path | Required evidence |
| --- | --- |
| Blocked test/observer, including a GUI callback or nested event loop when applicable | External supervision ends the affected execution within its fixed horizon. |
| Nonproductive heartbeats or continuous logs | Noise does not refresh accepted progress or extend a hard cap. |
| One stalled worker while another progresses | The stalled worker remains individually observable and bounded. |
| Parent exits while an owned descendant keeps an output pipe open | Descendant handling and pipe finalization return within the shutdown window. |
| Capture, teardown or cancellation fails to return promptly | The supervisor's own control path remains bounded and reports any uncertain termination. |
| Legitimate slow execution with credible progress | Progress is recognized, the valid path can complete within its contract, and the whole horizon remains fixed. |

Bind the proof to immutable supervisor/adapter inputs, execution contract, argv, working directory and declared environment. Execute the actual runner twice: its complete scenario must finish valid boundaries, and its blocked-callback scenario must enter the approved real callback/observer injection seam and then block after completed setup and an active run case. External supervision must establish the earliest applicable case, phase or total hard cap, a matching gate nonce, no event errors, confirmed stopped scope and complete capture within the original horizon. Preserve the actual contract rather than adjusting it to force a case-timeout endpoint. Healthy actual execution plus synthetic failures alone leaves adapter blocking coverage unverified. Synthetic canaries supplement the other failure paths. Keep the relevant product revision and neutral gate results in the acceptance evidence. Rebuild the gate when bound inputs change. A native runner is eligible only with evidence establishing equivalent observation, containment, ownership and proof requirements for that concrete invocation.

After each formal attempt, the resource helper runs a separate subprocess to revalidate the original receipt SHA and supervisor/adapter/contract/environment binding. This `validate-gate` check has a finite shutdown-budget deadline. Changed inputs, invalid proof or an incomplete/timed-out check leave the result unqualified; a successful prelaunch gate cannot certify inputs that changed during execution.

The gate demonstrates these controllable paths on its declared platform. It does not establish an absolute guarantee against kernel-level blocked I/O or an unkillable process state. Uncertain process termination or persistence remains unknown and requires retained resources and owner investigation.

The run owner prepares neutral events, timing, configuration and fixture/environment facts for test review; production stack frames, private locals and implementation diagnosis remain with Checkpoint/Fixer. Missing supervision, lifecycle observations, isolation or a current proof leaves execution **unverified**. Limited diagnostic runs can gather facts under finite containment, but their results do not qualify acceptance or complete the spec.

## Run and handle alerts

The resource helper records the contract and gate with the attempt before launch. The owner exposes bounded status and structured `execution-alert` delivery. Each alert/report identifies the invocation, attempt, worker, case, phase, owner, last accepted progress, progress status, applicable deadline, neutral reason and durable evidence pointers. Repeated alert polling is neither test progress nor a phase delivery.

In steps 6–10, the main conversation obtains these delivered facts through bounded runner/owner status queries and routes alerts to the existing role. Each caller wait returns control soon enough for user updates, within 60 seconds. The owner uses `execution-status --run RUN [--lock-timeout S]` for lightweight ledger metadata: owner/attempt, process identity, budgets and evidence/log pointers. Its lock-acquisition timeout defaults to 5 seconds and accepts `0 < S <= 60`; it performs no file scan, Git check or qualification audit. Owners separately report current worker/case/phase events and alerts through their permitted evidence access. `acceptance-status` and `seal` inspect files and source qualifications, so their callers must use bounded execution instead of treating them as liveness probes. A finite lock/caller policy is not an absolute OS wall-time guarantee.

The main conversation retains its dispatch-only boundary: the owner reads files, diagnoses processes and saves evidence. If an execution channel or agent stops reporting, inspect its real connection, pending tool/CLI state and the machine watchdog under the existing activity/recovery rules; do not mistake model activity for test health.

On suspected stall, collect the smallest bounded check that distinguishes a long valid execution from blocked work or an observation gap. At a fixed execution cap, save available neutral timing/lifecycle facts and necessary raw failure evidence, then end the affected attempt through its predeclared owned termination scope. Capture and graceful stop have finite sub-budgets; escalation and pipe/log completion consume the reserved shutdown window. Confirm actual wrapper/descendant termination before recording an idle or interrupted resource outcome.

If ownership, isolation or termination cannot be established, return a finite **unknown/unverified** result, retain the resources and necessary evidence, and report the missing capability or required human action. Shared processes, public services and devices remain outside automatic termination/recovery authority. Preserve unrelated tests/builds that are advancing. An interrupted, partially collected or incompletely terminated attempt cannot be recorded as passing merely because the direct child exited zero. A zero product exit with unverified lifecycle coverage, a timeout/exit race or changed source is also a supervised failure/qualification blocker; retain and classify it through the normal diagnosis path. Product exit zero does not clear the anomaly.

The supervisor writes durable terminal evidence before final ledger registration. If the bounded ledger lock cannot be acquired, the finite source check cannot establish the candidate, or registration fails, retain the attempt's terminal/evidence pointers and unresolved state; stop retrying those checks indefinitely. Unknown termination or registration retains its capacity claims. A terminal file by itself does not establish a registered, qualified acceptance result. The owner confirms stopped state and reconciles the existing attempt under the resource protocol without replacing its first-failure record.

## Classify and recover once

Follow the SKILL.md failure-classification and ownership rules before repairing or recovering: distinguish the measured business event, evidence wait, harness cap, observation mechanism and environment. Record the execution classification with `classify-run --run RUN --classification business|evidence|harness|environment|unknown --evidence PTR`; this execution category accompanies the existing hypothesis and responsible-owner report. On the first timeout, the existing Checkpoint/Fixer supplies a test-safe failure package for fresh failure-scoped test-review. Test/contract changes remain with the implementation-blind Test implementer and require the existing review/adjudication path.

An unknown classification is a diagnosis checkpoint, not a dead end. After confirming stopped state and recording the recovered attempt when necessary, the owner can supply new neutral evidence and classify it again. Preserve prior classifications in the history and the original terminal/failure evidence. Changing unknown to a supported classification enables the existing adjudication path; it does not itself resolve the failure or qualify acceptance.

Conditional automatic recovery is permitted only after diagnosis establishes a next action, ownership and isolation are verified, the previous scope is confirmed stopped, and repeating the operation is authorized and safe under its recorded external-effect assumptions. Otherwise preserve the scene and wait for human action. Recovery may restore an invocation-owned fixture or worker; it grants no authority to restart shared applications, services or devices.

Use a new attempt ID and its own fixed finite execution window. Link it to the original failure and stable failure key, retaining first-failure evidence, original business contract, resources, checkpoint/fixer round counts and recovery history. Supply `--recovery-evidence PTR` for the verified isolation, fixture reset and repeatability findings; the prior attempt must be classified, confirmed stopped and have completed evidence capture. A new window does not extend the ended attempt's deadline. For the same unresolved failure, conditional automatic recovery is available at most once; changing agents, commands, attempt IDs or failure labels does not replenish it. Diagnosis and test-review also do not reset existing repair budgets. A second stall hands off the objective, completed evidence, remaining uncertainty, original resources and live CLI identifiers to the owning main conversation for adjudication or replacement under the existing activity protocol.

Evidence-backed repair verification is distinct from automatic recovery. Fixers and checkpoint owners use `--validate-after RUN --repair-evidence PTR --repair-round N` to verify an actual repair; this route and `--retry-of` are mutually exclusive. Reference the same chain's latest completed attempt, preserving its evidence and business contract. The prior workload must be confirmed stopped with complete capture or a recorded manual stopped confirmation. A failed prior attempt must be classified first; a passing attempt may be followed by verification of an evidenced review repair.

Repair verification rejects an execution-policy change by default. A legitimate contract correction additionally supplies `--contract-change-evidence PTR`, linking authoritative adjudication and independent test-review evidence. Save the before/after contract and change history under the existing formal-test/contract ownership rules. Such a correction preserves the chain's repair rounds and used recovery credit; it grants no authority to change a business SLA without its authorized contract decision.

Set `--repair-limit 1|2|3` on the chain's initial formal run to the existing phase budget. The final fixer default is 3; checkpoint runs explicitly select their adjudicated 1 or 2 rounds. Each repair verification consumes the next round, strictly the recorded round plus one; the initial limit remains fixed through retries, replacements and owner changes. Repair verification does not replenish the chain's one automatic recovery, and automatic recovery does not reset repair counts. If the phase budget is exhausted or there is no new repair evidence, return the outstanding diagnosis/decision to the main conversation rather than starting another verification. Review repairs after an already green suite use this same evidence/round path.

A later complete green run records that attempt's observed success. It does not erase the first failure or demonstrate its cause was repaired. Explain and resolve the hang with a justified diagnosis and relevant verification, or leave final acceptance **unverified** and the PR **draft**. `resolve` for an execution-contract attempt requires a non-unknown classification and `--validation PTR` in addition to its recorded reason, including when the original supervision did not produce a registered terminal result. The responsible owner and relevant review verify that classification, repair, contract-change and validation pointers are real, readable evidence supporting the stated root cause and correction. A supplied pointer or later green run alone is not a root-cause explanation. Keep necessary unresolved evidence under the resource protocol; diagnostic-only results cannot support final qualification.

## Qualify the final delivery

The owner checks `acceptance-status` for qualified runs, source-qualification gaps and unresolved blockers, then reconciles them with the final candidate, coverage and review results. Historical qualification is excluded when the run's recorded revision differs from its current or preserved worktree candidate. A qualified checkpoint subset or an older revision cannot establish full final acceptance.

For verified sealing, use `seal --pr-json FILE --acceptance-run RUN --acceptance-scope FILE`. Select the completed, qualified final run at the fresh REST PR head revision. Supply the full approved acceptance scope with a source pointer to the pinned coverage/public-contract evidence:

```json
{
  "acceptance": ["spec@revision: criterion 1", "spec@revision: criterion 2"],
  "source": "Pinned approved coverage report and acceptance-contract revision"
}
```

The owner verifies that this list includes the complete approved final scope. Each required criterion must be supported by an actually executed, valid passing test in the selected run, with the approved observable evidence; a `full-suite` label or skip-only criterion cannot substitute for passing coverage. A suite may have nonrequired skips, but those tests contribute no required coverage. The selected run's recorded acceptance pointers must cover the scope, and all unresolved execution failures still block qualification. The helper checks the source pointer's presence and the recorded scope/revision relationships; the responsible owners and independent coverage review establish the evidence's semantics and criterion-to-passing-test mapping.

A sealed failure handoff remains **unverified** and retains its evidence. It requires a fresh native REST PR object with `draft: true`; a ready PR or missing draft status cannot support this path. Sealing records the qualification result and does not by itself authorize ready-for-review.

## Bundled runner interface

Use `resources.py --help` and `execution_supervisor.py --help` for CLI details. Formal attempts supply `run --test --acceptance --execution-contract FILE --execution-gate FILE --failure-key KEY` against a committed clean worktree. Their initial run fixes `--repair-limit 1|2|3` (default 3; checkpoint owners explicitly choose 1 or 2). `--test` alone remains a nonformal evidence entry. Conditional recovery adds `--retry-of RUN --recovery-evidence PTR`; repair verification instead adds `--validate-after RUN --repair-evidence PTR --repair-round N`, plus `--contract-change-evidence PTR` only for an adjudicated/reviewed policy correction. Both preserve the original failure key, ledger resources, fixed repair limit and recovery history. Use `execution-status` for live metadata and bounded `acceptance-status`/`seal` calls for qualification.

The supervisor contract uses `version: 1` and these keys:

```json
{
  "version": 1,
  "budgets": {
    "total": {"seconds": 120, "source": "Recorded provisional whole-attempt bound"},
    "shutdown": {"seconds": 10, "source": "Verified supervisor shutdown allowance"},
    "case": {"seconds": 40, "source": "Comparable case evidence pointer"},
    "phase": {
      "setup": {"seconds": 20, "source": "Comparable setup evidence pointer"},
      "run": {"seconds": 80, "source": "Comparable run-phase evidence pointer"},
      "cleanup": {"seconds": 10, "source": "Comparable cleanup evidence pointer"}
    },
    "stall": {"seconds": 15, "source": "Recorded investigation threshold"}
  },
  "long_cases": {},
  "case_profiles": {},
  "progress_kinds": [],
  "adapter": {"files": ["tests/acceptance_adapter.py"], "environment": []}
}
```

These numbers and the adapter path illustrate the schema; select and source project-specific values and an existing adapter before running. `long_cases` maps a case ID to its sourced case budget; `case_profiles` maps a declared profile to its sourced case budget. `progress_kinds` lists the accepted progress kinds; an empty list means internal progress is unknown. `adapter.files` names the nonempty set of proof-bound adapter inputs and `adapter.environment` names proof-bound environment variables. Include every input whose change could invalidate the proof.

The supervisor supplies `IMPLEMENT_SPEC_ATTEMPT_ID` and `IMPLEMENT_SPEC_EVENTS_PATH` to the project adapter. Append UTF-8 JSONL lifecycle events to that path, preserving complete frames when workers write concurrently. Scope each event to the supplied attempt ID and a stable worker ID; stdout remains ordinary diagnostic output.

Version-1 lifecycle events carry `version`, `attempt_id`, `worker_id` and `kind`. A worker's minimum sequence is `worker_start`, setup `phase_start`/`phase_end`, run `phase_start`, at least one `case_start`/`case_end`, run `phase_end`, cleanup `phase_start`/`phase_end`, and `worker_end`. Phase values are `setup`, `run` and `cleanup`. Case events carry `case_id`; `case_start` may select a declared `profile`. A `progress` event carries the current `case_id`, a declared `progress_kind` and a fresh `evidence` token. Heartbeats provide liveness clues only. Every started worker must finish its declared boundaries for qualification.

Create a gate receipt with `execution_supervisor.py gate --contract FILE --cwd DIR --output RECEIPT -- COMMAND`. Both actual-runner invocations receive `IMPLEMENT_SPEC_EXECUTION_GATE=1` and acknowledge `IMPLEMENT_SPEC_GATE_NONCE` through `gate_ready` with a matching `nonce`. `IMPLEMENT_SPEC_GATE_SCENARIO=complete` selects the healthy finite lifecycle. `IMPLEMENT_SPEC_GATE_SCENARIO=blocked_callback` selects the real callback/observer seam: complete setup, enter an active run case, then block until the earliest applicable case/phase/total hard cap. Require zero event errors, confirmed stopping and complete capture within the unchanged contract horizon. Keep this injection mechanism in the approved neutral adapter infrastructure; the test side receives public events/timing, not business implementation diagnosis. Separate synthetic canaries cover the additional failure paths. Ordinary supervised runs clear the gate, nonce and scenario environment variables. A hand-written receipt or `passed: true` declaration supplies no proof. The bundled ownership implementation requires Linux `/proc`; unsupported platforms fail closed until an equivalent runner and proof are available.
