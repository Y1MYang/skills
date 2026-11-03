"""Independent public-CLI safety cases for the v3 runtime contract.

Authority: docs/plans/implement-spec-v3-runtime-contract.md, sections 1 and 3.
Production source is outside this author's input boundary. Every execution
receipt used below comes from run_command.py in a test-owned workspace.
"""

import json
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys
import threading
import unittest

import test_cycle as fixtures


class CycleSafetyTests(unittest.TestCase):
    # Reuse fixture operations without inheriting and rerunning its test cases.
    setUp = fixtures.CycleContractTests.setUp
    write_json = fixtures.CycleContractTests.write_json
    initialize = fixtures.CycleContractTests.initialize
    apply = fixtures.CycleContractTests.apply
    open_example = fixtures.CycleContractTests.open_example
    install_fee_fixture = fixtures.CycleContractTests.install_fee_fixture
    run_prepared = fixtures.CycleContractTests.run_prepared
    record = fixtures.CycleContractTests.record
    establish_valid_red = fixtures.CycleContractTests.establish_valid_red

    def cycle_result(self, *arguments):
        result = subprocess.run(
            [sys.executable, str(fixtures.CYCLE), "--state", str(self.state), *arguments],
            cwd=self.root, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=15, check=False,
        )
        self.assertIn(result.returncode, (0, 2), "Public CLI must use its documented exit codes.")
        lines = result.stdout.splitlines()
        self.assertTrue(lines, "Public CLI must emit a final JSON object.")
        try:
            output = json.loads(lines[-1])
        except json.JSONDecodeError:
            self.fail("Public CLI final stdout line must be JSON.")
        self.assertIsInstance(output, dict)
        self.assertIs(output.get("ok"), result.returncode == 0)
        if result.returncode == 2:
            self.assertIsInstance(output.get("error"), dict)
            for field in ("code", "message"):
                self.assertIsInstance(output["error"].get(field), str)
        return result.returncode, output

    def cycle(self, *arguments, expected_exit=0):
        code, output = self.cycle_result(*arguments)
        accepted = expected_exit if isinstance(expected_exit, tuple) else (expected_exit,)
        self.assertIn(code, accepted, "Public CLI result violated the expected acceptance decision.")
        return output

    def test_changed_criterion_cannot_use_old_green_for_its_first_close(self):
        """A fresh passing regression cannot repair an unclosed, stale Red/Green pair."""
        self.establish_valid_red()
        (self.workspace / "src" / "fee.txt").write_text("10", encoding="utf-8")
        green = self.apply(
            "criterion-green", "prepare", example="fee-99", purpose="green",
            timeout_seconds=5,
        )
        self.run_prepared(green, expected_exit=0)
        self.record("record-criterion-green", green)
        # Change both declared criterion groups after Green, before preparing a
        # fresh regression. The changed criterion still passes on fee 10.
        test_path = self.workspace / "tests" / "test_fee.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8") + "\n# Exact fee text is required.\n",
            encoding="utf-8",
        )
        (self.workspace / "spec.md").write_text(
            "REQ-1: 99 costs 10, represented by the exact text '10'.\n",
            encoding="utf-8",
        )
        before_prepare = self.cycle("inspect")
        regression = self.apply(
            "regression-after-criterion-change", "prepare", example="fee-99",
            purpose="regression", timeout_seconds=5, expected_exit=(0, 2),
        )
        if not regression["ok"]:
            # Early rejection is also conforming; it cannot consume a new
            # attempt or turn the unclosed example into a historical close.
            after_prepare = self.cycle("inspect")
            self.assertEqual(after_prepare["budget"], before_prepare["budget"])
            self.assertEqual(after_prepare["last_seq"], before_prepare["last_seq"])
            self.assertEqual(after_prepare["active_by_flow"]["main"], "fee-99")
            self.assertEqual(
                after_prepare["examples"]["fee-99"]["attempt_ids"],
                before_prepare["examples"]["fee-99"]["attempt_ids"],
            )
            self.assertNotEqual(after_prepare["examples"]["fee-99"]["state"], "closed")
            return
        self.run_prepared(regression, expected_exit=0)
        self.apply(
            "record-new-criterion-regression", "record",
            attempt_id=regression["attempt_id"], expected_exit=(0, 2),
        )
        before_close = self.cycle("inspect")

        rejected = self.apply(
            "first-close-with-stale-green", "close", example="fee-99",
            regression_attempt_id=regression["attempt_id"], expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        after_close = self.cycle("inspect")
        self.assertNotEqual(after_close["examples"]["fee-99"]["state"], "closed")
        self.assertEqual(after_close["active_by_flow"]["main"], "fee-99")
        self.assertEqual(after_close["budget"], before_close["budget"])
        self.assertEqual(after_close["last_seq"], before_close["last_seq"])

    def independent_flow_events(self, flow_count, *, max_attempts):
        self.install_fee_fixture("10")
        template = self.plan["examples"][0]
        self.plan["budget"]["max_attempts"] = max_attempts
        self.plan["flows"] = [
            {"id": f"flow-{index}", "write_paths": [f"src/flow-{index}"]}
            for index in range(flow_count)
        ]
        self.plan["examples"] = [
            {**template, "id": f"example-{index}", "flow": f"flow-{index}",
             "requirement": f"REQ-1/read-{index}"}
            for index in range(flow_count)
        ]
        self.initialize()
        event_paths = []
        for index in range(flow_count):
            self.open_example(f"example-{index}")
            path = self.root / f"prepare-{index}.json"
            self.write_json(path, {
                "schema": 1, "op_id": f"concurrent-probe-{index}", "op": "prepare",
                "example": f"example-{index}", "purpose": "probe", "timeout_seconds": 5,
            })
            event_paths.append(path)
        return event_paths

    def parallel_apply(self, event_paths):
        start = threading.Barrier(len(event_paths), timeout=10)

        def prepare(path):
            start.wait()
            return self.cycle_result("apply", "--event", str(path))

        # Every worker owns a distinct immutable event file. The barrier only
        # coordinates test callers; it imposes no CLI performance deadline.
        with ThreadPoolExecutor(max_workers=len(event_paths)) as pool:
            pending = [pool.submit(prepare, path) for path in event_paths]
            return [future.result(timeout=25) for future in pending]

    def test_concurrent_flows_cannot_both_spend_the_final_attempt(self):
        """One remaining attempt is a shared limit even for independent flows."""
        event_paths = self.independent_flow_events(6, max_attempts=1)
        before = self.cycle("inspect")
        results = self.parallel_apply(event_paths)
        successes = [(index, output) for index, (code, output) in enumerate(results) if code == 0]
        self.assertLessEqual(
            len(successes), 1,
            "Concurrent public commands cannot both succeed using one remaining attempt.",
        )
        # All calls may return busy. Once competitors have finished, retry one
        # identical event to exercise the still-available reservation.
        if not successes:
            successes = [(0, self.cycle("apply", "--event", str(event_paths[0])))]
        winner_index, prepared = successes[0]
        reserved = self.cycle("inspect")
        self.assertEqual(reserved["budget"], {
            "attempts_used": 1, "formal_failures_used": 0,
            "seconds_used": 0, "seconds_reserved": 5,
        })
        self.assertEqual(reserved["last_seq"], before["last_seq"] + 1)
        self.assertEqual(len(reserved["pending_attempts"]), 1)
        self.assertEqual(reserved["pending_attempts"][0]["attempt_id"], prepared["attempt_id"])
        self.assertEqual(reserved["pending_attempts"][0]["example"], f"example-{winner_index}")
        for index, path in enumerate(event_paths):
            if index == winner_index:
                self.assertEqual(self.cycle("apply", "--event", str(path)), prepared)
            else:
                self.cycle("apply", "--event", str(path), expected_exit=2)
        self.assertEqual(self.cycle("inspect"), reserved)
        self.assertIs(self.cycle("verify")["valid"], True)

        self.run_prepared(prepared, expected_exit=0)
        self.record("record-concurrent-winner", prepared)
        settled = self.cycle("inspect")
        self.assertEqual(settled["budget"]["attempts_used"], 1)
        self.assertEqual(settled["budget"]["seconds_reserved"], 0)
        self.assertEqual(settled["pending_attempts"], [])
        self.assertEqual(settled["last_seq"], reserved["last_seq"] + 1)
        self.assertIs(self.cycle("verify")["valid"], True)

    def test_independent_concurrent_successes_and_busy_retries_are_never_lost(self):
        """With available quota, every accepted or retried flow keeps one attempt."""
        flow_count = 6
        event_paths = self.independent_flow_events(flow_count, max_attempts=flow_count)
        before = self.cycle("inspect")
        results = self.parallel_apply(event_paths)
        successes = {}
        for index, (code, output) in enumerate(results):
            if code == 0:
                successes[index] = output
            else:
                self.assertEqual(output["error"]["code"], "busy")
        after_parallel = self.cycle("inspect")
        self.assertEqual(after_parallel["last_seq"], before["last_seq"] + len(successes))
        self.assertEqual(after_parallel["budget"], {
            "attempts_used": len(successes), "formal_failures_used": 0,
            "seconds_used": 0, "seconds_reserved": 5 * len(successes),
        })
        self.assertCountEqual(
            [item["attempt_id"] for item in after_parallel["pending_attempts"]],
            [item["attempt_id"] for item in successes.values()],
        )
        for index, path in enumerate(event_paths):
            if index not in successes:
                # Retry the very same op_id and bytes after competing writers
                # return. A busy rejection must not permanently consume it.
                successes[index] = self.cycle("apply", "--event", str(path))
        accepted = self.cycle("inspect")
        attempt_ids = [item["attempt_id"] for item in successes.values()]
        self.assertEqual(len(set(attempt_ids)), flow_count)
        self.assertEqual(accepted["last_seq"], before["last_seq"] + flow_count)
        self.assertEqual(accepted["budget"]["attempts_used"], flow_count)
        self.assertEqual(accepted["budget"]["seconds_reserved"], 5 * flow_count)
        self.assertCountEqual(
            [item["attempt_id"] for item in accepted["pending_attempts"]], attempt_ids,
        )
        for index, path in enumerate(event_paths):
            self.assertEqual(self.cycle("apply", "--event", str(path)), successes[index])
            self.assertEqual(
                accepted["examples"][f"example-{index}"]["attempt_ids"],
                [successes[index]["attempt_id"]],
            )
        self.assertEqual(self.cycle("inspect"), accepted)
        for index in range(flow_count):
            self.run_prepared(successes[index], expected_exit=0)
            self.record(f"record-independent-{index}", successes[index])
        settled = self.cycle("inspect")
        self.assertEqual(settled["budget"]["attempts_used"], flow_count)
        self.assertEqual(settled["budget"]["seconds_reserved"], 0)
        self.assertEqual(settled["pending_attempts"], [])
        self.assertEqual(settled["last_seq"], accepted["last_seq"] + flow_count)
        self.assertIs(self.cycle("verify")["valid"], True)

    def test_invalid_event_schema_returns_json_without_consuming_sequence_or_budget(self):
        """Malformed public input is a structured rejection, never a partial command."""
        self.install_fee_fixture("10")
        self.initialize()
        self.open_example()
        valid = {
            "schema": 1, "op_id": "schema-probe", "op": "prepare",
            "example": "fee-99", "purpose": "probe", "timeout_seconds": 5,
        }
        cases = [
            ("array-root", []),
            ("unknown-field", {**valid, "unrecognized": "must reject"}),
            ("boolean-schema", {**valid, "schema": True}),
            ("boolean-timeout", {**valid, "timeout_seconds": True}),
            ("infinite-timeout", {**valid, "timeout_seconds": float("inf")}),
            ("nan-timeout", {**valid, "timeout_seconds": float("nan")}),
            ("array-operation", {**valid, "op": []}),
            ("object-example", {**valid, "example": {"id": "fee-99"}}),
        ]
        before = self.cycle("inspect")
        for name, event in cases:
            path = self.root / f"invalid-{name}.json"
            self.write_json(path, event)
            # Stop at the first failed boundary so later invalid inputs cannot
            # be "rejected" merely because a prior invalid event changed state.
            rejected = self.cycle("apply", "--event", str(path), expected_exit=2)
            self.assertIs(rejected["ok"], False, name)
            after = self.cycle("inspect")
            self.assertEqual(after["last_seq"], before["last_seq"], name)
            self.assertEqual(after["budget"], before["budget"], name)
            self.assertEqual(after["pending_attempts"], [], name)
            self.assertEqual(after["examples"], before["examples"], name)
            self.assertEqual(after["active_by_flow"], before["active_by_flow"], name)
        # The same valid op_id remains available after schema failures. A CLI
        # that simply refuses all prepares cannot satisfy this positive control.
        valid_path = self.root / "valid-after-invalid-inputs.json"
        self.write_json(valid_path, valid)
        prepared = self.cycle("apply", "--event", str(valid_path))
        accepted = self.cycle("inspect")
        self.assertEqual(accepted["last_seq"], before["last_seq"] + 1)
        self.assertEqual(accepted["budget"]["attempts_used"], 1)
        self.run_prepared(prepared, expected_exit=0)
        self.record("record-schema-positive-control", prepared)
        self.assertIs(self.cycle("verify")["valid"], True)


if __name__ == "__main__":
    unittest.main()
