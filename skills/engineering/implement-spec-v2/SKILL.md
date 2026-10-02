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

**Delegation rules for the test and implement phases (steps 6-10): the main conversation does no file work.** Every file query (reading code, docs, notes, diffs, test output) and every file modification (writing code, tests, merges, fixes, worktrees) is performed by a subagent. The main conversation does exactly two things: **dispatch subagents** (in the background where possible), and, when a subagent **completes, fails, or times out**, query its **status and deliverables** (task output, final report, notes-directory artifacts) to decide what to dispatch next. On failure or timeout, never absorb the subagent's file work into the main conversation - query what it left behind, then re-dispatch with that context.

6. Dispatch the **test side**. By default a single **test implementer subagent**; split by architectural module only if the architecture doc shows >= 2 modules with clean boundaries and small public faces AND there are more than 6 tickets. Test implementers work in their own worktree(s), on a dedicated **test branch**. They write tests derived **only from the spec and the architecture doc - they never read implementation code**. Shared helpers: the first test implementer produces them, later ones reuse them, never duplicates. Deliverables: the tests on the test branch, and a **ticket -> test file mapping table** saved in the out-of-repo notes directory. You only dispatch and then query status/results on completion, failure, or timeout - every file query and modification happens inside the test implementer(s).

7. Dispatch the **implementer side**: one **implementer subagent** per ticket, each in its own worktree, on its own branch. Implementers MUST read the architecture doc; cross-ticket seams (module boundaries, public APIs, data contracts) are bound by it, while in-ticket implementation details are their own call. Implementers do not commit tests - they may write throwaway tests for themselves, but those never enter the repo. Once an implementer completes, merge its work to the PR branch with a **merger subagent**. If this changes the **frontier** of available tickets, kick off more implementer subagents to work on the new tickets. The same delegation rule applies: implementer and merger subagents do all file queries and modifications; you dispatch them and query status/results on completion, failure, or timeout.

8. Once all tests are implemented, run /code-review on the test branch and fix all issues there. Then dispatch a **coverage-audit subagent** to verify **spec coverage**: it checks that every requirement and acceptance criterion in the spec has at least one test per the mapping table, and reports the gaps to you. Gaps go back to the test implementers. Only then are the tests **blessed**. The test branch does not merge into the PR branch before step 10.

9. Run the **integration checkpoint**, once: when the foundational ticket is merged AND the tests are blessed, dispatch a **one-off checkpoint subagent** to open a **scratch worktree**, union-merge the PR branch and the test branch in it, run the test subset mapped to the foundational ticket, then discard the worktree - no permanent merge - and report the results. The commands are mechanical, but they are still file work: the subagent runs them, you adjudicate from its report. Fix contract mismatches per the ownership rules below: implementation-side mismatches are fixed by a fixer subagent directly on the PR branch (that ticket's worktree is already merged and gone); test-side mismatches are fixed by the test implementer on the test branch. Budget 1-2 rounds, then adjudicate yourself. If the tests are not yet blessed, defer the checkpoint until they are; if every ticket merges before that, the checkpoint degenerates into step 10.

10. Once all tickets are complete: merge the test branch into the PR branch with a merger subagent, and have it run the full test suite for the first time and report the results. Apply the ownership rules below with a **single fixer subagent** that runs the suite, fixes, and reruns itself, reporting after each round - up to 3 rounds of run -> fix -> rerun, then escalate to yourself. Once the suite is green, run /code-review on the PR branch and fix all issues raised in a single implementer subagent.

11. Mark the PR as ready for review, then report to the user. If step 5 produced an **irreversibility report**, it leads the report: each highly irreversible public API, data model, or interface the architecture introduced, with its final signature and a one-line rationale, so the user can review the decisions now that they are implemented.

12. Clean up all subagent worktrees, including the test side's.

## Conflict and ownership rules

- **Architecture doc vs ticket**: cross-ticket seams follow the architecture doc; in-ticket details follow the ticket and the implementer. You adjudicate conflicts and record them.
- **Ticket amendments**: only amend tickets that have not been dispatched. Never interrupt an in-flight implementer; record the conflict and let step 10 handle it. Same for tickets already merged.
- **Test failure ownership**: the implementation is wrong by default - fix the code. Change a test only when it contradicts the spec, and record the justification. If the spec itself is ambiguous, adjudicate against the spec; only escalate to the user if you cannot resolve it.

## Discipline

- Context pointers, not duplication.
- In the test and implement phases (steps 6-10), the main conversation never touches files: subagents do every file query and modification; the main conversation dispatches and, on completion/failure/timeout, queries the subagent's status and deliverables - then re-dispatches rather than taking the file work over.
- Implementers stay **blind to spec tests** while writing code. This is what keeps the tests an independent oracle. Checkpoint fixes happen after their code is written, so the independence of authoring is preserved.
