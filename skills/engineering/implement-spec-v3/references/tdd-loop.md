# One example at a time

Read before a flow's first example, when first-run Green occurs, or when a repair/refactor changes the current test. [TDD](../../tdd/SKILL.md), or its installed pointer resolved at startup, supplies the general behavior-testing rules; v3 adds independent authoring and version-bound evidence here. A [persistent flow assignment](dispatch-and-isolation.md#persistent-flow-assignments) may authorize several sequential cycles; only the current example's test and implementation advance at a time, and the flow's workcopy is its write scope.

## 1. Select and pin

Choose one new behavior example from the coverage plan. Record its requirement/criterion, flow, ordinary prerequisites, applicable checkpoint gates, public-contract revision, and known product baseline. Confirm the interface needed to express its public observation. Start only after the previous example and its affected regression checks are Green; downstream consumers also need current checkpoint releases.

## 2. Author one main test

Blind Test author writes one main test for this example. Multiple assertions may describe the same observable result; one function must not bundle several not-yet-verified behaviors. Use public observable behavior and approved seams; derive expected values from the requirement, never from product output.

**Prewriting (depth 1).** While the flow's current example is being implemented, the blind Test author may prewrite the next example's test from its already-pinned requirement and public interface. Record it with a `stage` event — test digest plus the lightweight oracle check — and keep the file in the flow's staging area outside every snapshot's regression scope. Never stage more than one test per flow, and skip staging when the next example's interface is not yet pinned by a closed prerequisite. A staged test enters the live regression scope only through `promote` (by Runner, when the example becomes current) followed by `open`. If a staged test's interface later changes, the blind side restages it; a stale stage is discarded, never silently promoted.

The lightweight oracle check records:

- requirement source and pinned public contract;
- public input, observation boundary, expected result, and its independent derivation;
- the concrete failure condition and why it distinguishes the target behavior;
- test and dependency snapshot: helpers, fixtures, configuration, and assumptions.

This check makes the example eligible for a Red attempt. It is not the complete dual-axis `test-review`, and it does not establish that the next failure is valid Red.

## 3. Observe Red before implementation

Runner receives the author's expected failure and runs the exact pinned test on the known baseline under [bounded execution](execution-and-recovery.md). Preserve test/dependency and product snapshots, command, output evidence, and actual cause. Valid Red means this execution failed because the target public behavior is absent or incorrect. A missing target public interface can be valid Red when it is precisely the absence under test. Unrelated compilation, environment/setup, fixture, import, and harness faults are not valid Red.

Only a recorded valid Red, following the lightweight check, releases Implementer for this new example. A nonzero exit code or an author's prediction alone cannot do so. Classify other failures and route the next distinguishing check under the recovery protocol. Give the blind side only neutral permitted facts when its judgment is needed.

**First-run Green:** Preserve it as existing-capability verification. Blind Test author verifies that the test meaningfully exercises the requirement, using neutral facts or an isolated check of the test mechanism if needed. Runner confirms the applicable regressions. Once test validity and scope are accounted for, close this example through the existing-capability path without claiming new Red → Green history. Never break working behavior merely to manufacture Red; unresolved test validity remains a gap.

**Pipeline the execution boundary.** While Implementer works the current example, the flow must not idle: the blind side prewrites (§2), and Runner's next dispatch rolls the current Green, its affected regressions, and the next example's Red probe into as few bounded executions as their scopes allow — one command may establish Green and affected regression, and the next example's probe may ride in the same dispatch batch when its pinned inputs already exist. Red-before-implementation still applies per example: a next-example probe classifies independently and never releases its own Implementer early.

## 4. Make the smallest change, then Green

Implementer may read the current independent test and previous delivered tests. Implement only what the current example requires; use the public contract to avoid a fixture-specific shortcut. Do not pre-implement the next example or change the independent oracle to gain a pass. A disputed test goes back as a requirement-level question with neutral evidence to the blind side.

Run the current test and the affected regression scope on the resulting product snapshot. One command may establish both Green and affected regression when its actual scope covers both; record that coverage and use its same evidence rather than rerunning the command solely for a second label. Keep the same test/contract/dependency identity as Red, or explicitly invalidate/re-establish affected evidence after a change. Record Green only from actual passing execution. Unexplained failures remain open even if a later attempt happens to pass.

## 5. Refactor if useful, then finish the cycle

Refactoring is optional after Green. Implementer owns product refactors. Blind Test author owns test/fixture/helper/configuration refactors, including consolidation of already-verified examples for one rule into a parameterized test. Preserve their individual requirement and evidence mappings. Test review remains read-only.

Before a test-side refactor changes the test snapshot, record `close` using the existing Green and affected passing regression to preserve the example's historical behavior completion. The flow's assigned coordinator keeps it on the same example's Refactor phase: do not start its next example or work that needs the refreshed proof. The blind test side then refactors, and Runner refreshes the historically closed example with `prepare(regression) → execution → record`, followed by any affected independent requalification. Only the resulting regression Green completes this cycle. Here `close` saves behavior evidence; it does not finish the ongoing Refactor phase, manufacture a new Red, or relabel the example as existing capability. Product refactors keep the normal Green → refactor → affected regression path.

Run affected tests after every refactor and invalidate affected qualification where dependencies changed. Refactoring preserves public behavior; a new behavior returns to the next example's test-first loop. Finish with the test/contract/dependency versions, Red or existing-capability evidence, result product version, current and regression Green, any refactor result, and open issues.

The assigned owners advance directly to the next authorized, ready example when this development evidence is current — promoting a staged test first when one exists. They retain their contexts and record each cycle as it happens; a batched report never hides unrecorded evidence or revives a discarded stage. Formal test qualification and product acceptance remain separate gates at critical checkpoints and final delivery.
