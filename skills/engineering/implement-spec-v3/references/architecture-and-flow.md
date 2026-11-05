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

An example is ready only when its ordinary prerequisite examples have current Green plus affected-regression evidence and its required checkpoint release edges are satisfied. Tickets may contain many serial examples. Assign their ready sequence to persistent role owners under [flow delegation](dispatch-and-isolation.md#persistent-flow-assignments); readiness is checked at each transition without a new main-agent dispatch.

**Parallelism is planned, then mechanically checked.** The plan's dependency graph is an example-level DAG. Every set of simultaneously ready examples must sit in distinct flows: the runtime computes ready levels from `depends_on` and rejects a plan that parks siblings in one serial flow (`unnamed-parallelism`), because a sibling waiting behind an unrelated Red/Green cycle is the most expensive idling a run can plan in. Flow assignment is the only serial decision; within a flow the cycle order follows the DAG. A genuinely serial chain stays one flow — do not mint flows to inflate parallelism that dependencies do not offer.

**One workcopy per flow.** Every parallel flow owns a workcopy root distinct from the integration workspace, declared as the flow's `root`; all its examples' snapshot roots point there. Byte-scope evidence is captured inside that workcopy, so concurrent flows cannot corrupt each other's before/after snapshots. The single authoritative workspace remains the integration target: Integrator merges each finished flow there and Runner verifies the combined result in the workspace before any gate or final evidence. Independent flows remain parallel; avoid making an unrelated ticket wait for a checkpoint outside its dependency closure.

A critical checkpoint is a real release gate for its **consumers**: required test scope independently qualified, prerequisites integrated, and formal execution passed on a fixed candidate. A test batch alone does not create a checkpoint.

Keep checkpoint prerequisites and blocked consumers distinct. The checkpoint must be executable before the consumers it blocks exist. Check the graph including both prerequisite and release edges for cycles. For example, `99 → shipping fee` may advance to `100 → free shipping` after ordinary Green; both examples prepare the shipping checkpoint. A downstream checkout flow that consumes the complete shipping contract waits for that checkpoint's qualification and formal pass. Making the second shipping example wait would deadlock its own checkpoint.

## Parallel ownership and integration

Each independent flow's workcopy root (its declared `root`) isolates its writes and evidence. Within a flow, only its current phase writes its owned target. Give each shared test helper one blind Test author owner; other flows read a pinned revision. Route shared mutations through the owner or an exclusive integration phase. Merely assigning different JSON fields in one mutable state file does not isolate writes.

Integrate a fixed revision in the authoritative workspace before taking accepted integrated evidence: per-flow workcopies do not establish accepted run evidence on their own. Persistent assignments do not create support for cross-worktree evidence or allow overlapping writes while a command observes its snapshot.

Integrator alone writes the integration branch/shared index. Admission considers dependency readiness, environment capacity, and declared budgets, not ticket count. Deliver fixed revisions/digests and explicit test/contract dependencies. Integrator verifies the combined result through Runner against affected behaviors; independently Green branches do not prove the merge is Green. Test conflicts or semantic test edits return to blind Test author. Product conflicts return to Implementer when they require implementation judgment.

## Progressive contract changes

Use one change path:

1. Architect records the public before/after difference and authoritative basis. An implementation inconvenience is not new business authority.
2. Map the affected examples, consumers, tests, helpers, fixtures, configuration, and previous qualifications/executions. Unknown impact requires a wider check.
3. Pause affected consumers at a safe boundary, saving work and evidence. Unrelated flows can continue. Keep existing checkpoint identity, history, and budgets.
4. Pin the revised contract. Blind Test author updates independent tests; changed tests require lightweight checking before development and affected-scope independent review before formal qualification.
5. Refresh affected execution and review evidence. Resume the consumers only when their applicable gates are current.

A stale checkpoint stops new releases through that checkpoint. A proven contract correction also pauses affected in-flight reliance at a safe boundary. Neither condition requires discarding unrelated completed work. Record evidence invalidation and any justified carry-forward explicitly; changing a contract, helper, fixture, or configuration can invalidate several earlier examples or batches.
