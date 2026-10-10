---
name: test-review
description: Review test changes for spec coverage and reliable acceptance criteria, including stronger assertions, timing budgets, and timeout failures. Use before blessing spec tests or when a failure may come from the test contract.
---

Review tests as an independent oracle. Produce a read-only assessment of requirement fidelity, whole-spec coverage, and whether the tests can distinguish the required behavior from realistic failures. Test validity, coverage, and observed product success are separate conclusions.

## Inputs and independence

Keep every participant **implementation blind**, including the coordinator, both reviewers, and any Expert. Review only:

- the spec and its recorded decisions;
- public architecture contracts: interfaces, types, error semantics, and approved observation/injection seams;
- acceptance contracts, test source, fixtures, helpers, test configuration, and repository testing standards;
- neutral execution facts supplied by a separate runner: timestamps, public events, assertion outcomes, environment metadata, and evidence identifiers.

Treat this list as the input boundary. Test imports may name production modules; reading that declaration does not authorize opening those modules. Use Git metadata/path names to inventory test-side paths, then constrain commands to those paths **before reading diff contents**. Production patches and commit explanations stay outside the review.

Pin public contracts, test materials, and clearly labeled synthetic event sequences as supplied. Synthetic inputs support mechanism reasoning, require no fabricated runner or sanitization receipts, and establish no product-run result. For excerpts or runtime evidence derived from implementation-bearing material, an input owner outside the review prepares them before delivery, excluding implementation notes, architectural algorithms, production source, private stack frames/locals, and diagnosis. Record the sanitization scope and original evidence identifier with its owner; reviewers do not open the raw material to filter it themselves.

Dispatch in fresh contexts without inherited conversation history. Pass only the allowed pointers and this boundary, including to nested reviewers and Expert help. If a participant has already seen the candidate's production implementation, replace that participant with a fresh one; an instruction to forget it cannot restore independence. If input sanitization cannot be established, report the boundary gap and keep the affected review unqualified. Missing behavior facts remain gaps, never guesses from the implementation.

The review may read files and report findings. It has no authority to edit tests, product code, acceptance deadlines, or the spec. For execution, use only isolated checks of the test's decision mechanism with controlled events/clocks and no production imports. A separate runner owns product integration and supplies neutral facts. Avoid collection, imports, shell wrappers, or logs that reveal production source. Route implementation diagnosis to the caller's checkpoint/fixer, outside this review.

## Pin the review

Record the spec/public-contract revisions, allowed file inventory, and candidate version before reviewing. For a committed candidate, use concrete resolved base/head SHAs. Choose explicitly between direct base-to-head comparison and a merge-base comparison; record the resolved merge-base when using it. An old review's head is often the appropriate direct base for a delta. Do not silently use three-dot semantics.

For an uncommitted candidate, pin HEAD plus the contents of relevant staged, unstaged, deleted, and untracked test files; a commit SHA alone is insufficient. Compare against the selected base with explicit allowed paths, and include untracked files separately. A content digest or equivalent immutable snapshot identifies the reviewed state. A changing snapshot needs a new version or a stated qualification.

Choose the scope:

| Scope | Work and completion condition |
| --- | --- |
| `full` | Review all candidate test changes and the existing tests needed to map every spec requirement and acceptance criterion. Finish both axes and reconcile the complete coverage set. |
| `delta` | Cite a pinned prior review, including a failed or partial review, compare its exact version to the new candidate, and review the affected dependency closure: shared helpers, fixtures, configuration, public contracts, and requirements. Carry forward only qualified, unaffected evidence with matching inputs; recheck unresolved findings relevant to the requested qualification, and add, change, and remove coverage entries explicitly. An unavailable prior version or unknown closure requires a wider review. A prior failure does not prohibit incremental repair review or supply an overall blessing. |
| `failure` | Start with the failing test, its dependent helpers/configuration, and neutral first-failure facts. Classify the concrete uncertainty and request the next discriminating check. Widen to affected axes/coverage only when that evidence warrants it; do not automatically repeat a whole review or full suite. |

Without a spec, perform the validity/standards assessment and mark requirement fidelity and whole-spec coverage **unverified**. Missing spec is not permission to infer the intended behavior from production. A partial review cannot bless the complete suite.

## Review and reconcile

Read [references/acceptance-contract.md](references/acceptance-contract.md) whenever reviewing acceptance assertions, changed success criteria, numbers, asynchronous evidence, or a failure. It is the single source for acceptance and timing rules; pass the resolved pointer to each relevant reviewer.

With a spec, for `full` and substantive `delta` reviews, dispatch these axes in parallel, with disjoint briefs and the same pinned allowed inputs:

- **Spec/coverage reviewer:** check requirement fidelity, the source of every new or changed acceptance assertion and numeric constraint, extra restrictions, and missing or partial coverage. Map every requirement to a test and the specific observable behavior it proves; a filename alone is insufficient.
- **Validity/standards reviewer:** check the test's decision mechanism, causal evidence of required behavior, relevant false-success and false-failure paths, fixtures/helpers, asynchronous ordering, isolation/cleanup, and repository testing standards. Apply the acceptance reference; distinguish confirmed defects from risks requiring a check.

The **Coverage audit** coordinator reconciles the requirement set with the union of both reports and the test mapping. Account for every requirement as covered, partial, missing, or unverified, including negative/error cases the spec requires. Count only valid assertions as verified coverage; an invalid or unresolved mechanism leaves the affected link partial or unverified. Resolve disagreement through source evidence or a scoped check, and keep independent whole-spec coverage and validity conclusions. Coverage of a requirement does not prove the product currently satisfies it.

When called from a workflow with selected models, explicitly dispatch the Spec/coverage reviewer with its **Spec reviewer** model and the Validity/standards reviewer with its **Standards reviewer** model; the coordinating agent uses **Coverage audit**. Reuse that mapping for replacements and nested dispatches. Do not add a startup model questionnaire. Standalone reviews honor supplied choices; otherwise follow runtime selection. If the platform cannot parallelize, perform and label the two assessments sequentially.

For `failure`, the coordinator may make the initial narrow assessment directly or assign the relevant axis. Suggest ownership as **implementation**, **test**, **environment**, **spec decision**, or **unknown**, with evidence and the next check. The caller adjudicates and routes repairs. Preserve its existing fix-round counts and deadlines; a new review, helper, or replacement does not reset them.

## Deliver

Return a compact versioned report containing:

- scope, base/comparison method, candidate snapshot, allowed input revisions, prior evidence reused, and independence limitations;
- separate Spec/coverage and Validity/standards results; identify any axis not run;
- whole-spec coverage conclusion and requirement-to-observable-test mapping, with explicit partial/missing/unverified entries;
- findings classified as **confirmed defect**, **risk**, or **missing business decision**: test location, requirement/source, failure mechanism, and next discriminating check;
- failure ownership recommendation, remaining evidence gaps, and the caller's next action.

Give each conclusion a **pass**, **fail**, or **unverified** status with its basis. Confirmed defects fail the affected conclusion; missing necessary evidence leaves it unverified; an unproven risk needs a qualification and discriminating check.

Separate reasoning, isolated mechanism checks, and runner observations. State which were actually performed. Keep revised acceptance success separate from success under the previous contract and from any performance claim. Stop when the chosen scope is accounted for; report unresolved decisions instead of optimizing the product or retrying until green.
