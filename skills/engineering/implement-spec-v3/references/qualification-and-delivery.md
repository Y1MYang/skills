# Qualification, checkpoints, and delivery

Read when a critical checkpoint becomes runnable, test dependencies change, or the whole-spec candidate is ready.

## Independent test qualification

Delegate [test-review](../../test-review/SKILL.md) to the implementation-blind Coverage audit coordinator using the resolved installed pointer if needed. Pass explicit spec/criterion scope, public-contract revisions, pinned test base/head or immutable snapshot, allowed inventory, dependency closure, prior qualification evidence, and the invocation's model mapping. Spec reviewer and Standards reviewer run their separate axes with those selected models. Apply the resolved [acceptance contract](../../test-review/references/acceptance-contract.md) to acceptance assertions, numeric/timing rules, and failures.

Use the dependency's actual scope semantics:

| Scope | Use and required result |
| --- | --- |
| `batch` | Qualify a checkpoint's explicit criteria and dependency closure. Both axes must pass; qualification is local to those pinned inputs. |
| `delta` | Compare exact prior inputs to the new candidate for a named batch or full target. Recheck affected closure and unresolved findings; carry forward only qualified, unchanged evidence. A failed prior review supplies history, not qualification. |
| `full` | Reconcile every spec criterion, all applicable tests, shared dependencies, and cross-batch interactions. Reuse only still-valid local evidence; the union of batch passes is insufficient. |
| `failure` | Triage a failing test from neutral facts and identify the next distinguishing check. It does not automatically renew qualification or require rerunning every review. |

Keep requirement fidelity/coverage, test validity, and observed product success separate. A filename-only requirement mapping is insufficient: name the observable behavior and assertion that establishes it. Unresolved validity/coverage gaps remain partial, missing, or unverified. Every test repair, including an apparently mechanical helper or fixture change, belongs to blind Test author; review participants remain read-only.

Changes to shared helpers, fixtures, configuration, acceptance timing, or public contracts reopen all affected qualification scopes. Unknown dependency closure requires a wider review. Product-only changes with unchanged dependency declarations do not by themselves repeat unchanged test-review; their product execution and code-review evidence still need current binding. Expanding a snapshot dependency inventory through `include` requires affected qualification and execution again even when file hashes match. Preserve old evidence and explain each carry-forward or invalidation.

## Critical checkpoint release

Plan formal checkpoints by exception. Each one costs a frozen candidate, a full-scope formal run, and dual-axis review, so a checkpoint earns its place only when a **critical contract is consumed by another flow** before final delivery. Examples that merely share a repository do not need a checkpoint between them; the final gate covers them. Declaring zero intermediate checkpoints is the default for a single-flow run.

Before recording a checkpoint release, Integrator and Runner report all of:

1. The checkpoint's prerequisite examples and required integration checks are complete.
2. Tests for every in-scope criterion have current independent local qualification on the applicable contract/dependencies.
3. The candidate is clean, committed, and frozen for formal execution, with its exact SHA and full scope recorded.
4. Runner's bounded formal execution of that scope passes with valid evidence; no relevant unresolved failure or hang remains.

Only then record the release against the checkpoint inputs. Later consumer `open` checks the gate's HEAD and declared dependencies; uncommitted consumer tests or other dirty files outside that dependency closure do not alone invalidate release. Missing qualification or stale execution blocks consumers, not the checkpoint's own remaining prerequisite examples. Repairs use the existing checkpoint history, scope identity, and finite budget; renaming a batch or checkpoint cannot replenish it.

**A failed formal attempt is judged before any repair is dispatched.** Record and classify the failure (and its `diagnose` event when classification needs evidence) first; the repair brief cites that record. The runtime enforces the diagnosis before requalification or retry of the same scope. Dispatching a repair against an unjudged failure repeats the 2026-11-02 spec-issue1-v1 mistake where the fix brief predated the failure's own adjudication.

## Same-candidate final acceptance and review

Once every planned example is integrated, Coverage audit performs `full` test reconciliation. Integrator assembles a clean committed whole-spec candidate, records the complete acceptance scope, and freezes HEAD. While that candidate stays unchanged, run in parallel where possible:

- Runner executes complete formal acceptance with the required execution evidence and budgets.
- Fresh implementation-visible **Spec reviewer** and **Standards reviewer** instances review the same frozen HEAD against a resolved base and explicit comparison method. Spec review receives the authoritative spec and full criterion mapping; standards review receives applicable repository standards. Both receive the fixed candidate and report exact reviewed scope and unresolved findings.

If an installed `code-review` skill is used, bind it to the explicit spec and fixed base/head, preserve the invocation's selected reviewer models, and keep all file work delegated. Its default context/model rules cannot relax v3's boundaries. Final code-review contexts are distinct from blind test-review contexts even when the same models are used.

Collect both review axes and full execution before coordinating repairs. Assign product repairs to Implementer, test repairs to blind Test author, environment repairs to the relevant owner, and missing business choices to the user. Failure classification and any neutral test-review package precede repair. Maintain one owner per shared write target.

Every modified candidate has a new binding. Before final readiness, Integrator records the new frozen HEAD and the code-review axes examine changes plus affected scope; the **formal execution scope depends on the delivery stage**: a repair before final readiness reruns formal acceptance over the affected scope (a gate's prerequisites or the repaired examples plus their dependent closure), while a repair after the whole-spec final attempt reruns complete final acceptance, because final is the last chance to prove the whole spec on one HEAD. Unaffected qualified review evidence may carry forward only with explicit old/new revision links and unchanged inputs. Changed test dependencies also require the appropriate `delta`/`full` test qualification. A passed run or review of a previous HEAD does not support delivery of a different HEAD by itself.

## Ready and handoff

Deliver one PR for the complete spec by default, using the repository's PR conventions. Mark it ready only when whole-spec test qualification, complete valid acceptance, and both final code-review axes all support the exact delivered HEAD, with no pending attempt across any flow or scope. Account for every criterion and resolve material findings through the appropriate authority. Every non-Red execution failure requires diagnosis followed by eligible formal execution covering its scope on the current candidate; diagnosis or acceptance of a finding alone cannot replace that evidence. An interrupted run, unexplained hang, or unknown failure leaves readiness unverified. Preserve historical failures after resolution.

Have owners reconcile and release idle temporary resources under [execution and recovery](execution-and-recovery.md) — probe work directories, per-flow worktrees, and scratch copies included — preserving the delivery branch/commits, compact evidence, and any justified failure scene. Final report gives the PR/head, covered scope, test/execution/review conclusions, real limitations, and released/retained resources with reasons. Publishing and unrelated post-merge cleanup remain subject to the user's actual authorization; v3 resources are not inputs to v2 cleanup tools.
