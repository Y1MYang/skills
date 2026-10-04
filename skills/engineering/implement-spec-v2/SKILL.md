---
name: implement-spec-v2
description: "Implement a specification in code, with an architecture phase and an independent test-oracle track."
disable-model-invocation: true
---

You have been provided a spec. This spec should have tickets associated with it, describing how to implement the spec.

The goal is a PR which implements the entire spec on a single branch, plus a test suite derived **independently** from the implementation.

The tickets are not a list of steps. They are a **task graph** with blocking relationships between them. This means there is always a **frontier** of tickets which are ready to be grabbed.

Communication to and from subagents should be sparse. Communicate primarily through **context pointers**: to the spec, tickets, exploration notes, the architecture doc, and previous commits. Don't duplicate information already available via pointers.

**Implementer subagents** should be run in the background where possible for **maximum concurrency**.

## Subagent model selection

At the start of each invocation, before step 1 or any subagent dispatch, collect the user's explicit model selections for the roles below. Ask for any selections not already supplied with this invocation, presenting all six categories together and the current runtime's available model choices when known. Offer both category-wide selections and individual role selections; leave unanswered selections unset.

| Category | Roles |
| --- | --- |
| 1 | Exploration |
| 2 | Architect |
| 3 | Test implementer, Implementer |
| 4 | Coverage audit, Standards reviewer, Spec reviewer |
| 5 | Merger, Checkpoint, Fixer |
| 6 | Expert |

Accept category numbers, role names, or both in one reply. A category selection applies to every role in that category; an individual role selection overrides the category selection for that role. The same model may be selected for multiple categories or roles.

Honor explicit selections supplied for this invocation and ask only for missing or ambiguous selections. Wait for the user's answer until all eleven roles have an explicit model. A partial reply, no reply, or elapsed time leaves the remaining roles unassigned. Never fill them from the main conversation's model, runtime defaults, or a previous invocation. The user may explicitly choose the main conversation's model for any role.

Check that the selected models are supported by the current runtime and that its dispatch tool can select them. If a model is unavailable or explicit selection cannot be honored, explain the limitation and ask for a supported choice or a workflow change; do not silently substitute a model. Once all eleven assignments are resolved, show the role-to-model mapping and proceed without another confirmation.

Retain this mapping for the invocation and save it in the shared notes directory once that directory exists. Every instance, retry, replacement, and nested delegation must use its role's selected model. A user-requested change updates future dispatches for the affected roles.

Pass the selected model explicitly through the dispatch tool's model parameter or supported equivalent; a model name written only in the task prompt does not select the model. When model overrides require a fresh or bounded context instead of a full-history fork, use that mode and provide the task's context pointers, preserving the test side's independent inputs.

For `/code-review` in steps 8 and 10, a **coverage-audit subagent** coordinates the review using the Coverage audit model. Give it the resolved mapping and require it to explicitly select the Standards reviewer and Spec reviewer models when dispatching those reviewers. This includes nested retries and replacements. All review file work is delegated under the existing steps 6-10 rules.

## On-demand Expert help

The **Expert** model is selected at startup, but the role is dispatched **only on a qualified help request**, never as part of the normal workflow. Any working subagent, including nested reviewers, or the main conversation may request help after one evidence-backed investigation leaves a specific technical blocker unresolved with no known executable way to proceed.

Resolve the Expert protocol pointer relative to this SKILL.md into a location accessible to the subagents. Pass that resolved pointer, the Expert model assignment, and this help rule to every subagent, including nested dispatches. A requester reports a **needs-help** event with its blocker and investigation evidence; the main conversation verifies the request from that report and dispatches a fresh Expert. Nested requests reach the main conversation through their coordinating subagent.

Subagents requesting or handling Expert help read [references/expert.md](references/expert.md) for role-specific triggers, the request and handoff protocol, read-only diagnosis, one-shot termination, and escalation to the user, and include the applicable protocol requirements in their reports to the main conversation. Give the dispatched Expert that reference and only the inputs its task is allowed to see. In steps 6-10, the main conversation delegates any needed reference lookup as file work and relies on the resulting report. This protocol applies in every phase, including within a checkpoint or fixer round; consulting an Expert preserves the existing ownership, input boundaries, and round budgets.

## Steps

1. Read the spec and tickets. Read enough to understand the task graph.

2. Dispatch an **exploration subagent** to conduct the exploration required by the tickets - relevant codebase files or external documentation. This step is **mandatory**: the architecture phase depends on it. The exploration subagent must be able to save files - it saves its markdown notes in a directory outside the repo, accessible by all future subagents.

3. Create a branch, and a draft PR. The PR should be marked as 'closing' the spec issue and tickets.

4. Dispatch an **architect subagent**. Its inputs are the spec, the tickets, and the exploration notes; it may do small supplementary exploration, but the notes are the primary source. It produces an **architecture doc** for the new code introduced by the spec, saved in the same out-of-repo notes directory. The doc must satisfy this **content contract** before it can be released:
   - module boundaries and responsibilities
   - concrete public API signatures and types
   - core data structures
   - error semantics
   - observability seams: where tests enter the system, where mocks/fixtures are injected
   - integration seams: which existing modules the spec touches, which existing public surfaces the new code hangs on, compatibility/migration constraints

5. Review the architecture doc yourself. On approval, release **both sides at once** (test side and implementer side). If the design introduces highly irreversible surfaces - public APIs, data models, or other cross-service interfaces - do not pause for sign-off; instead record them in an **irreversibility report** in the notes directory, to be surfaced to the user in the final PR report (step 11). While reviewing, designate a **foundational ticket**: topologically early with the most dependents.

**Delegation rules for the test and implement phases (steps 6-10): the main conversation does no file work.** Every file query (reading code, docs, notes, diffs, test output) and every file modification (writing code, tests, merges, fixes, worktrees) is performed by a subagent. The main conversation does exactly two things: **dispatch subagents** (in the background where possible), and, when a subagent **completes, fails, times out, or requests Expert help**, query its **status and deliverables** (task output, final report, notes-directory artifacts) to decide what to dispatch next. On failure or timeout, never absorb the subagent's file work into the main conversation - query what it left behind, then re-dispatch with that context.

6. Dispatch the **test side**. By default a single **test implementer subagent**; split by architectural module only if the architecture doc shows >= 2 modules with clean boundaries and small public faces AND there are more than 6 tickets. Test implementers work in their own worktree(s), on a dedicated **test branch**. They write tests derived **only from the spec and the architecture doc - they never read implementation code**. Shared helpers: the first test implementer produces them, later ones reuse them, never duplicates. Deliverables: the tests on the test branch, and a **ticket -> test file mapping table** saved in the out-of-repo notes directory. You only dispatch and then query status/results on completion, failure, timeout, or an Expert help request - every file query and modification happens inside subagents under their role's ownership and permissions.

7. Dispatch the **implementer side**: one **implementer subagent** per ticket, each in its own worktree, on its own branch. Implementers MUST read the architecture doc; cross-ticket seams (module boundaries, public APIs, data contracts) are bound by it, while in-ticket implementation details are their own call. Implementers do not commit tests - they may write throwaway tests for themselves, but those never enter the repo. Once an implementer completes, merge its work to the PR branch with a **merger subagent**. If this changes the **frontier** of available tickets, kick off more implementer subagents to work on the new tickets. The same delegation rule applies: subagents do all file queries and modifications under their role's ownership and permissions; you dispatch them and query status/results on completion, failure, timeout, or an Expert help request.

8. Once all tests are implemented, dispatch a **coverage-audit subagent** to run /code-review on the test branch with the selected reviewer models, and send its findings to the test implementer(s) to fix all issues there. Then dispatch a **coverage-audit subagent** to verify **spec coverage**: it checks that every requirement and acceptance criterion in the spec has at least one test per the mapping table, and reports the gaps to you. Gaps go back to the test implementers. Only then are the tests **blessed**. The test branch does not merge into the PR branch before step 10.

9. Run the **integration checkpoint**, once: when the foundational ticket is merged AND the tests are blessed, dispatch a **one-off checkpoint subagent** to open a **scratch worktree**, union-merge the PR branch and the test branch in it, run the test subset mapped to the foundational ticket, then discard the worktree - no permanent merge - and report the results. The commands are mechanical, but they are still file work: the subagent runs them, you adjudicate from its report. Fix contract mismatches per the ownership rules below: implementation-side mismatches are fixed by a fixer subagent directly on the PR branch (that ticket's worktree is already merged and gone); test-side mismatches are fixed by the test implementer on the test branch. Budget 1-2 rounds, then adjudicate yourself. If the tests are not yet blessed, defer the checkpoint until they are; if every ticket merges before that, the checkpoint degenerates into step 10.

10. Once all tickets are complete: merge the test branch into the PR branch with a merger subagent, and have it run the full test suite for the first time and report the results. Apply the ownership rules below with a **single fixer subagent** that runs the suite, fixes, and reruns itself, reporting after each round - up to 3 rounds of run -> fix -> rerun, then escalate to yourself. Once the suite is green, dispatch a **coverage-audit subagent** to run /code-review on the PR branch with the selected reviewer models, and fix all issues raised in a single implementer subagent.

11. Mark the PR as ready for review, then report to the user. If step 5 produced an **irreversibility report**, it leads the report: each highly irreversible public API, data model, or interface the architecture introduced, with its final signature and a one-line rationale, so the user can review the decisions now that they are implemented.

12. Clean up all subagent worktrees, including the test side's.

## Conflict and ownership rules

- **Architecture doc vs ticket**: cross-ticket seams follow the architecture doc; in-ticket details follow the ticket and the implementer. You adjudicate conflicts and record them.
- **Ticket amendments**: only amend tickets that have not been dispatched. Never interrupt an in-flight implementer; record the conflict and let step 10 handle it. Same for tickets already merged.
- **Test failure ownership**: the implementation is wrong by default - fix the code. Change a test only when it contradicts the spec, and record the justification. If the spec itself is ambiguous, adjudicate against the spec; only escalate to the user if you cannot resolve it.

## Discipline

- Context pointers, not duplication.
- In the test and implement phases (steps 6-10), the main conversation never touches files: subagents do every file query and modification; the main conversation dispatches and, on completion/failure/timeout/Expert help request, queries the subagent's status and deliverables - then re-dispatches rather than taking the file work over.
- Implementers stay **blind to spec tests** while writing code. This is what keeps the tests an independent oracle. Checkpoint fixes happen after their code is written, so the independence of authoring is preserved.
