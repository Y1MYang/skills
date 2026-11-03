# Architecture and development flow

Read while preparing the task graph, refining a public interface, admitting parallel work, or changing a contract.

## Prepare the whole scope, refine the current example

Exploration inventories relevant repository facts, dependencies, existing public behavior, runner facilities, and evidence for execution budgets. It creates separate implementation notes and a test-safe package, keeping observed behavior distinct from authoritative requirements. Architect uses this evidence to establish:

- every spec criterion/ticket mapped to planned observable examples, including required negative and interaction behavior;
- global external boundaries, critical cross-module contracts, integration surfaces, compatibility constraints, and observation/injection seams;
- per-flow dependencies, owned write targets, test dependencies, and the intended integration order;
- critical checkpoints with explicit scope, contract version, prerequisite examples, and consumer release edges;
- finite run budgets and command deadlines, progress signals, stop scope, available capacity, and the evidence/estimate supporting them. Set issue-local diagnostic allocations when the issue is known, using [evidence-based renewal](diagnostic-budgets.md), not a universal fixed retry count.

Plan whole-spec coverage without implementing all tests in advance. Before each example, pin only the public signature/types/errors and seams needed for that example. Leave internal algorithms and structures to emerge from implementation and refactoring. Public contracts delivered to the blind side include their requirement basis, not implementation-derived instructions.

The main agent can review architecture during preparation. Once the test/implementation phases begin, delegate further document reads/edits and rely on structured Architect reports. Genuine missing business or compatibility choices go to the user; behavior-preserving technical refinements stay with Architect.

## Dependency and checkpoint graph

An example is ready only when its ordinary prerequisite examples have current Green plus affected-regression evidence and its required checkpoint release edges are satisfied. Tickets may contain many serial examples. Assign their ready sequence to persistent role owners under [flow delegation](dispatch-and-isolation.md#persistent-flow-assignments); readiness is checked at each transition without a new main-agent dispatch. Independent flows remain parallel; avoid making an unrelated ticket wait for a checkpoint outside its dependency closure.

A critical checkpoint is a real release gate for its **consumers**: required test scope independently qualified, prerequisites integrated, and formal execution passed on a fixed candidate. A test batch alone does not create a checkpoint.

Keep checkpoint prerequisites and blocked consumers distinct. The checkpoint must be executable before the consumers it blocks exist. Check the graph including both prerequisite and release edges for cycles. For example, `99 → shipping fee` may advance to `100 → free shipping` after ordinary Green; both examples prepare the shipping checkpoint. A downstream checkout flow that consumes the complete shipping contract waits for that checkpoint's qualification and formal pass. Making the second shipping example wait would deadlock its own checkpoint.

## Parallel ownership and integration

Give each independent flow its own workcopy/branch and evidence destination. Within a flow, only its current phase writes its owned target. Give each shared test helper one blind Test author owner; other flows read a pinned revision. Route shared mutations through the owner or an exclusive integration phase. Merely assigning different JSON fields in one mutable state file does not isolate writes.

Keep development workcopies separate from the runtime's authoritative snapshot workspace: the current ledger requires evidence roots to match that workspace. Integrate a fixed revision there before taking accepted integrated evidence. Persistent assignments do not create support for cross-worktree evidence or allow overlapping writes while a command observes its snapshot.

Integrator alone writes the integration branch/shared index. Admission considers dependency readiness, environment capacity, and declared budgets, not ticket count. Deliver fixed revisions/digests and explicit test/contract dependencies. Integrator verifies the combined result through Runner against affected behaviors; independently Green branches do not prove the merge is Green. Test conflicts or semantic test edits return to blind Test author. Product conflicts return to Implementer when they require implementation judgment.

## Progressive contract changes

Use one change path:

1. Architect records the public before/after difference and authoritative basis. An implementation inconvenience is not new business authority.
2. Map the affected examples, consumers, tests, helpers, fixtures, configuration, and previous qualifications/executions. Unknown impact requires a wider check.
3. Pause affected consumers at a safe boundary, saving work and evidence. Unrelated flows can continue. Keep existing checkpoint identity, history, and budgets.
4. Pin the revised contract. Blind Test author updates independent tests; changed tests require lightweight checking before development and affected-scope independent review before formal qualification.
5. Refresh affected execution and review evidence. Resume the consumers only when their applicable gates are current.

A stale checkpoint stops new releases through that checkpoint. A proven contract correction also pauses affected in-flight reliance at a safe boundary. Neither condition requires discarding unrelated completed work. Record evidence invalidation and any justified carry-forward explicitly; changing a contract, helper, fixture, or configuration can invalidate several earlier examples or batches.
