# Candidate optimized execution handoff

Exploration applied explain-the-number, sequence-verifiable-units, and prove-it-works. Initial clean baseline is 874982f1f83cfb1f38bf673416920be5bbf4d993. Only scaffold and existing currency regression exist; no new tests or implementation authored. Python 3.12.10 and Git available. Authoritative project: C:/Users/admin/AppData/Local/Temp/v3-perf-candidate-20261103-qhq_ie8t.

## Authorities and context reuse

All ten explicitly selected roles use actual gpt-6.1-sol dispatch. Architect next confirms proposed-plan.json and writes separate architect-test-safe-package; its report must NEVER enter a blind context. Main remains dispatch-only. A persistent compatible nonblind flow owner may combine Implementer, Runner and Integrator because all selected models match; brief must explicitly grant each role, keep Runner interpretation distinct from Integrator state operations, and own the sole project/state writes during its phase. Exploration and Architect may reuse compatible nonblind context, but not as independent reviewers. Blind Test author has its own fresh fork_turns=none context, may persist for the three serial examples, and writes tests only. Coordinator can route ready-next-example handoffs directly without main-agent round trips. Never send implementation-bearing replies to the blind author.

Coverage audit and both full test-review axes start fresh fork_turns=none with ONLY architect-test-safe-package and explicitly allowed pinned test files/dependencies; no architect report, production contents/diffs, or implementation-bearing messages. Coverage audit dispatches Spec and Standards axes in parallel with actual selected models. Fresh implementation-visible Spec/Standards code-review instances are distinct from test reviewers; parallel with formal acceptance on frozen committed HEAD. Expert only on a concrete blocker; no mandatory gratuitous call.

## Plan and budgets

One flow, no checkpoint consumers or critical cross-module contracts. Three examples exactly: threshold (10000 => 0), below (9999 => 500), negative (-1 raises ValueError), edges threshold -> below -> negative. Every example snapshots tests directory, README.md contract and shipping.py product in same authoritative workspace. Currency regression is mandatory in all Green and final runs. No external dependencies, fixtures, helpers, configuration or type validation. No new tests until their serial turn. Planned 7 normal execution attempts: three probes, three combined Green/regressions, one formal full run. Run ceiling 20 attempts / 600 command seconds / 3 formal failures; estimate tiny pure unittest commands at <=30 seconds each including Git/snapshot preflight, with recovery margin. Each command 30 seconds; runner progress is best-effort one-second publication; teardown <=5 additional seconds. Local diagnostics allocated only on concrete issues, renewable per frozen diagnostic-budgets reference. Existing initial currency sanity run is preparation evidence, not a runtime acceptance attempt. Tests use python -B to prevent snapshot cache pollution.

## Exact CLI protocol

Use frozen script C:/Users/admin/AppData/Local/Temp/implement-spec-v3-candidate-9fgw2e6t/implement-spec-v3/scripts/cycle.py. Keep all plan/events/requests/receipts/logs/state outside project, under candidate evidence. Integrator first confirms architect plan then runs:

```powershell
python C:/Users/admin/AppData/Local/Temp/implement-spec-v3-candidate-9fgw2e6t/implement-spec-v3/scripts/cycle.py --state E:/Repos/skills/docs/validation/implement-spec-v3-performance-20261103/agent-eval/candidate/state init --plan E:/Repos/skills/docs/validation/implement-spec-v3-performance-20261103/agent-eval/candidate/plan.json
```

For each example blind author writes one current test and lightweight oracle record; Integrator persists open. Runner prescribes target probe argv (python, -B, -m, unittest, discover, -s, tests, -v is valid full current scope) and expected specific target assertion/error. Execute request contains schema=1, prepare={schema:1,op_id:<unique>,op:prepare,example:<id>,purpose:probe,timeout_seconds:30}, record_op_id=<different unique>, argv=<exact list>. Run:

```powershell
python C:/Users/admin/AppData/Local/Temp/implement-spec-v3-candidate-9fgw2e6t/implement-spec-v3/scripts/cycle.py --state E:/Repos/skills/docs/validation/implement-spec-v3-performance-20261103/agent-eval/candidate/state execute --request E:/Repos/skills/docs/validation/implement-spec-v3-performance-20261103/agent-eval/candidate/requests/threshold-probe.json
```

Runner inspects real logs/receipt, classifies target-specific actual Red; Integrator persists judge(valid-red) before implementation. Implementer makes only current minimal change. Green execute uses purpose=green, same test/contract versions, and full unittest discovery argv. Passing Green covers current example plus all existing currency/previous example regressions: close uses its same attempt_id and explicit regression_scope; do not rerun solely for a second label. Author next test only after current close. One compatible owner can execute all mechanical events without new spawn per transition.

Use batch --events <absolute events JSON> only for already-supported events, e.g. passing Green close and any independent metadata decisions, or final qualify after both review reports. Never batch an anticipated judge or close before real command and semantic review. Each JSON event has schema=1, unique op_id, op and required fields. Execute intentionally combines prepare/run/record and preserves original events, not semantic judgment.

After three cycles, complete blind full test-review then qualify(scope={final:true}) with real pinned axis reports. Commit and freeze clean whole-spec candidate. Formal request uses prepare-formal scope={final:true}, timeout_seconds=30, exact complete argv above. Run execute --request <formal request>. Concurrent fresh code review axes compare initial baseline directly to exact frozen HEAD. Complete finish only with formal attempt_id and both review IDs/head/pass bound to that identical HEAD. End with inspect and verify, clean Git check and local handoff; no PR/remote requested or authorized here. Retain delivery repo/commits and compact evidence; release idle temporary execution resources after checking identities.

## Evidence and measurements

candidate-events.jsonl begins with observed spawn=1/followup=0 at Exploration dispatch, timestamp 2026-11-03 08:18:40 UTC (second resolution). Integrator owns later append-only recording from coordinator-provided observed tool counts. Count actual spawn_agent role creation, followup_task reactivation/instruction, send_message separately, wait_agent separately. Do not infer counts from role names or historical text. First-dispatch preclock supplied by coordinator, not fabricated subsecond timing. One candidate trial establishes this run only, not statistical speedup. Preserve command timing and dispatch count definitions with reported duration; verify every required work unit really ran.
