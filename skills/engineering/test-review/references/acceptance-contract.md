# Acceptance contract

Use this reference for acceptance assertions and numeric constraints, including strengthened assertions and timeout diagnosis. It defines review criteria, not authority to change a contract.

## Behavior and evidence

For each acceptance test, identify the initiating action, required behavior, observation boundary, and success evidence. Trace each new or changed assertion and number to the spec, an explicit recorded decision, a public architecture contract, or a justified test mechanism. Label a proposed restriction as a proposal; an inherited literal with an unknown source remains unknown. Repository conventions guide the mechanism but do not silently create business requirements.

Explain the causal chain: how does the observed evidence establish that this action produced the required behavior? In an asynchronous resume scenario, an enabled button or a displayed running state may establish UI behavior but cannot by itself establish execution. Distinguish the prior position/attempt from the resumed attempt and identify a public effect or acknowledged transition caused by this action. Scope observations to the relevant task, run, attempt, or position so an old event cannot satisfy a new action.

Review shared fixtures/helpers as part of this chain: controlled inputs and expected values, asynchronous ordering, clock use, observation side effects, cleanup, and state isolation. Expected outcomes need an independent source; copying the tested calculation or assuming current production behavior supplies no oracle. Use approved public seams; if the required evidence is unavailable there, report the observability gap for the caller rather than reading private implementation.

## Timing

Classify each time limit by its actual role and evidence:

| Role | Meaning and required basis |
| --- | --- |
| Business deadline or performance SLA | A required externally observable time behavior. Cite its source and define the workload/environment. Preserve it unless the authorized contract changes. |
| Evidence wait | A bounded opportunity for required asynchronous evidence to become observable. Justify synchronization, expected progress, observation cost, and termination; this is not automatically a performance SLA. |
| Harness wall cap | A finite bound on the test or command itself. State scope and what work it contains; it does not by itself establish business performance. |

One limit can serve more than one role; record each explicitly. Unknown provenance or semantics is a gap, not a default assignment to the harness category.

For every relevant limit, specify `t0`, `t1`, clock, measured interval, and execution conditions. Include setup, fixed delays, polling frequency, synchronous observer work, event delivery, intermediate business work, cleanup, and nested framework/process timeouts where they affect the interval. A predicate or callback can overrun a deadline before the loop checks it again. Explain what the reported duration measures: whole test, command, resume acknowledgement, or completion of a later business stage.

Where a functional wait uses progress, distinguish credible business progress from heartbeats, repeated status, elapsed time, and counters that can grow during empty looping. Scope progress to required work and retain a finite whole-wait cap that does not restart on progress. Explain stall detection and bounded termination; use the project's supported policy and evidence for values rather than prescribing a universal timeout.

## Changed success criteria

For a strengthened assertion, compare the old and new contracts together:

- Which behaviors were accepted before, and which are accepted now?
- Did the success endpoint move from UI acknowledgement to execution, or to a later business stage?
- Did workload, observation cost, fixture behavior, or environment change inside the measured interval?
- Which budgets still have a valid basis for this interval, and which need a decision or measurement?

Keeping an old numeric literal does not preserve the contract when its predicate or measured work changes. Stronger execution evidence can be necessary while its waiting mechanism still needs revision. Report these separately. A valid business SLA stays binding; an unsupported extra restriction needs a decision. Recommend a concrete waiting/measurement change with its basis and limits, but leave test and contract edits to the caller's authorized owner.

## Counterfactual checks

For the affected mechanism, assess an ideal compliant path and the plausible failure paths that matter to its risk. Reasoning can be enough for a simple predicate; use isolated deterministic events/clocks when ordering, progress, or timeout interaction is uncertain. Record the method and its limits instead of requiring every acceptance test to rerun the product.

For a resume/progress check, useful paths include UI change with no execution, stale evidence from the prior pause, the real resumed attempt reaching the required effect, and nonproductive activity that must eventually fail. A long but genuinely progressing path can expose an evidence-wait problem; only its actual contract decides whether it is also a business-time violation. Tailor negatives to the requirement and mechanism rather than adding a universal matrix.

An isolated model can demonstrate how a test decides or terminates. It cannot prove product performance, actual scheduler behavior, or a throughput guarantee. Repeated timeouts do not prove mathematical impossibility. Claim an infeasible budget only with an applicable lower bound or other direct evidence, stating its assumptions.

## Failure classification

Preserve the first failure's candidate, assertion/predicate, interval, command, environment, and evidence identifier. Examine the failed condition before choosing a repair direction:

- required behavior or evidence absent: implementation fault, observation flaw, or unknown;
- stale/UI-only evidence accepted: test mechanism defect;
- legitimate progress exceeds an unsupported evidence wait: contract/mechanism review;
- sourced business deadline exceeded under its conditions: performance or business-time failure;
- contaminated fixtures, observation overhead, or external resource interference: test/environment investigation;
- contradictory or unspecified acceptance semantics: spec decision.

These are hypotheses until supported. Use comparable candidate/environment facts and an equivalent oracle before attributing a new performance regression. Ask for the smallest check that distinguishes the remaining causes. Keep revised-contract results, old failures, and product-performance conclusions separate; a new green result neither erases the old result nor proves a performance fix.
