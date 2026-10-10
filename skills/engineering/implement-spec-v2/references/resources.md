# Resource lifecycle protocol

Read this protocol when creating resources, running tests, handing a task to a replacement, or releasing resources. For formal acceptance, execution alerts or recovery, also read [test-execution.md](test-execution.md). Use the helper bundled at `../scripts/resources.py`; its `--help` is the parameter reference. Git and Python 3 standard libraries are the only helper dependencies. Select the available Python 3 executable on the destination machine and resolve the helper from the skill location.

## Invocation scope and ownership

The exploration agent uses `init --notes-root` before writing notes. The notes root must be new or empty, outside the repository and Git metadata, and contain the ledger as a strict child directory. The helper records its directory identity and `.implement-spec-notes` marker. Pass the notes, state and helper paths as context pointers. The state contains resource metadata and compact run records, not source-tree archives. Keep each author's access to evidence within the existing test/implementation input boundaries; resource bookkeeping grants no additional access to code, tests, or another role's records.

Use `create` to acquire an empty data directory or a Git worktree at a previously nonexistent path; its parent directory must already exist. The helper creates and registers it in one workflow. Existing directories cannot be adopted; this protocol does not scan or clean historical tasks. Record the role and owner, revision, parent resource if physically contained, command usage, and eventual disposition. Keep the state outside every resource it manages. Generated results go outside the source repository; required fixtures remain governed by the project.

Use allocated data directories for test temporary files, logs, generated reports, disposable databases, and necessary diagnostic inputs. Configure the project's runner to place these files there. A directory's name or `.gitignore` entry is not evidence that its contents are disposable. Dependencies and build outputs created inside a worktree must be accounted for before release. Reuse dependencies and caches through the package manager or build tool's native concurrency-safe mechanism; keep mutable environments, databases, build outputs, and role-specific results isolated. Shared caches outside this invocation remain outside its cleanup scope.

Step 3 creates the PR branch in a new registered PR working copy. Mergers and fixers use that resource as their `--cwd-resource`; an existing primary checkout cannot be adopted. Keep the PR working copy through integration and review repairs, then release it against the delivered PR branch while retaining that branch and its commits.

Prefer a revision pointer and necessary uncommitted diff to another complete source copy. If an experiment genuinely needs a separate checkout, create another registered worktree with its own purpose and release condition. A failure or agent replacement inherits the existing resource IDs, evidence pointers, and round budget.

## Running commands and keeping evidence

Run commands using registered resources through `run`, listing every resource they use and supplying the capacity reservations described below. The helper records activity before starting, releases its short ledger lock while the command runs, and records completion afterward. It streams stdout and stderr into compressed files in the allocated output directory, avoiding a second full-sized log copy. Configure additional test outputs into that directory too; the helper cannot discover every file a project-specific runner creates.

For a test attempt, pass `--test`, then use `record-test` with a compact JSON summary. Formal acceptance additionally requires `--acceptance --execution-contract FILE --execution-gate FILE --failure-key KEY` under the execution protocol. `--test` alone records nonformal diagnostics or throwaway tests; it cannot qualify acceptance. The contract/gate and resulting execution facts accompany the attempt record. The helper retains the command, working directory, source revision, timestamps, exit code, and Git/Python/OS information. The owner supplies the project's runtime and dependency versions or lockfile fingerprints, random seeds, relevant input revisions, failure explanation, and reproducible command in the summary. Keep these records small; reference large inputs by immutable revision and fingerprint, retaining necessary non-regenerable inputs in an owned data directory.

Commit the candidate and confirm a clean formal worktree before launch; the owner keeps its source immutable and exclusively controlled for the entire attempt, writing run outputs into allocated data resources. Final qualification also requires the recorded HEAD to remain unchanged and a bounded final clean/source check to succeed. Before/after checks cannot certify that no concurrent temporary edit occurred. Missing source verification leaves acceptance unverified. Formal completion also revalidates the original gate receipt SHA and binding in a separate shutdown-bounded subprocess. The initial formal run fixes `--repair-limit 1|2|3`: final fixer runs default to 3, while checkpoint owners explicitly select their existing 1 or 2 round budget.

Conditional automatic recovery uses a new run ID with `--retry-of RUN --failure-key KEY --recovery-evidence PTR`; retain the first failure, inherited contract/resource pointers and original repair/recovery counts. The execution protocol defines the one-recovery limit and required classification, stopped-state, complete capture, isolation and repeatability evidence. Replacement agents inherit this history. A fixed execution horizon includes shutdown and log finalization; unknown termination keeps the existing resource and capacity claims until confirmed stopped. A zero direct-child exit or later green attempt does not clear an interrupted or unexplained execution failure. Use `classify-run` for execution diagnosis, `resolve --validation PTR` for justified resolution, and `acceptance-status` before final qualification; read the execution protocol for these gates.

For actual repair verification, use a new run ID with `--validate-after RUN --failure-key KEY --repair-evidence PTR --repair-round N`, referencing the same chain's latest completed attempt. This route is mutually exclusive with automatic recovery. Require classified prior failure (or an already passing prior attempt for an evidenced review repair), confirmed stopped state/complete capture or recorded manual stopped confirmation, and the next consecutive repair round within the original fixed limit. The verification route preserves the used recovery credit and cannot restart repair counts by changing owner or run names.

Execution-policy changes on that route are refused unless `--contract-change-evidence PTR` records authoritative adjudication and independent test-review. Preserve before/after contracts and history, plus the original round/recovery counts. The owner and review establish that evidence pointers are readable and substantiate the correction; pointer syntax or a later green run supplies no causal proof.

For live metadata, an owner uses `execution-status --run RUN [--lock-timeout S]` (default 5 seconds; `0 < S <= 60`). It returns ledger owner/attempt, process identity, budgets and evidence/log pointers without file scans, Git checks or qualification work. `acceptance-status` and `seal` require file/source checks and bounded caller execution; their lock policy is not an absolute OS wall-time guarantee.

The summary schema is:

```json
{
  "tests": {"passed": 8, "failed": 0, "skipped": 1, "errors": 0, "total": 9},
  "acceptance": ["ticket-42: acceptance criterion 3"],
  "reproduce": "Checkout the recorded revision, install from the recorded lockfile, then run the recorded command with seed 17.",
  "notes": "Project runtime and dependency fingerprint; relevant input revision; diagnosis if needed."
}
```

Counts are nonnegative integers and `total` equals their sum. `acceptance` and `reproduce` are required. The summary input is bounded to 64 KiB. The owner must verify that the statistics describe the actual run and that the reproduction information is sufficient; schema and checksum validation cannot establish those semantic facts.

Acceptance pointers must map required criteria to actually executed, valid passing assertions. A skip-only criterion or suite label supplies no required passing coverage; nonrequired skips may remain in the suite. Product exit zero also does not clear unverified lifecycle coverage, a timeout/exit race or a changed-source result: preserve these supervised anomalies, classify them and obtain justified validation before resolving their qualification blockers.

After a passing attempt's record is validated, release its regenerable raw outputs. Compact updates create small immutable record generations; the ledger references a completed generation and its checksum, so interruption during an update does not overwrite the previous evidence. For a failure, preserve the necessary diagnostic scene until the issue is explained and resolved. `resolve` requires the justification and changes the retention state; it does not delete files. A later passing run alone is insufficient justification for deleting an unexplained intermittent failure. An unexplained first hang leaves final acceptance unverified and the PR draft under the execution protocol. Final acceptance follows the same compact-record policy; retain no separate final acceptance archive.

Store failure evidence outside scratch worktrees before releasing them. Preserve source revisions or saved changes needed to reconstruct the experiment; a path into a deleted checkout is not a durable context pointer. Do not copy an entire environment into an archive merely to delete the original.

## PR handoff for later cleanup

New invocations use the owned notes-root protocol. Historical ledgers created without it retain their existing development/release behavior but cannot publish a cleanup handoff; `cleanup-spec-v2` audits those tasks only.

Before creating the draft PR, use `publish-branch --resource PR_ID --remote-url URL` for the PR branch's first remote publication. Use the intended head repository's native REST `clone_url` exactly. The helper first verifies the remote ref is absent, persists `creating`, pushes with an empty expected-ref lease, and requires Git's porcelain result to confirm a new ref was created. An existing same-OID ref or a concurrent no-op is not creation evidence. Only a verified first publication becomes `created`; an interruption or uncertain push remains retained and cannot be automatically retried or adopted. Subsequent development pushes target this same destination and branch. If another invocation-created branch is published remotely, register its first publication with this helper too.

After creating the draft PR, fetch its fresh native REST response and pass the saved JSON to `bind-pr --pr-resource PR_ID --pr-json FILE`. It binds the PR's host, ID, number, base/head repository identities, refs and SHA to the invocation-created, first-published branch. This input establishes a delivery pointer, not cleanup permission or proof that the PR is merged. The helper writes one discovery index JSON per invocation, grouped by the SHA-256 of the common Git directory, under `${XDG_STATE_HOME:-~/.local/state}/implement-spec-v2`; use `--index-root` at initialization for another location outside notes/repository/Git metadata.

Save native REST JSON in the notes root outside the ledger, for example `$NOTES_DIR/pr.json`, so the sealed notes snapshot records it; the ledger subtree contains only `lock`, `state.json`, `handoff.json` and `records`.

After final pushes, integration/review repairs, resource reconciliation and final note writing, stop the invocation watch and verify its recorded completion under [resource-audit.md](resource-audit.md). Then fetch another fresh native REST PR response and use `seal --pr-json FILE --acceptance-run RUN --acceptance-scope FILE` for verified final delivery. The scope file contains the full approved acceptance pointers and their pinned coverage/public-contract source under [test-execution.md](test-execution.md#qualify-the-final-delivery). The selected qualified run must match the fresh PR head and cover that scope; older-source or partial-checkpoint success cannot qualify final acceptance. An unverified failure handoff may still be sealed, but the fresh REST object must explicitly establish `draft: true`; ready or missing draft state is refused.

Sealing verifies the final PR head against the local branch and the live owned remote ref, records expected local/remote OIDs, active worktree HEADs and existing or anticipated release-anchor refs, and writes `state/handoff.json` plus its identity/checksum into the index. It also records acceptance qualification and blockers; a sealed draft/failure delivery is not ready-for-review approval. The notes snapshot hashes ordinary files outside the ledger and still-registered resource subtrees; symlinks, mounts and special files become explicit blockers. Later unexplained additions or changes must not be swept into cleanup.

The handoff also fingerprints every active data resource's relative contents, entry types, identities, file hashes and symlink-target bytes without following links. Each registered child subtree has its own fingerprint and is excluded from its parent's fingerprint, so safely releasing a child does not change the parent baseline. Mounts, special files, or an unknown replacement at a released child path become blockers. Cleanup compares data both with this sealed baseline and the user's confirmed inventory; personal files added after sealing are retained. If an existing command finishes after sealing and changes its output, the original owner can validate its record and safely release the output under this protocol before another cleanup plan. Cleanup does not rebaseline changed output or invent a failure resolution.

Sealing closes new allocations, command runs and publications. Existing runs can still be recorded, recovered or resolved, and existing resources can still be safely released. Release may create an anticipated revision anchor after sealing; later cleanup rechecks it after releasing its worktree. Keep the sealed handoff, index, compact records and delivered branches available until the user explicitly invokes `cleanup-spec-v2 <PR number>` after merge and confirms its complete list. That separate workflow can then delete all invocation-owned local/remote branches, refs, notes and records; a partial cleanup retains the ledger and evidence needed for the remaining resources.

## Release boundaries

| Resource | Responsible role and release condition |
| --- | --- |
| Implementer worktree | Merger, after the target branch contains the delivery, necessary evidence is preserved, and all users are idle. |
| Test-author worktree | Test owner or merger, after final integration and review repairs finish; coverage blessing alone is too early. |
| PR working copy | Merger/fixer, after all integration and review repairs finish and the delivered branch/commits are preserved. |
| Checkpoint scratch worktree | Checkpoint owner, after recording the union inputs/result and transferring any necessary failure scene outside it. |
| Successful test output | Run owner, after validating the compact record and any required non-regenerable inputs. |
| Failed test output | Run owner, after diagnosis/resolution is recorded and necessary evidence remains accessible. |
| Failed, interrupted, or replaced task environment | Original or replacement owner; reuse and hand off first, retain active commands and unsaved work. |

Each reached boundary creates an obligation and requires a handling receipt in the corresponding delivery report. Read [resource-audit.md](resource-audit.md) when reaching a boundary, receiving a resource alert, or checking stage completion; it defines candidates, owner verification, receipts, and the 30-minute fallback.

Use `preflight` to distinguish machine blockers from checks still requiring the owner; supply its confirmation flags only after actually checking. Its assessment is a snapshot. `release` repeats preflight against current state and only acts on registered resources whose identity still matches. It blocks active or unknown command outcomes, unvalidated evidence, unresolved failures affecting the resource, and unreleased contained resources. A normal worktree also needs a `--merged-into` target containing its current commit, and clean tracked/untracked state. Ignored contents are reviewed by the owner and accounted for separately before release; the helper does not force-remove them. For `checkpoint`/`scratch` worktrees, a completed failed attempt may release the clean checkout after its compact record and externally owned failure scene are verified; the unresolved data stays retained. This exception preserves a reconstruction revision and does not require falsely declaring the failure resolved. Code refs and branches remain available.

`--idle-confirmed` is the responsible owner's confirmation that commands outside the wrapper also no longer use the resource. It does not authorize stopping processes. If inactivity cannot be established, retain the resource and report why. A killed wrapper or missing completion record remains active/unknown for cleanup purposes, even if its PID disappears. Follow the task's existing monitoring/recovery protocol and preserve normally advancing CLI work. Only after independently verifying that the original wrapper, child, and descendant workloads have all stopped, use `recover-run --run ID --stopped-confirmed --reason TEXT` to record an interrupted outcome. This still needs test evidence and a justified `resolve` before cleanup. No age-based or timeout-based deletion is performed.

For execution-contract attempts, a missing terminal registration never bypasses classification and validation. Preserve any durable supervisor terminal, reconcile the existing attempt after verified stopped state, and append further neutral classification evidence as diagnosis advances. Final ledger lock acquisition is bounded by the shutdown budget; a failed registration stays unknown with its resources and claims retained instead of waiting indefinitely for the lock.

On platforms without Python's safe descriptor-relative directory deletion, the helper retains data and reports the capability limitation. Precondition refusals leave the resource intact. An I/O failure during deletion can leave a partially removed directory; the ledger does not mark it released. Inspect the remaining scene and preserve its recovery pointer. Likewise, an interrupted creation or release remains an explicit transitional state to investigate rather than an automatically adoptable directory.

If release is blocked by generated ignored/untracked files, inspect only the owned worktree, preserve any source or diagnostic material, and remove only individually verified disposable outputs under the owner's authorized scope. Then retry the guarded release. Prefer directing future outputs to allocated data directories so this review is unnecessary. Do not use a broad clean or force deletion to bypass a blocked release.

## Space admission and reporting

New invocations enable capacity reservations. Before creating resources or running a command that uses them, use `reserve` with an ID, the owning agent, an existing destination parent, estimated remaining growth (`--next-bytes`), and a machine safety floor (`--reserve-bytes`). Give `create` and `run` the matching `--owner` and `--reservation` IDs; repeat the latter to cover every used resource's filesystem. Each active task has its own reservation. Admission is checked under the ledger lock against actual free space on each destination filesystem, the sum of this invocation's remaining reservations there, and the largest applicable safety floor, counted once. `capacity` reports the same shared budget for planning; it does not reserve space. Historical ledgers explicitly report capacity enforcement disabled rather than silently acquiring a new policy.

A reservation permits one active allocation/command at a time. Completion returns the claim but keeps the remaining growth estimate reserved for later work. At an idle phase boundary, the owner can use `reservation --remaining-bytes` to update that estimate or `reservation --release` when no further growth is expected; changes require `--owner`, `--idle-confirmed`, and a reason, and increases undergo admission again. Active or unknown commands retain their claims. Estimates are not filesystem quotas: keep them conservative, state uncertainty, and reestimate from this invocation's relevant directories or phase results. The helper cannot reserve space against unrelated applications or stop a running command from exceeding its estimate.

When capacity suffices, keep normal concurrency. Under pressure, release eligible resources first, then temporarily start fewer new tasks while existing tests/builds continue. If one task still cannot fit, report the deficit and required capacity. Do not change acceptance coverage or retry the same overflowing allocation indefinitely.

Before the final user report, the existing owners reconcile `status`, handling receipts, and remaining reservations: each resource or reservation is released or retained with a reason and recovery pointer. Default status avoids directory-size traversal; use `status --measure` for a deliberate phase measurement. Sizes are logical bytes rather than guaranteed recoverable disk blocks. Report observed space usage, release outcomes, and remaining resources. Reconcile this same invocation on failure/cancellation/recovery; a hard process kill can prevent automatic finalization, so its durable ledger is the checkpoint. Ledger reconciliation does not expand into scanning old tasks.

## Example: one ticket attempt

The variables below are invocation-specific context pointers, agent IDs, and byte estimates. This example keeps the worktrees and notes on one filesystem; use separate reservations when their destinations differ. Paths must be new where `init` and `create` require them. Configure the watch as described in [resource-audit.md](resource-audit.md) after initialization. Adapt the test command to the project; these shell examples are not a dependency of the Python helper.

```sh
RESOURCE_TOOL="$SKILL_DIR/scripts/resources.py"
STATE_DIR="$NOTES_DIR/resource-state"
python3 "$RESOURCE_TOOL" init --state-dir "$STATE_DIR" --repo "$REPO" --notes-root "$NOTES_DIR"
python3 "$RESOURCE_TOOL" reserve --state "$STATE_DIR" --id pr-budget \
  --path "$WORKTREE_ROOT" --next-bytes "$PR_GROWTH_BYTES" \
  --reserve-bytes "$MACHINE_RESERVE_BYTES" --owner "$PR_OWNER"
python3 "$RESOURCE_TOOL" create --state "$STATE_DIR" --id pr \
  --kind worktree --role merger --path "$WORKTREE_ROOT/pr" \
  --ref "$BASE_REF" --branch "$PR_BRANCH" --owner "$PR_OWNER" --reservation pr-budget
python3 "$RESOURCE_TOOL" reserve --state "$STATE_DIR" --id ticket-42-budget \
  --path "$WORKTREE_ROOT" --next-bytes "$TICKET_GROWTH_BYTES" \
  --reserve-bytes "$MACHINE_RESERVE_BYTES" --owner "$TICKET_OWNER"
python3 "$RESOURCE_TOOL" create --state "$STATE_DIR" --id ticket-42 \
  --kind worktree --role implementer --path "$WORKTREE_ROOT/ticket-42" \
  --ref "$PR_BRANCH" --branch "codex/ticket-42-$RUN_KEY" \
  --owner "$TICKET_OWNER" --reservation ticket-42-budget
python3 "$RESOURCE_TOOL" create --state "$STATE_DIR" --id ticket-42-output \
  --kind data --role implementer --path "$NOTES_DIR/ticket-42-output" \
  --owner "$TICKET_OWNER" --reservation ticket-42-budget
python3 "$RESOURCE_TOOL" run --state "$STATE_DIR" --id ticket-42-attempt-1 \
  --cwd-resource ticket-42 --output-resource ticket-42-output \
  --owner "$TICKET_OWNER" --reservation ticket-42-budget --test -- \
  python3 -m unittest discover
python3 "$RESOURCE_TOOL" record-test --state "$STATE_DIR" \
  --run ticket-42-attempt-1 --summary "$NOTES_DIR/ticket-42-summary.json"
```

The owner configures test temporary/output paths inside `ticket-42-output` using the runner's supported options. The implementer keeps independently authored throwaway tests outside Git commits and remains blind to the formal spec tests.

The example above records the implementer's nonformal throwaway tests. For a checkpoint or final acceptance attempt, first prepare and prove the project execution contract under [test-execution.md](test-execution.md), then use the same resource/reservation flags with:

```sh
python3 "$RESOURCE_TOOL" run --state "$STATE_DIR" --id "$ACCEPTANCE_RUN_ID" \
  --cwd-resource pr --output-resource "$ACCEPTANCE_OUTPUT_ID" \
  --owner "$PR_OWNER" --reservation pr-budget --test --acceptance \
  --execution-contract "$EXECUTION_CONTRACT" --execution-gate "$EXECUTION_GATE" \
  --failure-key "$ACCEPTANCE_FAILURE_KEY" --repair-limit 3 -- \
  "$PROJECT_RUNNER" "$PROJECT_TEST_ARGUMENT"
```

Choose the real project command and arguments, with proof-bound adapter/configuration and output paths. The compact summary's acceptance labels alone cannot establish execution qualification.

This example selects the final fixer's 3-round budget. A checkpoint command explicitly uses its original 1 or 2 limit. Subsequent repaired candidates retain that failure key and use `--validate-after "$PREVIOUS_RUN" --repair-evidence "$REPAIR_EVIDENCE" --repair-round "$NEXT_REPAIR_ROUND"`; an automatic recovery uses the separate `--retry-of` route instead.

After a failure, keep the output directory and hand off the same resources as needed. When diagnosis and repair have resolved the issue:

```sh
python3 "$RESOURCE_TOOL" resolve --state "$STATE_DIR" --run ticket-42-attempt-1 \
  --reason "Recorded diagnosis, repair revision, and verification attempt."
python3 "$RESOURCE_TOOL" release --state "$STATE_DIR" \
  --resource ticket-42-output --idle-confirmed
```

After the merger verifies the delivery and all worktree users finish:

```sh
python3 "$RESOURCE_TOOL" due --state "$STATE_DIR" --resource ticket-42 \
  --event-id ticket-42-integrated --stage ticket-integrated \
  --evidence "$PR_BRANCH@$DELIVERY_SHA" --owner "$MERGER_OWNER"
python3 "$RESOURCE_TOOL" release --state "$STATE_DIR" \
  --resource ticket-42 --merged-into "$PR_BRANCH" --idle-confirmed
python3 "$RESOURCE_TOOL" reservation --state "$STATE_DIR" --id ticket-42-budget \
  --owner "$TICKET_OWNER" --release --idle-confirmed \
  --reason "Ticket delivery is merged; its commands and further growth are finished."
python3 "$RESOURCE_TOOL" status --state "$STATE_DIR"
```

The registered `pr` resource remains available for subsequent merger/fixer commands. After the complete invocation's integration, review, and evidence work finishes, release it with `--resource pr --merged-into "$PR_BRANCH" --idle-confirmed`.

If the helper cannot verify a release prerequisite, preserve the resource, report its precise block reason, and return it to the existing responsible role. Cleanup does not introduce a new agent role or change the selected models.
