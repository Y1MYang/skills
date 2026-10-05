---
name: cleanup-spec-v2
description: "After an implement-spec-v2 PR is merged, inventory its local resources and remote branch, then remove the approved items."
disable-model-invocation: true
---

Use only when the user explicitly invokes `cleanup-spec-v2 <PR number>` in the corresponding project's Git checkout. A new conversation needs no previous development conversation: the producer's handoff index supplies the resource ownership evidence.

## 1. Inventory

Resolve this skill's `scripts/cleanup.py` and the installed `implement-spec-v2/scripts/resources.py` from their skill locations. Normally both skills are siblings. Use Python 3, Git, and an authenticated GitHub CLI; a missing helper or capability is a reported limitation, not permission to substitute broad deletion commands. Consult the helpers' `--help` for optional parameters.

```sh
python3 "$CLEANUP_SKILL/scripts/cleanup.py" plan "$PR_NUMBER" \
  --repo "$PROJECT" --resource-tool "$RESOURCE_TOOL"
```

The plan resolves the PR number against the current repository's Git common directory and its unique handoff. Verify the returned GitHub host, base repository, full PR link, merged state, and head repository. Remote deletion targets the recorded head repository, including fork PRs; preserve the user's GitHub CLI defaults. A missing or ambiguous handoff, or a historical PR without the new protocol, receives an audit report only.

Check activity beyond ledger-wrapped commands: the development owners' completion records, open terminals, tests/builds/services, and local process use of each directory. Linux `/proc` observations are supporting evidence; a missing PID alone does not prove inactivity. Keep active or uncertain resources and report the command/process and reason. This skill leaves running workloads intact.

Regenerate the plan with one `--idle-resource <id>` for each resource whose inactivity you can establish, and `--notes-idle` only after establishing inactivity of the notes/state root. These assertions concern observed inactivity; they do not authorize stopping processes.

Show the **complete final inventory** in the conversation: every resource, local branch, recovery ref, remote branch, notes/evidence/ledger/index, and cleanup journal; each item's exact path or ref, ownership evidence, expected identity or SHA, proposed action, and block reason. Include already absent items, all retained items, `plan_path`, and `plan_sha256`. Describe the final deletion of development records and reproduction evidence. This step is complete only when the user can review every proposed deletion and everything that will remain.

## 2. Confirm and apply

Request explicit human confirmation of the displayed inventory and its digest. Invocation authorizes inventory; approval of this exact plan authorizes deletion. Wait for that confirmation before supplying `--approved-digest`.

```sh
python3 "$CLEANUP_SKILL/scripts/cleanup.py" apply \
  --plan "$PLAN_PATH" --approved-digest "$APPROVED_SHA256" \
  --resource-tool "$RESOURCE_TOOL"
```

Apply rechecks the approved identities and SHAs. Changed branches, new commits, dirty worktrees, uncertain ownership, unverified merge evidence, and active resources remain blocked while independently verified items may be removed. Keep the returned reasons; resolve a blocker through its owning workflow, then create a fresh complete plan and obtain fresh confirmation. A failed or interrupted apply also requires a new plan and confirmation before another mutation. Use the guarded helper rather than bypassing a refused check.

## 3. Finish

Report deleted, already absent, and retained items with reasons in the conversation. Partial completion retains the handoff, ledger, and journal needed to continue. Full completion removes every invocation-owned resource and record, including local temporary recovery refs, development notes and test evidence, handoff/index entry, and cleanup's own temporary journal. The shared index container may remain for other invocations; their entries and resources remain owned by those invocations.

Completion requires a merged PR, every approved deletion verified, and no remaining invocation-owned objects. Leave the result in the conversation; create no permanent cleanup report or replacement archive.
