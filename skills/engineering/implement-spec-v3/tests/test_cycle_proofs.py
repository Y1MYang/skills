"""Implementation-blind tests of durable public cycle proof boundaries.

Authority: docs/plans/implement-spec-v3-runtime-contract.md, sections 2 and 3.
All execution evidence comes from the real runner in isolated workspaces.
Only the public CLI, request/receipt artifacts, and inspect output are read.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CYCLE = Path(__file__).resolve().parents[1] / "scripts" / "cycle.py"
RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "run_command.py"
ROLES = (
    "exploration", "architect", "test_author", "implementer", "runner",
    "integrator", "coverage_audit", "spec_reviewer", "standards_reviewer", "expert",
)


class CycleProofTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="v3-cycle-proofs-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        for directory in ("src", "tests", "shared"):
            (self.workspace / directory).mkdir()
        (self.workspace / "spec.md").write_text("REQ-1: The fee for 99 is 10.\n", encoding="utf-8")
        (self.workspace / "src" / "fee.txt").write_text("10", encoding="utf-8")
        (self.workspace / "shared" / "assertions.py").write_text(
            "from pathlib import Path\n"
            "def assert_fee(case):\n"
            "    case.assertEqual(Path('src/fee.txt').read_text(), '10')\n",
            encoding="utf-8",
        )
        (self.workspace / "tests" / "test_fee.py").write_text(
            "import runpy\n"
            "import unittest\n"
            "check = runpy.run_path('shared/assertions.py')['assert_fee']\n"
            "class FeeExample(unittest.TestCase):\n"
            "    def test_fee_for_99(self):\n"
            "        check(self)\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )
        self.state = self.root / "state"
        self.plan_path = self.root / "plan.json"
        self.models = {role: f"explicit-proof-fixture-{role}" for role in ROLES}
        self.plan = {
            "schema": 1, "run_id": "proof-boundary-run", "workspace": str(self.workspace),
            "spec_sources": ["spec.md"], "models": self.models,
            "budget": {"max_attempts": 12, "max_formal_failures": 3, "max_seconds": 90},
            "flows": [{"id": "main", "write_paths": ["src"]}],
            "examples": [{
                "id": "fee-99", "flow": "main", "requirement": "REQ-1/example-99",
                "depends_on": [], "snapshot": {
                    "schema": 1, "root": str(self.workspace),
                    "tests": ["tests/test_fee.py"], "contract": ["spec.md"],
                    "product": ["src"], "binding": None,
                },
            }],
            "gates": [],
        }

    def write_json(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def cycle(self, *arguments, expected_exit=0, state=None):
        # Fifteen seconds bounds one local CLI invocation, including startup;
        # it is a harness hang cap, not an acceptance performance requirement.
        result = subprocess.run(
            [sys.executable, str(CYCLE), "--state", str(state or self.state), *arguments],
            cwd=self.root, capture_output=True, text=True, encoding="utf-8",
            timeout=15, check=False,
        )
        self.assertEqual(
            result.returncode, expected_exit,
            f"Public {arguments[0]} exit was {result.returncode}; expected {expected_exit}. "
            "Raw implementation diagnostics are withheld.",
        )
        lines = result.stdout.splitlines()
        self.assertTrue(lines, "The CLI must emit a public JSON result.")
        try:
            observed = json.loads(lines[-1])
        except json.JSONDecodeError:
            self.fail("The public CLI's final stdout line must be JSON.")
        self.assertIsInstance(observed, dict)
        return observed

    def apply(self, op_id, operation, *, expected_exit=0, **fields):
        event_path = self.root / "event.json"
        self.write_json(event_path, {"schema": 1, "op_id": op_id, "op": operation, **fields})
        return self.cycle("apply", "--event", str(event_path), expected_exit=expected_exit)

    def initialize(self):
        self.write_json(self.plan_path, self.plan)
        return self.cycle("init", "--plan", str(self.plan_path))

    def git(self, *arguments):
        result = subprocess.run(
            ["git", *arguments], cwd=self.workspace, capture_output=True,
            text=True, encoding="utf-8", timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, "The isolated Git fixture must succeed.")
        return result.stdout.strip()

    def commit_fixture(self):
        self.git("add", "--all")
        self.git(
            "-c", "user.name=Cycle Proof Fixture", "-c", "user.email=proof@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "proof fixture",
        )
        return self.git("rev-parse", "HEAD")

    def run_prepared(self, prepared, *, expected_exit=0, formal=False, command=None):
        # Five seconds is the explicit fixture reservation. Twenty seconds
        # covers it, the contract's five-second cleanup, and wrapper startup.
        argv = [
            sys.executable, str(RUNNER), "--receipt", prepared["receipt_path"],
            "--cwd", str(self.workspace), "--timeout", "5",
            "--snapshot", prepared["request_path"],
        ]
        if formal:
            argv.append("--formal")
        argv.extend(["--", sys.executable, "-B", *(command or ["tests/test_fee.py"])])
        result = subprocess.run(
            argv, cwd=self.root, capture_output=True, timeout=20, check=False,
        )
        self.assertEqual(
            result.returncode, expected_exit,
            "The real runner must produce the expected fixture outcome; diagnostics are withheld.",
        )
        return json.loads(Path(prepared["receipt_path"]).read_text(encoding="utf-8"))

    def record(self, label, prepared, *, expected_exit=0):
        return self.apply(label, "record", attempt_id=prepared["attempt_id"], expected_exit=expected_exit)

    def qualify(self, label):
        # Explicit review declarations exercise the public boundary; they do
        # not claim that production implementation has undergone actual review.
        return self.apply(
            label, "qualify", scope={"final": True},
            spec_review={"review_id": f"{label}-spec", "source": "spec.md / REQ-1",
                         "independent_context": "fixture-spec-oracle", "verdict": "pass"},
            standards_review={"review_id": f"{label}-standards", "source": "fixture-tests",
                              "independent_context": "fixture-standards-oracle", "verdict": "pass"},
        )

    def finish(self, label, prepared, head, *, expected_exit=0):
        return self.apply(
            label, "finish", attempt_id=prepared["attempt_id"], expected_exit=expected_exit,
            code_reviews={
                "spec": {"head": head, "review_id": f"{label}-spec", "verdict": "pass"},
                "standards": {"head": head, "review_id": f"{label}-standards", "verdict": "pass"},
            },
        )

    def open_fee(self, label="open-fee"):
        self.apply(
            label, "open", example="fee-99", light_check={
                "source": "spec.md / REQ-1", "observation": "The public fee for 99 equals 10.",
                "expected_failure": "The assertion fails for any fee other than 10.",
                "independent_context": "implementation-blind-proof-fixture",
            },
        )

    def completed_final(self, *, include_helper=True):
        if include_helper:
            self.plan["examples"][0]["snapshot"]["tests"].append("shared/assertions.py")
        self.git("init", "--quiet")
        self.initialize()
        self.open_fee()
        probe = self.apply("prepare-probe", "prepare", example="fee-99", purpose="probe", timeout_seconds=5)
        self.run_prepared(probe)
        self.record("record-probe", probe)
        self.apply(
            "judge-existing", "judge", attempt_id=probe["attempt_id"], classification="existing",
            reason="The assertion independently requires fee 10 and rejects a different fee.",
            evidence=[probe["receipt_path"]],
        )
        regression = self.apply(
            "prepare-regression", "prepare", example="fee-99", purpose="regression", timeout_seconds=5,
        )
        self.run_prepared(regression)
        self.record("record-regression", regression)
        self.apply("close-fee", "close", example="fee-99", regression_attempt_id=regression["attempt_id"])
        head = self.commit_fixture()
        self.qualify("qualify-original")
        final = self.apply("prepare-original-final", "prepare-formal", scope={"final": True}, timeout_seconds=5)
        self.run_prepared(final, formal=True)
        self.record("record-original-final", final)
        return head, final

    def test_include_shared_helper_preserves_closed_history_and_refreshes_formal_proof(self):
        """An omitted test dependency can be included without resetting or editing state."""
        head, original_final = self.completed_final(include_helper=False)
        self.finish("finish-original", original_final, head)
        before = self.cycle("inspect")
        original_receipt = Path(original_final["receipt_path"]).read_bytes()

        included = self.apply(
            "include-shared-helper", "include", source="tests/test_fee.py imports shared/assertions.py",
            reason="Independent dependency review found the assertion helper omitted from the snapshot.",
            items=[{"example": "fee-99", "tests": ["shared/assertions.py"], "contract": [], "product": []}],
        )

        self.assertEqual(included["included_examples"], ["fee-99"])
        self.assertEqual(included["status"], "active")
        after = self.cycle("inspect")
        self.assertEqual(after["run_id"], before["run_id"])
        self.assertEqual(after["status"], "active")
        self.assertEqual(after["budget"], before["budget"])
        self.assertEqual(after["failures"], before["failures"])
        self.assertEqual(after["examples"]["fee-99"]["state"], "closed")
        self.assertEqual(after["examples"]["fee-99"]["mode"], "existing")
        self.assertEqual(after["examples"]["fee-99"]["attempt_ids"], before["examples"]["fee-99"]["attempt_ids"])
        self.assertEqual(after["active_by_flow"], {"main": None})
        self.assertEqual(after["pending_attempts"], [])
        self.assertEqual(Path(original_final["receipt_path"]).read_bytes(), original_receipt)
        self.assertIs(self.cycle("init", "--plan", str(self.plan_path))["created"], False)
        self.assertEqual(self.cycle("inspect"), after)
        self.assertIs(self.finish("reject-original-final", original_final, head, expected_exit=2)["ok"], False)
        rejected = self.apply(
            "reject-old-qualification", "prepare-formal", scope={"final": True},
            timeout_seconds=5, expected_exit=2,
        )
        self.assertIs(rejected["ok"], False)
        self.assertEqual(self.cycle("inspect"), after)

        self.qualify("qualify-with-helper")
        qualified = self.cycle("inspect")
        self.assertIs(
            self.finish("reject-old-final-after-qualify", original_final, head, expected_exit=2)["ok"],
            False,
        )
        self.assertEqual(self.cycle("inspect"), qualified)
        refreshed = self.apply(
            "prepare-final-with-helper", "prepare-formal", scope={"final": True}, timeout_seconds=5,
        )
        request = json.loads(Path(refreshed["request_path"]).read_text(encoding="utf-8"))
        self.assertIn("shared/assertions.py", request["tests"])
        receipt = self.run_prepared(refreshed, formal=True)
        for phase in ("before", "after"):
            paths = [entry["path"] for entry in receipt["snapshot"][phase]["tests"]["entries"]]
            self.assertIn("shared/assertions.py", paths)
        self.record("record-final-with-helper", refreshed)
        ready = self.finish("finish-with-helper", refreshed, head)
        self.assertEqual((ready["status"], ready["head"]), ("ready", head))
        observed = self.cycle("inspect")
        self.assertEqual(observed["run_id"], before["run_id"])
        self.assertEqual(observed["budget"]["attempts_used"], before["budget"]["attempts_used"] + 1)
        self.assertEqual(observed["budget"]["formal_failures_used"], before["budget"]["formal_failures_used"])
        self.assertEqual(observed["budget"]["seconds_reserved"], 0)
        self.assertAlmostEqual(
            observed["budget"]["seconds_used"], before["budget"]["seconds_used"] + receipt["duration_seconds"],
        )
        self.assertEqual(observed["examples"]["fee-99"]["state"], "closed")
        self.assertIs(self.cycle("verify")["valid"], True)

    def test_record_settles_real_snapshot_change_without_granting_existing(self):
        """A complete runner result with changing inputs is settled but remains ineligible."""
        self.plan["examples"][0]["snapshot"]["tests"].append("shared/assertions.py")
        self.initialize()
        self.open_fee()
        prepared = self.apply(
            "prepare-changing-probe", "prepare", example="fee-99", purpose="probe", timeout_seconds=5,
        )
        receipt = self.run_prepared(prepared, command=[
            "-c",
            "import runpy; from pathlib import Path; "
            "fixture=runpy.run_path('tests/test_fee.py'); "
            "fixture['FeeExample']('test_fee_for_99').debug(); "
            "p=Path('tests/test_fee.py'); "
            "p.write_text(p.read_text()+'\\n# target changed this input during execution\\n')",
        ])
        receipt_bytes = Path(prepared["receipt_path"]).read_bytes()
        self.assertEqual((receipt["outcome"], receipt["exit_code"]), ("exited", 0))
        self.assertIs(receipt["cleanup_complete"], True)
        self.assertNotEqual(receipt["snapshot"]["before"]["tests"], receipt["snapshot"]["after"]["tests"])

        recorded = self.record("record-changing-probe", prepared)

        self.assertEqual(
            {key: recorded[key] for key in ("ok", "attempt_id", "eligible", "reason")},
            {"ok": True, "attempt_id": prepared["attempt_id"], "eligible": False, "reason": "snapshot-changed"},
        )
        self.assertIs(recorded["ok"], True)
        self.assertIs(recorded["eligible"], False)
        observed = self.cycle("inspect")
        self.assertEqual(observed["pending_attempts"], [])
        self.assertEqual(observed["active_by_flow"], {"main": "fee-99"})
        self.assertEqual(observed["budget"], {
            "attempts_used": 1, "formal_failures_used": 0,
            "seconds_used": receipt["duration_seconds"], "seconds_reserved": 0,
        })
        self.assertEqual(len(observed["failures"]), 1)
        failure = observed["failures"][0]
        self.assertEqual(failure["attempt_id"], prepared["attempt_id"])
        self.assertEqual(failure["classification"], "ineligible")
        self.assertEqual(failure["reason"], "snapshot-changed")
        self.assertIs(failure["resolved"], False)
        self.assertEqual(failure["diagnoses"], [])
        self.assertEqual(Path(prepared["receipt_path"]).read_bytes(), receipt_bytes)
        self.assertEqual(self.record("record-changing-probe", prepared), recorded)
        self.assertEqual(self.cycle("inspect"), observed)
        rejected = self.apply(
            "reject-changing-existing", "judge", attempt_id=prepared["attempt_id"],
            classification="existing", reason="The target assertion passed but its input changed during execution.",
            evidence=[prepared["receipt_path"]], expected_exit=2,
        )
        self.assertIs(rejected["ok"], False)
        self.assertEqual(self.cycle("inspect"), observed)
        self.assertIs(self.cycle("verify")["valid"], True)

    def test_finish_cannot_ignore_another_pending_final_attempt(self):
        """A prior successful final cannot hide a new unsettled formal reservation."""
        head, original_final = self.completed_final()
        pending = self.apply(
            "prepare-later-final", "prepare-formal", scope={"final": True}, timeout_seconds=5,
        )
        before = self.cycle("inspect")
        self.assertEqual([item["attempt_id"] for item in before["pending_attempts"]], [pending["attempt_id"]])
        self.assertEqual(before["budget"]["seconds_reserved"], 5)
        self.assertFalse(Path(pending["receipt_path"]).exists())

        rejected = self.finish("reject-final-while-pending", original_final, head, expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.assertEqual(self.cycle("inspect"), before)
        self.run_prepared(pending, formal=True)
        self.record("record-later-final", pending)
        # The rejected op_id was not consumed. With the pending work now
        # settled, this identical event may use the still-current old success.
        ready = self.finish("reject-final-while-pending", original_final, head)
        self.assertEqual((ready["status"], ready["head"]), ("ready", head))
        self.assertEqual(self.cycle("inspect")["pending_attempts"], [])
        self.assertIs(self.cycle("verify")["valid"], True)

    def test_later_formal_failure_requires_diagnosis_and_new_success_before_finish(self):
        """Old success and explanation alone cannot resolve a later real formal failure."""
        head, original_final = self.completed_final()
        failed = self.apply(
            "prepare-failing-final", "prepare-formal", scope={"final": True}, timeout_seconds=5,
        )
        receipt = self.run_prepared(failed, formal=True, expected_exit=1, command=[
            "-c",
            "import runpy; fixture=runpy.run_path('tests/test_fee.py'); "
            "fixture['FeeExample']('test_fee_for_99').debug(); "
            "raise RuntimeError('test-owned formal command failed after the requirement assertion')",
        ])
        self.assertEqual((receipt["outcome"], receipt["exit_code"]), ("exited", 1))
        self.assertEqual(receipt["snapshot"]["before"], receipt["snapshot"]["after"])
        self.assertEqual(receipt["formal"]["head_before"], head)
        self.assertEqual(receipt["formal"]["head_after"], head)
        self.assertIs(receipt["formal"]["clean_before"], True)
        self.assertIs(receipt["formal"]["clean_after"], True)
        self.record("record-failing-final", failed)
        before = self.cycle("inspect")
        self.assertEqual(before["pending_attempts"], [])
        self.assertEqual(before["budget"]["formal_failures_used"], 1)
        self.assertEqual(len(before["failures"]), 1)
        self.assertEqual(before["failures"][0]["attempt_id"], failed["attempt_id"])
        self.assertIs(before["failures"][0]["resolved"], False)
        self.assertEqual(before["failures"][0]["diagnoses"], [])

        rejected = self.finish("reject-final-after-failure", original_final, head, expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.assertEqual(self.cycle("inspect"), before)
        rejected_retry = self.apply(
            "prepare-post-diagnosis-final", "prepare-formal", scope={"final": True},
            timeout_seconds=5, expected_exit=2,
        )
        self.assertIs(rejected_retry["ok"], False)
        self.assertEqual(self.cycle("inspect"), before)
        self.apply(
            "diagnose-failing-final", "diagnose", attempt_id=failed["attempt_id"],
            reason="The test-owned formal command raised after the unchanged requirement assertion passed.",
            evidence=[failed["receipt_path"]],
            next_action="Execute the original acceptance command again in a new formal attempt.",
        )
        diagnosed = self.cycle("inspect")
        self.assertEqual(diagnosed["budget"], before["budget"])
        self.assertEqual(diagnosed["failures"][0]["attempt_id"], failed["attempt_id"])
        self.assertIs(diagnosed["failures"][0]["resolved"], False)
        self.assertEqual(len(diagnosed["failures"][0]["diagnoses"]), 1)
        self.assertIs(self.finish("reject-explanation-only", original_final, head, expected_exit=2)["ok"], False)
        self.assertEqual(self.cycle("inspect"), diagnosed)

        refreshed = self.apply(
            "prepare-post-diagnosis-final", "prepare-formal", scope={"final": True}, timeout_seconds=5,
        )
        success = self.run_prepared(refreshed, formal=True)
        self.record("record-post-diagnosis-final", refreshed)
        ready = self.finish("finish-post-diagnosis-final", refreshed, head)
        self.assertEqual((ready["status"], ready["head"]), ("ready", head))
        observed = self.cycle("inspect")
        self.assertEqual(observed["pending_attempts"], [])
        self.assertEqual(len(observed["failures"]), 1)
        self.assertEqual(observed["failures"][0]["attempt_id"], failed["attempt_id"])
        self.assertEqual(observed["failures"][0]["classification"], before["failures"][0]["classification"])
        self.assertEqual(observed["failures"][0]["diagnoses"], diagnosed["failures"][0]["diagnoses"])
        self.assertIs(observed["failures"][0]["resolved"], True)
        self.assertEqual(observed["budget"]["formal_failures_used"], 1)
        self.assertEqual(observed["budget"]["attempts_used"], diagnosed["budget"]["attempts_used"] + 1)
        self.assertAlmostEqual(observed["budget"]["seconds_used"], diagnosed["budget"]["seconds_used"] + success["duration_seconds"])
        self.assertIs(self.cycle("verify")["valid"], True)

    @unittest.skipUnless(os.name == "nt", "This case observes native Windows path aliases.")
    def test_windows_spec_case_alias_cannot_start_a_new_scope_budget(self):
        """Different casing for the same source file cannot mint another active run."""
        source = self.workspace / "spec.md"
        alias = self.workspace / "SPEC.MD"
        if not alias.exists() or not source.samefile(alias):
            self.skipTest("The fixture directory is case-sensitive; these names are different objects.")
        self.plan["examples"][0]["snapshot"]["tests"].append("shared/assertions.py")
        # Accept the alias first, so rejecting all uppercase spellings cannot
        # masquerade as preserving one scope for equivalent source paths.
        self.plan["spec_sources"] = ["SPEC.MD"]
        self.initialize()
        self.open_fee()
        reserved = self.apply(
            "reserve-original-scope", "prepare", example="fee-99", purpose="probe", timeout_seconds=5,
        )
        before = self.cycle("inspect")
        self.assertEqual(before["budget"]["attempts_used"], 1)
        self.assertEqual([item["attempt_id"] for item in before["pending_attempts"]], [reserved["attempt_id"]])
        other_plan_path = self.root / "alias-plan.json"
        self.write_json(other_plan_path, {**self.plan, "run_id": "case-alias-new-run", "spec_sources": ["spec.md"]})

        rejected = self.cycle(
            "init", "--plan", str(other_plan_path), state=self.root / "alias-state", expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertEqual(self.cycle("inspect"), before)
        self.assertIs(self.cycle("verify")["valid"], True)

    @unittest.skipUnless(os.name == "nt", "This case observes native Windows path aliases.")
    def test_windows_case_alias_does_not_hide_parent_child_write_overlap(self):
        """A differently cased child path remains inside the first flow's directory."""
        product = self.workspace / "src" / "fee.txt"
        alias = self.workspace / "SRC" / "fee.txt"
        if not alias.exists() or not product.samefile(alias):
            self.skipTest("The fixture directory is case-sensitive; these names are different objects.")
        self.plan["examples"][0]["snapshot"]["tests"].append("shared/assertions.py")
        self.plan["flows"][0]["write_paths"] = ["SRC"]
        invalid_plan = {
            **self.plan,
            "flows": [*self.plan["flows"], {"id": "alias-writer", "write_paths": ["src/fee.txt"]}],
        }
        self.write_json(self.plan_path, invalid_plan)

        rejected = self.cycle("init", "--plan", str(self.plan_path), expected_exit=2)

        self.assertIs(rejected["ok"], False)
        # Rejection must leave the scope available for a valid original plan.
        initialized = self.initialize()
        self.assertIs(initialized["created"], True)
        observed = self.cycle("inspect")
        self.assertEqual(observed["active_by_flow"], {"main": None})
        self.assertEqual(observed["budget"], {
            "attempts_used": 0, "formal_failures_used": 0, "seconds_used": 0, "seconds_reserved": 0,
        })
        self.assertIs(self.cycle("verify")["valid"], True)

    def test_new_spec_content_after_ready_starts_a_new_run_and_preserves_old_history(self):
        """A completed historical candidate permits a genuinely changed requirement run."""
        head, original_final = self.completed_final()
        self.finish("finish-previous-requirement", original_final, head)
        before = self.cycle("inspect")
        original_receipt = Path(original_final["receipt_path"]).read_bytes()
        self.assertEqual(before["status"], "ready")
        self.assertGreater(before["budget"]["attempts_used"], 0)
        (self.workspace / "spec.md").write_text("REQ-1: The fee for 99 is now 11.\n", encoding="utf-8")
        new_head = self.commit_fixture()
        self.assertNotEqual(new_head, head)
        next_plan_path = self.root / "next-requirement.json"
        next_state = self.root / "next-requirement-state"
        self.write_json(next_plan_path, {**self.plan, "run_id": "next-requirement-run"})

        created = self.cycle("init", "--plan", str(next_plan_path), state=next_state)

        self.assertIs(created["created"], True)
        self.assertEqual(created["run_id"], "next-requirement-run")
        new_run = self.cycle("inspect", state=next_state)
        self.assertEqual(new_run["run_id"], "next-requirement-run")
        self.assertEqual(new_run["status"], "active")
        self.assertEqual(new_run["models"], self.models)
        self.assertEqual(new_run["budget"], {
            "attempts_used": 0, "formal_failures_used": 0, "seconds_used": 0, "seconds_reserved": 0,
        })
        self.assertEqual(new_run["pending_attempts"], [])
        self.assertEqual(new_run["failures"], [])
        self.assertEqual(new_run["examples"]["fee-99"]["state"], "planned")
        self.assertEqual(new_run["examples"]["fee-99"]["attempt_ids"], [])
        previous_run = self.cycle("inspect")
        for field in ("run_id", "models", "budget", "failures"):
            self.assertEqual(previous_run[field], before[field])
        for field in ("state", "mode", "attempt_ids"):
            self.assertEqual(previous_run["examples"]["fee-99"][field], before["examples"]["fee-99"][field])
        self.assertEqual(Path(original_final["receipt_path"]).read_bytes(), original_receipt)
        self.assertIs(self.cycle("verify", state=next_state)["valid"], True)

    @unittest.skipUnless(os.name == "nt", "This case observes native Windows path aliases.")
    def test_windows_duplicate_source_aliases_cannot_mint_another_scope_budget(self):
        """Adding a second spelling of the same source does not enlarge the scope set."""
        source = self.workspace / "spec.md"
        alias = self.workspace / "SPEC.MD"
        if not alias.exists() or not source.samefile(alias):
            self.skipTest("The fixture directory is case-sensitive; these names are different objects.")
        self.plan["examples"][0]["snapshot"]["tests"].append("shared/assertions.py")
        self.initialize()
        self.open_fee()
        reserved = self.apply(
            "reserve-source-set", "prepare", example="fee-99", purpose="probe", timeout_seconds=5,
        )
        before = self.cycle("inspect")
        self.assertEqual(before["budget"]["attempts_used"], 1)
        self.assertEqual([item["attempt_id"] for item in before["pending_attempts"]], [reserved["attempt_id"]])
        duplicate_plan_path = self.root / "duplicate-source-plan.json"
        self.write_json(duplicate_plan_path, {
            **self.plan, "run_id": "duplicate-source-new-run", "spec_sources": ["spec.md", "SPEC.MD"],
        })

        rejected = self.cycle(
            "init", "--plan", str(duplicate_plan_path),
            state=self.root / "duplicate-source-state", expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertEqual(self.cycle("inspect"), before)
        self.assertIs(self.cycle("verify")["valid"], True)


    def test_include_existing_and_new_dependency_rejects_without_partial_append(self):
        """One already-declared path rejects the whole include at a safe boundary."""
        # This real assertion dependency is intentionally omitted from the
        # original declaration so the include event has a genuinely new path.
        (self.workspace / "tests" / "extra.py").write_text("EXPECTED_FEE = '10'\n", encoding="utf-8")
        (self.workspace / "shared" / "assertions.py").write_text(
            "from pathlib import Path\n"
            "import runpy\n"
            "def assert_fee(case):\n"
            "    expected = runpy.run_path('tests/extra.py')['EXPECTED_FEE']\n"
            "    case.assertEqual(Path('src/fee.txt').read_text(), expected)\n",
            encoding="utf-8",
        )
        head, original_final = self.completed_final()
        self.finish("finish-before-invalid-include", original_final, head)
        original_request = json.loads(Path(original_final["request_path"]).read_text(encoding="utf-8"))
        self.assertIn("tests/test_fee.py", original_request["tests"])
        self.assertNotIn("tests/extra.py", original_request["tests"])
        before = self.cycle("inspect")
        self.assertEqual(before["status"], "ready")
        self.assertEqual(before["examples"]["fee-99"]["state"], "closed")
        self.assertEqual(before["active_by_flow"], {"main": None})
        self.assertEqual(before["pending_attempts"], [])

        rejected = self.apply(
            "include-duplicate-and-new", "include",
            source="shared/assertions.py loads tests/extra.py for the fee assertion",
            reason="Dependency review found an omitted helper alongside an already declared test.",
            items=[{
                "example": "fee-99", "tests": ["tests/test_fee.py", "tests/extra.py"],
                "contract": [], "product": [],
            }],
            expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertEqual(self.cycle("inspect"), before)
        unchanged = self.apply(
            "prepare-after-invalid-include", "prepare-formal", scope={"final": True}, timeout_seconds=5,
        )
        unchanged_request = json.loads(Path(unchanged["request_path"]).read_text(encoding="utf-8"))
        self.assertEqual(unchanged_request["tests"], original_request["tests"])
        self.assertNotIn("tests/extra.py", unchanged_request["tests"])
        self.run_prepared(unchanged, formal=True)
        self.record("record-after-invalid-include", unchanged)
        ready = self.finish("finish-after-invalid-include", unchanged, head)
        self.assertEqual((ready["status"], ready["head"]), ("ready", head))
        before_corrected = self.cycle("inspect")
        self.assertEqual(before_corrected["pending_attempts"], [])
        # A rejected op_id remains available. The genuinely new dependency
        # must still be accepted when the duplicate is removed from the event.
        included = self.apply(
            "include-duplicate-and-new", "include",
            source="shared/assertions.py loads tests/extra.py for the fee assertion",
            reason="Dependency review found an omitted helper alongside an already declared test.",
            items=[{"example": "fee-99", "tests": ["tests/extra.py"], "contract": [], "product": []}],
        )
        self.assertEqual(included["included_examples"], ["fee-99"])
        self.assertEqual(included["status"], "active")
        after_corrected = self.cycle("inspect")
        self.assertEqual(after_corrected["last_seq"], before_corrected["last_seq"] + 1)
        self.assertEqual(after_corrected["budget"], before_corrected["budget"])
        self.assertEqual(after_corrected["examples"]["fee-99"]["state"], "closed")
        self.qualify("qualify-after-corrected-include")
        refreshed = self.apply(
            "prepare-after-corrected-include", "prepare-formal", scope={"final": True}, timeout_seconds=5,
        )
        refreshed_request = json.loads(Path(refreshed["request_path"]).read_text(encoding="utf-8"))
        self.assertEqual(refreshed_request["tests"], sorted([*original_request["tests"], "tests/extra.py"]))
        receipt = self.run_prepared(refreshed, formal=True)
        for phase in ("before", "after"):
            paths = [entry["path"] for entry in receipt["snapshot"][phase]["tests"]["entries"]]
            self.assertIn("tests/extra.py", paths)
        self.record("record-after-corrected-include", refreshed)
        ready = self.finish("finish-after-corrected-include", refreshed, head)
        self.assertEqual((ready["status"], ready["head"]), ("ready", head))
        self.assertEqual(self.cycle("inspect")["pending_attempts"], [])
        self.assertIs(self.cycle("verify")["valid"], True)


if __name__ == "__main__":
    unittest.main()
