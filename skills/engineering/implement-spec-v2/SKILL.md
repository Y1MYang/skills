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

5. Review the architecture doc yourself. On approval, release **both sides at once** (test side and implementer side). If the spec introduces public APIs or data models - high irreversibility - pause and get user sign-off first. While reviewing, designate a **foundational ticket**: topologically early with the most dependents.

6. Dispatch the **test side**. By default a single **test implementer subagent**; split by architectural module only if the architecture doc shows >= 2 modules with clean boundaries and small public faces AND there are more than 6 tickets. Test implementers work in their own worktree(s), on a dedicated **test branch**. They write tests derived **only from the spec and the architecture doc - they never read implementation code**. Shared helpers: the first test implementer produces them, later ones reuse them, never duplicates. Deliverables: the tests on the test branch, and a **ticket -> test file mapping table** saved in the out-of-repo notes directory.

7. Dispatch the **implementer side**: one **implementer subagent** per ticket, each in its own worktree, on its own branch. Implementers MUST read the architecture doc; cross-ticket seams (module boundaries, public APIs, data contracts) are bound by it, while in-ticket implementation details are their own call. Implementers do not commit tests - they may write throwaway tests for themselves, but those never enter the repo. Once an implementer completes, merge its work to the PR branch with a **merger subagent**. If this changes the **frontier** of available tickets, kick off more implementer subagents to work on the new tickets.

8. Once all tests are implemented, run /code-review on the test branch and fix all issues there. Then verify **spec coverage** yourself: every requirement and acceptance criterion in the spec has at least one test per the mapping table. Gaps go back to the test implementers. Only then are the tests **blessed**. The test branch does not merge into the PR branch before step 10.

9. Run the **integration checkpoint**, once: when the foundational ticket is merged AND the tests are blessed, open a **one-off scratch worktree**, union-merge the PR branch and the test branch in it, run the test subset mapped to the foundational ticket, then discard the worktree - no permanent merge. You run the merge and test commands yourself; they are mechanical. Fix contract mismatches per the ownership rules below: implementation-side mismatches are fixed by a fixer subagent directly on the PR branch (that ticket's worktree is already merged and gone); test-side mismatches are fixed by the test implementer on the test branch. Budget 1-2 rounds, then adjudicate yourself. If the tests are not yet blessed, defer the checkpoint until they are; if every ticket merges before that, the checkpoint degenerates into step 10.

10. Once all tickets are complete: merge the test branch into the PR branch with a merger subagent, then run the full test suite for the first time. Apply the ownership rules below with a **single fixer subagent**, up to 3 rounds of run -> fix -> rerun, then escalate to yourself. Once the suite is green, run /code-review on the PR branch and fix all issues raised in a single implementer subagent.

11. Mark the PR as ready for review.

12. Clean up all subagent worktrees, including the test side's.

## Conflict and ownership rules

- **Architecture doc vs ticket**: cross-ticket seams follow the architecture doc; in-ticket details follow the ticket and the implementer. You adjudicate conflicts and record them.
- **Ticket amendments**: only amend tickets that have not been dispatched. Never interrupt an in-flight implementer; record the conflict and let step 10 handle it. Same for tickets already merged.
- **Test failure ownership**: the implementation is wrong by default - fix the code. Change a test only when it contradicts the spec, and record the justification. If the spec itself is ambiguous, adjudicate against the spec; only escalate to the user if you cannot resolve it.

## Discipline

- Context pointers, not duplication.
- Implementers stay **blind to spec tests** while writing code. This is what keeps the tests an independent oracle. Checkpoint fixes happen after their code is written, so the independence of authoring is preserved.
