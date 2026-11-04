---
name: codex-takeover
description: Monitor a Codex Desktop thread from a zcode session and take over its task when the thread stalls on exhausted usage limits, errors, or inactivity. Use when the user gives a codex://threads/<uuid> deep link and wants the work continued unattended.
---

# Codex Takeover

Watch a Codex Desktop thread from this zcode session. When the thread stops making progress — usage limit exhausted, an error, or inactivity — reconstruct its context from the on-disk transcript and drive the task to completion with zcode's own model and quota. This session owns the task from takeover to the task's natural end (commit, PR, or a written stopping report).

## Contract

- The user starts this skill in a running zcode session (manually, or via a scheduled automation that launches such a session). Recommend full-automatic permission mode: nobody is present to approve steps.
- From takeover onward this session exclusively owns the task. If the Codex thread shows new activity (the user resumed it), ignore it and keep working; the user's contract is to check this zcode session first when they return.
- Work toward the task's natural end. If zcode's own capacity runs out first, finish with the stopping report so the task is resumable.
- The stalled Codex thread never resumes by itself: its turn ended with an error payload, so there is no risk of two agents editing the same repository.

## Stage 0 — Locate and parse the thread

Input: a `codex://threads/<uuid>` deep link. Extract the UUID.

Resolve it to a rollout file under `C:\Users\admin\.codex\sessions\YYYY\MM\DD\rollout-<UTC-timestamp>-<id>.jsonl`:

1. Glob recent day directories (start with today, walk back up to 14 days) for files whose trailing `<id>` equals the UUID.
2. If none matches, grep the first line (`session_meta`) of recent rollouts for `"session_id":"<uuid>"` — the filename id is the thread id and can differ from the session id (subagent forks). `C:\Users\admin\.codex\session_index.jsonl` maps ids to thread names and timestamps as a cross-check.

Extract from the file: `cwd` (the working directory for all takeover work), the original user prompt (first `response_item` with `role:"user"`), and the tail (last few hundred lines): recent assistant messages, tool calls, and the last `turn_context`. Rollouts can exceed 10k lines — never read the whole file.

Completion criterion: you can state the task, the working directory, and what Codex did last, each in one sentence.

## Stage 1 — Monitor

Baseline the file's current line count, then poll for new appended lines every 30 seconds as a background task. Fire on either trigger:

- **Error trigger**: a new `event_msg` → `task_complete` record with an `error.codex_error_info` field (`usage_limit_exceeded`, `server_overloaded`, others). Take over immediately.
- **Stall trigger**: no new lines for 20 minutes (configurable). Before firing, re-check: if the last line is a tool call with no matching output record, the command is still running — treat as busy and keep waiting.

Completion criterion: a trigger fired, with the triggering record quoted as evidence.

## Stage 2 — Take over

1. Write the takeover doc to `<cwd>\TAKEOVER.md`: the task as understood, current repository state (`git status`, whether tests/build run), and the continuation plan.
2. Continue from the repository exactly as Codex left it — keep its uncommitted changes and unfinished edits — and drive the task to completion using this session's model and permissions. Report the takeover in this session's reply before starting the work.
3. On completion, write the stopping report to `<cwd>\TAKEOVER-REPORT.md`: what was done, what was not, how to verify, and how to resume if anything remains. Then report completion in this session.

## Edge cases

- **Multiple rollout files for one thread**: pick the most recently modified.
- **Thread spans midnight**: the file lives in the day directory where the thread started; later lines keep appending to it.
- **File does not exist / UUID unresolvable**: ask the user for the thread name or a fresh deep link — do not guess.
- **Auto-launch**: to start the monitoring session at a scheduled time, pair this skill with a zcode scheduled automation whose prompt opens a zcode session in (or pointing at) the thread's `cwd` and invokes this skill with the deep link.
