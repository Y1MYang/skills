# Implement-spec-v3 performance evidence (2026-11-03)

Status: complete. The candidate reduced local CLI workflow elapsed time on both fixed workloads while preserving the measured work. This is not a model/agent end-to-end speed claim.

## Final measurements

Python 3.12.10, native Windows 11 build 26200, 32 reported logical CPUs. Each scenario used one excluded warmup per arm, followed by six measured pairs in exact `AB, BA, AB, BA, AB, BA` order (`A` = baseline). No heavy regression or agent evaluation ran during this measurement window. All 28 trials completed: 24 measured plus four warmups. No measured trial failed, was discarded, or required replacement.

| Scenario | Baseline median (range), seconds | Candidate median (range), seconds | Median paired saving | Candidate/baseline paired ratio |
| --- | --- | --- | --- | --- |
| Small, repair, shared dependency refresh | 5.215 (5.162–5.294) | 4.339 (4.265–4.421) | 0.899 s / 17.20% | 0.8280 |
| Synthetic history/log volume | 18.174 (18.078–18.553) | 14.472 (14.331–14.633) | 3.729 s / 20.55% | 0.7945 |

Both scenarios have `n=6` per arm. Sample standard deviations were 0.059/0.059 seconds for small and 0.177/0.102 seconds for history/logs (baseline/candidate). Every measured pair favored the candidate; paired savings ranged 14.79–18.12% and 19.20–22.36%, respectively. Summed measured wall time was 31.336→26.050 seconds for small and 109.384→86.814 seconds for history/logs. Those sums describe this chosen workload mix, not typical project throughput. Full individual values are in [matched-results.json](matched-results.json); derived totals and phase/profile details are in [analysis.json](analysis.json).

The harness launched 37→25 outer subprocesses per small trial and 120→70 per history/log trial. These are actual `commands.jsonl` records, not theoretical savings or total descendant-process counts. Both arms committed 24/88 original events, ran 6/25 actual target commands, and executed 10/168 unittest cases per trial, respectively. Expected Reds and the intentional failed Green are preserved; zero failed *benchmark trials* does not mean failure paths were omitted.

## Where the elapsed time went

Median phase times below are independently computed and need not sum exactly because medians are not additive.

| Observed phase, seconds | Small baseline→candidate | History/log baseline→candidate |
| --- | --- | --- |
| Prepare + owned execution + record pipeline | 3.507→2.627 | 13.554→9.914 |
| Receipt-managed execution, inside that pipeline | 1.868→1.882 | 6.483→6.439 |
| Actual target unittest body, inside receipt time | 0.312→0.316 | 1.403→1.407 |
| Pipeline outside receipt-managed execution | 1.640→0.740 | 7.076→3.464 |
| Other ledger commands | 1.540→1.572 | 4.302→4.367 |

The gain is concentrated around the prepare/run/record command boundary. Actual assertion work and receipt-managed execution stayed comparable. Remaining elapsed time is bounded by owned subprocess startup/completion polling, complete history/evidence audits, and durable state serialization/I/O; removing interpreter boundaries cannot remove those obligations.

Separate final-fixture profiles (one per arm, excluded from all comparison timings) support that explanation. Both performed 90 full history audits, 1,171 receipt checks, 89 state saves, 114 atomic JSON writes, 50 runner snapshots, and 29 owned executions including formal Git helpers. Runtime snapshot calls inside the ledger changed 70→66; no history audit was skipped. Import machinery cumulative time was 4.270→2.747 seconds, while owned-execution cumulative time was 5.361→5.677 seconds and state-save cumulative time was 1.994→2.113 seconds. These are overlapping profiler quantities, not an additive wall-time breakdown. The runner's existing 50 ms completion polling accounts for the observed `time.sleep` profile entries; the harness introduced no sleep. See [baseline profile](baseline-profile-instrumented-summary.txt), [candidate profile](candidate-profile-summary.txt), and selected call counts in [analysis.json](analysis.json).

## Work equivalence and exclusions

Every pair matched actual target argv, outcomes, exit codes, test/contract/product snapshot byte hashes at every execution, and final fixture source hashes. Each run separately required before/after snapshot equality, cleanup completion, a clean stable formal HEAD, final `ready`, settled attempts, resolved failure history, and `verify` success.

The retained [equivalence audit](equivalence-audit.json) additionally compared all full original event payloads, not just counts. It normalized only each trial's absolute temporary-root prefix, final Git SHA, and generated attempt IDs in preparation order. Fresh directories, commit metadata, and generated identity are expected to differ. Timing, PID/ownership tokens, and resulting receipt/log hashes are not cross-arm byte-equality criteria; individual receipt SHA-256 values were checked against the retained original bytes. The new helper's execution-binding provenance is intentionally additional candidate state. No claim of byte-identical whole ledgers is made. Reproduce this evidence audit without executing targets using [audit_equivalence.py](audit_equivalence.py).

Only this Windows/Python environment and these two small deterministic workloads were measured. The history/log workload is synthetic, and target bodies are deliberately short, so process/ledger overhead is prominent. Six local pairs establish the reported local observation; they do not establish other-platform, large-project, model-queueing, authoring, review, or whole-task speed. The benchmark does not quantify unrelated-flow wait removal or model handoff savings. Those require separate workflow evidence.

## Preserved input

Baseline captured before edits at `C:\Users\admin\AppData\Local\Temp\implement-spec-v3-baseline-20261103-144424-069` contains the complete `implement-spec-v3`, `tdd`, and `test-review` directories. `baseline-sha256.json` records every copied file, including pre-existing bytecode. Final benchmarking makes frozen source-only execution copies of both arms, excluding pre-existing `__pycache__` and `.pyc` files, then uses `-B` and `PYTHONDONTWRITEBYTECODE=1` to prevent new caches. (`-B` alone does not prevent reading old caches.) Per-arm source hashes are embedded in the result. Historical validation artifacts elsewhere in the repository are unchanged.

`baseline-source.zip` is the complete retained baseline plus its manifest, so reproduction does not depend on the original temporary directory surviving.

The measured candidate is source-frozen at `C:\Users\admin\AppData\Local\Temp\implement-spec-v3-candidate-9fgw2e6t`, also retained as [candidate-source.zip](candidate-source.zip) with [candidate-sha256.json](candidate-sha256.json). Runtime `cycle.py` SHA-256 is `ad858e5bc5dd9458fc93ecd2865ae36004ddcba06e657c1fc131cfcd98d317b5`; independent 43-case test SHA-256 is `5b726580139693d62bd0ee2021473a2e14e0e30d6d19d42dbeb6ea0e294c22f1`; public contract revision 1 is `b6ede11f51d5c3a0f509d97e9026a0caadcb2900fb8cc14d10c223c5d2a48d0b`. The candidate manifest's initial metadata hash was corrected from a pre-write LF string digest to the actual CRLF file-byte digest; the source/archive pins never changed. [Correction record](candidate-freeze-metadata-correction.json).

All raw paired commands, receipts, logs, state, and source copies remain at `C:\Users\admin\AppData\Local\Temp\v3-matched-bench-4vsj5gll`. Final profile roots are recorded in their JSON results. Prior diagnostic runs remain separate and were not substituted into matched results.

## Measurement contract

`benchmark.py` exercises the actual public Python CLI and process-containment runner. Every fresh trial creates a disposable Git workspace and performs one newly authored behavior example at a time: target-specific failing assertion, recorded and judged Red, product edit, passing cumulative regressions, and close. It then commits a clean candidate, supplies explicitly mechanical qualification fixtures, runs full formal acceptance, records its real receipt, finishes, and verifies the ledger. It checks target assertion identity, the exact number of executed tests, actual exit status, stable snapshots, complete cleanup, final clean HEAD, absence of pending attempts, resolved Red history, and expected attempt count. A failed command aborts the run rather than becoming a fast sample.

Two fixed workloads are used:

- `small`: two serial behavior examples, negligible target log volume; the second behavior has a real wrong implementation, a failed Green, explicit judgment/diagnosis, and a corrected Green. After both closes, an actual test-owned shared-data refactor adds a declared dependency, invalidates prior qualification, and is refreshed by new qualification plus final formal acceptance.
- `history_logs`: twelve serial behavior examples, 32 KiB of deterministic trace output per test, cumulative regression execution, and growing ledger/snapshot history. This is a deliberately synthetic scaling case, not a claim about typical projects.

There are no artificial sleeps, simulated model delays, or conversions from event counts to latency. Fresh directories and actual target execution avoid stale acceptance/cache reuse. The same generated requirements, tests, successive product versions, command budgets, and final checks run on both arms. Test creation and product edits are deterministic fixture operations; they do **not** measure authoring/reasoning time.

Baseline executes separate prepare → owned runner → record commands. Candidate uses the new `execute` helper for exactly that mechanical sequence, preserving the original prepare/record IDs. Judgment, diagnosis, close, qualification, and delivery remain explicit. No future semantic decision is prewritten to force a batch opportunity. Paired trials must match their entire ordered `(op_id, op)` sequence, all actual execution outcomes and test/contract/product snapshot hashes, and final source-file hashes; the harness rejects a comparison that does different work.

The final matched comparison uses one excluded warmup per arm and scenario, then six pairs in alternating baseline→candidate / candidate→baseline order. Wall-clock time encloses fixture setup, Git, ledger commands, target executions, final acceptance, and verification; subprocess phase durations are separately retained. The identical test command on both arms emits an actual monotonic measurement of its unittest import/discovery/execution body. `target_body_seconds` excludes interpreter startup; `receipt_managed_seconds` includes runner preflight, snapshots, owned execution, and cleanup. Neither is mislabeled as model/agent time. `outer_process_invocations` counts the harness's actual launches only, not all descendants. `commands.jsonl`, every request/receipt/log, and each trial result remain in the named temporary trial root. Timing output includes run count, min/max, mean, standard deviation, median, and paired differences. Separate profiled runs identify the limiting paths; their overhead is excluded from matched timing.

Earlier `baseline-diagnostic-small.json` and `baseline-diagnostic-history.json` files are exploratory runs before the final shared-helper/repair fixture was established. They are retained as diagnostics and excluded from matched results. `baseline-diagnostic-repair-refresh.json` checks the added repair/refactor behavior, and `baseline-diagnostic-final.json` additionally checks actual target timing markers against the baseline. A single diagnostic duration is not a performance comparison.

## Scope and limits

The qualification/code-review payloads in this CLI benchmark are clearly marked fixture inputs. They exercise mechanical gates and make no claim to be actual independent test or code reviews. Real multi-agent workflow validation, including isolation, main-agent dispatch-only behavior, role reuse, and both review axes, is separate evidence owned by the coordinating validation track. CLI latency does not establish model-agent workflow latency or savings from fewer agent handoffs.

Applied `principle-explain-the-number`, `principle-build-the-lever`, and `principle-prove-it-works`. The number principle references `../benchmark-checklist/SKILL.md`, but that file is absent from both the repository and installed local skills, and a broader `.codex` filename search found no copy. No unavailable instructions were invented. The equivalent explicit measurement procedure above is used, with run count/spread/limiter and checks for skipped work, errors, caching, noise, and workload relevance.

## Reproduction

Use Python 3.12+ and Git on native Windows, with independently preserved baseline and candidate skill directories:

```powershell
python -B .\docs\validation\implement-spec-v3-performance-20261103\benchmark.py --baseline <baseline-skill-directory> --candidate <candidate-skill-directory> --pairs 6 --output <new-results.json>
```

Diagnostic/profile runs are separate from comparisons:

```powershell
python -B .\docs\validation\implement-spec-v3-performance-20261103\benchmark.py --baseline <skill-directory> --single history_logs --profile --output <profile-result.json>
```

Retained evidence includes an aborted first profile harness attempt: standard-library `python -m cProfile` returned zero even though the profiled CLI's receipt reported target exit one. `profile_cli.py` now preserves `SystemExit` while dumping stats. This diagnostic failure is excluded from all timings; it was a harness issue and did not change product/runtime behavior.
