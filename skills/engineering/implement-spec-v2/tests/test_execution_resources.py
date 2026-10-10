"""Exercise formal acceptance and recovery through the real resource CLI."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

import test_execution_supervisor as fixtures
import test_resources as lifecycle


class ExecutionResourceTests(unittest.TestCase):
    setUp = lifecycle.ResourceLifecycleTests.setUp
    git = lifecycle.ResourceLifecycleTests.git
    command = lifecycle.ResourceLifecycleTests.command
    cli = lifecycle.ResourceLifecycleTests.cli
    tree = lifecycle.ResourceLifecycleTests.tree
    data = lifecycle.ResourceLifecycleTests.data
    record = lifecycle.ResourceLifecycleTests.record
    cleanup_invocation = lifecycle.ResourceLifecycleTests.cleanup_invocation
    publish_pr = lifecycle.ResourceLifecycleTests.publish_pr

    def tearDown(self):
        fixtures.retain_failed_terminal_evidence(self)

    FULL_SCOPE = ["fixture/full-suite/setup-action-cleanup", "fixture/full-suite/terminal-and-safety"]

    def prepare(self):
        self.cwd_resource = "ticket"
        self.cwd = self.tree()
        self.data()
        self.configure_adapter()

    def prepare_delivery(self):
        self.cleanup_invocation()
        self.cwd_resource = "pr"
        self.cwd = self.publish_pr()
        self.data()
        self.configure_adapter()

    def configure_adapter(self):
        self.adapter = self.root / "adapter.py"
        self.adapter.write_text(fixtures.ADAPTER)
        self.contract = self.root / "execution.json"
        contract = fixtures.contract_for(self.adapter)
        contract["budgets"]["shutdown"] = fixtures.budget(1.0,
            "fixture cold post-run gate/source proof measured 0.30696s; threefold metadata margin rounded to 1.0s")
        contract["budgets"]["total"] = fixtures.budget(1.85,
            "fixture preserves original 0.85s active horizon; adds 1.0s shutdown from 0.30696s cold proof with threefold metadata margin")
        self.contract.write_text(json.dumps(contract))

    def argv(self, mode):
        return [sys.executable, str(self.adapter), mode]

    def gate(self, mode):
        self.gate_number = getattr(self, "gate_number", 0) + 1
        receipt = self.root / (mode + "-" + str(self.gate_number) + "-gate.json")
        process = subprocess.run([sys.executable, str(fixtures.SUPERVISOR), "gate",
            "--contract", str(self.contract), "--cwd", str(self.cwd),
            "--output", str(receipt), "--", *self.argv(mode)],
            capture_output=True, text=True, timeout=20)
        if process.returncode != 0:
            # Teardown removes the disposable directory. Keep the public probe
            # results in the failure report so the first failure remains useful.
            evidence = Path(str(receipt) + ".evidence")
            terminals = []
            for path in evidence.rglob("*.terminal.json"):
                try:
                    result = json.loads(path.read_text())
                except (OSError, json.JSONDecodeError) as error:
                    terminals.append({"terminal": str(path), "read_error": str(error)})
                    continue
                terminals.append({"terminal": str(path), **{name: result.get(name) for name in
                    ("outcome", "elapsed_seconds", "stopped", "capture_complete", "capture_errors", "coverage_verified", "diagnostics")}})
            self.fail(process.stdout + process.stderr + "\nPublic gate terminal evidence:\n" + json.dumps(terminals))
        self.assertTrue(receipt.is_file())
        return receipt

    def formal_arguments(self, name, *, gate, retry=None, key="full-suite", repair_limit=None,
                         validate_after=None, repair_evidence=None, repair_round=None, contract_change_evidence=None):
        arguments = ["--id", name, "--cwd-resource", self.cwd_resource, "--output-resource", "output",
            "--test", "--acceptance", "--execution-contract", self.contract,
            "--execution-gate", gate, "--failure-key", key]
        if retry:
            arguments += ["--retry-of", retry, "--recovery-evidence",
                "fixture/isolation-and-reset: only disposable processes and no external mutations"]
        for flag, value in (("--repair-limit", repair_limit), ("--validate-after", validate_after),
                            ("--repair-evidence", repair_evidence), ("--repair-round", repair_round),
                            ("--contract-change-evidence", contract_change_evidence)):
            if value is not None:
                arguments += [flag, value]
        return arguments

    def formal(self, name, mode, *, gate, retry=None, ok=True, key="full-suite", repair_limit=None,
               validate_after=None, repair_evidence=None, repair_round=None, contract_change_evidence=None):
        arguments = self.formal_arguments(name, gate=gate, retry=retry, key=key, repair_limit=repair_limit,
            validate_after=validate_after, repair_evidence=repair_evidence, repair_round=repair_round,
            contract_change_evidence=contract_change_evidence)
        result = self.cli("run", *arguments, "--", *self.argv(mode), ok=ok)
        if result.returncode == 2:
            return json.loads(result.stderr)
        return json.loads(result.stdout)

    def formal_command(self, name, mode, *, gate):
        # Reserve before a deliberate lock conflict; the command under test
        # must be the actual formal-run entry point, not fixture setup.
        return self.command("run", "--state", self.state,
                            *self.formal_arguments(name, gate=gate), "--", *self.argv(mode))

    @contextmanager
    def hold_ledger_lock(self):
        ready, release = self.root / "lock-ready", self.root / "release-lock"
        ready.unlink(missing_ok=True)
        release.unlink(missing_ok=True)
        code = ("import fcntl,sys,time; from pathlib import Path; "
                "lock=open(sys.argv[1],'a'); fcntl.flock(lock,fcntl.LOCK_EX); "
                "Path(sys.argv[2]).write_text('locked'); "
                "\nwhile not Path(sys.argv[3]).exists(): time.sleep(.01)\n")
        process = subprocess.Popen([sys.executable, "-c", code, str(self.state / "lock"),
                                    str(ready), str(release)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < deadline:
                self.assertIsNone(process.poll(), "isolated lock holder failed")
                time.sleep(.01)
            self.assertTrue(ready.is_file(), "isolated lock holder did not acquire the ledger")
            yield
        finally:
            release.write_text("release")
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()  # The exact process was created by this test.
                process.wait(timeout=1)

    def communicate_before_safety_timeout(self, process, *, timeout=6):
        started = time.monotonic()
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()  # Only this isolated CLI wrapper is eligible.
            process.communicate(timeout=1)
            self.fail("formal CLI exceeded the independent outer safety timeout")
        self.assertLess(time.monotonic() - started, timeout)
        return stdout, stderr

    def record_acceptance(self, name, pointers):
        summary = self.root / (name + "-coverage.json")
        summary.write_text(json.dumps({"tests": {"passed": 1, "failed": 0, "errors": 0,
            "skipped": 0, "total": 1}, "acceptance": list(pointers),
            "reproduce": "Use the recorded acceptance adapter, revision and contract."}))
        self.cli("record-test", "--run", name, "--summary", summary)

    def scope_file(self):
        path = self.root / "approved-acceptance-scope.json"
        path.write_text(json.dumps({"acceptance": self.FULL_SCOPE,
            "source": "fixture/approved-complete-acceptance-contract-and-coverage-map"}))
        return path

    def seal_delivery(self, name, *, required_scope=None, ok=True):
        scope = required_scope or self.scope_file()
        return self.cli("seal", "--pr-json", self.pr_json, "--acceptance-run", name,
                        "--acceptance-scope", scope, ok=ok)

    def handoff_acceptance(self):
        return json.loads((self.state / "handoff.json").read_text())["acceptance"]

    def interrupted_summary(self, name):
        path = self.root / (name + "-summary.json")
        path.write_text(json.dumps({"tests": {"passed": 0, "failed": 0, "errors": 0,
            "skipped": 0, "total": 0}, "acceptance": ["fixture/full-suite"],
            "reproduce": "Use the recorded adapter, command and execution contract."}))
        self.cli("record-test", "--run", name, "--summary", path)

    def assess(self):
        return json.loads(self.cli("acceptance-status").stdout)

    def test_ordinary_test_records_cannot_qualify_and_formal_requires_gate(self):
        self.prepare()
        rejected = self.cli("run", "--id", "missing-gate", "--cwd-resource", "ticket",
            "--output-resource", "output", "--test", "--acceptance", "--",
            *self.argv("complete"), ok=False)
        self.assertIn("formal acceptance requires", rejected.stderr)
        self.assertNotIn("missing-gate", json.loads((self.state / "state.json").read_text())["runs"])
        self.cli("run", "--id", "ordinary", "--cwd-resource", "ticket", "--output-resource", "output",
            "--test", "--", sys.executable, "-c", "print('ordinary diagnostic test')")
        self.record("ordinary")
        self.assertEqual(self.assess()["status"], "unverified")
        self.assertEqual(self.assess()["qualified_runs"], [])

    def test_gate_is_bound_to_the_command_before_launch(self):
        self.prepare()
        receipt = self.gate("complete")
        result = self.formal("changed-command", "modal", gate=receipt, ok=False)
        self.assertIn("error", result)
        self.assertNotIn("changed-command", json.loads((self.state / "state.json").read_text())["runs"])

    def test_first_timeout_survives_retry_owner_change_and_later_passing(self):
        self.prepare()
        failed = self.formal("first", "modal", gate=self.gate("modal"), ok=False)
        self.assertEqual(failed["status"], "completed", failed)
        self.assertNotEqual(failed["exit_code"], 0)
        self.assertFalse(failed["acceptance_qualified"])
        first_record = Path(failed["record"])
        first_bytes = first_record.read_bytes()
        self.interrupted_summary("first")
        self.cli("classify-run", "--run", "first", "--classification", "unknown",
            "--evidence", "fixture/initial-checkpoint")
        passing_gate = self.gate("complete")
        refused = self.formal("before-classification", "complete", gate=passing_gate, retry="first", ok=False)
        self.assertIn("classify", refused["error"])
        self.cli("classify-run", "--run", "first", "--classification", "harness",
            "--evidence", "fixture/known-blocking-callback-and-stopped-processes")
        self.cli("handoff", "--resource", "ticket", "--owner", "replacement-agent")
        recovered = self.formal("replacement-run", "complete", gate=passing_gate, retry="first")
        self.assertTrue(recovered["acceptance_qualified"])
        self.record("replacement-run")
        assessment = self.assess()
        self.assertEqual(assessment["status"], "unverified")
        self.assertIn("first", [row["run"] for row in assessment["blockers"]])
        self.cli("resolve", "--run", "first", "--reason", "Fixed the disposable fixture", ok=False)
        self.cli("resolve", "--run", "first", "--reason", "Known fixture interruption handled",
            "--validation", "fixture/replacement-run-qualified-complete-scope")
        self.assertEqual(self.assess()["status"], "verified")
        again = self.formal("third-run", "complete", gate=passing_gate,
            retry="replacement-run", ok=False)
        self.assertIn("one automatic recovery", again["error"])
        renamed = self.formal("renamed-initial", "complete", gate=passing_gate, ok=False)
        self.assertIn("changing run IDs", renamed["error"])
        ledger = json.loads((self.state / "state.json").read_text())
        self.assertEqual(ledger["execution_chains"]["full-suite"]["attempts"], ["first", "replacement-run"])
        self.assertTrue(ledger["execution_chains"]["full-suite"]["recovery_used"])
        self.assertEqual(ledger["runs"]["first"]["classification_history"][0]["kind"], "unknown")
        self.assertEqual(first_record.read_bytes(), first_bytes, "first terminal evidence was overwritten")

    def test_unknown_classification_does_not_resolve_the_acceptance_blocker(self):
        self.prepare()
        self.formal("first", "modal", gate=self.gate("modal"), ok=False)
        self.interrupted_summary("first")
        self.cli("classify-run", "--run", "first", "--classification", "unknown", "--evidence", "checkpoint")
        refusal = self.cli("resolve", "--run", "first", "--reason", "Later run is green",
            "--validation", "unrelated-passing-run", ok=False)
        self.assertIn("classify", refusal.stderr)
        self.assertEqual(self.assess()["status"], "unverified")

    def test_missing_terminal_recovery_cannot_remove_supervised_failure_rules(self):
        self.prepare()
        receipt = self.gate("slow_complete")
        before = set(self.root.glob("adapter-*.identity.json"))
        process = subprocess.Popen(self.formal_command("missing-terminal", "slow_complete", gate=receipt),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 3
            identity_files = set()
            while time.monotonic() < deadline and process.poll() is None:
                identity_files = set(self.root.glob("adapter-*.identity.json")) - before
                if identity_files:
                    break
                time.sleep(.005)
            self.assertTrue(identity_files, "the formal fixture did not launch")
            identities = [json.loads(path.read_text()) for path in identity_files]
            process.kill()  # This wrapper belongs exclusively to this test.
            process.communicate(timeout=1)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if all(not ((live := fixtures.ExecutionSupervisorTests.process_identity(item["pid"]))
                            and live["start_ticks"] == item["start_ticks"] and live["state"] != "Z")
                       for item in identities):
                    break
                time.sleep(.01)
            for item in identities:
                state = fixtures.ExecutionSupervisorTests.process_identity(item["pid"])
                self.assertTrue(not state or state["state"] == "Z", "fixture runner did not stop naturally")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=1)
        self.assertFalse(list((self.root / "output").rglob("*.terminal.json")),
                         "interrupted fixture unexpectedly persisted terminal evidence")
        self.cli("recover-run", "--run", "missing-terminal", "--stopped-confirmed",
                 "--reason", "This fixture wrapper was killed and the bounded runner finished.")
        self.interrupted_summary("missing-terminal")
        self.cli("classify-run", "--run", "missing-terminal", "--classification", "harness",
                 "--evidence", "fixture/wrapper-interrupted-terminal-capture")
        self.cli("resolve", "--run", "missing-terminal", "--reason", "Known isolated wrapper interruption", ok=False)
        refused = self.formal("unsafe-retry", "complete", gate=self.gate("complete"),
                              retry="missing-terminal", ok=False)
        self.assertIn("error", refused)
        self.cli("resolve", "--run", "missing-terminal", "--reason", "Explained the isolated wrapper interruption",
                 "--validation", "fixture/manual-interruption-identity-and-stop-check")
        self.assertEqual(self.assess()["status"], "unverified",
                         "human recovery and explanation cannot recreate missing supervision evidence")
        ledger = json.loads((self.state / "state.json").read_text())
        self.assertIn("execution_contract", ledger["runs"]["missing-terminal"])
        self.assertNotIn("unsafe-retry", ledger["runs"])

    def test_formal_initial_registration_cannot_wait_forever_for_a_ledger_lock(self):
        self.prepare()
        receipt = self.gate("complete")
        command = self.formal_command("initial-lock-conflict", "complete", gate=receipt)
        with self.hold_ledger_lock():
            started = time.monotonic()
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = self.communicate_before_safety_timeout(process)
            self.assertNotEqual(process.returncode, 0, stdout + stderr)
            self.assertIn("lock", (stdout + stderr).lower(), "the refusal must come from the ledger lock")
            shutdown = json.loads(self.contract.read_text())["budgets"]["shutdown"]["seconds"]
            self.assertLess(time.monotonic() - started, shutdown + .7,
                            "initial registration must use the declared lock budget plus the original startup margin")
        self.assertNotIn("initial-lock-conflict", json.loads((self.state / "state.json").read_text())["runs"])

    def test_terminal_capture_survives_a_lock_blocked_final_ledger_write(self):
        self.prepare()
        wait_mode = '''if mode == "wait_for_lock":
    begin()
    (Path(__file__).resolve().parent / "action-ready").write_text("ready")
    index = 0
    while not (Path(__file__).resolve().parent / "finish-action").exists():
        emit("progress", case_id="case-a", progress_kind="assertion", evidence="wait-" + str(index))
        index += 1
        time.sleep(.02)
    end()
elif mode == "missing":'''
        self.adapter.write_text(fixtures.ADAPTER.replace('if mode == "missing":', wait_mode))
        contract = json.loads(self.contract.read_text())
        contract["budgets"]["total"] = fixtures.budget(2.5,
            "fixture preserves original 1.5s controlled action horizon; adds 1.0s shutdown from 0.30696s cold proof with threefold metadata margin")
        contract["budgets"]["case"] = fixtures.budget(1.0)
        contract["budgets"]["phase"] = {name: fixtures.budget(1.3) for name in ("setup", "run", "cleanup")}
        self.contract.write_text(json.dumps(contract))
        receipt = self.gate("wait_for_lock")
        process = subprocess.Popen(self.formal_command("final-lock-conflict", "wait_for_lock", gate=receipt),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            ready = self.root / "action-ready"
            deadline = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=1)
                    self.fail("formal fixture exited before its controlled action: " + stdout + stderr)
                time.sleep(.01)
            self.assertTrue(ready.is_file(), "formal fixture did not reach its action")
            with self.hold_ledger_lock():
                (self.root / "finish-action").write_text("finish")
                started = time.monotonic()
                stdout, stderr = self.communicate_before_safety_timeout(process)
                self.assertNotEqual(process.returncode, 0, stdout + stderr)
                self.assertIn("lock", (stdout + stderr).lower(), "the refusal must come from final ledger registration")
                self.assertLess(time.monotonic() - started, contract["budgets"]["shutdown"]["seconds"] + .9,
                                "final registration must use the declared lock budget plus the original capture margin")
                status_command = self.command("execution-status", "--state", self.state,
                    "--run", "final-lock-conflict", "--lock-timeout", "0.2")
                status_started = time.monotonic()
                status = subprocess.run(status_command, capture_output=True, text=True, timeout=2)
                self.assertNotEqual(status.returncode, 0)
                self.assertIn("lock", status.stderr.lower())
                self.assertLess(time.monotonic() - status_started, .8,
                                "ledger-only status must honor its own explicit lock budget")
        finally:
            (self.root / "finish-action").write_text("finish")
            if process.poll() is None:
                self.communicate_before_safety_timeout(process)
            else:
                process.communicate(timeout=1)
        self.cli("execution-status", "--run", "final-lock-conflict", "--lock-timeout", "0.2")
        for invalid in ("nan", "inf", "0", "-1", "61"):
            with self.subTest(lock_timeout=invalid):
                invalid_status = subprocess.run(self.command("execution-status", "--state", self.state,
                    "--run", "final-lock-conflict", "--lock-timeout", invalid),
                    capture_output=True, text=True, timeout=2)
                self.assertNotEqual(invalid_status.returncode, 0, invalid_status.stdout)
                self.assertIn("error", json.loads(invalid_status.stderr),
                              "invalid timeout must be rejected with an otherwise available ledger")
        terminals = list((self.root / "output").rglob("*.terminal.json"))
        self.assertTrue(terminals, "a blocked ledger must not erase already captured terminal evidence")
        result = json.loads(terminals[-1].read_text())
        self.assertEqual(result["outcome"], "completed")
        self.assertTrue(result["capture_complete"])
        self.assertEqual(self.assess()["status"], "unverified",
                         "a terminal snapshot cannot silently complete an unregistered ledger outcome")

    def test_formal_admission_rejects_an_initially_dirty_worktree(self):
        self.prepare()
        receipt = self.gate("complete")
        for filename in ("source.txt", "initial-untracked.txt"):
            with self.subTest(filename=filename):
                path = self.cwd / filename
                original = path.read_bytes() if path.exists() else None
                try:
                    path.write_text("uncommitted acceptance source\n")
                    refused = self.formal("dirty-source", "complete", gate=receipt, ok=False)
                    self.assertIn("error", refused)
                    self.assertNotIn("dirty-source", json.loads((self.state / "state.json").read_text())["runs"])
                finally:
                    if original is None:
                        path.unlink()
                    else:
                        path.write_bytes(original)

    def assert_runtime_source_mutation_is_not_qualified(self, mode):
        self.prepare()
        mutation = r'''if mode in ("mutate_tracked", "produce_untracked"):
    begin()
    path = Path("source.txt") if mode == "mutate_tracked" else Path("runtime-untracked.txt")
    path.write_text("runtime acceptance source mutation\n")
    end()
elif mode == "missing":'''
        self.adapter.write_text(fixtures.ADAPTER.replace('if mode == "missing":', mutation))
        result = self.formal("source-mutated", mode, gate=self.gate(mode), ok=False)
        self.assertEqual(result["exit_code"], 0, "retain the product's actual exit status")
        self.assertFalse(result["acceptance_qualified"], "complete callbacks cannot qualify changed acceptance source")
        self.interrupted_summary("source-mutated")
        assessment = self.assess()
        self.assertEqual(assessment["status"], "unverified")
        self.assertIn("source-mutated", [row["run"] for row in assessment["blockers"]],
                      "source drift is the first failed acceptance attempt")

    def test_tracked_source_changed_during_acceptance_is_a_failure(self):
        self.assert_runtime_source_mutation_is_not_qualified("mutate_tracked")

    def test_untracked_source_produced_during_acceptance_is_a_failure(self):
        self.assert_runtime_source_mutation_is_not_qualified("produce_untracked")

    def test_external_adapter_self_mutation_cannot_qualify_even_with_clean_git(self):
        self.prepare()
        mutation = r'''if mode == "mutate_adapter":
    begin()
    path = Path(__file__)
    path.write_text(path.read_text() + "\n# adapter changed during real acceptance\n")
    end()
elif mode == "missing":'''
        self.adapter.write_text(fixtures.ADAPTER.replace('if mode == "missing":', mutation))
        result = self.formal("adapter-mutated", "mutate_adapter", gate=self.gate("mutate_adapter"), ok=False)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(self.git("status", "--porcelain", cwd=self.cwd), "",
                         "this counterexample changes only the external adapter")
        self.assertFalse(result["acceptance_qualified"])
        self.interrupted_summary("adapter-mutated")
        self.gate("mutate_adapter")  # A fresh valid probe cannot wash the prior failed run.
        assessment = self.assess()
        self.assertEqual(assessment["status"], "unverified")
        self.assertIn("adapter-mutated", [row["run"] for row in assessment["blockers"]])
        self.cli("resolve", "--run", "adapter-mutated", "--reason", "The new gate now passes", ok=False)

    def test_retry_cannot_change_the_fixed_execution_contract(self):
        self.prepare()
        self.formal("first-hang", "modal", gate=self.gate("modal"), repair_limit=1, ok=False)
        self.interrupted_summary("first-hang")
        self.cli("classify-run", "--run", "first-hang", "--classification", "harness",
                 "--evidence", "fixture/known-isolated-callback-hang")
        changed = json.loads(self.contract.read_text())
        changed["budgets"]["case"]["seconds"] = .6
        changed["budgets"]["case"]["source"] = "fixture/new-budget-authority"
        self.contract.write_text(json.dumps(changed))
        refused = self.formal("changed-contract-retry", "complete", gate=self.gate("complete"),
                              retry="first-hang", repair_limit=1, ok=False)
        self.assertIn("error", refused)
        ledger = json.loads((self.state / "state.json").read_text())
        self.assertNotIn("changed-contract-retry", ledger["runs"])
        self.assertFalse(ledger["execution_chains"]["full-suite"]["recovery_used"])
        self.assertEqual(self.assess()["status"], "unverified")

    def test_contract_revalidation_requires_authority_and_keeps_old_limits(self):
        self.prepare()
        initial = self.formal("initial-green", "complete", gate=self.gate("complete"), repair_limit=1)
        self.record("initial-green")
        changed = json.loads(self.contract.read_text())
        changed["budgets"]["case"]["seconds"] = .6
        changed["budgets"]["case"]["source"] = "fixture/approved-harness-budget-correction"
        self.contract.write_text(json.dumps(changed))
        changed_gate = self.gate("complete")
        refused = self.formal("unapproved-budget", "complete", gate=changed_gate, repair_limit=1,
            validate_after="initial-green", repair_round=1, repair_evidence="fixture/review-budget-fix", ok=False)
        self.assertIn("error", refused)
        authorized = self.formal("approved-budget-green", "complete", gate=changed_gate, repair_limit=1,
            validate_after="initial-green", repair_round=1, repair_evidence="fixture/review-budget-fix",
            contract_change_evidence="fixture/authority-ruling; fixture/test-review-evidence")
        self.assertTrue(authorized["acceptance_qualified"])
        self.record("approved-budget-green")
        beyond = self.formal("budget-reset-attempt", "complete", gate=changed_gate, repair_limit=1,
            validate_after="approved-budget-green", repair_round=2, repair_evidence="fixture/second-budget-fix",
            contract_change_evidence="fixture/authority-ruling; fixture/test-review-evidence", ok=False)
        self.assertIn("error", beyond)
        ledger = json.loads((self.state / "state.json").read_text())
        chain = ledger["execution_chains"]["full-suite"]
        self.assertEqual(chain["attempts"], ["initial-green", "approved-budget-green"])
        self.assertFalse(chain["recovery_used"])
        self.assertEqual(len(chain["policy_history"]), 1)
        adjudication = chain["policy_history"][0]
        self.assertEqual(adjudication["run"], "approved-budget-green")
        self.assertEqual(adjudication["before"]["budgets"]["case"]["seconds"], .42)
        self.assertEqual(adjudication["after"]["budgets"]["case"]["seconds"], .6)
        self.assertEqual(adjudication["evidence"], "fixture/authority-ruling; fixture/test-review-evidence")
        self.assertEqual(chain["execution_policy"], adjudication["after"])
        original = json.loads(Path(initial["record"]).read_text())
        self.assertEqual(original["execution_contract"]["value"]["budgets"]["case"]["seconds"], .42)
        self.assertEqual(ledger["runs"]["approved-budget-green"]["contract_adjudication"], adjudication)

    def test_review_revalidation_uses_a_fixed_chain_limit_across_owner_changes(self):
        self.prepare()
        receipt = self.gate("complete")
        self.formal("first-green", "complete", gate=receipt, repair_limit=1)
        self.record("first-green")
        (self.cwd / "source.txt").write_text("committed review repair\n")
        self.git("add", "source.txt", cwd=self.cwd)
        self.git("commit", "-m", "review repair", cwd=self.cwd)
        self.cli("handoff", "--resource", "ticket", "--owner", "replacement-review-agent")
        second = self.formal("review-green", "complete", gate=receipt, repair_limit=1,
                             validate_after="first-green", repair_round=1,
                             repair_evidence="fixture/review-request-and-committed-repair")
        self.assertTrue(second["acceptance_qualified"])
        self.record("review-green")
        self.cli("handoff", "--resource", "ticket", "--owner", "another-review-agent")
        third = self.formal("renamed-third", "complete", gate=receipt, repair_limit=1,
                            validate_after="review-green", repair_round=2,
                            repair_evidence="fixture/second-review-repair", ok=False)
        self.assertIn("error", third)
        self.assertNotIn("renamed-third", json.loads((self.state / "state.json").read_text())["runs"])
        expanded = self.formal("expanded-budget", "complete", gate=receipt, repair_limit=3,
                               validate_after="review-green", repair_round=2,
                               repair_evidence="fixture/request-to-expand-budget", ok=False)
        self.assertIn("error", expanded)
        chain = json.loads((self.state / "state.json").read_text())["execution_chains"]["full-suite"]
        self.assertEqual(chain["attempts"], ["first-green", "review-green"])
        self.assertFalse(chain["recovery_used"])

    def test_review_round_does_not_renew_an_already_used_automatic_recovery(self):
        self.prepare()
        modal_gate, complete_gate = self.gate("modal"), self.gate("complete")
        self.formal("initial-hang", "modal", gate=modal_gate, repair_limit=1, ok=False)
        self.interrupted_summary("initial-hang")
        self.cli("classify-run", "--run", "initial-hang", "--classification", "harness",
                 "--evidence", "fixture/known-modal-block-and-verified-stop")
        self.formal("automatic-green", "complete", gate=complete_gate, repair_limit=1, retry="initial-hang")
        self.record("automatic-green")
        self.cli("resolve", "--run", "initial-hang", "--reason", "Known fixture reset and recovery",
                 "--validation", "fixture/automatic-green-validation")
        self.cli("handoff", "--resource", "ticket", "--owner", "review-replacement")
        self.formal("review-hang", "modal", gate=modal_gate, repair_limit=1,
                    validate_after="automatic-green", repair_round=1,
                    repair_evidence="fixture/review-revalidation-contract", ok=False)
        self.interrupted_summary("review-hang")
        self.cli("classify-run", "--run", "review-hang", "--classification", "harness",
                 "--evidence", "fixture/known-second-modal-block")
        refused = self.formal("second-auto-recovery", "complete", gate=complete_gate,
                              repair_limit=1, retry="review-hang", ok=False)
        self.assertIn("error", refused)
        chain = json.loads((self.state / "state.json").read_text())["execution_chains"]["full-suite"]
        self.assertTrue(chain["recovery_used"])
        self.assertEqual(chain["attempts"], ["initial-hang", "automatic-green", "review-hang"])

    def test_exit_zero_without_cleanup_preserves_a_supervised_failure(self):
        self.prepare()
        incomplete = self.formal("missing-cleanup", "incomplete", gate=self.gate("incomplete"), ok=False)
        self.assertEqual(incomplete["exit_code"], 0)
        self.assertFalse(incomplete["acceptance_qualified"])
        first_record = Path(incomplete["record"]).read_bytes()
        self.interrupted_summary("missing-cleanup")
        self.cli("classify-run", "--run", "missing-cleanup", "--classification", "harness",
                 "--evidence", "fixture/incomplete-run-cleanup-boundaries")
        self.cli("resolve", "--run", "missing-cleanup", "--reason", "Explained cleanup omission", ok=False)
        self.assertEqual(self.assess()["status"], "unverified")
        self.cli("resolve", "--run", "missing-cleanup", "--reason", "Explained cleanup omission",
                 "--validation", "fixture/incomplete-lifecycle-diagnosis")
        self.assertEqual(self.assess()["status"], "unverified", "a resolved explanation is insufficient without a valid final run")
        green = self.formal("full-lifecycle-green", "complete", gate=self.gate("complete"), retry="missing-cleanup")
        self.assertTrue(green["acceptance_qualified"])
        self.record("full-lifecycle-green")
        self.assertEqual(self.assess()["status"], "verified")
        self.assertEqual(Path(incomplete["record"]).read_bytes(), first_record,
                         "a later green attempt cannot rewrite the original incomplete terminal evidence")

    def test_seal_requires_selected_full_scope_run_at_the_delivered_head(self):
        self.prepare_delivery()
        run = self.formal("delivery-green", "complete", gate=self.gate("complete"))
        self.assertTrue(run["acceptance_qualified"])
        self.record_acceptance("delivery-green", self.FULL_SCOPE)
        self.pr["draft"] = False
        self.pr_json.write_text(json.dumps(self.pr))
        self.seal_delivery("delivery-green")
        self.assertEqual(self.handoff_acceptance()["status"], "verified")

    def test_green_revision_a_cannot_verify_untested_delivered_revision_b(self):
        self.prepare_delivery()
        tested_oid = self.git("rev-parse", "HEAD", cwd=self.cwd)
        self.formal("old-head-green", "complete", gate=self.gate("complete"))
        self.record_acceptance("old-head-green", self.FULL_SCOPE)
        (self.cwd / "source.txt").write_text("untested delivery revision B\n")
        self.git("add", "source.txt", cwd=self.cwd)
        self.git("commit", "-m", "untested revision B", cwd=self.cwd)
        delivered_oid = self.git("rev-parse", "HEAD", cwd=self.cwd)
        self.assertNotEqual(tested_oid, delivered_oid)
        self.git("push", self.remote, "codex/pr", cwd=self.cwd)
        self.pr["head"]["sha"] = delivered_oid
        self.pr_json.write_text(json.dumps(self.pr))
        self.seal_delivery("old-head-green")
        handoff = json.loads((self.state / "handoff.json").read_text())
        self.assertEqual(handoff["delivery_oid"], delivered_oid)
        self.assertEqual(handoff["acceptance"]["status"], "unverified",
                         "a green run from an earlier revision cannot qualify a fresh PR head")

    def test_green_checkpoint_subset_cannot_verify_required_whole_scope(self):
        self.prepare_delivery()
        receipt = self.gate("complete")
        self.formal("historical-full-green", "complete", gate=receipt)
        self.record_acceptance("historical-full-green", self.FULL_SCOPE)
        self.formal("checkpoint-green", "complete", gate=receipt, key="checkpoint-suite")
        self.record_acceptance("checkpoint-green", self.FULL_SCOPE[:1])
        self.seal_delivery("checkpoint-green")
        self.assertEqual(self.handoff_acceptance()["status"], "unverified",
                         "the selected checkpoint cannot borrow another run's historical full coverage")

    def test_green_history_without_explicit_run_and_scope_stays_unverified(self):
        self.prepare_delivery()
        self.formal("historical-green", "complete", gate=self.gate("complete"))
        self.record_acceptance("historical-green", self.FULL_SCOPE)
        self.cli("seal", "--pr-json", self.pr_json)
        self.assertEqual(self.handoff_acceptance()["status"], "unverified")

    def test_unverified_seal_rejects_ready_or_missing_native_draft_state(self):
        self.cleanup_invocation()
        self.publish_pr()
        for draft in (False, None):
            with self.subTest(draft=draft):
                fresh = dict(self.pr)
                if draft is None:
                    fresh.pop("draft")
                else:
                    fresh["draft"] = draft
                self.pr_json.write_text(json.dumps(fresh))
                self.cli("seal", "--pr-json", self.pr_json, ok=False)
                ledger = json.loads((self.state / "state.json").read_text())
                self.assertFalse(ledger.get("sealed_at"), "refused native draft state cannot seal the invocation")
        self.pr_json.write_text(json.dumps(self.pr))
        self.cli("seal", "--pr-json", self.pr_json)
        self.assertEqual(self.handoff_acceptance()["status"], "unverified")

    def test_sealed_draft_handoff_retains_unverified_acceptance(self):
        self.cleanup_invocation()
        self.publish_pr()
        self.cli("seal", "--pr-json", self.pr_json)
        handoff = json.loads((self.state / "handoff.json").read_text())
        self.assertEqual(handoff["acceptance"]["status"], "unverified")
        self.assertEqual(handoff["acceptance"]["qualified_runs"], [])


if __name__ == "__main__":
    unittest.main()
