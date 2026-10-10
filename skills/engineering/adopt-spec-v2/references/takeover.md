# Takeover protocol

Read this reference for the evidence gate, reuse decisions, role inputs, and exceptions when adopting work already in progress. The main skill resolves and passes `V2_SKILL`, `V2_RESOURCE_PROTOCOL`, `V2_RESOURCE_HELPER`, and `V2_EXPERT_PROTOCOL`; these are context pointers to the installed v2 files, not literal paths or new protocols. Read the applicable v2 section at each execution stage. This reference changes only the conditions listed below.

## Evidence gate

Resolve all eleven role-to-model assignments for this invocation before dispatching Exploration. A historical mapping is evidence of the old run, not a selection for the new one. The newly selected mapping governs future dispatches, retries, replacements, and nested delegation; already running tasks keep their model until their delivery boundary.

Delegate the investigation to Exploration. Split independent scopes among Exploration instances when useful; name one coordinator to consolidate the record and own any ledger initialization. Investigation is read-only with respect to the project and existing resources. Before saving findings, that coordinator establishes whether an original notes/ledger scope can actually continue; otherwise it initializes fresh notes and a nested ledger under `V2_RESOURCE_PROTOCOL`. When v2 provides owned notes roots, use `init --notes-root` on a new/empty root before any note writing; do not write into a directory and then attempt to adopt it. Preserve sealed historical notes as immutable evidence. Provide the authoritative spec pointer and known ticket, PR, branch, checkout, and previous-run pointers rather than requiring an exhaustive machine scan.

Exploration reports:

- **Requirements:** the authoritative spec and acceptance criteria, amendments and applicable repository rules, and any contradictions that cannot be adjudicated from those sources.
- **Delivery:** the PR state and identity, target/base/head revisions, commits and uncommitted work, ticket dependencies, and which acceptance criteria each delivery demonstrably implements. Use immutable revisions or saved diffs; distinguish observed behavior from required behavior.
- **Architecture:** existing material against all six items in v2's architecture content contract; current public seams, compatibility constraints, and the specific omissions affecting remaining work.
- **Verification:** requirement-to-test links, test provenance and author input evidence, coverage/review blessing, recorded checkpoint inputs and outcome, full-suite runs and the exact revisions they exercised, and unresolved failures and consumed repair rounds.
- **Ownership and activity:** resource ledger and invocation identity, owners and recovery authority, dirty or active checkouts, branches used by ongoing work, and command/session IDs, deadlines, latest real progress, and required failure evidence. Preserve normally progressing tests and builds under the existing monitoring rules.

Completion means every acceptance criterion has a classified implementation state and independent-verification state, every relevant active delivery/resource has an owner and next boundary, and unknowns are named with evidence needed to resolve them. A passing suite, a ticket marked done, or a previous v2 invocation is insufficient alone. Unknown implementation state calls for targeted investigation, not automatic reimplementation. Ask the user only for unresolved requirement or scope decisions; delegate missing technical evidence to the responsible role.

## Takeover record

Keep a compact `takeover.md` in the shared out-of-repository notes directory. It is the **coordinator's implementation-bearing record**, not a Test implementer input. Provide that author a separate test-safe requirement map, normative architecture, and allowlist; give every role a manifest containing only its permitted pointers. Use this minimum schema; link source artifacts rather than copying them:

| Field | Required content |
| --- | --- |
| Identity | Spec revision, repository, PR URL/state, base and verified head revision, record time, and resolved v2 rule/protocol/helper fingerprints. |
| Mode | `same-invocation recovery` or `new takeover`, supporting evidence, original invocation/ledger pointer when applicable. |
| Models | This invocation's explicit eleven-role mapping; active legacy tasks retain their existing assignments until delivery. |
| Requirement map | Criterion/ticket ID, dependencies, implementation state and immutable evidence, independent-verification state and provenance, remaining delta and owning role. |
| Contracts | Approved architecture revision, compatibility sources, separately labeled implementation observations, and remaining contract gaps. |
| Handoff | Resource IDs or historical pointers, owner, branch/ref, unsaved-work pointer, active CLI IDs, existing deadline, delivery condition, retained reason, and native cleanup-handoff eligibility or its specific limitation. |
| Budgets | Failure/checkpoint identity, input revisions, previous attempts and outcomes, consumed/remaining rounds, unknown counts and main-conversation adjudication. |
| Inputs | Per-role context pointers; explicit neutral-infrastructure whitelist and admitted independent-test provenance. |
| Decisions | Applicable exceptions, spec/architecture conflict adjudications, and which previous evidence remains valid or needs replacement. |

Each state is `verified complete`, `partial`, `missing`, or `unknown`; independent verification additionally distinguishes admitted independent tests from regression-only tests. Keep the remaining delta concrete enough to dispatch, including completed tickets whose only remaining work is verification. Store implementation-bearing investigation separately from the test-safe package: a shared directory or ledger does not grant every role permission to every artifact.

The main conversation adjudicates the reports and releases the resulting plan. It does not obtain missing file evidence itself during the v2 implementation/test phases.

## Recovery and reuse decisions

**Same-invocation recovery** requires a verifiable original invocation and ledger, recoverable task/role ownership, saved delivery/evidence pointers, identifiable consumed budgets, and a ledger that permits the required continuation operations. Reuse the original registered resources and their ownership and retention state. Reconcile interrupted records under `V2_RESOURCE_PROTOCOL`; investigation of a live CLI is distinct from proving it has stopped. Readable evidence of a prior v2 invocation without recoverable ownership is a **new takeover**. A sealed ledger cannot be unsealed or appended merely to continue construction: preserve its handoff and notes and use a new takeover for further commands, retaining the failure history.

**New takeover** establishes fresh notes and a fresh ledger for resources created by this invocation. Reference historical resources with their original owner and recovery pointer outside the new ledger's managed-resource set. The helper cannot adopt existing directories; never register them as newly created, remove them through the new ledger, or imply that a new ledger resets unresolved failure budgets.

Apply reuse per deliverable, independently of the mode:

| Evidence | Decision |
| --- | --- |
| Implementation satisfies spec and applicable repository rules; required seams are usable. | Preserve it. Missing historical architecture-first procedure is not a rewrite trigger. |
| Implementation has a specific spec defect, applicable standards defect, unusable remaining integration seam, or missing necessary observation point. | Dispatch the smallest justified implementation delta under the approved contract. Record the defect and affected acceptance criteria. |
| Ticket is partially delivered. | Preserve verified parts and dispatch only the remaining delta; rebuild dependency edges around what actually blocks the frontier. |
| Implementation is complete but verification is missing. | Dispatch test/coverage/review work, not another implementation of the ticket. |
| Tickets or exploration notes are absent or stale. | Exploration reconstructs the executable task graph from the authoritative spec and verified state. Mark observations as observations. |
| Architecture is absent or incomplete. | Architect repairs the necessary contract, satisfying all six v2 content items. Reuse adequate portions and existing compatible signatures. |
| Existing test has adequate independent-authoring provenance and matches the spec and approved contract. | Admit it to the independent coverage map; preserve its source revision and applicable review evidence. |
| Existing behavior test has unknown or implementation-derived provenance. | Keep it as a regression asset. Derive missing independent coverage without exposing it to a new oracle author. |

Architect may inspect existing implementation to establish real seams and compatibility. Expected behavior comes from the spec and authoritative compatibility constraints. Keep accidental behavior and unresolved conflicts in a separate observations section; only adjudicated requirements enter the normative architecture or test-safe package. Preserve v2's irreversibility reporting for relevant adopted or changed public surfaces.

## Role-scoped inputs and test provenance

Create a test-safe package before dispatching a fresh Test implementer. A path allowlist is explicit: for each permitted file/artifact identify its revision, purpose, and why it is neutral. Exploration verifies neutrality; the main conversation approves the package from that report. Approval is ordinary workflow adjudication, not a new user confirmation.

Allowed neutral infrastructure includes test-runner configuration, runtime/dependency declarations, construction or wiring instructions, and helpers/fixtures that supply inputs without embedding implementation-derived expected outputs. A familiar filename or directory is insufficient proof. Extract a small neutral helper or document the required runner interface when a file mixes infrastructure and behavioral answers. Provide public API signatures through the approved architecture instead of exposing implementation files.

Provenance must identify the test source revision, authoring inputs and their revisions, and evidence that the author did not read the implementation or derive expected results from it. Suitable evidence includes original bounded-context dispatches and delivery records tied to that test revision. A test name, assertion quality, Git author, passing run, or claimed v2 usage alone does not prove independence. Admitting an old independent test does not exempt it from spec coverage and applicable review checks.

| Role | Input boundary |
| --- | --- |
| Exploration | Relevant existing code, tests, notes, revisions, ledger, and activity evidence; produces separately scoped findings. |
| Architect | Spec, tickets, exploration, compatibility evidence and necessary existing code; normative output separates requirements from observed behavior. |
| Test implementer | Fresh/bounded context containing spec, approved architecture, test-safe requirement map, neutral whitelist, and admitted independent tests/helpers permitted for reuse. Exclude implementation, regression-only behavior tests, answer-bearing fixtures, and implementation-bearing takeover notes or run logs. |
| Implementer | Spec, remaining ticket delta, approved architecture, necessary existing implementation and delivery revisions. Keep authors blind to formal spec tests while writing code; record historical exposure that cannot be undone rather than claiming retroactive blindness. |
| Coverage audit and its reviewers | Test-review uses fresh implementation-blind contexts with the test-safe package, permitted oracle artifacts, full-spec coverage/provenance records, and neutral failure facts. Final code-review has its own stage-permitted context; implementation-bearing findings are not forwarded to independent test authors or test-review. Fixed-version blessing is still required for newly authored or changed oracle tests. |
| Merger, Checkpoint, Fixer | Permitted integration inputs, verified refs, resource ownership and run evidence, and inherited round counts. Keep test-side repairs with the Test implementer under v2 failure ownership. |
| Expert | Only the requester's permitted package and the v2 one-shot help protocol; consultation grants no new author access or repair budget. |

Choose fresh or bounded dispatch contexts when the runtime requires them for explicit model selection or author isolation. Never full-history-fork an implementation-bearing conversation into an oracle author or test-review coordinator/reviewer. Keep the original test/implementation ownership when returning review or Expert advice; authors receive only permitted evidence.

Independent coverage spans the **entire spec**, including already delivered implementation. Map every requirement and acceptance criterion to admitted independent tests, then let Coverage audit invoke test-review's contract axis to verify those links as part of the blessing review. Retain useful regression tests alongside that coverage. Author missing oracle tests in distinct files unless amending an admitted independent source; preserve regression-only source files. Newly authored or changed oracle tests stay on the dedicated test branch until v2 final integration; historical tests already integrated need not be removed and replayed, but their presence does not authorize early merging of new oracle changes. If no oracle changes are needed, audit and bless the already integrated fixed test revisions and mapping, then skip the empty authoring/branch/merge operations.

## PR and workspace handoff

For an open PR, retain its identity, branch and delivery history. Existing ready status does not satisfy acceptance. For active work with no PR, create the draft PR using the ordinary v2 issue/ticket linkage. For a closed or merged PR, report verified state and remaining gaps and ask the user to define the next objective before further implementation or publication; do not reopen it or create a follow-up PR by inference.

Stop assigning new legacy-flow work under the current conversation's authority. Let in-flight tasks reach a saved, verifiable delivery boundary with their original deadlines and acceptance conditions. Exploration may proceed concurrently. Receive their delivered revisions, recompute remaining work and frontier, and apply the newly selected role models to future dispatches. Use authorized coordination channels; ownership outside this conversation is not automatically transferred.

For same-invocation recovery, continue the registered PR worktree after reconciling its true state. For new takeover:

1. Have the historical owner deliver uncommitted work as a verified commit or a necessary durable diff at its normal boundary. Preserve original dirty/active resources until that delivery is verified. Unavailable work remains an explicit gap; do not silently omit or recreate it.
2. Merger creates a new helper-registered PR working copy and working branch from the verified historical PR head, then imports delivered changes under the appropriate ownership. Existing independent tests and implementation are historical inputs; new oracle changes retain their separate branch.
3. At each delivery to the original PR branch, verify its current remote head and the local refs/checkouts that may still use it. Integrate concurrent committed changes into the managed working branch and revalidate affected evidence. Preserve the historical owner's checkout and its ongoing work; never move a ref checked out by an active owner or overwrite uncommitted changes.
4. Synchronize the reviewed delivery through a normal commit-preserving update to the original PR branch. If concurrent ownership or head movement prevents a safe update, retain the prepared commits and obtain a verifiable delivery boundary through existing authority. Do not force an overwrite to complete the handoff.

Record source and destination revisions and the destination's confirmed inclusion of each delivered change. Cleanup applies only to resources owned by the recovered invocation or newly created takeover. Historical retained paths are reported with their original owners; they do not become cleanup targets.

## PR publication and cleanup handoff

Apply this section when the resolved v2 resource protocol provides first-publication registration, `bind-pr`, or `seal`. These operations require actual creation/ownership evidence, not merely a PR URL.

| Construction state | Publication and final handoff |
| --- | --- |
| This invocation creates the PR on its new registered branch. | Follow v2's first `publish-branch`, native REST `bind-pr`, final publication and `seal` protocol. |
| Recoverable original ledger already has a qualified PR binding. | Retain that binding and publication identity; do not repeat first publication. Reconcile resources, write final notes, and seal the original invocation when its protocol permits it. |
| New takeover delivers to a pre-existing PR, or a historical recovery lacks the required first-publication/notes-root evidence. | Treat the PR as an external delivery identity. Preserve PR URL/base/final head, managed-resource evidence, original owners and durable recovery pointers in the adoption record. Ordinary commit-preserving delivery does not give this ledger a native sealed cleanup handoff. |

In the external-PR case, never register its existing remote branch as first-published by the new invocation, bind an unrelated integration branch as the PR head, edit ownership metadata to force sealing, or reopen a sealed historical ledger. Report the specific native cleanup-handoff limitation and preserve the unsealed ledger/notes; do not promise that `cleanup-spec-v2` can delete these resources automatically. Eligible owned worktrees and regenerable outputs still follow ordinary release/reconciliation rules. This exception changes cleanup discovery, not independent coverage, final PR validation, or resource ownership.

## Checkpoint history and repair budgets

Classify past stage evidence by **its inputs and result**, rather than by its stage label. A useful checkpoint identifies the implementation/test union revisions, mapped foundational requirements, command and outcome, and necessary failure scene. A useful full-suite run identifies the complete delivery revision and test inputs. A review identifies its scope, base and head and dispositions. A note saying “tests ran” cannot discharge a gate.

- Reuse valid previous integration/blessing evidence for unchanged inputs. Do not recreate “first merge”, “first full run”, or a completed checkpoint merely to match v2 chronology.
- If checkpoint evidence is missing and work remains, retain the recorded foundational ticket when identifiable; otherwise designate a topologically early ticket with the most dependents in the full graph, including already delivered tickets. Follow the v2 checkpoint trigger when that implementation is delivered and tests are blessed. If all implementation is already delivered, final integration/full-suite verification replaces the preliminary checkpoint, as in v2's degenerate case.
- Material contract or oracle changes invalidate affected historical evidence. Run the needed verification on the revised inputs and record why; this is a new evidence obligation, not a fictional restart of the project.
- Track each unresolved failure across names, models, agents, workspaces and skill invocations. Preserve v2's checkpoint budget of 1–2 rounds and full-suite fixer budget of 3 rounds with any previously consumed rounds for that failure. Expert consultations and replacement agents remain inside the current attempt.
- Unknown consumed rounds are **unknown**, not zero. Exploration seeks available evidence; the main conversation records a reasoned budget adjudication before commissioning repairs. Escalate exhausted budgets as v2 requires. Do not manufacture a fresh blocker identity to gain more attempts.

Keep the original stage-local counts and one shared failure identity; do not silently sum, transfer, or renew rounds on a phase change. An exhausted or unknown checkpoint budget cannot automatically become three new fixes for the same unresolved failure at full-suite integration. The main conversation first adjudicates from existing diagnosis and counts: it may continue unblocked work, seek permitted read-only diagnosis or qualified Expert help, commission verification without implying new repair allowance, or deliver a recoverable checkpoint. Any justified next action records its v2 phase, bounded allowance and inherited counts; adjudication does not silently expand a phase's budget. Escalate only when the inherited rules leave no executable way forward. A first standards correction is a remaining delta when no earlier attempt for that defect exists; otherwise preserve its repair history as well.

The final accepted revision must receive the complete project suite, including admitted independent tests and retained regression tests. A prior run can satisfy this only when its evidence describes that exact final revision and applicable inputs. Whole-PR Standards and Spec review compares the original PR base to the prepared integration head, covering pre-takeover changes too. After synchronization, that accepted review head, full-suite revision, and actual PR head must agree. Fix valid defects under v2 ownership and revalidate acceptance after repairs.

## Exception applicability

Record only exceptions actually used, with evidence and their completion condition. Everything else follows `V2_SKILL`, including concurrency, task frontier, Expert triggers, role models, file-work delegation, failure ownership, and resource release.

| V2 condition adapted | Applicability and replacement obligation |
| --- | --- |
| New invocation-owned PR checkout and draft PR. | True recovery reuses verified original registered resources; new takeover uses a new registered working branch but delivers to the existing open PR. Historical directories retain their owner. No-PR work follows the normal draft creation rule. |
| Invocation-owned first publication, PR binding and cleanup sealing, when supported by v2. | A new takeover cannot claim creation of the existing PR branch. Use the external-delivery/unsealed-record path above; qualified original bindings and newly created PRs still follow native sealing. Sealed historical ledgers remain external evidence for later construction. |
| Exploration/architecture precede all implementation. | Existing code survives when correct and usable. Complete missing evidence and contract requirements before releasing further authoring; document historical gaps without retroactively claiming the original sequence. |
| Tickets represent all implementation to perform. | Exploration builds the remaining task graph, preserving verified completed portions; verification-only gaps are owned by verification roles. |
| Spec tests have independent authoring and separate pre-integration branch. | Admit historical independent tests by provenance; uncertain tests are regression-only. Preserve already integrated historical tests, while all new oracle authoring keeps v2 isolation and final-integration timing. Already integrated unchanged oracle sources still require coverage/review gates but no empty branch merge. |
| Foundational checkpoint and first full-suite run occur in fixed chronology. | Reuse valid historical evidence or apply the remaining-work checkpoint. Fully delivered implementation goes to final verification. Always establish acceptance for the exact final revision. |
| Models selected at invocation start. | No exception: collect fresh explicit assignments for all eleven roles before any evidence dispatch. Active legacy tasks keep their assignments through their boundary. |
| Repair rounds and invocation resource scope. | No budget reset for an unresolved failure. Recover original managed resources only with verifiable identity/ownership; a fresh ledger manages only new resources. |
| Final review and ready-for-review delivery. | No reduction of scope: final checks cover the entire spec and whole PR. Closed/merged PRs require a user-defined next objective before further work. |

The adoption gate is complete when the mode and applicable exceptions are decided, in-flight ownership is accounted for, the remaining task graph and architecture are usable, and both authoring sides have correctly scoped inputs. The skill finishes only after v2 acceptance and whole-PR review, resource reconciliation, ready-for-review delivery, and a final report of evidence, exceptions, retained resources and irreversibility decisions; a state/gap report for a closed or merged PR is an explicit scope stop, not a claim of completed implementation.
