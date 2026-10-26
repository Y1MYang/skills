"""Exercise approved checkpoint plans through the public CLI in disposable repos."""

import copy
import json
from pathlib import Path
import subprocess
import time
import unittest

import test_execution_resources as execution
import test_execution_supervisor as supervisor


class AcceptancePlanTests(unittest.TestCase):
    setUp = execution.ExecutionResourceTests.setUp
    tearDown = execution.ExecutionResourceTests.tearDown
    git = execution.ExecutionResourceTests.git
    command = execution.ExecutionResourceTests.command
    cli = execution.ExecutionResourceTests.cli
    tree = execution.ExecutionResourceTests.tree
    data = execution.ExecutionResourceTests.data
    cleanup_invocation = execution.ExecutionResourceTests.cleanup_invocation
    publish_pr = execution.ExecutionResourceTests.publish_pr
    configure_adapter = execution.ExecutionResourceTests.configure_adapter
    argv = execution.ExecutionResourceTests.argv
    gate = execution.ExecutionResourceTests.gate
    record_acceptance = execution.ExecutionResourceTests.record_acceptance
    scope_file = execution.ExecutionResourceTests.scope_file
    seal_delivery = execution.ExecutionResourceTests.seal_delivery
    handoff_acceptance = execution.ExecutionResourceTests.handoff_acceptance
    scenario = execution.ExecutionResourceTests.scenario
    classify = execution.ExecutionResourceTests.classify
    FULL_SCOPE = execution.ExecutionResourceTests.FULL_SCOPE

    def prepare(self, *, delivery=False):
        if delivery:
            self.cleanup_invocation()
            self.cwd_resource, self.cwd = "pr", self.publish_pr()
        else:
            self.cwd_resource, self.cwd = "ticket", self.tree()
        self.data()
        self.configure_adapter()

    def plan(self):
        return {"version": 1, "approval": "fixture/architecture-approved-execution-plan",
            "max_parallel_checkpoints": 1, "max_checkpoint_attempts": 8,
            "checkpoints": [
                {"key": "contract-a", "acceptance": self.FULL_SCOPE[:1], "depends_on": [],
                 "repair_limit": 2, "max_attempts": 4, "max_total_seconds": 12},
                {"key": "contract-b", "acceptance": self.FULL_SCOPE[1:], "depends_on": [],
                 "repair_limit": 2, "max_attempts": 4, "max_total_seconds": 12}],
            "final": {"key": "final-suite", "acceptance": self.FULL_SCOPE}}

    def register(self, plan=None, *, amendment=None, ok=True):
        path = self.root / "plan.json"
        path.write_text(json.dumps(plan if plan is not None else self.plan()))
        args = ["--plan", path]
        if amendment is not None:
            args += ["--amendment-evidence", amendment]
        return self.cli("register-plan", *args, ok=ok)

    def inputs(self, *, contract="fixture/approved-public-contract-v1", implementation=None,
               tests=None):
        revision = self.git("rev-parse", "HEAD", cwd=self.cwd)
        path = self.root / "checkpoint-inputs.json"
        path.write_text(json.dumps({"implementation": implementation or revision,
            "tests": tests or revision, "contract": contract}))
        return path

    def run_arguments(self, name, *, gate, key="contract-a", inputs=True,
                      recheck=None, evidence="fixture/approved-dependent-input-change",
                      cwd_resource=None, output_resource=None, **repair):
        args = execution.ExecutionResourceTests.formal_arguments(
            self, name, gate=gate, key=key, **repair)
        if cwd_resource is not None:
            args[args.index("--cwd-resource") + 1] = cwd_resource
        if output_resource is not None:
            args[args.index("--output-resource") + 1] = output_resource
        if inputs and key != "final-suite":
            path = self.inputs() if inputs is True else inputs
            args += ["--checkpoint-inputs", path]
        if recheck is not None:
            args += ["--recheck-after", recheck, "--recheck-evidence", evidence]
        return args

    def run_formal(self, name, *, gate, mode="complete", ok=True, **kwargs):
        result = self.cli("run", *self.run_arguments(name, gate=gate, **kwargs),
                          "--", *self.argv(mode), ok=ok)
        return json.loads(result.stderr if result.returncode == 2 else result.stdout)

    def ledger(self):
        return json.loads((self.state / "state.json").read_text())

    def assert_not_launched(self, name, response):
        self.assertIn("error", response)
        self.assertNotIn(name, self.ledger()["runs"])

    def commit_change(self, text="changed candidate\n"):
        (self.cwd / "source.txt").write_text(text)
        self.git("add", "source.txt", cwd=self.cwd)
        self.git("commit", "-m", "candidate input changed", cwd=self.cwd)

    def record_failure(self, name):
        summary = self.root / (name + "-failed-summary.json")
        summary.write_text(json.dumps({"tests": {"passed": 0, "failed": 1, "errors": 0,
            "skipped": 0, "total": 1}, "acceptance": self.FULL_SCOPE[:1],
            "reproduce": "fixture/recorded-scenario-command-and-candidate"}))
        self.cli("record-test", "--run", name, "--summary", summary)

    def test_plan_validation_is_atomic_and_registration_is_idempotent(self):
        valid = self.plan()
        invalid = []
        for field, value in (("max_parallel_checkpoints", 0),
                             ("max_checkpoint_attempts", -1), ("version", 99)):
            plan = copy.deepcopy(valid)
            plan[field] = value
            invalid.append(plan)
        for field, value in (("max_attempts", 0), ("max_total_seconds", float("inf")),
                             ("repair_limit", -1), ("acceptance", ["outside-approved-scope"]),
                             ("depends_on", ["unknown-key"])):
            plan = copy.deepcopy(valid)
            plan["checkpoints"][0][field] = value
            invalid.append(plan)
        duplicate = copy.deepcopy(valid)
        duplicate["checkpoints"][1]["key"] = "contract-a"
        invalid.append(duplicate)
        cycle = copy.deepcopy(valid)
        cycle["checkpoints"][0]["depends_on"] = ["contract-b"]
        cycle["checkpoints"][1]["depends_on"] = ["contract-a"]
        invalid.append(cycle)
        collision = copy.deepcopy(valid)
        collision["final"]["key"] = "contract-a"
        invalid.append(collision)
        missing_final = copy.deepcopy(valid)
        del missing_final["final"]
        invalid.append(missing_final)
        before = self.ledger()
        for number, plan in enumerate(invalid):
            with self.subTest(invalid_plan=number):
                self.register(plan, ok=False)
                self.assertEqual(self.ledger(), before, "a rejected plan partially changed the ledger")
        self.register(valid)
        registered = self.ledger()
        self.register(valid)
        self.assertEqual(self.ledger(), registered)
        expanded = copy.deepcopy(valid)
        expanded["checkpoints"][0]["max_attempts"] += 1
        self.register(expanded, ok=False)
        self.assertEqual(self.ledger(), registered, "re-registration reset or expanded approved limits")

    def test_admission_requires_registered_keys_fixed_inputs_and_repair_limit(self):
        self.prepare()
        receipt = self.gate("complete")
        self.assert_not_launched("before-plan", self.run_formal("before-plan", gate=receipt, ok=False))
        self.register()
        for name, kwargs in (("renamed-checkpoint", {"key": "contract-a-batch-2"}),
                             ("missing-inputs", {"inputs": False}),
                             ("expanded-repair", {"repair_limit": 3})):
            with self.subTest(name=name):
                self.assert_not_launched(name, self.run_formal(name, gate=receipt, ok=False, **kwargs))
        unrelated = self.git("commit-tree", "HEAD^{tree}", "-m", "unrelated root", cwd=self.cwd)
        bad_inputs = self.inputs(tests=unrelated)
        self.assert_not_launched("wrong-candidate", self.run_formal(
            "wrong-candidate", gate=receipt, inputs=bad_inputs, ok=False))
        valid = self.run_formal("pinned-candidate", gate=receipt)
        self.assertTrue(valid["acceptance_qualified"])

    def test_summary_scope_cannot_understate_or_expand_the_approved_checkpoint(self):
        self.prepare()
        plan = self.plan()
        plan["checkpoints"][0]["acceptance"] = self.FULL_SCOPE
        self.register(plan)
        self.run_formal("scope-run", gate=self.gate("complete"))
        path = self.root / "summary.json"
        for pointers in (self.FULL_SCOPE[:1], [*self.FULL_SCOPE, "unapproved-extra"]):
            with self.subTest(pointers=pointers):
                path.write_text(json.dumps({"tests": {"passed": 1, "failed": 0,
                    "errors": 0, "skipped": 0, "total": 1}, "acceptance": pointers,
                    "reproduce": "fixture/recorded-command-and-revision"}))
                self.cli("record-test", "--run", "scope-run", "--summary", path, ok=False)
        self.record_acceptance("scope-run", self.FULL_SCOPE)

    def test_recheck_requires_a_recorded_pass_and_changed_inputs_without_fake_repairs(self):
        self.prepare()
        self.register()
        receipt = self.gate("complete")
        initial = self.run_formal("initial", gate=receipt)
        original = Path(initial["record"]).read_bytes()
        self.commit_change()
        self.assert_not_launched("unrecorded", self.run_formal(
            "unrecorded", gate=receipt, recheck="initial", ok=False))
        self.record_acceptance("initial", self.FULL_SCOPE[:1])
        self.assert_not_launched("missing-change-evidence", self.run_formal(
            "missing-change-evidence", gate=receipt, recheck="initial", evidence="", ok=False))
        self.assert_not_launched("recheck-as-repair", self.run_formal(
            "recheck-as-repair", gate=receipt, recheck="initial", validate_after="initial",
            repair_round=1, repair_evidence="fixture/unrelated-repair-path", ok=False))
        self.cli("handoff", "--resource", "ticket", "--owner", "replacement-checkpoint-runner")
        changed = self.run_formal("changed", gate=receipt, recheck="initial")
        self.assertTrue(changed["acceptance_qualified"])
        self.record_acceptance("changed", self.FULL_SCOPE[:1])
        self.assert_not_launched("unchanged", self.run_formal(
            "unchanged", gate=receipt, recheck="changed", ok=False))
        changed_contract = self.inputs(contract="fixture/approved-public-contract-v2")
        latest = self.run_formal("contract-change", gate=receipt, recheck="changed", inputs=changed_contract)
        self.assertTrue(latest["acceptance_qualified"])
        self.record_acceptance("contract-change", self.FULL_SCOPE[:1])
        newest_contract = self.inputs(contract="fixture/approved-public-contract-v3")
        self.assert_not_launched("stale-predecessor", self.run_formal(
            "stale-predecessor", gate=receipt, recheck="initial", inputs=newest_contract, ok=False))
        chain = self.ledger()["execution_chains"]["contract-a"]
        self.assertEqual(chain["attempts"], ["initial", "changed", "contract-change"])
        self.assertEqual(chain["repair_rounds"], 0)
        self.assertEqual(chain["verifications"], 0)
        self.assertFalse(chain["recovery_used"])
        self.assertEqual(Path(initial["record"]).read_bytes(), original)

    def test_recheck_cannot_bypass_failed_or_unresolved_history(self):
        self.prepare()
        self.register()
        self.scenario(fail=["case-a"])
        receipt = self.gate("scenario")
        self.run_formal("failed", gate=receipt, mode="scenario", ok=False)
        self.record_failure("failed")
        self.classify("failed", "fixture/business-assertion-failed")
        self.scenario(pass_cases=["case-a"])
        self.assert_not_launched("failure-as-recheck", self.run_formal(
            "failure-as-recheck", gate=receipt, mode="scenario", recheck="failed", ok=False))
        repaired = self.run_formal("repair", gate=receipt, mode="scenario", validate_after="failed",
                                  repair_round=1, repair_evidence="fixture/authorized-business-repair")
        self.assertTrue(repaired["acceptance_qualified"])
        self.record_acceptance("repair", self.FULL_SCOPE[:1])
        self.commit_change()
        self.assert_not_launched("unresolved-history", self.run_formal(
            "unresolved-history", gate=receipt, mode="scenario", recheck="repair", ok=False))
        self.cli("resolve", "--run", "failed", "--reason", "The business assertion was repaired",
                 "--validation", "fixture/repair-qualified-run")
        self.assertTrue(self.run_formal("resolved-recheck", gate=receipt, mode="scenario",
                                      recheck="repair")["acceptance_qualified"])
        chain = self.ledger()["execution_chains"]["contract-a"]
        self.assertEqual(chain["attempts"], ["failed", "repair", "resolved-recheck"])
        self.assertEqual(chain["repair_rounds"], 1)

    def test_dependencies_require_latest_recorded_pass_and_resolved_history(self):
        self.prepare()
        plan = self.plan()
        plan["checkpoints"][1]["depends_on"] = ["contract-a"]
        self.register(plan)
        self.scenario(pass_cases=["case-a"])
        receipt = self.gate("scenario")
        self.assert_not_launched("missing-prerequisite", self.run_formal(
            "missing-prerequisite", gate=receipt, mode="scenario", key="contract-b", ok=False))
        self.run_formal("initial-a", gate=receipt, mode="scenario")
        self.assert_not_launched("unrecorded-prerequisite", self.run_formal(
            "unrecorded-prerequisite", gate=receipt, mode="scenario", key="contract-b", ok=False))
        self.record_acceptance("initial-a", self.FULL_SCOPE[:1])
        self.scenario(fail=["case-a"])
        self.run_formal("failed-a", gate=receipt, mode="scenario", recheck="initial-a", ok=False)
        self.record_failure("failed-a")
        self.classify("failed-a", "fixture/changed-contract-exposes-business-failure")
        self.assert_not_launched("failed-prerequisite", self.run_formal(
            "failed-prerequisite", gate=receipt, mode="scenario", key="contract-b", ok=False))
        self.scenario(pass_cases=["case-a"])
        self.run_formal("repaired-a", gate=receipt, mode="scenario", validate_after="failed-a",
                        repair_round=1, repair_evidence="fixture/authorized-contract-repair")
        self.record_acceptance("repaired-a", self.FULL_SCOPE[:1])
        self.assert_not_launched("unresolved-prerequisite", self.run_formal(
            "unresolved-prerequisite", gate=receipt, mode="scenario", key="contract-b", ok=False))
        self.cli("resolve", "--run", "failed-a", "--reason", "Contract regression repaired",
                 "--validation", "fixture/repaired-a-qualified-run")
        dependent = self.run_formal("qualified-dependent", gate=receipt, mode="scenario", key="contract-b")
        self.assertTrue(dependent["acceptance_qualified"])

    def test_per_checkpoint_and_global_attempt_limits_survive_rechecks_and_owners(self):
        self.prepare()
        plan = self.plan()
        plan["checkpoints"][0]["max_attempts"] = 1
        plan["max_checkpoint_attempts"] = 2
        self.register(plan)
        receipt = self.gate("complete")
        self.run_formal("first", gate=receipt)
        self.record_acceptance("first", self.FULL_SCOPE[:1])
        self.commit_change()
        self.cli("handoff", "--resource", "ticket", "--owner", "another-runner")
        self.assert_not_launched("extra-a", self.run_formal(
            "extra-a", gate=receipt, recheck="first", ok=False))
        self.run_formal("second-key", gate=receipt, key="contract-b")
        self.record_acceptance("second-key", self.FULL_SCOPE[1:])
        self.commit_change("another change\n")
        self.assert_not_launched("extra-global", self.run_formal(
            "extra-global", gate=receipt, key="contract-b", recheck="second-key", ok=False))
        self.assertTrue(self.run_formal("final-unrestricted", gate=receipt,
                                      key="final-suite")["acceptance_qualified"])

    def test_time_budget_charges_declared_attempt_horizons_without_refunds(self):
        self.prepare()
        plan = self.plan()
        total = json.loads(self.contract.read_text())["budgets"]["total"]["seconds"]
        plan["checkpoints"][0]["max_total_seconds"] = total * 1.5
        self.register(plan)
        receipt = self.gate("complete")
        self.run_formal("quick-pass", gate=receipt)
        self.record_acceptance("quick-pass", self.FULL_SCOPE[:1])
        self.commit_change()
        self.assert_not_launched("no-time-refund", self.run_formal(
            "no-time-refund", gate=receipt, recheck="quick-pass", ok=False))
        self.assertEqual(self.ledger()["execution_chains"]["contract-a"]["attempts"], ["quick-pass"])

    def test_append_only_plan_amendment_keeps_original_limits_and_spending(self):
        self.prepare()
        base = self.plan()
        base["max_checkpoint_attempts"] = 2
        base["checkpoints"][0]["max_attempts"] = 1
        new_checkpoint = base["checkpoints"].pop()
        self.register(base)
        receipt = self.gate("complete")
        self.run_formal("before-amendment", gate=receipt)
        self.record_acceptance("before-amendment", self.FULL_SCOPE[:1])
        original = self.ledger()
        amended = copy.deepcopy(base)
        amended["checkpoints"].append(new_checkpoint)
        self.register(amended, ok=False)
        changed_budget = copy.deepcopy(amended)
        changed_budget["checkpoints"][0]["max_attempts"] += 1
        changed_global = copy.deepcopy(amended)
        changed_global["max_checkpoint_attempts"] += 1
        changed_final = copy.deepcopy(amended)
        changed_final["final"]["acceptance"].append("unapproved-final-criterion")
        removed_key = copy.deepcopy(amended)
        removed_key["checkpoints"].pop(0)
        overlapping = copy.deepcopy(amended)
        overlapping["checkpoints"][1]["acceptance"] = self.FULL_SCOPE[:1]
        for bad in (changed_budget, changed_global, changed_final, removed_key, overlapping):
            self.register(bad, amendment="fixture/architecture-approved-addition", ok=False)
            self.assertEqual(self.ledger(), original)
        self.register(amended, amendment="fixture/architecture-approved-addition")
        self.assertEqual(self.ledger()["execution_chains"], original["execution_chains"])
        registered = self.ledger()
        self.register(amended, amendment="fixture/architecture-approved-addition")
        self.assertEqual(self.ledger(), registered)
        self.commit_change()
        self.assert_not_launched("old-budget-reset", self.run_formal(
            "old-budget-reset", gate=receipt, recheck="before-amendment", ok=False))
        self.run_formal("new-checkpoint", gate=receipt, key="contract-b")
        self.record_acceptance("new-checkpoint", self.FULL_SCOPE[1:])
        self.commit_change("post-amendment candidate\n")
        self.assert_not_launched("global-budget-reset", self.run_formal(
            "global-budget-reset", gate=receipt, key="contract-b", recheck="new-checkpoint", ok=False))

    def test_concurrency_budget_is_shared_across_checkpoint_keys(self):
        self.prepare()
        held = '''if mode == "held":
    begin()
    fixture_root = Path(__file__).resolve().parent
    (fixture_root / "action-ready").write_text("ready")
    index = 0
    while not (fixture_root / "finish-action").exists():
        emit("progress", case_id="case-a", progress_kind="assertion", evidence="wait-" + str(index))
        index += 1
        time.sleep(.02)
    end()
elif mode == "missing":'''
        self.adapter.write_text(supervisor.ADAPTER.replace('if mode == "missing":', held))
        contract = json.loads(self.contract.read_text())
        contract["budgets"]["total"] = supervisor.budget(4, "fixture: 3s controlled action plus existing 1s shutdown")
        contract["budgets"]["case"] = supervisor.budget(2, "fixture: bounded CLI admission while callback remains live")
        contract["budgets"]["phase"] = {name: supervisor.budget(2.5) for name in ("setup", "run", "cleanup")}
        self.contract.write_text(json.dumps(contract))
        self.register()
        receipt = self.gate("held")
        other_cwd = self.tree("other-checkpoint")
        self.data("other-output")
        original_cwd = self.cwd
        try:
            self.cwd = other_cwd
            other_receipt = self.gate("held")
        finally:
            self.cwd = original_cwd
        command = self.command("run", "--state", self.state,
                               *self.run_arguments("active-a", gate=receipt), "--", *self.argv("held"))
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 3
            while not (self.root / "action-ready").exists() and time.monotonic() < deadline:
                self.assertIsNone(process.poll(), "fixture exited before starting its held callback")
                time.sleep(.01)
            self.assertTrue((self.root / "action-ready").exists())
            self.assert_not_launched("concurrent-b", self.run_formal(
                "concurrent-b", gate=other_receipt, key="contract-b", mode="held",
                cwd_resource="other-checkpoint", output_resource="other-output", ok=False))
        finally:
            (self.root / "finish-action").write_text("finish")
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()  # Only this disposable test's CLI wrapper.
                process.communicate(timeout=1)
                self.fail("fixture did not finish within its declared horizon")
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertTrue(self.run_formal("after-a", gate=other_receipt, key="contract-b", mode="held",
                                      cwd_resource="other-checkpoint", output_resource="other-output")
                        ["acceptance_qualified"])

    def test_full_scope_checkpoint_cannot_be_selected_as_final_delivery(self):
        self.prepare(delivery=True)
        plan = self.plan()
        plan["checkpoints"][0]["acceptance"] = self.FULL_SCOPE
        self.register(plan)
        receipt = self.gate("complete")
        self.run_formal("complete-checkpoint", gate=receipt)
        self.record_acceptance("complete-checkpoint", self.FULL_SCOPE)
        self.seal_delivery("complete-checkpoint")
        self.assertEqual(self.handoff_acceptance()["status"], "unverified")

    def test_designated_final_key_can_verify_the_full_delivered_scope(self):
        self.prepare(delivery=True)
        self.register()
        self.run_formal("complete-final", gate=self.gate("complete"), key="final-suite")
        self.record_acceptance("complete-final", self.FULL_SCOPE)
        self.pr["draft"] = False
        self.pr_json.write_text(json.dumps(self.pr))
        self.seal_delivery("complete-final")
        self.assertEqual(self.handoff_acceptance()["status"], "verified")

    def test_legacy_upgrade_preserves_real_history_and_consumed_checkpoint_budget(self):
        self.prepare()
        # Historical persisted ledgers predate the new protocol field. Only the
        # format marker is absent; every attempt below comes from the real CLI.
        ledger = self.ledger()
        ledger.pop("acceptance_plan_protocol")
        (self.state / "state.json").write_text(json.dumps(ledger))
        receipt = self.gate("complete")
        initial = self.run_formal("legacy-first", gate=receipt, inputs=False, repair_limit=2)
        self.record_acceptance("legacy-first", self.FULL_SCOPE[:1])
        self.commit_change()
        self.run_formal("legacy-repair", gate=receipt, inputs=False, repair_limit=2,
                        validate_after="legacy-first", repair_round=1,
                        repair_evidence="fixture/legacy-reviewed-repair")
        self.record_acceptance("legacy-repair", self.FULL_SCOPE[:1])
        before = self.ledger()
        terminal = Path(initial["record"]).read_bytes()
        invalid = []
        too_few = self.plan()
        too_few["checkpoints"][0]["max_attempts"] = 1
        invalid.append(too_few)
        too_short = self.plan()
        total = json.loads(self.contract.read_text())["budgets"]["total"]["seconds"]
        too_short["checkpoints"][0]["max_total_seconds"] = total * 1.5
        invalid.append(too_short)
        wrong_repair_limit = self.plan()
        wrong_repair_limit["checkpoints"][0]["repair_limit"] = 1
        invalid.append(wrong_repair_limit)
        missing_key = self.plan()
        missing_key["checkpoints"].pop(0)
        invalid.append(missing_key)
        for plan in invalid:
            self.register(plan, ok=False)
            self.assertEqual(self.ledger(), before)
        valid = self.plan()
        valid["checkpoints"][0]["max_attempts"] = 3
        self.register(valid)
        after_chain = self.ledger()["execution_chains"]["contract-a"]
        for field, value in before["execution_chains"]["contract-a"].items():
            self.assertEqual(after_chain[field], value, "upgrading a plan rewrote " + field)
        self.assertEqual(self.ledger()["runs"], before["runs"])
        self.assertEqual(Path(initial["record"]).read_bytes(), terminal)
        self.commit_change("post-upgrade change\n")
        continued = self.run_formal("migrated-recheck", gate=receipt, recheck="legacy-repair")
        self.assertTrue(continued["acceptance_qualified"])
        self.record_acceptance("migrated-recheck", self.FULL_SCOPE[:1])
        self.commit_change("fourth candidate\n")
        self.assert_not_launched("fresh-budget-attempt", self.run_formal(
            "fresh-budget-attempt", gate=receipt, recheck="migrated-recheck", ok=False))
        self.assertEqual(self.ledger()["execution_chains"]["contract-a"]["attempts"],
                         ["legacy-first", "legacy-repair", "migrated-recheck"])


if __name__ == "__main__":
    unittest.main()
