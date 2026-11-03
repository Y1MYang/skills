---
name: tdd
description: Build features or fix bugs with test-driven development. Use when the user requests TDD, test-first work, or red-green-refactor.
---

# Test-Driven Development

Work in small Red → Green → Refactor cycles. Each cycle adds one concrete behavior example and leaves the relevant tests passing before the next example starts.

## Set the boundary

Identify the public boundaries under test, the behavior they promise, and how callers observe it. A **seam** is one of these boundaries. Reuse established contracts and the user's existing authorization; choose routine test seams within that scope without asking for approval again. Ask only when a consequential business or compatibility decision remains unresolved.

Read the project's `GLOSSARY.md`, if present, and relevant ADRs so test names and interfaces use its domain language. Establish external boundaries and integration constraints up front; refine the current example's public interface before testing it. Let internal structure evolve with the loop.

Keep a coverage list from the requirements, including important boundaries and failure cases. It is a plan for later cycles, not a batch of tests to write before implementation.

## Run the loop

1. **Choose one example.** Select the next concrete input and observable outcome from the coverage list. Write one main test for that example. Multiple assertions can describe the same outcome; the full set of a behavior's boundary cases belongs in successive cycles.
2. **Red.** Run the new test against the current baseline. Confirm that it fails because the target behavior is missing or wrong. A missing required public interface can be valid Red; unrelated compilation, environment, or fixture failures need repair before the result counts.
3. **Green.** Add only the implementation needed for the current example. Run that test and affected regression tests until they pass.
4. **Refactor.** While Green, improve the structure of implementation or tests as needed without changing behavior. Already verified examples of the same rule can become a parameterized test. Rerun affected tests after changes. If no useful refactor is needed, finish the cycle.
5. **Continue.** Record the example's result, update the coverage list, and select the next example. New behavior starts a new cycle rather than entering through refactoring.

If the first run is already Green, inspect whether the test exercises the intended behavior and would detect a violation. Record it as verified existing capability and proceed to the next missing example. Keep the working implementation intact; do not manufacture a Red result or claim a Red → Green history that did not occur.

Before completion, check the requested behavior coverage and run the relevant project checks against the final changes. Report actual results and any unresolved gaps.

## Keep tests useful

Derive expected outcomes from requirements or independently worked examples. Exercise public behavior so tests catch a broken promise and survive internal restructuring. Observable behavior can include return values, errors, persisted state, outgoing requests, or emitted messages when those effects are part of the public contract.

- Read [tests.md](tests.md) when choosing assertions or evaluating test quality.
- Read [mocking.md](mocking.md) when replacing dependencies or controlling external effects in a test.
