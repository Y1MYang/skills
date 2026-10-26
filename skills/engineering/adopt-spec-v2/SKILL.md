---
name: adopt-spec-v2
description: "Take over an in-progress spec with minimal rework and carry it to a review-ready PR under implement-spec-v2 rules."
disable-model-invocation: true
---

Take over a spec already under construction, whether or not it started with implement-spec-v2. Preserve usable work, establish evidence for the whole spec, and coordinate the remaining work through a review-ready PR. This skill runs only when the user explicitly invokes it.

## Rule source and delegation

Resolve [implement-spec-v2](../implement-spec-v2/SKILL.md) from the sibling skill directory, or locate the installed skill by name. Keep the resolved entry as `V2_SKILL`. Read it as the **rule source**, not as a second invocation starting at its step 1. Keep that skill unchanged. Resolve its `references/resources.md`, `scripts/resources.py`, and `references/expert.md` against its actual directory; pass these accessible pointers as `V2_RESOURCE_PROTOCOL`, `V2_RESOURCE_HELPER`, and `V2_EXPERT_PROTOCOL` to the responsible agents. Resolve v2's test-review dependency and acceptance-contract reference before exploration as well. Record their revisions or fingerprints; if they change during adoption, delegate an impact check and adjudicate affected gates before using the changed rules.

This skill owns the continuation schedule below. Its conditional exceptions are defined in [the takeover protocol](references/takeover.md); inherit all other v2 model-selection, role, architecture, ownership, review, Expert, and resource rules. If the dependency is unavailable or its rules cannot be reconciled with this protocol, report the concrete limitation and obtain a supported workflow choice instead of silently substituting a weaker process.

Delegate project evidence lookup to **Exploration**, contract reconciliation to **Architect**, and execution to the existing v2 roles. Prefer background delegation and context pointers while capacity permits. During the test and implementation phases, including their reviews, merges, checkpoints, fixes, and resource work, the main conversation performs **no file queries or modifications**: dispatch agents and adjudicate their status and deliverable reports at completion, failure, timeout, or a qualified Expert request. Re-dispatch failed work with its checkpoint rather than taking it over.

## Continuation schedule

### 1. Select all eleven models anew

Before project evidence lookup or any agent dispatch, follow v2's **Subagent model selection** section: present all six categories, obtain an explicit selection for all eleven roles, verify runtime support, and show the resolved mapping. Choices explicitly supplied for this adoption count; choices from earlier work do not. This applies even when recovering the same construction invocation.

Save the mapping when the notes directory becomes available. Pass models explicitly through the dispatch tool for every role, including nested reviewers, retries, and replacements. The new mapping governs future dispatches; already-running agents keep their original assignments until their delivery boundary. Expert selection does not cause an Expert dispatch: retain v2's qualified, fresh, read-only help protocol.

**Exit:** all eleven assignments are explicit and executable. Partial answers, elapsed time, and runtime defaults do not fill gaps.

### 2. Establish the adoption baseline

Read [the takeover protocol](references/takeover.md) before dispatching Exploration. Have Exploration inspect the authoritative spec and its tickets, repository rules, actual revisions and dirty work, PR state, prior notes and test provenance, resource owners, running commands, and repair history. It first determines the usable notes/ledger scope under that protocol, initializing a fresh owned notes root before writing findings when required by v2. It saves evidence and exploration notes outside the source repository and reconstructs missing tickets from the spec where needed. It must distinguish facts, unknowns, and current implementation observations.

Stop new old-flow dispatches only within this task's authorized coordination scope. Preserve already-running work, normal tests/builds, original deadlines, and consumed repair budgets. Receive in-flight deliveries at a verifiable boundary; refresh the baseline and remaining graph afterward. Stale prerequisite evidence blocks new dependent dispatches while active work may continue. A proven public-contract change pauses only affected work at a safe saved boundary; use v2's contract-change rules to reconcile its remaining delta.

Classify **same-invocation recovery** versus **new takeover** from evidence, not from a claim that v2 was once invoked. Reuse an original ledger only when its identity, resources, ownership, and continuation state are verifiable and it permits the needed continuation operations. Otherwise Exploration initializes a fresh v2 ledger and records historical resources as external pointers, never adopts or cleans them. Preserve sealed historical notes and handoffs as external evidence instead of reopening them.

If the PR is merged or closed, deliver its state and verified gaps and ask the user to define the next goal before reopening it or starting follow-up work. Missing authoritative requirements or irreconcilable requirement ambiguity need a specific user decision; missing tickets or notes alone do not.

**Exit:** a revision-bound adoption record, requirement/implementation/independent-test/remaining-work map, historical checkpoint identities and budgets, mode decision, and safe handoff plan. Unknown delivery state is not permission to reimplement it.

### 3. Prepare the integration target

Dispatch **Merger** using the protocol's PR and workspace handoff rules. In a verified recovery, retain the original registered integration resource. In a new takeover, use the v2 helper to create a registered working branch/worktree from the verified delivered revision. Reuse the existing PR; create a draft PR under v2's issue-linking rules only if the active construction has none.

Use the registered integration branch for ticket merges, checkpoint inputs, and fixer commands. Keep the original PR branch as the delivery target when it is checked out elsewhere. Merger owns synchronization at a safe boundary, checking the expected PR head and preserving original checkout ownership and uncommitted work. Refresh and adjudicate unexpected movement before integration. Pass the registered resource ID/path and both branch identities to every merger, checkpoint, and fixer. Apply the protocol's conditional publication/binding rules: updating an existing PR does not confer first-publication or cleanup ownership of its branch.

**Exit:** one PR target and an owned, registered integration resource; existing deliveries are accounted for without moving a branch underneath an active checkout.

### 4. Reconcile the architecture and remaining graph

Dispatch **Architect** with the spec, tickets, and Exploration notes. Reuse or supplement the architecture document until it satisfies v2's content contract and the actual integration seams. Requirements and compatibility constraints govern expected behavior; observed implementation behavior is separately labeled. Keep compliant existing design and code. Rework addresses a spec violation, real defect, applicable repository standard, necessary integration seam, or missing observation point—not missing historical ceremony.

Review the contract and adjudicate conflicts under v2 ownership rules. Record highly irreversible surfaces introduced by the spec for the final report, without adding a user sign-off gate. Group the remaining deltas into independently verifiable **work units**, retaining complete ticket/requirement traceability and already-delivered dependencies. Implementation-complete tickets may still have verification work without being reopened for implementation.

Approve v2's finite acceptance plan in this existing architecture gate: test-contract batches, critical-contract checkpoint scopes and stable keys, the designated final key, augmented dependencies, concurrency, and execution budgets. Check the augmented graph for cycles. Reconcile historical checkpoint evidence and consumed allowances under the takeover protocol before registering the plan; changing the schedule preserves actual history. Release only work whose implementation and critical-contract prerequisites are satisfied, while unrelated work stays parallel.

**Exit:** an approved, source-grounded contract and registered finite plan for the remaining work. Release missing test work and ready implementation work together; a side with nothing to author proceeds to its verification gates.

### 5. Author only the missing work

Follow v2 steps **6–7** for test-contract batches, dedicated test branches/worktrees, helpers, one implementer per ready work unit, and merger delivery/release. Give each agent only its permitted context pointers.

Use the takeover protocol's **test provenance and input boundary** rules. The independent oracle covers the **entire spec**, including already-implemented behavior. Reuse demonstrably independent, applicable tests; retain other tests as regression assets and independently derive tests for acceptance criteria still lacking an oracle. New test authors use fresh contexts and never read implementation or unverified behavioral tests. Preserve independent authoring for future implementation by keeping implementers blind to the formal spec tests; record prior exposure without claiming it can be undone.

Retain historical tests already merged into the PR. Keep newly authored or changed oracle tests isolated on the test branch until final integration. Historical authoring order and first-run/first-merge claims are not recreated.

Stages 5 and 6 **overlap**: review each delivered test-contract batch for local qualification; execute each planned critical-contract checkpoint when its fixed implementation inputs and qualified batch are ready. Advance the work-unit frontier after merger deliveries and passing current checkpoints. All implementation deltas being delivered is a gate for final integration, not for batch review or eligible checkpoints.

**Delivery gates:** each work unit has an individually verified delivery mapped to its tickets and requirements; the oracle has a complete requirement-to-test map ready for reconciliation. If no oracle changes are needed, review the existing fixed revisions and mapping without inventing an authoring task. No remaining implementation work does not mean the adoption is complete.

### 6. Bless coverage, checkpoint, integrate, and review

Follow v2 steps **8–10** and their selected reviewer models. Fresh, implementation-blind Coverage audit invokes `/test-review` with `batch` scope on fixed oracle and contract inputs, including admitted reused tests. Local qualification covers only that batch; final `full` reconciliation verifies every requirement and acceptance criterion before whole-spec blessing. Reuse qualified, unaffected evidence with matching inputs, including historical reviews, and review changed dependencies through `delta`. Passing legacy tests or a collection of batch passes alone cannot satisfy whole-spec reconciliation. Preserve v2's failure-scoped review after test failures.

Apply the protocol's **checkpoint history and repair budgets** rules to historical checkpoints and the registered plan. Each critical-contract checkpoint uses an immutable scratch union of fixed implementation, test, and contract inputs; formal test branches remain separate until final integration. Only a current passing checkpoint releases its dependent work. Reuse applicable historical evidence without replaying its chronology; fully delivered implementation may proceed to final integration when no remaining dependent work requires an intermediate checkpoint. Changed inputs require the plan's honest continuation path after a pass, or the existing repair/recovery path for an unresolved failure. Models, replacements, batch changes, and renamed invocations preserve stable checkpoint keys and budgets; unknown history requires adjudication, not an invented zero count.

Once all implementation deltas are delivered and whole-spec coverage is blessed, Merger integrates any pending oracle changes and freezes a clean committed candidate. If all admitted oracle tests are already integrated and unchanged, skip the empty branch/merge operation. Start complete formal acceptance and read-only whole-PR code review concurrently against that same SHA. Review the **prepared integration head against the recorded original PR base**, including pre-adoption changes; a review of the old remote PR head cannot validate pending delivery. Collect both results before coordinated repairs under v2 ownership and bounded fixer rounds. Each repaired candidate needs applicable review evidence and a complete qualified acceptance run; retain compact evidence and inherited failure history.

Merger synchronizes the original PR only at the verified handoff boundary. Confirm that the full-suite revision, accepted review head, and final PR head are the same delivery revision; if new changes arrive, account for them and revalidate before declaring readiness.

**Exit:** blessed whole-spec coverage, a passing full suite for the delivered revision, and resolved whole-PR review findings—not merely a clean adoption-only delta.

### 7. Reconcile resources and report

Have responsible agents apply v2 steps **11–12** to the owned ledger: preserve delivered commits, release eligible resources at their existing boundaries, and retain blocked resources with explicit reasons and recovery pointers. Historical resources outside the resumed ledger remain with their owners. Apply the takeover protocol's **PR publication and cleanup handoff** rules when v2 provides binding/sealing: preserve a qualified original binding or seal a newly created PR, but report an unsealed adoption record for an externally owned existing PR rather than forging ownership or claiming automatic cleanup eligibility. Follow the task's existing monitoring and recovery protocol; handoffs preserve active command identifiers, evidence, deadlines, and budgets.

Mark the verified PR ready for review and report its URL and delivery revision, whole-spec validation and review evidence, preserved work, adoption exceptions, and release/retention outcomes. The irreversibility report leads when applicable. On failure or interruption, deliver a checkpoint with the goal, file scope, completed evidence, remaining blockers, owners, and still-running CLI identifiers instead of claiming readiness.

**Exit:** the full spec is delivered in one review-ready PR with independent verification and reconciled resource ownership, or an explicit recoverable failure/blocked handoff. A handoff is not successful completion.
