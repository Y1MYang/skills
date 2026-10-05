# Resource lifecycle protocol

Read this protocol when creating resources, running tests, handing a task to a replacement, or releasing resources. Use the helper bundled at `../scripts/resources.py`; its `--help` is the parameter reference. Git and Python 3 standard libraries are the only helper dependencies. Select the available Python 3 executable on the destination machine and resolve the helper from the skill location.

## Invocation scope and ownership

The exploration agent uses `init --notes-root` before writing notes. The notes root must be new or empty, outside the repository and Git metadata, and contain the ledger as a strict child directory. The helper records its directory identity and `.implement-spec-notes` marker. Pass the notes, state and helper paths as context pointers. The state contains resource metadata and compact run records, not source-tree archives. Keep each author's access to evidence within the existing test/implementation input boundaries; resource bookkeeping grants no additional access to code, tests, or another role's records.

Use `create` to acquire an empty data directory or a Git worktree at a previously nonexistent path; its parent directory must already exist. The helper creates and registers it in one workflow. Existing directories cannot be adopted; this protocol does not scan or clean historical tasks. Record the role and owner, revision, parent resource if physically contained, command usage, and eventual disposition. Keep the state outside every resource it manages. Generated results go outside the source repository; required fixtures remain governed by the project.

Use allocated data directories for test temporary files, logs, generated reports, disposable databases, and necessary diagnostic inputs. Configure the project's runner to place these files there. A directory's name or `.gitignore` entry is not evidence that its contents are disposable. Dependencies and build outputs created inside a worktree must be accounted for before release. Prefer the project's supported external package cache; keep mutable environments and role-specific outputs isolated.

Step 3 creates the PR branch in a new registered PR working copy. Mergers and fixers use that resource as their `--cwd-resource`; an existing primary checkout cannot be adopted. Keep the PR working copy through integration and review repairs, then release it against the delivered PR branch while retaining that branch and its commits.

Prefer a revision pointer and necessary uncommitted diff to another complete source copy. If an experiment genuinely needs a separate checkout, create another registered worktree with its own purpose and release condition. A failure or agent replacement inherits the existing resource IDs, evidence pointers, and round budget.

## Running commands and keeping evidence

Run commands using registered resources through `run`, listing every resource they use. The helper records activity before starting, releases its short ledger lock while the command runs, and records completion afterward. It streams stdout and stderr into compressed files in the allocated output directory, avoiding a second full-sized log copy. Configure additional test outputs into that directory too; the helper cannot discover every file a project-specific runner creates.

For a test attempt, pass `--test`, then use `record-test` with a compact JSON summary. The helper retains the command, working directory, source revision, timestamps, exit code, and Git/Python/OS information. The owner supplies the project's runtime and dependency versions or lockfile fingerprints, random seeds, relevant input revisions, failure explanation, and reproducible command in the summary. Keep these records small; reference large inputs by immutable revision and fingerprint, retaining necessary non-regenerable inputs in an owned data directory.

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

After a passing attempt's record is validated, release its regenerable raw outputs. Compact updates create small immutable record generations; the ledger references a completed generation and its checksum, so interruption during an update does not overwrite the previous evidence. For a failure, preserve the necessary diagnostic scene until the issue is explained and resolved. `resolve` requires the justification and changes the retention state; it does not delete files. A later passing run alone is insufficient justification for deleting an unexplained intermittent failure. Final acceptance follows the same compact-record policy; retain no separate final acceptance archive.

Store failure evidence outside scratch worktrees before releasing them. Preserve source revisions or saved changes needed to reconstruct the experiment; a path into a deleted checkout is not a durable context pointer. Do not copy an entire environment into an archive merely to delete the original.

## PR handoff for later cleanup

New invocations use the owned notes-root protocol. Historical ledgers created without it retain their existing development/release behavior but cannot publish a cleanup handoff; `cleanup-spec-v2` audits those tasks only.

Before creating the draft PR, use `publish-branch --resource PR_ID --remote-url URL` for the PR branch's first remote publication. Use the intended head repository's native REST `clone_url` exactly. The helper first verifies the remote ref is absent, persists `creating`, pushes with an empty expected-ref lease, and requires Git's porcelain result to confirm a new ref was created. An existing same-OID ref or a concurrent no-op is not creation evidence. Only a verified first publication becomes `created`; an interruption or uncertain push remains retained and cannot be automatically retried or adopted. Subsequent development pushes target this same destination and branch. If another invocation-created branch is published remotely, register its first publication with this helper too.

After creating the draft PR, fetch its fresh native REST response and pass the saved JSON to `bind-pr --pr-resource PR_ID --pr-json FILE`. It binds the PR's host, ID, number, base/head repository identities, refs and SHA to the invocation-created, first-published branch. This input establishes a delivery pointer, not cleanup permission or proof that the PR is merged. The helper writes one discovery index JSON per invocation, grouped by the SHA-256 of the common Git directory, under `${XDG_STATE_HOME:-~/.local/state}/implement-spec-v2`; use `--index-root` at initialization for another location outside notes/repository/Git metadata.

Save native REST JSON in the notes root outside the ledger, for example `$NOTES_DIR/pr.json`, so the sealed notes snapshot records it; the ledger subtree contains only `lock`, `state.json`, `handoff.json` and `records`.

After final pushes, integration/review repairs, resource reconciliation and final note writing, fetch another fresh native REST PR response and use `seal --pr-json FILE`. It verifies the final PR head against the local branch and the live owned remote ref, records expected local/remote OIDs, active worktree HEADs and existing or anticipated release-anchor refs, and writes `state/handoff.json` plus its identity/checksum into the index. The notes snapshot hashes ordinary files outside the ledger and still-registered resource subtrees; symlinks, mounts and special files become explicit blockers. Later unexplained additions or changes must not be swept into cleanup.

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

`release` only acts on registered resources whose identity still matches. It blocks active or unknown command outcomes, unvalidated evidence, unresolved failures affecting the resource, and unreleased contained resources. A normal worktree also needs a `--merged-into` target containing its current commit, and clean tracked/untracked state. Ignored contents are reviewed by the owner and accounted for separately before release; the helper does not force-remove them. For `checkpoint`/`scratch` worktrees, a completed failed attempt may release the clean checkout after its compact record and externally owned failure scene are verified; the unresolved data stays retained. This exception preserves a reconstruction revision and does not require falsely declaring the failure resolved. Code refs and branches remain available.

`--idle-confirmed` is the responsible owner's confirmation that commands outside the wrapper also no longer use the resource. It does not authorize stopping processes. If inactivity cannot be established, retain the resource and report why. A killed wrapper or missing completion record remains active/unknown for cleanup purposes, even if its PID disappears. Follow the task's existing monitoring/recovery protocol and preserve normally advancing CLI work. Only after independently verifying that the original wrapper, child, and descendant workloads have all stopped, use `recover-run --run ID --stopped-confirmed --reason TEXT` to record an interrupted outcome. This still needs test evidence and a justified `resolve` before cleanup. No age-based or timeout-based deletion is performed.

On platforms without Python's safe descriptor-relative directory deletion, the helper retains data and reports the capability limitation. Precondition refusals leave the resource intact. An I/O failure during deletion can leave a partially removed directory; the ledger does not mark it released. Inspect the remaining scene and preserve its recovery pointer. Likewise, an interrupted creation or release remains an explicit transitional state to investigate rather than an automatically adoptable directory.

If release is blocked by generated ignored/untracked files, inspect only the owned worktree, preserve any source or diagnostic material, and remove only individually verified disposable outputs under the owner's authorized scope. Then retry the guarded release. Prefer directing future outputs to allocated data directories so this review is unnecessary. Do not use a broad clean or force deletion to bypass a blocked release.

## Space admission and reporting

Use `capacity` before allocating work that can materially grow disk usage. Supply the next task's measured or conservatively estimated additional bytes and a configurable reserve covering machine needs and remaining growth of active tasks. Pass `--path` with an existing destination parent to check the filesystem receiving those resources; the default checks the state directory's filesystem. Account separately for output locations on other filesystems. Samples come from this invocation's relevant resource directories and phase reports, without repeated full-disk scans. With no reliable sample, state the estimate and uncertainty rather than treating it as a guaranteed peak bound.

When capacity suffices, keep normal concurrency. Under pressure, release eligible resources first, then temporarily start fewer new tasks while existing tests/builds continue. If one task still cannot fit, report the deficit and required capacity. Do not change acceptance coverage or retry the same overflowing allocation indefinitely.

Before the final user report, the existing owners reconcile `status`: each resource is released or retained with a reason and recovery pointer. Default status avoids directory-size traversal; use `status --measure` for a deliberate phase measurement. Sizes are logical bytes rather than guaranteed recoverable disk blocks. Report observed space usage, release outcomes, and remaining resources. Reconcile this same invocation on failure/cancellation/recovery; a hard process kill can prevent automatic finalization, so its durable ledger is the checkpoint. Ledger reconciliation does not expand into scanning old tasks.

## Example: one ticket attempt

The variables below are invocation-specific context pointers. Paths must be new where `init` and `create` require them. Adapt the test command to the project; these shell examples are not a dependency of the Python helper.

```sh
RESOURCE_TOOL="$SKILL_DIR/scripts/resources.py"
STATE_DIR="$NOTES_DIR/resource-state"
python3 "$RESOURCE_TOOL" init --state-dir "$STATE_DIR" --repo "$REPO" --notes-root "$NOTES_DIR"
python3 "$RESOURCE_TOOL" create --state "$STATE_DIR" --id pr \
  --kind worktree --role merger --path "$WORKTREE_ROOT/pr" \
  --ref "$BASE_REF" --branch "$PR_BRANCH"
python3 "$RESOURCE_TOOL" create --state "$STATE_DIR" --id ticket-42 \
  --kind worktree --role implementer --path "$WORKTREE_ROOT/ticket-42" \
  --ref "$PR_BRANCH" --branch "codex/ticket-42-$RUN_KEY"
python3 "$RESOURCE_TOOL" create --state "$STATE_DIR" --id ticket-42-output \
  --kind data --role implementer --path "$NOTES_DIR/ticket-42-output"
python3 "$RESOURCE_TOOL" run --state "$STATE_DIR" --id ticket-42-attempt-1 \
  --cwd-resource ticket-42 --output-resource ticket-42-output --test -- \
  python3 -m unittest discover
python3 "$RESOURCE_TOOL" record-test --state "$STATE_DIR" \
  --run ticket-42-attempt-1 --summary "$NOTES_DIR/ticket-42-summary.json"
```

The owner configures test temporary/output paths inside `ticket-42-output` using the runner's supported options. The implementer keeps independently authored throwaway tests outside Git commits and remains blind to the formal spec tests.

After a failure, keep the output directory and hand off the same resources as needed. When diagnosis and repair have resolved the issue:

```sh
python3 "$RESOURCE_TOOL" resolve --state "$STATE_DIR" --run ticket-42-attempt-1 \
  --reason "Recorded diagnosis, repair revision, and verification attempt."
python3 "$RESOURCE_TOOL" release --state "$STATE_DIR" \
  --resource ticket-42-output --idle-confirmed
```

After the merger verifies the delivery and all worktree users finish:

```sh
python3 "$RESOURCE_TOOL" release --state "$STATE_DIR" \
  --resource ticket-42 --merged-into "$PR_BRANCH" --idle-confirmed
python3 "$RESOURCE_TOOL" status --state "$STATE_DIR"
```

The registered `pr` resource remains available for subsequent merger/fixer commands. After the complete invocation's integration, review, and evidence work finishes, release it with `--resource pr --merged-into "$PR_BRANCH" --idle-confirmed`.

If the helper cannot verify a release prerequisite, preserve the resource, report its precise block reason, and return it to the existing responsible role. Cleanup does not introduce a new agent role or change the selected models.
