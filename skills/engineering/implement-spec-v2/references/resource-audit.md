# Resource obligations and alerts

Read this reference when setting up the invocation watch, reaching a release boundary, handling a resource alert, or reconciling a stage. Resource owners do the file work; the existing merger checks handling receipts. Use the helper from [resources.md](resources.md). This protocol adds neither an agent role nor a model assignment.

## Delivery obligations

Use `due` to record each reached [release boundary](resources.md#release-boundaries) against the affected resource, its owner, a unique event ID, stage, and an evidence pointer. Reuse the event ID when retrying that same obligation; a later boundary needs its own ID. `record-test` for a successful attempt and `resolve` automatically register the output's obligation and return its `release_due` event; use that ID for receipts rather than registering the same boundary twice. A test command finishing starts evidence work. A ticket worktree becomes a candidate after verified integration. Checkpoint and final-review boundaries follow the table. Failure, interruption, and replacement require a retention or handoff receipt, not an assumption that the environment is disposable.

The helper can identify a **candidate requiring owner verification** from registered events and command metadata. It cannot establish that diagnostic inputs are regenerable, a test summary is truthful, or external workloads are idle. The owner verifies those facts and the guarded release prerequisites before deleting anything. A new command or changed resource invalidates an earlier assessment; the release operation checks current state again.

Before returning the corresponding delivery report, handle every due resource and include its event ID and receipt:

- **Released:** `release` records its attempt/result and binds a successful receipt to the current obligation. Report that result and durable delivery/evidence pointers; a failed attempt is not a released receipt.
- **Retained:** use `disposition --kind retained` with the event ID, concrete blocker, evidence pointer, and next check time or event. A future checkpoint requiring a test worktree is a valid retention condition; “clean up later” is not.
- **Handed off:** use `disposition --kind handoff` to name the receiving owner and preserve the original resources, budgets, evidence, and round counts. The receiver records `--kind accept` for that event so a departing owner cannot silently leave an obligation unowned.

After acceptance, transfer each inherited idle budget with `reservation --id BUDGET --owner OLD_OWNER --transfer-to NEW_OWNER --idle-confirmed --reason ACCEPTANCE_POINTER`. A budget still claimed by a running or uncertain command stays with that command until normal completion or confirmed stopped recovery; then transfer it before the receiver starts new work. This preserves the existing estimate without allocating a second environment or impersonating the previous owner. The legacy `handoff` command remains for environments without a release obligation; event-bound obligations use the accepted handoff above.

Keep receipt details within the original input boundaries. A merger checking test-side obligations reads neutral metadata and routes missing work to the test owner; resource bookkeeping does not grant access to independent tests or implementation details. Retrying the same check, repeating a retention explanation, or acknowledging a message does not constitute progress.

## Watch and report delivery

The exploration agent starts one invocation-scoped helper `watch --state STATE` after ledger initialization. It checks immediately and every 30 minutes while the invocation runs. The helper registers its process and stdout delivery in the ledger; exploration reports the runtime's CLI/session handle and output channel so the scheduler can receive its structured reports. Watch state and reports remain in the existing `state.json`; the ledger directory retains its existing file whitelist. Use the CLI's stdout or an existing execution output channel, without adding monitor files or a machine-wide scheduled job.

The watch reads only this invocation's ledger metadata and destination-filesystem free space. It neither traverses source/output trees nor diagnoses tests, deletes resources, terminates business commands, or scans older tasks. Missing PIDs, old timestamps, and unknown command outcomes require owner investigation; they are never cleanup permission.

The script persists a report every 30 minutes while it is running and emits changed action items; unchanged healthy checks do not add repeated output. That does not guarantee platform notification or model wakeup. The scheduler handles delivered notifications when available; otherwise it obtains the watch's report through a responsible subagent at the next completion or timeout boundary. If the runtime cannot keep the watch alive or expose its output, report that limitation explicitly and continue the event-driven checks; do not claim the periodic fallback is active.

Use `watch-stop --state STATE` when the invocation finishes, then confirm the watch's exit and recorded `stopped` state before `seal`. A `stop_requested` state is insufficient. On recovery, inherit the existing watch registration and inspect its real CLI state before starting a replacement. An uncertain or missing process is not evidence that it is safe to replace the registration. Preserve all normally advancing test/build processes.

## Dispatch and escalation

The main conversation may dispatch from a delivered structured `resource-alert`; it does not open the ledger or resource files in steps 6–10. Alerts contain invocation, resource, event, owner, check identity/time, missing handling step, and evidence pointers; omit code, test contents, and raw logs.

On the first missing or overdue handling receipt, automatically route verification and cleanup to the original owner, or a replacement using that role's selected model and existing resources. An owner still doing business work continues to its next safe boundary. The first independent observation counts as one; if the second still finds no substantive progress, escalate to the existing merger for reconciliation. Independent checks are separated by 30 minutes or correspond to a genuinely new registered stage event; replaying one report or polling repeatedly does not advance escalation. Use a stable `audit --check-id` for retries and `--trigger` only for an already registered event.

Substantive progress changes the obligation: a successful release, a verified blocker change with evidence and a next check, or an accepted handoff. The merger repairs ownership and routing, asks the authorized owner to inspect restricted evidence, and performs only releases within its existing authority. It does not reinterpret “needs verification” as “safe to delete” or interrupt active commands to make space.

At every existing merger delivery, check this invocation's outstanding obligations and receipts using metadata only. A boundary with no receipt is an evidenced process omission; an owner-verified resource with no release result or blocker is an execution omission. A supported retention condition before its next check is normal retained work. Report the event, owner, missing action, and next route rather than treating every retained directory as a failure.

For example, after registering `ticket-42-integrated` as shown in [resources.md](resources.md), the merger can assess and release the worktree, then check the stage:

```sh
python3 "$RESOURCE_TOOL" preflight --state "$STATE_DIR" --resource ticket-42 \
  --merged-into "$PR_BRANCH" --idle-confirmed --evidence-confirmed
python3 "$RESOURCE_TOOL" release --state "$STATE_DIR" --resource ticket-42 \
  --merged-into "$PR_BRANCH" --idle-confirmed
python3 "$RESOURCE_TOOL" audit --state "$STATE_DIR" \
  --check-id ticket-42-stage-check --trigger ticket-42-integrated
```

The confirmation flags assert the owner's completed checks; omit them until verified. If release is blocked, record a receipt such as `disposition --state "$STATE_DIR" --resource ticket-42 --event-id ticket-42-integrated --kind retained --reason "Run ticket-42-build still uses the worktree" --evidence ticket-42-build --recheck-at "$NEXT_CHECK_UTC"`. Return the resulting structured report and receipt to the scheduler.
