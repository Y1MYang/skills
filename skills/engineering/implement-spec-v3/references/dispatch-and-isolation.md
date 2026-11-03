# Dispatch and isolation

Read before the first dispatch and whenever replacing a participant or crossing the test/implementation boundary.

## Responsibilities and model binding

Responsibilities define authority, not ten permanently running agents. Save the invocation's explicit role-to-model mapping with its run record through the Integrator. Use the selected model in every real dispatch, including nested `test-review` calls. If model selection requires a context mode other than full-history inheritance, use that mode; implementation-blind contexts always start without inherited history. A user-requested model change applies to subsequent dispatches and is recorded with its effective point.

| Responsibility | Output and authority |
| --- | --- |
| Exploration | Repository/dependency facts, plus a separately authored test-safe package. Implementation-bearing notes stay on the implementation side. |
| Architect | Global external boundaries, public contracts, integration constraints, dependency graph, and contract-change impact. Derives semantics from authoritative requirements. |
| Test author | Current independent example test, lightweight oracle check, and all test repairs/refactors, including shared helpers and fixtures. Remains implementation blind. |
| Implementer | Minimal implementation, product refactors, and implementation repairs. May read independent tests; does not edit their oracle, helpers, fixtures, or configuration. |
| Runner | Pinned command and execution limits, actual Red classification, versioned run facts, and sanitized test-safe summaries. Receives the declared expected failure before running. |
| Integrator | Single-writer merges/shared index, state/resource operations, and integration-verification coordination. Routes test conflicts back to Test author. |
| Coverage audit | Implementation-blind `test-review` coordinator and requirement coverage reconciliation. |
| Spec reviewer | Independent requirement/coverage axis of test-review; a separate fresh instance performs the final implementation-visible spec code review. |
| Standards reviewer | Independent validity/standards axis of test-review; a separate fresh instance performs the final implementation-visible standards code review. |
| Expert | Scoped help on a specific unresolved blocker. Test-side and implementation-side instances have separate contexts and input boundaries. |

Pass role, model mapping, owned write targets, allowed pointers, required artifact/version bindings, stopping limits, and expected report shape in each brief. Distinguish run/user limits from the issue's current [renewable local diagnostic allocation](diagnostic-budgets.md), linking its latest revision rather than copying an old fixed retry count. The Expert is available when a concrete blocker needs specialist diagnosis, not a required extra review of every example. Help inherits the requester's input boundary and existing failure history/spending.

## Persistent flow assignments

Dispatch a ready flow with authority to complete its planned sequence of one-example cycles within the existing graph, write ownership, and budgets. Name a persistent nonblind coordinator for routine routing; this can be an already assigned owner, not an extra responsibility or mandatory agent. Keep the Test author, Implementer, Runner, and state owner available as needed across cycles. Evidence events are tool operations within that assignment, not reasons to spawn a new agent or return to the main agent for permission. Persist each transition before using its result; report completed cycles or actionable exceptions together.

One context may hold compatible nonblind responsibilities only when their explicitly selected models are identical and its brief names each authority and write boundary. Shared state and integration still have one Integrator owner across flows. Keep the blind author separate from implementation-visible work, and keep independent review axes in their required separate contexts. When models differ, reuse separate role contexts and route their bounded work directly; a prompt naming another role does not change the executing model. A new skill invocation still collects all ten explicit choices before any reuse, and retained contexts must match those choices.

Runner supplies the pinned command, expected failure, limits, and scope. Integrator may invoke the [mechanical execution helper](runtime-ledger.md#execute-and-record-one-attempt) under its state-mutation authority; the helper performs bounded execution and records the actual receipt. Runner then inspects the result and supplies any semantic classification or sanitized packet. Calling that tool does not transfer Runner's judgment to Integrator or authorize merging differently selected role models.

Continue to the next ready example after the current cycle's evidence is complete. Stop the affected work for an unmet dependency/checkpoint, unresolved authority or contract change, contamination, ownership uncertainty, or a real budget/resource limit. Send the corresponding structured report to main; ready unrelated flows continue. Routine test-side questions use the allowed-input route below and do not turn the main agent into a file operator.

## Independent review dispatch

The Coverage audit coordinator dispatches Spec reviewer and Standards reviewer with their selected models. For full, batch, and substantive delta test-review, dispatch these axes in parallel against the same pinned test inputs; use and label sequential assessments only when the platform cannot parallelize. Final code review uses new implementation-visible instances with the same role selections; a final code reviewer cannot subsequently become an independent test reviewer in that context.

## Test-side allowed inputs

Start every new blind context with an explicit allowlist containing only:

- the specification, tickets, authoritative decisions, and their versions;
- public signatures, types, errors, compatibility rules, and approved observation/injection seams with requirement provenance;
- test source, fixtures, shared test helpers, test configuration, testing standards, and their fixed versions;
- neutral runner facts: public inputs/outputs, public events, timestamps, assertion outcomes, fixture/environment facts, and evidence identifiers.

Resolve pointers before dispatch; an allowed pointer grants access only to its stated scope. Inventory paths without opening production diffs, then constrain reads to allowed test paths. A test import naming a production module does not authorize reading that module. Test-side inspection must not execute collection/import wrappers that expose production source or private diagnostics; Runner owns product execution.

Exclude production source/diffs, implementation algorithms, implementation-bearing history and commit descriptions, raw debug logs/private stacks/locals, and exploratory implementation notes. A fresh worktree is not a fresh context. Run a blind agent with `fork_turns="none"` or the runtime's equivalent, never a full-history fork with an instruction to ignore what it inherited. An unpolluted Test author context may persist across examples in the same flow. Every new test-review starts its coordinator, reviewers, and any test-side Expert in fresh contexts containing only pinned allowed inputs.

Runner, Exploration, Architect, or another material owner outside test-review prepares any derived input before forwarding it. Record the original evidence identifier, owner, and sanitization scope. Reviewers never open raw material to sanitize it themselves. Neutral observed output can expose a failure but cannot become the expected output without a requirement basis. Relabeling implementation diagnosis as a public contract does not establish that basis.

Include complete recipient identifiers and the return route in each test-safe dispatch packet, including a known nonblind coordinator for missing routing information. Blind participants use those supplied routes; if an address is missing, report it to that coordinator instead of enumerating global agent or chat inventories. Global status listings, including completed-agent summaries, are outside the blind allowlist and can expose implementation facts. A coordinator that dispatches blind reviewers supplies their exact approved reporting routes too.

Implementation-side progress, internal work coordination, and diagnostics go to the named nonblind coordinator. A blind participant receives only a separately prepared allowed-input packet from Runner or the designated neutral-material owner. Keep this routing even for short waiting or completion updates; persistent contexts and direct worker messaging confer no additional read authority. Route blind-side outputs to the designated recipients without copying implementation-side replies back into that context.

If contamination occurs, mark the affected context and artifacts unqualified. Replace the participant with a clean context; reconstruct from the allowed package and independently reassess or rewrite affected tests. Preserve the incident and artifact lineage. Instructions to forget, agent replacement, or an unchanged assertion do not by themselves restore independent qualification. If the clean input boundary cannot be established, keep the gate unverified. This is an auditable workflow boundary, not a physical filesystem sandbox.

## Main-agent boundary and reports

At test authoring, implementation, checkpoint, final-review, and repair phases, main-agent activity is dispatch/status queries, structured-report consumption, contract coordination, and user communication. All file work remains with the appropriate subagent, including looking up references, reading resource ledgers, examining failures, cleanup, and PR preparation. The main agent may decide technical routing from reports; it does not inspect raw files to verify or take over a stalled owner.

Reports identify run/flow/example or checkpoint, responsibility/model, pinned inputs and output revision/digest, owned resources, completed check and its evidence identifier, unresolved finding/classification, budgets used/remaining, and the next permitted transition. A flow report may summarize several already recorded cycles with evidence pointers; raw history remains complete and immutable. Test-safe reports also identify allowlist and sanitization provenance. Keep raw implementation diagnosis on its own side; send only permitted material when asking the blind side to assess a disputed test.
