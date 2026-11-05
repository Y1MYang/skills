"""Implementation-blind contract tests for the public cycle.py CLI.

Authority: docs/plans/implement-spec-v3-runtime-contract.md, sections 1 and 3.
Only the command interface and its documented JSON observations are used.
Each test owns a temporary workspace and state directory; no real repo is changed.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CYCLE = Path(__file__).resolve().parents[1] / "scripts" / "cycle.py"
RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "run_command.py"
ROLES = (
    "exploration",
    "architect",
    "test_author",
    "implementer",
    "runner",
    "integrator",
    "coverage_audit",
    "spec_reviewer",
    "standards_reviewer",
    "expert",
)


class CycleContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="v3-cycle-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "tests").mkdir()
        (self.workspace / "src").mkdir()
        (self.workspace / "spec.md").write_text("REQ-1: 99 costs 10.\n", encoding="utf-8")
        self.state = self.root / "state"
        self.plan_path = self.root / "plan.json"
        self.models = {role: f"explicit-model-for-{role}" for role in ROLES}
        self.plan = {
            "schema": 1,
            "run_id": "cycle-contract-example",
            "workspace": str(self.workspace),
            "spec_sources": ["spec.md"],
            "models": self.models,
            "budget": {
                "max_attempts": 12,
                "max_formal_failures": 2,
                "max_seconds": 60,
            },
            "flows": [{"id": "main", "write_paths": ["src"]}],
            "examples": [{
                "id": "fee-99",
                "flow": "main",
                "requirement": "REQ-1/example-99",
                "depends_on": [],
                "snapshot": {
                    "schema": 1,
                    "root": str(self.workspace),
                    "tests": ["tests"],
                    "contract": ["spec.md"],
                    "product": ["src"],
                    "binding": None,
                },
            }],
            "gates": [],
        }

    def write_json(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def initialize(self):
        self.write_json(self.plan_path, self.plan)
        return self.cycle("init", "--plan", str(self.plan_path))

    def apply(self, op_id, operation, *, expected_exit=0, **fields):
        event = {"schema": 1, "op_id": op_id, "op": operation, **fields}
        event_path = self.root / "event.json"
        self.write_json(event_path, event)
        return self.cycle("apply", "--event", str(event_path), expected_exit=expected_exit)

    def open_example(self, example="fee-99", *, expected_exit=0):
        requirement = next(
            (item["requirement"] for item in self.plan["examples"] if item["id"] == example),
            example,
        )
        return self.apply(
            f"open-{example}",
            "open",
            example=example,
            light_check={
                "source": f"spec.md / {requirement}",
                "observation": f"Public behavior of {example} under its declared requirement",
                "expected_failure": f"A missing or incorrect public result violates {requirement}",
                "independent_context": "test-author-context-with-no-product-input",
            },
            expected_exit=expected_exit,
        )

    def install_fee_fixture(self, value="0"):
        """A test-owned toy product lets the real runner observe a real assertion."""
        (self.workspace / "src" / "fee.txt").write_text(value, encoding="utf-8")
        (self.workspace / "tests" / "test_fee.py").write_text(
            "from pathlib import Path\n"
            "import unittest\n"
            "class FeeExample(unittest.TestCase):\n"
            "    def test_fee_for_99_is_10(self):\n"
            "        self.assertEqual(Path('src/fee.txt').read_text(), '10')\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )

    def run_prepared(self, prepared, *, expected_exit, formal=False, test_file="tests/test_fee.py"):
        # The fixture declares a five-second execution allowance. The outer
        # 20-second harness cap adds the contract's five-second cleanup window
        # and ten seconds for wrapper startup, snapshot, and Git observations.
        command = [
            sys.executable, str(RUNNER), "--receipt", prepared["receipt_path"],
            "--cwd", str(self.workspace), "--timeout", "5",
            "--snapshot", prepared["request_path"],
        ]
        if formal:
            command.append("--formal")
        command.extend(["--", sys.executable, "-B"])
        if test_file is None:
            command.extend(["-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"])
        else:
            command.append(test_file)
        result = subprocess.run(
            command, cwd=self.root, capture_output=True, text=True,
            encoding="utf-8", timeout=20, check=False,
        )
        self.assertEqual(
            result.returncode, expected_exit,
            "The real runner must produce the expected fixture result; "
            "raw implementation diagnostics are withheld.",
        )
        self.assertTrue(Path(prepared["receipt_path"]).is_file())

    def record(self, label, prepared):
        return self.apply(label, "record", attempt_id=prepared["attempt_id"])

    def establish_valid_red(self):
        self.install_fee_fixture()
        self.initialize()
        self.open_example()
        red = self.apply(
            "probe-for-red", "prepare", example="fee-99", purpose="probe",
            timeout_seconds=5,
        )
        self.run_prepared(red, expected_exit=1)
        self.record("record-red", red)
        self.apply(
            "judge-red", "judge", attempt_id=red["attempt_id"],
            classification="valid-red",
            reason="The public fee result is 0; REQ-1 requires 10 for amount 99.",
            evidence=[red["receipt_path"]],
        )
        return red

    def complete_existing_example(self, example="fee-99", *, start_run=True, label="existing"):
        if start_run:
            self.install_fee_fixture("10")
            self.initialize()
        self.open_example(example)
        probe = self.apply(
            f"{label}-probe", "prepare", example=example, purpose="probe",
            timeout_seconds=5,
        )
        self.run_prepared(probe, expected_exit=0)
        self.record(f"record-{label}-probe", probe)
        self.apply(
            f"judge-{label}", "judge", attempt_id=probe["attempt_id"],
            classification="existing",
            reason="The independent assertion checks fee 99 equals 10 and detects a wrong fee.",
            evidence=[probe["receipt_path"]],
        )
        regression = self.apply(
            f"{label}-regression", "prepare", example=example,
            purpose="regression", timeout_seconds=5,
        )
        self.run_prepared(regression, expected_exit=0)
        self.record(f"record-{label}-regression", regression)
        closed = self.apply(
            f"close-{label}", "close", example=example,
            regression_attempt_id=regression["attempt_id"],
        )
        return closed, probe, regression

    def complete_red_green_example(self):
        red = self.establish_valid_red()
        (self.workspace / "src" / "fee.txt").write_text("10", encoding="utf-8")
        green = self.apply(
            "green-after-product-change", "prepare", example="fee-99",
            purpose="green", timeout_seconds=5,
        )
        self.run_prepared(green, expected_exit=0)
        self.record("record-green", green)
        closed = self.apply(
            "close-fee-99", "close", example="fee-99",
            regression_attempt_id=green["attempt_id"],
            regression_scope="The command runs the sole example and all affected regression.",
        )
        return closed, red, green

    def git(self, *arguments):
        # Small local-fixture Git operations share the CLI's 15-second hang cap;
        # elapsed Git time is not an acceptance criterion for the product.
        result = subprocess.run(
            ["git", *arguments], cwd=self.workspace, capture_output=True,
            text=True, encoding="utf-8", timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, "The isolated Git fixture command must succeed.")
        return result.stdout.strip()

    def commit_fixture(self, *, allow_empty=False):
        self.git("add", "--all")
        self.git(
            "-c", "user.name=Cycle Contract Fixture",
            "-c", "user.email=cycle-fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture candidate",
            *(["--allow-empty"] if allow_empty else []),
        )
        return self.git("rev-parse", "HEAD")

    def qualify(self, op_id, scope):
        # These explicit fixture inputs exercise the qualification boundary;
        # they make no claim of an actual review of the skill implementation.
        return self.apply(
            op_id, "qualify", scope=scope,
            spec_review={
                "review_id": "fixture-spec-review", "source": "spec.md / REQ-1",
                "independent_context": "fixture-spec-oracle", "verdict": "pass",
            },
            standards_review={
                "review_id": "fixture-standards-review", "source": "fixture-test-boundary",
                "independent_context": "fixture-standards-oracle", "verdict": "pass",
            },
        )

    def code_review_fixture(self, head):
        return {
            "spec": {"head": head, "review_id": "fixture-code-spec", "verdict": "pass"},
            "standards": {"head": head, "review_id": "fixture-code-standards", "verdict": "pass"},
        }

    def record_final_candidate(self):
        self.git("init", "--quiet")
        self.complete_existing_example()
        head = self.commit_fixture()
        self.qualify("qualify-final", {"final": True})
        formal = self.apply(
            "prepare-final", "prepare-formal", scope={"final": True}, timeout_seconds=5,
        )
        self.run_prepared(formal, expected_exit=0, formal=True)
        self.record("record-final", formal)
        return head, formal

    def cycle(self, *arguments, expected_exit=0):
        # A 15-second harness ceiling only prevents a hung CLI from wedging the
        # suite. It is not an acceptance deadline for any product behavior.
        result = subprocess.run(
            [sys.executable, str(CYCLE), "--state", str(self.state), *arguments],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
        accepted_exits = expected_exit if isinstance(expected_exit, tuple) else (expected_exit,)
        self.assertIn(
            result.returncode,
            accepted_exits,
            f"Public cycle command {arguments[0]!r} returned {result.returncode}; "
            f"expected {expected_exit}. Raw implementation diagnostics are withheld.",
        )
        lines = result.stdout.splitlines()
        self.assertTrue(lines, "The public CLI must return a JSON result.")
        try:
            output = json.loads(lines[-1])
        except json.JSONDecodeError:
            self.fail("The last public stdout line is not JSON.")
        self.assertIsInstance(output, dict)
        return output

    def test_init_preserves_this_runs_explicit_ten_role_choices(self):
        """Current-run model choices are observable without inferred defaults."""
        self.write_json(self.plan_path, self.plan)
        self.cycle("init", "--plan", str(self.plan_path))

        observed = self.cycle("inspect")

        self.assertIs(observed["ok"], True)
        self.assertEqual(observed["run_id"], "cycle-contract-example")
        self.assertEqual(observed["status"], "active")
        self.assertEqual(observed["models"], self.models)

    def test_init_rejects_a_role_without_an_explicit_current_run_model(self):
        """The Expert choice cannot be inherited from another role or default."""
        del self.plan["models"]["expert"]
        self.write_json(self.plan_path, self.plan)

        rejected = self.cycle("init", "--plan", str(self.plan_path), expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.assertIsInstance(rejected["error"]["code"], str)
        self.assertTrue(rejected["error"]["code"])

    def test_init_rejects_an_unbounded_time_budget(self):
        """NaN cannot provide the finite positive execution boundary required."""
        self.plan["budget"]["max_seconds"] = float("nan")
        self.write_json(self.plan_path, self.plan)

        rejected = self.cycle("init", "--plan", str(self.plan_path), expected_exit=2)

        self.assertIs(rejected["ok"], False)

    def test_repeated_identical_init_preserves_the_original_run(self):
        """A retried initialization acknowledges the existing durable run."""
        self.write_json(self.plan_path, self.plan)
        created = self.cycle("init", "--plan", str(self.plan_path))
        original = self.cycle("inspect")

        repeated = self.cycle("init", "--plan", str(self.plan_path))

        self.assertIs(created["created"], True)
        self.assertIs(repeated["created"], False)
        self.assertEqual(repeated["run_id"], created["run_id"])
        self.assertEqual(self.cycle("inspect"), original)

    def test_same_flow_cannot_open_a_second_unfinished_example(self):
        """A flow develops one behavior at a time, even without a dependency."""
        second = dict(self.plan["examples"][0])
        second.update(id="fee-100", requirement="REQ-1/example-100", depends_on=["fee-99"])
        self.plan["examples"].append(second)
        self.initialize()
        self.open_example()

        rejected = self.open_example("fee-100", expected_exit=2)

        self.assertIs(rejected["ok"], False)
        observed = self.cycle("inspect")
        self.assertEqual(observed["active_by_flow"]["main"], "fee-99")
        self.assertEqual(observed["examples"]["fee-100"]["state"], "planned")

    def test_green_preparation_requires_a_recorded_valid_red(self):
        """A light check and open example alone cannot authorize new behavior."""
        self.initialize()
        self.open_example()

        rejected = self.apply(
            "premature-green", "prepare", example="fee-99", purpose="green",
            timeout_seconds=5, expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        observed = self.cycle("inspect")
        self.assertEqual(observed["budget"]["attempts_used"], 0)
        self.assertEqual(observed["pending_attempts"], [])

    def test_open_example_can_reserve_its_first_probe(self):
        """The Red prerequisite still permits actual discovery of Red or Green."""
        self.initialize()
        self.open_example()

        prepared = self.apply(
            "first-probe", "prepare", example="fee-99", purpose="probe",
            timeout_seconds=5,
        )

        self.assertIs(prepared["ok"], True)
        self.assertTrue(prepared["attempt_id"])
        self.assertTrue(Path(prepared["request_path"]).is_file())
        self.assertFalse(Path(prepared["receipt_path"]).exists())
        observed = self.cycle("inspect")
        self.assertEqual(observed["budget"]["attempts_used"], 1)
        self.assertEqual(observed["budget"]["seconds_reserved"], 5)
        self.assertEqual(len(observed["pending_attempts"]), 1)

    def test_real_target_failure_judged_valid_red_unlocks_green_preparation(self):
        """Only a bound actual probe plus explicit valid-Red judgment unlocks Green."""
        red = self.establish_valid_red()

        green = self.apply(
            "authorized-green", "prepare", example="fee-99", purpose="green",
            timeout_seconds=5,
        )

        self.assertIs(green["ok"], True)
        self.assertNotEqual(green["attempt_id"], red["attempt_id"])
        observed = self.cycle("inspect")
        self.assertEqual(observed["budget"]["attempts_used"], 2)
        self.assertEqual(observed["budget"]["formal_failures_used"], 0)

    def test_matching_real_green_closes_the_behavior_and_releases_its_flow(self):
        """A real unchanged test passes after only the product fixture changes."""
        closed, red, green = self.complete_red_green_example()

        self.assertEqual(closed["mode"], "red-green")
        observed = self.cycle("inspect")
        self.assertIsNone(observed["active_by_flow"]["main"])
        self.assertEqual(observed["examples"]["fee-99"]["mode"], "red-green")
        self.assertCountEqual(
            observed["examples"]["fee-99"]["attempt_ids"],
            [red["attempt_id"], green["attempt_id"]],
        )
        self.assertEqual(observed["budget"]["attempts_used"], 2)
        self.assertEqual(observed["budget"]["formal_failures_used"], 0)
        self.assertEqual(observed["budget"]["seconds_reserved"], 0)
        self.assertEqual(observed["pending_attempts"], [])

    def test_first_green_uses_the_existing_capability_exit_without_a_fake_red(self):
        """Already-correct behavior closes as existing after a real regression."""
        closed, _, _ = self.complete_existing_example()

        self.assertEqual(closed["mode"], "existing")
        observed = self.cycle("inspect")
        self.assertEqual(observed["examples"]["fee-99"]["mode"], "existing")
        self.assertIsNone(observed["active_by_flow"]["main"])
        self.assertEqual(observed["budget"]["attempts_used"], 2)
        self.assertEqual(observed["failures"], [])

    def test_replaying_prepare_returns_the_original_attempt_without_double_charge(self):
        """A caller retry cannot duplicate reservation, evidence, or event history."""
        self.initialize()
        self.open_example()
        first = self.apply(
            "retry-safe-probe", "prepare", example="fee-99", purpose="probe",
            timeout_seconds=5,
        )
        before_retry = self.cycle("inspect")

        repeated = self.apply(
            "retry-safe-probe", "prepare", example="fee-99", purpose="probe",
            timeout_seconds=5,
        )

        self.assertEqual(repeated, first)
        self.assertEqual(self.cycle("inspect"), before_retry)

    def test_valid_red_still_consumes_the_declared_attempt_budget(self):
        """Expected Red is normal, but does not grant free extra executions."""
        self.plan["budget"]["max_attempts"] = 1
        self.establish_valid_red()

        rejected = self.apply(
            "over-budget-green", "prepare", example="fee-99", purpose="green",
            timeout_seconds=5, expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        observed = self.cycle("inspect")
        self.assertEqual(observed["budget"]["attempts_used"], 1)
        self.assertEqual(observed["budget"]["formal_failures_used"], 0)
        self.assertEqual(observed["pending_attempts"], [])

    def test_changed_test_bytes_cannot_reuse_the_previous_valid_red(self):
        """A Red from an earlier independent criterion cannot license changed tests."""
        self.establish_valid_red()
        test_path = self.workspace / "tests" / "test_fee.py"
        test_path.write_text(test_path.read_text(encoding="utf-8") + "\n# revised criterion version\n", encoding="utf-8")

        rejected = self.apply(
            "stale-red-green", "prepare", example="fee-99", purpose="green",
            timeout_seconds=5, expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertEqual(self.cycle("inspect")["budget"]["attempts_used"], 1)

    def test_record_rejects_a_real_receipt_whose_log_bytes_were_changed(self):
        """The receipt's claimed log hash cannot substitute for actual log bytes."""
        self.install_fee_fixture()
        self.initialize()
        self.open_example()
        probe = self.apply(
            "tamper-evidence-probe", "prepare", example="fee-99", purpose="probe",
            timeout_seconds=5,
        )
        self.run_prepared(probe, expected_exit=1)
        receipt = json.loads(Path(probe["receipt_path"]).read_text(encoding="utf-8"))
        # Deliberately invalidate real evidence; this is never trusted as a run.
        log_path = Path(receipt["logs"]["stderr"]["path"])
        original_log = log_path.read_bytes()
        self.assertGreater(len(original_log), 0, "The failing fixture must emit an assertion result.")
        log_path.write_bytes(bytes([original_log[0] ^ 1]) + original_log[1:])

        rejected = self.apply(
            "record-tampered", "record", attempt_id=probe["attempt_id"],
            expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertEqual(len(self.cycle("inspect")["pending_attempts"]), 1)

    def test_new_run_and_state_cannot_reset_the_existing_scope_budget(self):
        """Renaming the run cannot erase an exhausted attempt allowance."""
        self.plan["budget"]["max_attempts"] = 1
        self.establish_valid_red()
        original_state = self.state
        before_restart = self.cycle("inspect")
        self.plan["run_id"] = "renamed-run-with-same-requirements"
        self.state = self.root / "replacement-state"
        self.write_json(self.plan_path, self.plan)

        rejected = self.cycle("init", "--plan", str(self.plan_path), expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.state = original_state
        self.assertEqual(self.cycle("inspect"), before_restart)

    def test_recovery_charges_an_unstarted_attempt_once_without_resetting_the_run(self):
        """Recovery cancels a pending execution and retains its original cost."""
        self.initialize()
        self.open_example()
        prepared = self.apply(
            "interrupted-probe", "prepare", example="fee-99", purpose="probe",
            timeout_seconds=5,
        )
        resumed_models = {role: f"new-explicit-choice-{role}" for role in ROLES}
        self.apply("resume-call", "invocation", kind="resume", models=resumed_models)

        recovered = self.apply("recover-first", "recover", invocation_id="resume-call")

        self.assertIs(recovered["ok"], True)
        observed = self.cycle("inspect")
        self.assertEqual(observed["run_id"], self.plan["run_id"])
        self.assertEqual(observed["models"], resumed_models)
        self.assertEqual(observed["budget"]["attempts_used"], 1)
        self.assertEqual(observed["budget"]["seconds_used"], 5)
        self.assertEqual(observed["budget"]["seconds_reserved"], 0)
        self.assertEqual(len(observed["failures"]), 1)
        self.assertEqual(observed["failures"][0]["attempt_id"], prepared["attempt_id"])
        self.assertEqual(observed["pending_attempts"], [])

        self.apply("recover-again", "recover", invocation_id="resume-call")
        repeated = self.cycle("inspect")
        self.assertEqual(repeated["budget"], observed["budget"])
        self.assertEqual(repeated["failures"], observed["failures"])

    def test_gate_blocks_its_consumer_while_its_next_prerequisite_can_open(self):
        """An unqualified contract blocks consumers without deadlocking its own examples."""
        second = dict(self.plan["examples"][0])
        second.update(id="fee-100", requirement="REQ-2/example-100", depends_on=["fee-99"])
        consumer = dict(self.plan["examples"][0])
        consumer.update(id="checkout", flow="ui", requirement="REQ-3/checkout")
        self.plan["examples"].extend([second, consumer])
        self.plan["flows"].append({"id": "ui", "write_paths": ["ui"]})
        self.plan["gates"] = [{
            "id": "fee-contract", "prerequisites": ["fee-99", "fee-100"],
            "consumers": ["checkout"],
        }]
        (self.workspace / "spec.md").write_text(
            "REQ-1: 99 costs 10.\nREQ-2: 100 costs 0.\nREQ-3: Checkout uses the fee contract.\n",
            encoding="utf-8",
        )
        self.complete_existing_example()

        self.open_example("fee-100")
        rejected = self.open_example("checkout", expected_exit=2)

        self.assertIs(rejected["ok"], False)
        observed = self.cycle("inspect")
        self.assertEqual(observed["active_by_flow"]["main"], "fee-100")
        self.assertIsNone(observed["active_by_flow"]["ui"])
        self.assertEqual(observed["examples"]["checkout"]["state"], "planned")

    def test_current_formal_gate_evidence_releases_the_declared_consumer(self):
        """Both qualification and a real clean-candidate run permit consumer work."""
        consumer = dict(self.plan["examples"][0])
        consumer.update(id="checkout", flow="ui", requirement="REQ-3/checkout")
        self.plan["examples"].append(consumer)
        self.plan["flows"].append({"id": "ui", "write_paths": ["ui"]})
        self.plan["gates"] = [{
            "id": "fee-contract", "prerequisites": ["fee-99"], "consumers": ["checkout"],
        }]
        self.git("init", "--quiet")
        self.complete_existing_example()
        head = self.commit_fixture()
        self.qualify("qualify-fee", {"gate": "fee-contract"})
        formal = self.apply(
            "formal-fee", "prepare-formal", scope={"gate": "fee-contract"},
            timeout_seconds=5,
        )
        self.run_prepared(formal, expected_exit=0, formal=True)
        self.record("record-formal-fee", formal)

        released = self.apply(
            "release-fee", "release", gate="fee-contract", attempt_id=formal["attempt_id"],
        )
        self.open_example("checkout")

        self.assertIs(released["ok"], True)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.cycle("inspect")["active_by_flow"]["ui"], "checkout")

    def test_test_change_after_green_prevents_the_first_close(self):
        """A once-passing Green cannot close a newly changed test criterion."""
        self.establish_valid_red()
        (self.workspace / "src" / "fee.txt").write_text("10", encoding="utf-8")
        green = self.apply(
            "soon-stale-green", "prepare", example="fee-99", purpose="green",
            timeout_seconds=5,
        )
        self.run_prepared(green, expected_exit=0)
        self.record("record-soon-stale-green", green)
        test_path = self.workspace / "tests" / "test_fee.py"
        test_path.write_text(test_path.read_text(encoding="utf-8") + "\n# new test version\n", encoding="utf-8")

        rejected = self.apply(
            "close-with-stale-green", "close", example="fee-99",
            regression_attempt_id=green["attempt_id"],
            regression_scope="The original command covered all original assertions.",
            expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertEqual(self.cycle("inspect")["active_by_flow"]["main"], "fee-99")

    def test_rejudging_an_old_probe_cannot_reopen_a_closed_example(self):
        """Repeating a historical judgment must preserve completed work."""
        _, probe, _ = self.complete_existing_example()
        before = self.cycle("inspect")

        self.apply(
            "repeat-old-judgment-with-new-op-id", "judge", attempt_id=probe["attempt_id"],
            classification="existing",
            reason="The independent assertion checks fee 99 equals 10 and detects a wrong fee.",
            evidence=[probe["receipt_path"]], expected_exit=(0, 2),
        )

        after = self.cycle("inspect")
        for field in ("state", "mode"):
            self.assertEqual(after["examples"]["fee-99"][field], before["examples"]["fee-99"][field])
        self.assertCountEqual(
            after["examples"]["fee-99"]["attempt_ids"],
            before["examples"]["fee-99"]["attempt_ids"],
        )
        self.assertEqual(after["active_by_flow"], before["active_by_flow"])
        self.assertEqual(after["budget"], before["budget"])

    def test_an_alternate_spec_path_spelling_cannot_create_a_fresh_budget(self):
        """Scope follows the same requirement file, not its caller spelling."""
        self.plan["budget"]["max_attempts"] = 1
        self.establish_valid_red()
        original_state = self.state
        before = self.cycle("inspect")
        self.plan["spec_sources"] = ["./spec.md"]
        self.plan["run_id"] = "renamed-run-with-path-alias"
        self.state = self.root / "path-alias-state"
        self.write_json(self.plan_path, self.plan)

        rejected = self.cycle("init", "--plan", str(self.plan_path), expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.state = original_state
        self.assertEqual(self.cycle("inspect")["budget"], before["budget"])

    def test_verify_and_recover_reject_a_changed_cancellation_claim(self):
        """A cancellation used to settle budget remains immutable recovery evidence."""
        self.initialize()
        self.open_example()
        prepared = self.apply(
            "cancelled-probe", "prepare", example="fee-99", purpose="probe",
            timeout_seconds=5,
        )
        self.apply("resume-for-cancel", "invocation", kind="resume", models=self.models)
        self.apply("cancel-unstarted", "recover", invocation_id="resume-for-cancel")
        verified = self.cycle("verify")
        self.assertIs(verified["valid"], True)
        claim_path = Path(prepared["receipt_path"] + ".claim.json")
        claim_text = claim_path.read_text(encoding="utf-8")
        claim = json.loads(claim_text)
        self.assertEqual(claim["cancelled_attempt"], prepared["attempt_id"])
        # Invalidate genuine tool-created evidence, never manufacture trusted proof.
        timestamp = claim["created_at"]
        different_timestamp = ("1" if timestamp[0] != "1" else "2") + timestamp[1:]
        changed_claim = claim_text.replace(timestamp, different_timestamp, 1)
        self.assertNotEqual(changed_claim, claim_text)
        self.assertEqual(len(changed_claim.encode("utf-8")), len(claim_text.encode("utf-8")))
        claim_path.write_text(changed_claim, encoding="utf-8")

        rejected_verify = self.cycle("verify", expected_exit=2)
        rejected_recover = self.apply(
            "recover-changed-cancel", "recover", invocation_id="resume-for-cancel",
            expected_exit=2,
        )

        self.assertIs(rejected_verify["ok"], False)
        self.assertIs(rejected_recover["ok"], False)

    def test_rejudging_valid_red_cannot_reopen_a_red_green_completion(self):
        """An old failure judgment cannot turn completed new behavior back into Red."""
        _, red, _ = self.complete_red_green_example()
        before = self.cycle("inspect")

        self.apply(
            "repeat-valid-red-after-close", "judge", attempt_id=red["attempt_id"],
            classification="valid-red",
            reason="The original probe observed fee 0 while the independent spec required 10.",
            evidence=[red["receipt_path"]], expected_exit=(0, 2),
        )

        after = self.cycle("inspect")
        for field in ("state", "mode"):
            self.assertEqual(after["examples"]["fee-99"][field], before["examples"]["fee-99"][field])
        self.assertCountEqual(
            after["examples"]["fee-99"]["attempt_ids"],
            before["examples"]["fee-99"]["attempt_ids"],
        )
        self.assertEqual(after["active_by_flow"], before["active_by_flow"])
        self.assertEqual(after["budget"], before["budget"])

    def stage_fixture(self, example="fee-next", digest="staged-test-sha", *, expected_exit=0):
        return self.apply(
            f"stage-{example}", "stage", example=example, test_digest=digest,
            light_check={
                "source": "spec.md / staged requirement",
                "observation": f"Public behavior of {example} under its declared requirement",
                "expected_failure": f"A missing public result violates {example}'s requirement",
                "independent_context": "test-author-context-with-no-product-input",
            },
            expected_exit=expected_exit,
        )

    def prepare_next_example(self, *, depends_on=("fee-99",), flow="main"):
        example = dict(self.plan["examples"][0])
        example.update(id="fee-next", requirement="REQ-2/example-next", depends_on=list(depends_on))
        self.plan["examples"].append(example)
        return example

    def test_plan_rejects_sibling_ready_examples_in_one_flow(self):
        """Simultaneously ready examples must be planned on distinct flows."""
        sibling = dict(self.plan["examples"][0])
        sibling.update(id="fee-sibling", requirement="REQ-1/example-sibling")
        self.plan["examples"].append(sibling)
        self.write_json(self.plan_path, self.plan)

        rejected = self.cycle("init", "--plan", str(self.plan_path), expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.assertEqual(rejected["error"]["code"], "unnamed-parallelism")

    def test_plan_accepts_a_genuinely_serial_chain_in_one_flow(self):
        """A linear dependency chain has no unnamed parallelism to expose."""
        child = dict(self.plan["examples"][0])
        child.update(id="fee-100", requirement="REQ-1/example-100", depends_on=["fee-99"])
        self.plan["examples"].append(child)
        self.write_json(self.plan_path, self.plan)

        created = self.cycle("init", "--plan", str(self.plan_path))

        self.assertIs(created["ok"], True)

    def test_stage_requires_development_started_on_the_prerequisite(self):
        """Prewriting waits until the prerequisite example actually reaches development."""
        self.prepare_next_example()
        self.initialize()

        rejected = self.stage_fixture(expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.assertEqual(rejected["error"]["code"], "stage-not-ready")

    def test_staged_prewrite_survives_until_promotion_after_prerequisite_closes(self):
        """Depth-1 prewriting records the blind test before its example is current."""
        self.prepare_next_example()
        self.complete_existing_example()
        staged = self.stage_fixture()

        self.assertIs(staged["ok"], True)
        observed = self.cycle("inspect")
        self.assertEqual(observed["staged"]["fee-next"]["test_digest"], "staged-test-sha")

    def test_promotion_binds_the_staged_test_once_the_example_becomes_current(self):
        """A promoted staged test satisfies the dependency wait and stays promotable."""
        self.prepare_next_example()
        self.complete_existing_example()
        self.stage_fixture()

        promoted = self.apply("promote-next", "promote", example="fee-next")

        self.assertIs(promoted["ok"], True)
        observed = self.cycle("inspect")
        self.assertIn("promoted_seq", observed["staged"]["fee-next"])
        replayed = self.apply("promote-next", "promote", example="fee-next")
        self.assertEqual(replayed, promoted)

    def test_stage_rejects_a_second_prewrite_on_the_same_flow(self):
        """Depth 1 allows one prewritten test per flow until it is promoted."""
        self.prepare_next_example()
        second = dict(self.plan["examples"][0])
        second.update(id="fee-third", requirement="REQ-3/example-third", depends_on=["fee-next"])
        self.plan["flows"].append({"id": "second-flow", "write_paths": ["ui"]})
        second["flow"] = "second-flow"
        self.plan["examples"].append(second)
        self.complete_existing_example()
        self.stage_fixture()
        self.initialize()

        rejected = self.apply(
            "stage-second", "stage", example="fee-third", test_digest="second-test-sha",
            light_check={
                "source": "spec.md / third requirement", "observation": "Public behavior of fee-third",
                "expected_failure": "A missing public result violates fee-third",
                "independent_context": "test-author-context-with-no-product-input",
            },
            expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertEqual(rejected["error"]["code"], "stage-not-ready")

    def test_new_formal_failure_requires_diagnosis_before_scope_requalification(self):
        """Judge and diagnose a failed formal attempt before new qualification."""
        self.git("init", "--quiet")
        self.complete_existing_example()
        self.commit_fixture()
        self.qualify("qualify-first", {"final": True})
        # Break the delivered behavior so the frozen-candidate formal run fails.
        (self.workspace / "src" / "fee.txt").write_text("0", encoding="utf-8")
        formal = self.apply(
            "prepare-failing-final", "prepare-formal", scope={"final": True}, timeout_seconds=5,
        )
        self.run_prepared(formal, expected_exit=1)
        self.record("record-failing-final", formal)

        rejected = self.apply(
            "qualify-after-failure", "qualify", scope={"final": True},
            spec_review={
                "review_id": "fixture-spec-review-after-failure", "source": "spec.md / REQ-1",
                "independent_context": "fixture-spec-oracle", "verdict": "pass",
            },
            standards_review={
                "review_id": "fixture-standards-after-failure", "source": "fixture-test-boundary",
                "independent_context": "fixture-standards-oracle", "verdict": "pass",
            },
            expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertEqual(rejected["error"]["code"], "diagnosis-required")

    def test_parallel_flow_requires_a_distinct_workcopy_root(self):
        """A second flow cannot share the integration workspace as its snapshot root."""
        self.plan["flows"].append({"id": "ui", "write_paths": ["ui"], "root": str(self.workspace)})
        self.write_json(self.plan_path, self.plan)

        rejected = self.cycle("init", "--plan", str(self.plan_path), expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.assertEqual(rejected["error"]["code"], "invalid-flow")

    def test_final_execution_and_both_review_heads_finish_the_same_candidate(self):
        """Ready refers to one real clean candidate after full-scope execution."""
        head, formal = self.record_final_candidate()

        finished = self.apply(
            "finish-candidate", "finish", attempt_id=formal["attempt_id"],
            code_reviews=self.code_review_fixture(head),
        )

        self.assertEqual(finished["status"], "ready")
        self.assertEqual(finished["head"], head)
        self.assertEqual(self.cycle("inspect")["status"], "ready")

    def test_another_commit_cannot_reuse_the_previous_final_execution(self):
        """Even identical content at a different HEAD requires current final evidence."""
        old_head, formal = self.record_final_candidate()
        new_head = self.commit_fixture(allow_empty=True)
        self.assertNotEqual(new_head, old_head)

        rejected = self.apply(
            "finish-new-head-with-old-run", "finish", attempt_id=formal["attempt_id"],
            code_reviews=self.code_review_fixture(new_head), expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertNotEqual(self.cycle("inspect")["status"], "ready")

    def test_extend_adds_the_next_example_without_resetting_completed_history(self):
        """Progressive discovery appends work while retaining the same run and cost."""
        (self.workspace / "spec.md").write_text(
            "REQ-1: 99 costs 10.\nREQ-2: 100 costs 0.\n", encoding="utf-8",
        )
        self.complete_red_green_example()
        before = self.cycle("inspect")
        self.assertTrue(before["failures"], "The fixture must retain its original valid-Red trail.")
        next_example = dict(self.plan["examples"][0])
        next_example.update(id="fee-100", requirement="REQ-2/example-100", depends_on=["fee-99"])

        extended = self.apply(
            "extend-fee-examples", "extend", source="spec.md / REQ-2",
            reason="The next independent behavior can now be developed.",
            examples=[next_example], flows=[], gates=[],
        )

        self.assertEqual(extended["added"]["examples"], ["fee-100"])
        after = self.cycle("inspect")
        self.assertEqual(after["run_id"], before["run_id"])
        self.assertEqual(after["budget"], before["budget"])
        self.assertEqual(after["examples"]["fee-99"]["state"], before["examples"]["fee-99"]["state"])
        self.assertCountEqual(
            after["examples"]["fee-99"]["attempt_ids"],
            before["examples"]["fee-99"]["attempt_ids"],
        )
        self.assertEqual(after["failures"], before["failures"])
        self.assertEqual(after["examples"]["fee-100"]["state"], "planned")
        self.open_example("fee-100")
        self.assertEqual(self.cycle("inspect")["active_by_flow"]["main"], "fee-100")

    def test_a_new_diagnosis_allows_retry_without_erasing_the_interrupted_attempt(self):
        """A justified retry preserves the original interruption and its charge."""
        self.initialize()
        self.open_example()
        original = self.apply(
            "probe-before-interruption", "prepare", example="fee-99", purpose="probe",
            timeout_seconds=5,
        )
        self.apply("resume-for-diagnosis", "invocation", kind="resume", models=self.models)
        self.apply("recover-for-diagnosis", "recover", invocation_id="resume-for-diagnosis")
        before = self.cycle("inspect")
        self.apply(
            "unjustified-retry", "prepare", example="fee-99", purpose="probe",
            timeout_seconds=5, expected_exit=2,
        )
        claim_path = original["receipt_path"] + ".claim.json"

        self.apply(
            "diagnose-interruption", "diagnose", attempt_id=original["attempt_id"],
            reason="No runner started; the real cancellation claim closes that reservation.",
            evidence=[claim_path], next_action="Prepare one new bounded probe using the same criterion.",
        )

        diagnosed = self.cycle("inspect")
        self.assertEqual(diagnosed["budget"], before["budget"])
        self.assertEqual(diagnosed["failures"][0]["attempt_id"], original["attempt_id"])
        self.assertEqual(diagnosed["failures"][0]["diagnoses"][0]["evidence"], [claim_path])
        retried = self.apply(
            "justified-retry", "prepare", example="fee-99", purpose="probe",
            timeout_seconds=5,
        )
        self.assertNotEqual(retried["attempt_id"], original["attempt_id"])
        after = self.cycle("inspect")
        self.assertEqual(after["budget"]["attempts_used"], 2)
        self.assertEqual(after["budget"]["seconds_used"], 5)
        self.assertEqual(after["failures"][0]["attempt_id"], original["attempt_id"])

    def test_new_consumer_test_outside_gate_inputs_can_open_on_the_released_head(self):
        """Writing the consumer's first test does not invalidate unchanged gate inputs."""
        fee_snapshot = self.plan["examples"][0]["snapshot"]
        fee_snapshot["tests"] = ["tests/test_fee.py"]
        fee_snapshot["product"] = ["src/fee.txt"]
        consumer = dict(self.plan["examples"][0])
        consumer.update(id="checkout", flow="ui", requirement="REQ-3/checkout")
        consumer["snapshot"] = dict(fee_snapshot)
        consumer["snapshot"].update(tests=["tests/test_consumer.py"], product=["ui", "src/fee.txt"])
        self.plan["examples"].append(consumer)
        self.plan["flows"].append({"id": "ui", "write_paths": ["ui"]})
        self.plan["gates"] = [{
            "id": "fee-contract", "prerequisites": ["fee-99"], "consumers": ["checkout"],
        }]
        (self.workspace / "spec.md").write_text(
            "REQ-1: 99 costs 10.\nREQ-3: Checkout uses the fee contract.\n", encoding="utf-8",
        )
        self.git("init", "--quiet")
        self.complete_existing_example()
        released_head = self.commit_fixture()
        self.qualify("qualify-before-consumer-test", {"gate": "fee-contract"})
        formal = self.apply(
            "formal-before-consumer-test", "prepare-formal", scope={"gate": "fee-contract"},
            timeout_seconds=5,
        )
        self.run_prepared(formal, expected_exit=0, formal=True)
        self.record("record-before-consumer-test", formal)
        self.apply("release-before-consumer-test", "release", gate="fee-contract", attempt_id=formal["attempt_id"])
        (self.workspace / "tests" / "test_consumer.py").write_text(
            "import unittest\n"
            "class CheckoutExample(unittest.TestCase):\n"
            "    def test_consumer_uses_fee_contract(self):\n"
            "        from ui.checkout import fee\n"
            "        self.assertEqual(fee(99), 10)\n"
            "unittest.main()\n",
            encoding="utf-8",
        )
        self.assertTrue(self.git("status", "--porcelain", "--untracked-files=all"))
        self.assertEqual(self.git("diff", "--name-only"), "")
        self.assertEqual(self.git("rev-parse", "HEAD"), released_head)

        opened = self.open_example("checkout")

        self.assertIs(opened["ok"], True)
        self.assertEqual(self.cycle("inspect")["active_by_flow"]["ui"], "checkout")

    def test_init_rejects_an_indirect_cycle_through_a_gate_consumer(self):
        """A gate must not need its own blocked consumer through a relay dependency."""
        original = self.plan["examples"][0]
        relay = dict(original)
        relay.update(id="relay", requirement="REQ-2/relay", depends_on=["checkout"])
        consumer = dict(original)
        consumer.update(id="checkout", requirement="REQ-3/checkout")
        original["depends_on"] = ["relay"]
        self.plan["examples"].extend([relay, consumer])
        self.plan["gates"] = [{
            "id": "fee-contract", "prerequisites": ["fee-99"], "consumers": ["checkout"],
        }]
        self.write_json(self.plan_path, self.plan)

        rejected = self.cycle("init", "--plan", str(self.plan_path), expected_exit=2)

        self.assertIs(rejected["ok"], False)

    def test_revise_with_new_qualification_still_requires_completing_the_changed_behavior(self):
        """New test qualification cannot preserve completion of changed semantics."""
        self.git("init", "--quiet")
        self.complete_red_green_example()
        self.commit_fixture()
        before = self.cycle("inspect")
        (self.workspace / "spec.md").write_text("REQ-1: 99 now costs 20.\n", encoding="utf-8")
        test_path = self.workspace / "tests" / "test_fee.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8").replace("'10'", "'20'"), encoding="utf-8",
        )

        self.apply(
            "revise-fee-rule", "revise", examples=["fee-99"],
            source="spec.md / revised REQ-1", reason="The required fee changed from 10 to 20.",
        )

        revised = self.cycle("inspect")
        self.assertEqual(revised["budget"], before["budget"])
        self.assertCountEqual(
            revised["examples"]["fee-99"]["attempt_ids"],
            before["examples"]["fee-99"]["attempt_ids"],
        )
        self.assertEqual(revised["failures"], before["failures"])
        self.commit_fixture()
        self.qualify("qualify-revised-tests", {"final": True})
        rejected = self.apply(
            "formal-before-revised-completion", "prepare-formal", scope={"final": True},
            timeout_seconds=5, expected_exit=2,
        )
        self.assertIs(rejected["ok"], False)
        self.assertEqual(self.cycle("inspect")["budget"], before["budget"])

    def test_extend_invalidates_old_final_scope_even_after_new_existing_example_closes(self):
        """Unchanged bytes and HEAD cannot make an old final scope cover an added requirement."""
        (self.workspace / "spec.md").write_text(
            "REQ-1: 99 costs 10.\nREQ-2: The public fee value is the exact text '10'.\n",
            encoding="utf-8",
        )
        head, formal = self.record_final_candidate()
        self.apply(
            "finish-before-extension", "finish", attempt_id=formal["attempt_id"],
            code_reviews=self.code_review_fixture(head),
        )
        next_example = dict(self.plan["examples"][0])
        next_example.update(id="fee-text-format", requirement="REQ-2/text-format", depends_on=["fee-99"])
        self.apply(
            "extend-format-requirement", "extend", source="spec.md / REQ-2",
            reason="Track the independently stated text-format requirement in the final scope.",
            examples=[next_example], flows=[], gates=[],
        )
        self.complete_existing_example("fee-text-format", start_run=False, label="format")
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all"), "")

        rejected = self.apply(
            "finish-old-scope-after-extension", "finish", attempt_id=formal["attempt_id"],
            code_reviews=self.code_review_fixture(head), expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertNotEqual(self.cycle("inspect")["status"], "ready")

    def test_historical_gate_survives_consumer_commit_and_final_uses_the_new_head(self):
        """Historical release remains auditable while current final proof moves forward."""
        fee_snapshot = self.plan["examples"][0]["snapshot"]
        fee_snapshot["tests"] = ["tests/test_fee.py"]
        fee_snapshot["product"] = ["src/fee.txt"]
        consumer = dict(self.plan["examples"][0])
        consumer.update(id="checkout", flow="ui", requirement="REQ-3/checkout")
        consumer["snapshot"] = dict(fee_snapshot)
        consumer["snapshot"].update(tests=["tests/test_consumer.py"], product=["ui", "src/fee.txt"])
        self.plan["examples"].append(consumer)
        self.plan["flows"].append({"id": "ui", "write_paths": ["ui"]})
        self.plan["gates"] = [{
            "id": "fee-contract", "prerequisites": ["fee-99"], "consumers": ["checkout"],
        }]
        (self.workspace / "spec.md").write_text(
            "REQ-1: 99 costs 10.\nREQ-3: Checkout exposes the fee for 99 as integer 10.\n",
            encoding="utf-8",
        )
        self.git("init", "--quiet")
        self.complete_existing_example()
        gate_head = self.commit_fixture()
        self.qualify("qualify-historical-gate", {"gate": "fee-contract"})
        gate_run = self.apply(
            "prepare-historical-gate", "prepare-formal", scope={"gate": "fee-contract"},
            timeout_seconds=5,
        )
        self.run_prepared(gate_run, expected_exit=0, formal=True)
        self.record("record-historical-gate", gate_run)
        self.apply("release-historical-gate", "release", gate="fee-contract", attempt_id=gate_run["attempt_id"])

        (self.workspace / "tests" / "test_consumer.py").write_text(
            "from pathlib import Path\nimport sys\nimport unittest\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
            "class CheckoutExample(unittest.TestCase):\n"
            "    def test_consumer_uses_fee_contract(self):\n"
            "        from ui.checkout import fee\n"
            "        self.assertEqual(fee(99), 10)\n"
            "if __name__ == '__main__':\n    unittest.main()\n",
            encoding="utf-8",
        )
        self.open_example("checkout")
        red = self.apply("checkout-probe", "prepare", example="checkout", purpose="probe", timeout_seconds=5)
        self.run_prepared(red, expected_exit=1, test_file="tests/test_consumer.py")
        self.record("record-checkout-red", red)
        self.apply(
            "judge-checkout-red", "judge", attempt_id=red["attempt_id"], classification="valid-red",
            reason="The required public ui.checkout.fee interface is absent.", evidence=[red["receipt_path"]],
        )
        (self.workspace / "ui").mkdir()
        (self.workspace / "ui" / "checkout.py").write_text(
            "from pathlib import Path\ndef fee(amount):\n    return int(Path('src/fee.txt').read_text())\n",
            encoding="utf-8",
        )
        green = self.apply("checkout-green", "prepare", example="checkout", purpose="green", timeout_seconds=5)
        self.run_prepared(green, expected_exit=0, test_file="tests/test_consumer.py")
        self.record("record-checkout-green", green)
        self.apply(
            "close-checkout", "close", example="checkout", regression_attempt_id=green["attempt_id"],
            regression_scope="Checkout's public fee adapter and its unchanged fee dependency.",
        )
        final_head = self.commit_fixture()
        self.assertNotEqual(final_head, gate_head)

        self.assertIs(self.cycle("verify")["valid"], True)
        self.qualify("qualify-consumer-final", {"final": True})
        final_run = self.apply("consumer-final", "prepare-formal", scope={"final": True}, timeout_seconds=5)
        self.run_prepared(final_run, expected_exit=0, formal=True, test_file=None)
        self.record("record-consumer-final", final_run)
        finished = self.apply(
            "finish-consumer-final", "finish", attempt_id=final_run["attempt_id"],
            code_reviews=self.code_review_fixture(final_head),
        )
        self.assertEqual(finished["status"], "ready")
        self.assertEqual(finished["head"], final_head)


if __name__ == "__main__":
    unittest.main()
