"""Implementation-blind behavioral checks for the v3 performance contract.

Authority: docs/plans/implement-spec-v3-performance-contract.md (2026-11-03, revision 1),
plus the public runtime contract. Product execution belongs to the separate
Runner; this author reads only contracts and test materials.
"""

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest

import test_cycle as fixtures
import test_cycle_proofs as proof_fixtures
import test_cycle_recovery as recovery_fixtures


class CyclePerformanceTests(unittest.TestCase):
    # Reuse only test-owned public-CLI fixture operations, without collecting
    # the original class's test methods for a second time.
    setUp = fixtures.CycleContractTests.setUp
    write_json = fixtures.CycleContractTests.write_json
    initialize = fixtures.CycleContractTests.initialize
    apply = fixtures.CycleContractTests.apply
    cycle = fixtures.CycleContractTests.cycle
    open_example = fixtures.CycleContractTests.open_example
    install_fee_fixture = fixtures.CycleContractTests.install_fee_fixture
    native_process = recovery_fixtures.CycleRecoveryTests.native_process
    run_prepared = fixtures.CycleContractTests.run_prepared
    record = fixtures.CycleContractTests.record
    complete_existing_example = fixtures.CycleContractTests.complete_existing_example
    git = fixtures.CycleContractTests.git
    commit_fixture = fixtures.CycleContractTests.commit_fixture
    qualify = fixtures.CycleContractTests.qualify
    run_prepared_command = proof_fixtures.CycleProofTests.run_prepared

    def event(self, op_id, operation, **fields):
        return {"schema": 1, "op_id": op_id, "op": operation, **fields}

    def open_event(self, op_id="open-fee", example="fee-99"):
        return self.event(
            op_id, "open", example=example,
            light_check={
                "source": "spec.md / REQ-1",
                "observation": "The public fee result is checked by its independent example.",
                "expected_failure": "A missing or incorrect fee violates the criterion.",
                "independent_context": "performance-contract-blind-author",
            },
        )

    def batch(self, events, *, expected_exit=0):
        path = self.root / "batch.json"
        self.write_json(path, {"schema": 1, "events": events})
        return self.cycle("batch", "--events", str(path), expected_exit=expected_exit)

    def execute_request(self, label, *, purpose="probe", argv=None, timeout_seconds=5):
        return {
            "schema": 1,
            "prepare": self.event(
                f"prepare-{label}", "prepare", example="fee-99", purpose=purpose,
                timeout_seconds=timeout_seconds,
            ),
            "record_op_id": f"record-{label}",
            "argv": argv or [sys.executable, "-B", "tests/test_fee.py"],
        }

    def execute(self, request, *, expected_exit=0):
        path = self.root / "execute.json"
        self.write_json(path, request)
        return self.cycle("execute", "--request", str(path), expected_exit=expected_exit)

    def start_waiting_execute(self):
        # The 90-second reservation covers bounded control CLI observations
        # while the target waits for our socket signal. The 10-second startup
        # wait and 15-second collection cap are harness limits, not an SLA.
        self.plan["budget"]["max_seconds"] = 180
        self.initialize()
        self.open_example()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        listener.settimeout(10)
        self.addCleanup(listener.close)
        marker = self.root / "waiting-launches.txt"
        target = (
            "import socket; from pathlib import Path; "
            f"p=Path({str(marker)!r}); "
            "f=p.open('a',encoding='utf-8'); f.write('launch\\n'); f.close(); "
            f"s=socket.create_connection({listener.getsockname()!r}); "
            "s.sendall(b'R'); s.recv(1); s.close()"
        )
        request = self.execute_request(
            "waiting", argv=[sys.executable, "-B", "-c", target], timeout_seconds=90,
        )
        path = self.root / "waiting-execute.json"
        self.write_json(path, request)
        stdout_path = self.root / "waiting.stdout"
        stdout = stdout_path.open("wb")
        stderr = (self.root / "waiting.stderr").open("wb")
        self.addCleanup(stdout.close)
        self.addCleanup(stderr.close)
        controller = subprocess.Popen(
            [sys.executable, str(fixtures.CYCLE), "--state", str(self.state),
             "execute", "--request", str(path)],
            cwd=self.root, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
        )
        connections = []

        def cleanup():
            for connection in connections:
                try:
                    connection.sendall(b"X")
                except OSError:
                    pass
                connection.close()
            try:
                controller.wait(timeout=10)
            except subprocess.TimeoutExpired:
                controller.kill()
                controller.wait(timeout=5)

        self.addCleanup(cleanup)
        startup_deadline = time.monotonic() + 10
        connection, _ = listener.accept()
        connections.append(connection)
        remaining = startup_deadline - time.monotonic()
        self.assertGreater(remaining, 0, "The complete startup acknowledgement must fit its evidence wait.")
        connection.settimeout(remaining)
        self.assertEqual(connection.recv(1), b"R", "The target must acknowledge its own live execution.")
        self.assertIsNone(controller.poll())
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")
        return request, controller, connection, marker, stdout_path

    def separate_example(self, example_id="other-example", *, depends_on=None):
        return {
            "id": example_id, "flow": "other", "requirement": f"REQ-2/{example_id}",
            "depends_on": depends_on or [],
            "snapshot": {
                "schema": 1, "root": str(self.workspace), "tests": ["other-tests"],
                "contract": ["spec.md"], "product": ["other"], "binding": None,
            },
        }

    def prepare_unrelated_work(self):
        self.install_fee_fixture("10")
        self.plan["examples"][0]["snapshot"]["tests"] = ["tests/test_fee.py"]
        self.plan["flows"].append({"id": "other", "write_paths": ["other"]})
        self.plan["examples"].append(self.separate_example())
        self.initialize()
        self.open_example()
        prepared = self.apply(
            "pending-original", "prepare", example="fee-99", purpose="probe", timeout_seconds=5,
        )
        return prepared, self.cycle("inspect"), Path(prepared["request_path"]).read_bytes()

    def assert_original_attempt_unchanged_and_recordable(self, prepared, before, request_bytes, *, example="fee-99"):
        after = self.cycle("inspect")
        self.assertEqual(after["pending_attempts"], before["pending_attempts"])
        self.assertEqual(after["budget"], before["budget"])
        for key in ("state", "attempt_ids"):
            self.assertEqual(after["examples"][example][key], before["examples"][example][key])
        self.assertEqual(after["active_by_flow"]["main"], before["active_by_flow"]["main"])
        self.assertEqual(Path(prepared["request_path"]).read_bytes(), request_bytes)
        self.run_prepared(prepared, expected_exit=0)
        recorded = self.record("record-original-after-local-edit", prepared)
        self.assertIs(recorded["ok"], True)
        final = self.cycle("inspect")
        self.assertEqual(final["pending_attempts"], [])
        self.assertEqual(final["budget"]["attempts_used"], before["budget"]["attempts_used"])
        self.assertEqual(final["budget"]["seconds_reserved"], 0)
        self.assertEqual(final["failures"], [])

    def leave_bound_formal_preparation_before_launch(self):
        """Public preflight seam; provenance: SPEC-CLI-REPLAY-20261103.

        A dirty formal candidate fails before target launch. Clearing only the
        unrelated dirt leaves the original preparation available to the real
        standalone runner. No receipt or successful execution is fabricated.
        """
        self.git("init", "--quiet")
        self.complete_existing_example()
        self.commit_fixture()
        self.qualify("qualify-bound-formal", {"final": True})
        marker = self.root / "formal-launches.txt"
        target = (
            "from pathlib import Path; import runpy; "
            f"p=Path({str(marker)!r}); "
            "f=p.open('a',encoding='utf-8'); f.write('launch\\n'); f.close(); "
            "runpy.run_path('tests/test_fee.py',run_name='__main__')"
        )
        prepare = self.event(
            "prepare-bound-formal", "prepare-formal", scope={"final": True}, timeout_seconds=5,
        )
        request = {
            "schema": 1, "prepare": prepare, "record_op_id": "record-bound-formal",
            "argv": [sys.executable, "-B", "-c", target],
        }
        dirt = self.workspace / "unrelated-preflight-dirt.txt"
        dirt.write_text("Deliberately uncommitted formal candidate.\n", encoding="utf-8")
        rejected = self.execute(request, expected_exit=2)
        self.assertIs(rejected["ok"], False)
        self.assertFalse(marker.exists(), "The dirty formal preflight must prevent target launch.")
        prepared = self.apply(
            prepare["op_id"], "prepare-formal", scope={"final": True}, timeout_seconds=5,
        )
        self.assertFalse(Path(prepared["receipt_path"]).exists())
        self.assertEqual(
            [item["attempt_id"] for item in self.cycle("inspect")["pending_attempts"]],
            [prepared["attempt_id"]],
        )
        dirt.unlink()
        return request, prepared, target, marker

    def prepare_pending_final(self):
        self.git("init", "--quiet")
        self.complete_existing_example()
        self.commit_fixture()
        self.qualify("qualify-pending-final", {"final": True})
        self.apply("prepare-pending-final", "prepare-formal", scope={"final": True}, timeout_seconds=5)
        return self.cycle("inspect")

    def test_batch_open_prepare_replay_keeps_original_events_and_single_reservation(self):
        """PERF-B01 (§2): an ordered batch has ordinary event identity and replay."""
        self.initialize()
        before = self.cycle("inspect")
        events = [
            self.open_event(),
            self.event(
                "probe-fee", "prepare", example="fee-99", purpose="probe",
                timeout_seconds=5,
            ),
        ]

        first = self.batch(events)

        self.assertIs(first["ok"], True)
        self.assertEqual(len(first["results"]), 2)
        opened, prepared = first["results"]
        self.assertEqual(opened["example"], "fee-99")
        self.assertEqual(opened["state"], "open")
        self.assertEqual(opened["seq"], before["last_seq"] + 1)
        self.assertEqual(prepared["seq"], opened["seq"] + 1)
        after = self.cycle("inspect")
        self.assertEqual(after["last_seq"], before["last_seq"] + 2)
        self.assertEqual(after["budget"]["attempts_used"], 1)
        self.assertEqual(after["budget"]["seconds_reserved"], 5)
        self.assertEqual(after["active_by_flow"]["main"], "fee-99")
        self.assertEqual(
            [item["attempt_id"] for item in after["pending_attempts"]],
            [prepared["attempt_id"]],
        )

        self.assertEqual(self.batch(events), first)
        self.assertEqual(
            self.apply("probe-fee", "prepare", example="fee-99", purpose="probe", timeout_seconds=5),
            prepared,
        )
        self.assertEqual(self.cycle("inspect"), after)
        self.assertIs(self.cycle("verify")["valid"], True)

    def test_batch_state_rejection_keeps_prefix_and_retries_repaired_suffix(self):
        """PERF-B02 (§2): a rejected item consumes neither its ID nor later work."""
        self.initialize()
        before = self.cycle("inspect")
        replacement_models = {role: f"resumed-{role}" for role in fixtures.ROLES}
        events = [
            self.open_event(),
            self.event(
                "probe-after-open", "prepare", example="fee-99", purpose="green",
                timeout_seconds=5,
            ),
            self.event("later-invocation", "invocation", kind="resume", models=replacement_models),
        ]

        rejected = self.batch(events, expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.assertEqual(rejected["failed_index"], 1)
        self.assertEqual(len(rejected["results"]), 1)
        self.assertTrue(rejected["error"]["code"])
        prefix = self.cycle("inspect")
        self.assertEqual(prefix["last_seq"], before["last_seq"] + 1)
        self.assertEqual(prefix["active_by_flow"]["main"], "fee-99")
        self.assertEqual(prefix["budget"], before["budget"])
        self.assertEqual(prefix["pending_attempts"], [])
        self.assertEqual(prefix["models"], self.models)

        events[1]["purpose"] = "probe"
        retried = self.batch(events)

        self.assertEqual(retried["results"][0], rejected["results"][0])
        self.assertEqual(len(retried["results"]), 3)
        after = self.cycle("inspect")
        self.assertEqual(after["last_seq"], before["last_seq"] + 3)
        self.assertEqual(after["budget"]["attempts_used"], 1)
        self.assertEqual(after["budget"]["seconds_reserved"], 5)
        self.assertEqual(after["models"], replacement_models)
        self.assertEqual(
            after["pending_attempts"][0]["attempt_id"], retried["results"][1]["attempt_id"],
        )

    def test_batch_unknown_later_operation_rejects_before_any_mutation(self):
        """PERF-B03 (§2): all common headers are validated before the first item."""
        self.initialize()
        before = self.cycle("inspect")

        rejected = self.batch([
            self.open_event(),
            self.event("unrecognized-operation", "not-a-runtime-operation"),
        ], expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.assertEqual(rejected["results"], [])
        self.assertIsNone(rejected["failed_index"])
        self.assertTrue(rejected["error"]["code"])
        self.assertEqual(self.cycle("inspect"), before)
        accepted = self.batch([self.open_event()])
        self.assertEqual(accepted["results"][0]["seq"], before["last_seq"] + 1)

    def test_batch_operation_field_failure_preserves_the_successful_prefix(self):
        """PERF-B04 (§2): operation fields are checked at their own boundary."""
        self.initialize()
        before = self.cycle("inspect")
        events = [
            self.open_event(),
            self.event("bad-timeout", "prepare", example="fee-99", purpose="probe", timeout_seconds=True),
        ]

        rejected = self.batch(events, expected_exit=2)

        self.assertEqual(rejected["failed_index"], 1)
        self.assertEqual(len(rejected["results"]), 1)
        after = self.cycle("inspect")
        self.assertEqual(after["last_seq"], before["last_seq"] + 1)
        self.assertEqual(after["budget"], before["budget"])
        self.assertEqual(after["pending_attempts"], [])
        events[1]["timeout_seconds"] = 5
        repaired = self.batch(events)
        self.assertEqual(repaired["results"][0], rejected["results"][0])
        self.assertEqual(self.cycle("inspect")["budget"]["attempts_used"], 1)

    def test_execute_records_real_nonzero_probe_without_automatic_red(self):
        """PERF-E01 (§3): execution records facts; only an explicit judge permits Green."""
        self.install_fee_fixture("0")
        self.initialize()
        self.open_example()
        before = self.cycle("inspect")

        executed = self.execute(self.execute_request("real-failure"))

        self.assertIs(executed["ok"], True)
        self.assertEqual((executed["outcome"], executed["exit_code"]), ("exited", 1))
        self.assertEqual(executed["prepare"]["attempt_id"], executed["attempt_id"])
        self.assertEqual(executed["record"]["attempt_id"], executed["attempt_id"])
        self.assertEqual(executed["record"]["seq"], executed["prepare"]["seq"] + 1)
        observed = self.cycle("inspect")
        self.assertEqual(observed["last_seq"], before["last_seq"] + 2)
        self.assertEqual(observed["budget"]["attempts_used"], 1)
        self.assertEqual(observed["budget"]["seconds_reserved"], 0)
        self.assertEqual(observed["pending_attempts"], [])
        self.assertEqual(observed["active_by_flow"]["main"], "fee-99")
        self.assertEqual(observed["failures"][0]["classification"], "unclassified")
        self.assertFalse(observed["failures"][0]["resolved"])
        self.apply(
            "green-before-judgment", "prepare", example="fee-99", purpose="green",
            timeout_seconds=5, expected_exit=2,
        )
        self.assertEqual(self.cycle("inspect"), observed)

        self.apply(
            "judge-real-red", "judge", attempt_id=executed["attempt_id"],
            classification="valid-red", reason="The actual fee is 0, while REQ-1 requires 10.",
            evidence=[executed["prepare"]["receipt_path"]],
        )
        (self.workspace / "src" / "fee.txt").write_text("10", encoding="utf-8")
        green = self.execute(self.execute_request("real-green", purpose="green"))
        self.assertEqual((green["outcome"], green["exit_code"]), ("exited", 0))
        self.assertNotEqual(green["attempt_id"], executed["attempt_id"])
        final = self.cycle("inspect")
        self.assertEqual(final["budget"]["attempts_used"], 2)
        self.assertEqual(final["failures"][0]["classification"], "valid-red")
        self.assertTrue(final["failures"][0]["resolved"])

    def test_execute_canonical_replay_returns_original_facts_without_a_second_launch(self):
        """PERF-E02 (§3): a formatting-only retry preserves one actual target effect."""
        self.install_fee_fixture("10")
        self.initialize()
        self.open_example()
        marker = self.root / "launches.txt"
        target = (
            "from pathlib import Path; import runpy; "
            f"p=Path({str(marker)!r}); "
            "f=p.open('a',encoding='utf-8'); f.write('launch\\n'); f.close(); "
            "runpy.run_path('tests/test_fee.py',run_name='__main__')"
        )
        request = self.execute_request("exact-replay", argv=[sys.executable, "-B", "-c", target])

        original = self.execute(request)
        before_retry = self.cycle("inspect")
        canonical = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(original["execution_sha256"], hashlib.sha256(canonical.encode("utf-8")).hexdigest())
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")
        reordered = {key: request[key] for key in reversed(request)}
        retry_path = self.root / "reformatted-execute.json"
        retry_path.write_text(json.dumps(reordered, ensure_ascii=False, indent=4), encoding="utf-8")

        replayed = self.cycle("execute", "--request", str(retry_path))

        self.assertEqual(replayed, original)
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")
        self.assertEqual(self.cycle("inspect"), before_retry)
        self.assertEqual(before_retry["budget"]["attempts_used"], 1)
        self.assertEqual(before_retry["pending_attempts"], [])
        self.assertIs(self.cycle("verify")["valid"], True)

    def test_execute_changed_argv_cannot_reuse_a_bound_preparation(self):
        """PERF-E03 (§3): preparation identity binds the exact command permanently."""
        self.install_fee_fixture("10")
        self.initialize()
        self.open_example()
        request = self.execute_request("immutable-command")
        original = self.execute(request)
        before = self.cycle("inspect")
        unexpected_effect = self.root / "replacement-launched.txt"
        changed = dict(request)
        changed["argv"] = [
            sys.executable, "-c",
            f"from pathlib import Path; Path({str(unexpected_effect)!r}).write_text('changed')",
        ]

        rejected = self.execute(changed, expected_exit=2)

        self.assertEqual(rejected["error"]["code"], "execution-conflict")
        self.assertFalse(unexpected_effect.exists())
        self.assertEqual(self.cycle("inspect"), before)
        self.assertEqual(self.execute(request), original)

    def test_execute_cannot_adopt_an_unbound_apply_preparation(self):
        """PERF-E04 (§3): an ordinary preparation is never retroactively executable."""
        self.install_fee_fixture("10")
        self.initialize()
        self.open_example()
        marker = self.root / "unbound-launched.txt"
        request = self.execute_request("unbound", argv=[
            sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
        ])
        preparation = request["prepare"]
        self.apply(
            preparation["op_id"], preparation["op"], example=preparation["example"],
            purpose=preparation["purpose"], timeout_seconds=preparation["timeout_seconds"],
        )
        before = self.cycle("inspect")

        rejected = self.execute(request, expected_exit=2)

        self.assertEqual(rejected["error"]["code"], "execution-unbound")
        self.assertFalse(marker.exists())
        self.assertEqual(self.cycle("inspect"), before)

    def test_waiting_execute_releases_state_and_excludes_concurrent_duplicate_launch(self):
        """PERF-E05 (§3): independent state work completes while one target waits."""
        request, controller, connection, marker, stdout_path = self.start_waiting_execute()

        invocation = self.apply("while-target-waits", "invocation", kind="resume", models=self.models)
        self.assertIs(invocation["ok"], True)
        before = self.cycle("inspect")
        self.assertEqual(len(before["pending_attempts"]), 1)
        self.assertEqual(before["budget"]["attempts_used"], 1)
        self.assertEqual(before["budget"]["seconds_reserved"], 90)
        duplicate = self.execute(request, expected_exit=2)

        self.assertEqual(duplicate["error"]["code"], "recovery-required")
        self.assertIsNone(controller.poll(), "The independent operation must finish before target release.")
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")
        self.assertEqual(self.cycle("inspect"), before)
        connection.sendall(b"X")
        self.assertEqual(controller.wait(timeout=15), 0)
        output = json.loads(stdout_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertIs(output["ok"], True)
        self.assertEqual((output["outcome"], output["exit_code"]), ("exited", 0))
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")
        after = self.cycle("inspect")
        self.assertEqual(after["pending_attempts"], [])
        self.assertEqual(after["budget"]["attempts_used"], 1)
        self.assertEqual(after["budget"]["seconds_reserved"], 0)

    @unittest.skipUnless(os.name == "nt", "Uses an identity-checked Windows handle for owned interruption")
    def test_interrupted_execute_requires_recovery_and_cannot_relaunch_after_settlement(self):
        """PERF-E06 (§3): a dead owned runner retains its charge and cannot be retried."""
        request, controller, _, marker, _ = self.start_waiting_execute()
        pending = self.cycle("inspect")["pending_attempts"][0]
        claim_path = Path(pending["receipt_path"] + ".claim.json")
        claim = json.loads(claim_path.read_text(encoding="utf-8"))
        identity = claim["controller"]
        kernel, handle, _ = self.native_process(identity["pid"], identity["birth_token"])
        self.assertTrue(kernel.TerminateProcess(handle, 98))
        self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
        controller.wait(timeout=15)
        self.assertFalse(Path(pending["receipt_path"]).exists())
        before = self.cycle("inspect")

        rejected = self.execute(request, expected_exit=2)

        self.assertEqual(rejected["error"]["code"], "recovery-required")
        self.assertEqual(self.cycle("inspect"), before)
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")
        self.apply("resume-interrupted-helper", "invocation", kind="resume", models=self.models)
        self.apply("recover-interrupted-helper", "recover", invocation_id="resume-interrupted-helper")
        recovered = self.cycle("inspect")
        self.assertEqual(recovered["pending_attempts"], [])
        self.assertEqual(recovered["budget"]["attempts_used"], 1)
        self.assertEqual(recovered["budget"]["seconds_reserved"], 0)
        self.assertEqual(recovered["budget"]["seconds_used"], 90)
        self.assertEqual(recovered["failures"][0]["attempt_id"], pending["attempt_id"])
        self.assertEqual(recovered["failures"][0]["classification"], "interrupted")

        settled = self.execute(request, expected_exit=2)
        self.assertEqual(settled["error"]["code"], "execution-settled")
        self.assertEqual(self.cycle("inspect"), recovered)
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")

    def test_execute_unknown_ownership_preserves_live_work_and_requires_recovery(self):
        """PERF-E07 (§3): incomplete claim identity grants no retry or cancellation."""
        request, controller, connection, marker, _ = self.start_waiting_execute()
        pending = self.cycle("inspect")["pending_attempts"][0]
        claim_path = Path(pending["receipt_path"] + ".claim.json")
        original_claim = claim_path.read_bytes()
        claim = json.loads(original_claim)
        # Deliberately incomplete real ownership evidence, never a forged
        # receipt. Restore it before releasing the test-owned target.
        claim["controller"]["birth_token"] = None
        self.write_json(claim_path, claim)
        try:
            self.apply("resume-unknown-helper", "invocation", kind="resume", models=self.models)
            recovered = self.apply("recover-unknown-helper", "recover", invocation_id="resume-unknown-helper")
            self.assertEqual((recovered["status"], recovered["reason"]), ("blocked", "ownership-unknown"))
            before = self.cycle("inspect")
            self.assertEqual(before["pending_attempts"][0]["state"], "ownership-unknown")

            rejected = self.execute(request, expected_exit=2)

            self.assertEqual(rejected["error"]["code"], "recovery-required")
            self.assertIsNone(controller.poll())
            self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")
            self.assertEqual(self.cycle("inspect"), before)
        finally:
            claim_path.write_bytes(original_claim)
            connection.sendall(b"X")
        self.assertEqual(controller.wait(timeout=15), 0)
        self.assertEqual(self.cycle("inspect")["pending_attempts"], [])

    def test_extend_allows_an_unrelated_pending_ancestor_and_preserves_its_preparation(self):
        """PERF-S01 (§4): adding a dependent does not pull its active ancestor into impact."""
        prepared, before, request_bytes = self.prepare_unrelated_work()
        added = self.separate_example("later-dependent", depends_on=["fee-99"])

        extended = self.apply(
            "extend-local", "extend", source="spec.md / REQ-2", reason="Add the independently scoped next example.",
            examples=[added], flows=[], gates=[],
        )

        self.assertEqual(extended["added"]["examples"], ["later-dependent"])
        self.assertEqual(self.cycle("inspect")["examples"]["later-dependent"]["state"], "planned")
        self.assert_original_attempt_unchanged_and_recordable(prepared, before, request_bytes)

    def test_include_allows_unrelated_pending_work_and_preserves_its_preparation(self):
        """PERF-S02 (§4): a disjoint dependency addition does not stop another flow."""
        prepared, before, request_bytes = self.prepare_unrelated_work()
        (self.workspace / "other-helper.py").write_text("# Dependency of the other example.\n", encoding="utf-8")

        included = self.apply(
            "include-local", "include", source="REQ-2 dependency inventory",
            reason="The other example declares its omitted independent helper.",
            items=[{"example": "other-example", "tests": ["other-helper.py"], "contract": [], "product": []}],
        )

        self.assertEqual(included["included_examples"], ["other-example"])
        self.assert_original_attempt_unchanged_and_recordable(prepared, before, request_bytes)

    def test_revise_resets_only_the_named_active_flow_while_unrelated_attempt_records(self):
        """PERF-S03 (§4): unchanged shared read dependencies do not make revision global."""
        prepared, before, request_bytes = self.prepare_unrelated_work()
        self.open_example("other-example")

        revised = self.apply(
            "revise-local", "revise", examples=["other-example"],
            source="REQ-2 corrected behavior", reason="Revise the independently owned other example.",
        )

        self.assertIs(revised["ok"], True)
        after = self.cycle("inspect")
        self.assertEqual(after["examples"]["other-example"]["state"], "planned")
        self.assertIsNone(after["active_by_flow"]["other"])
        self.assert_original_attempt_unchanged_and_recordable(prepared, before, request_bytes)

    def test_include_overlapping_cross_group_dependency_blocks_affected_pending_flow(self):
        """PERF-S04 (§4): new dependency impact uses real path overlap across groups."""
        _, before, _ = self.prepare_unrelated_work()
        # On Windows this also exercises the actual case-equivalent path.
        added_path = "SRC/fee.txt" if os.name == "nt" else "src/fee.txt"
        self.assertTrue(os.path.samefile(self.workspace / added_path, self.workspace / "src/fee.txt"))

        rejected = self.apply(
            "include-affected-alias", "include", source="REQ-2 dependency inventory",
            reason="The other test also reads the main product value.",
            items=[{"example": "other-example", "tests": [added_path], "contract": [], "product": []}],
            expected_exit=2,
        )

        self.assertIn(rejected["error"]["code"], ("active-work", "attempt-pending"))
        self.assertEqual(self.cycle("inspect"), before)

    def test_execute_adopts_a_matching_complete_receipt_without_relaunch(self):
        """PERF-E08 (§3): the durable prepare/receipt prefix resumes at record only."""
        request, prepared, target, marker = self.leave_bound_formal_preparation_before_launch()
        receipt = self.run_prepared_command(prepared, formal=True, command=["-c", target])
        self.assertEqual(receipt["argv"], request["argv"])
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")
        before = self.cycle("inspect")

        resumed = self.execute(request)

        self.assertEqual(resumed["prepare"], prepared)
        self.assertEqual(resumed["attempt_id"], prepared["attempt_id"])
        self.assertEqual((resumed["outcome"], resumed["exit_code"]), ("exited", 0))
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")
        after = self.cycle("inspect")
        self.assertEqual(after["last_seq"], before["last_seq"] + 1)
        self.assertEqual(after["budget"]["attempts_used"], before["budget"]["attempts_used"])
        self.assertEqual(after["budget"]["seconds_reserved"], 0)
        self.assertEqual(after["pending_attempts"], [])
        self.assertEqual(self.execute(request), resumed)
        self.assertEqual(self.cycle("inspect"), after)

    def test_execute_replay_distinguishes_canonical_integer_and_decimal_requests(self):
        """PERF-E09 (§3): numeric equality does not replace exact JSON request identity."""
        self.install_fee_fixture("10")
        self.initialize()
        self.open_example()
        original_request = self.execute_request("numeric-identity", timeout_seconds=5)
        original = self.execute(original_request)
        before = self.cycle("inspect")
        changed = json.loads(json.dumps(original_request))
        changed["prepare"]["timeout_seconds"] = 5.0
        # Both are valid finite allowances, but their canonical JSON differs.
        canonical_original = json.dumps(original_request, sort_keys=True, separators=(",", ":"))
        canonical_changed = json.dumps(changed, sort_keys=True, separators=(",", ":"))
        self.assertNotEqual(canonical_original, canonical_changed)

        rejected = self.execute(changed, expected_exit=2)

        self.assertEqual(rejected["error"]["code"], "execution-conflict")
        self.assertEqual(self.cycle("inspect"), before)
        self.assertEqual(self.execute(original_request), original)

    def test_execute_refuses_a_real_unrecorded_receipt_with_different_argv(self):
        """PERF-E10 (§3): an actual successful different command is not the bound execution."""
        request, prepared, _, expected_marker = self.leave_bound_formal_preparation_before_launch()
        other_marker = self.root / "different-command.txt"
        other_target = f"from pathlib import Path; Path({str(other_marker)!r}).write_text('different')"
        receipt = self.run_prepared_command(prepared, formal=True, command=["-c", other_target])
        self.assertNotEqual(receipt["argv"], request["argv"])
        self.assertEqual(receipt["exit_code"], 0)
        self.assertEqual(other_marker.read_text(encoding="utf-8"), "different")

        rejected = self.execute(request, expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.assertTrue(rejected["error"]["code"])
        self.assertFalse(expected_marker.exists(), "Mismatched evidence must not trigger the bound target again.")

    def test_record_cannot_settle_a_bound_execution_using_a_real_different_command(self):
        """PERF-E11 (§1/§3): ordinary record cannot bypass the immutable execution binding."""
        request, prepared, _, expected_marker = self.leave_bound_formal_preparation_before_launch()
        receipt = self.run_prepared_command(prepared, formal=True, command=["-c", "print('other argv')"])
        self.assertNotEqual(receipt["argv"], request["argv"])
        self.assertEqual(receipt["exit_code"], 0)

        rejected = self.apply(
            request["record_op_id"], "record", attempt_id=prepared["attempt_id"], expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertTrue(rejected["error"]["code"])
        self.assertFalse(expected_marker.exists())

    def test_recover_cannot_adopt_a_bound_execution_receipt_from_different_argv(self):
        """PERF-E12 (§1/§3): recovery preserves the same exact command evidence boundary."""
        request, prepared, _, expected_marker = self.leave_bound_formal_preparation_before_launch()
        self.apply("resume-argv-check", "invocation", kind="resume", models=self.models)
        receipt = self.run_prepared_command(prepared, formal=True, command=["-c", "print('other argv')"])
        self.assertNotEqual(receipt["argv"], request["argv"])
        self.assertEqual(receipt["exit_code"], 0)

        rejected = self.apply(
            "recover-argv-check", "recover", invocation_id="resume-argv-check", expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertTrue(rejected["error"]["code"])
        self.assertFalse(expected_marker.exists())

    def test_same_size_restored_timestamp_log_tampering_is_reaudited_on_every_entry(self):
        """PERF-H01 (§1): old evidence is checked again across transitions and replay."""
        self.install_fee_fixture("10")
        self.initialize()
        self.open_example()
        request = self.execute_request("history-integrity")
        executed = self.execute(request)
        before = self.cycle("inspect")
        receipt = json.loads(Path(executed["prepare"]["receipt_path"]).read_text(encoding="utf-8"))
        log_path = Path(receipt["logs"]["stderr"]["path"])
        original = log_path.read_bytes()
        self.assertTrue(original, "The real unittest fixture emits its public result.")
        timestamps = log_path.stat()
        log_path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        os.utime(log_path, ns=(timestamps.st_atime_ns, timestamps.st_mtime_ns))
        self.assertEqual(log_path.stat().st_size, len(original))
        self.assertEqual(log_path.stat().st_mtime_ns, timestamps.st_mtime_ns)
        try:
            self.assertIs(self.execute(request, expected_exit=2)["ok"], False)
            self.assertIs(self.batch([request["prepare"]], expected_exit=2)["ok"], False)
            self.assertIs(self.apply(
                "mutation-after-tamper", "invocation", kind="resume", models=self.models,
                expected_exit=2,
            )["ok"], False)
            self.assertIs(self.cycle("verify", expected_exit=2)["ok"], False)
            self.assertIs(self.cycle("inspect", expected_exit=2)["ok"], False)
        finally:
            log_path.write_bytes(original)
            os.utime(log_path, ns=(timestamps.st_atime_ns, timestamps.st_mtime_ns))

        self.assertEqual(self.execute(request), executed)
        self.assertEqual(self.cycle("inspect"), before)

    def test_execute_records_actual_snapshot_drift_as_ineligible_and_replays_the_failure(self):
        """PERF-E13 (§1/§3): a zero exit cannot hide real before/after input drift."""
        self.install_fee_fixture("10")
        self.initialize()
        self.open_example()
        request = self.execute_request("drifting-input", argv=[
            sys.executable, "-B", "-c",
            "from pathlib import Path; Path('src/fee.txt').write_text('20',encoding='utf-8')",
        ])

        executed = self.execute(request)

        self.assertEqual((executed["outcome"], executed["exit_code"]), ("exited", 0))
        self.assertIs(executed["record"]["eligible"], False)
        self.assertEqual(executed["record"]["reason"], "snapshot-changed")
        before_retry = self.cycle("inspect")
        self.assertEqual(before_retry["pending_attempts"], [])
        self.assertEqual(before_retry["budget"]["attempts_used"], 1)
        self.assertEqual(before_retry["budget"]["seconds_reserved"], 0)
        self.assertEqual(before_retry["failures"][0]["classification"], "ineligible")
        self.assertFalse(before_retry["failures"][0]["resolved"])
        self.assertEqual(self.execute(request), executed)
        self.apply(
            "judge-drift-existing", "judge", attempt_id=executed["attempt_id"], classification="existing",
            reason="A zero exit is proposed as success.", evidence=[executed["prepare"]["receipt_path"]],
            expected_exit=2,
        )
        self.assertEqual(self.cycle("inspect"), before_retry)

    def test_revise_detects_changed_criterion_in_an_unlisted_pending_preparation(self):
        """PERF-S05 (§4): the prepared snapshot exposes affected work absent from caller IDs."""
        _, before, _ = self.prepare_unrelated_work()
        criterion = self.workspace / "tests" / "test_fee.py"
        criterion.write_text(criterion.read_text(encoding="utf-8") + "\n# Updated criterion version.\n", encoding="utf-8")

        rejected = self.apply(
            "revise-omitting-pending-change", "revise", examples=["other-example"],
            source="REQ-2 revision", reason="Revise the other example while another criterion also changed.",
            expected_exit=2,
        )

        self.assertIn(rejected["error"]["code"], ("active-work", "attempt-pending"))
        after = self.cycle("inspect")
        for key in ("last_seq", "pending_attempts", "budget", "active_by_flow"):
            self.assertEqual(after[key], before[key])

    def test_revise_uses_refreshed_adopted_inputs_before_preserving_an_unrelated_next_attempt(self):
        """PERF-S06 (§4): accepted regression replaces the old incomplete dependency baseline.

        Public scenario provenance: SPEC-SCOPE-ADOPTED-20261103.
        """
        self.plan["examples"][0]["snapshot"]["tests"] = ["tests/test_fee.py"]
        next_example = json.loads(json.dumps(self.plan["examples"][0]))
        next_example.update(id="next-main", requirement="REQ-1/next-main")
        self.plan["examples"].append(next_example)
        self.plan["flows"].append({"id": "other", "write_paths": ["other"]})
        self.plan["examples"].append(self.separate_example())
        self.complete_existing_example()
        (self.workspace / "stable-helper.py").write_text("# Stable additional criterion dependency.\n", encoding="utf-8")
        self.apply(
            "include-completed-helper", "include", source="REQ-1 dependency inventory",
            reason="Complete the closed example's dependency inventory.",
            items=[{"example": "fee-99", "tests": ["stable-helper.py"], "contract": [], "product": []}],
        )
        refreshed = self.apply(
            "refresh-adopted-baseline", "prepare", example="fee-99", purpose="regression", timeout_seconds=5,
        )
        self.run_prepared(refreshed, expected_exit=0)
        self.record("record-adopted-baseline", refreshed)
        self.open_example("next-main")
        pending = self.apply(
            "prepare-next-main", "prepare", example="next-main", purpose="probe", timeout_seconds=5,
        )
        before = self.cycle("inspect")
        request_bytes = Path(pending["request_path"]).read_bytes()

        revised = self.apply(
            "revise-independent-after-refresh", "revise", examples=["other-example"],
            source="REQ-2 revision", reason="The independently scoped behavior changed.",
        )

        self.assertIs(revised["ok"], True)
        self.assertEqual(self.cycle("inspect")["examples"]["fee-99"]["state"], "closed")
        self.assert_original_attempt_unchanged_and_recordable(pending, before, request_bytes, example="next-main")

    def test_revise_checks_a_pending_formal_baseline_even_when_historical_inputs_match_again(self):
        """PERF-S07 (§4): pending formal captures remain applicable impact baselines.

        Public scenario provenance: SPEC-PENDING-FORMAL-20261103.
        """
        self.plan["examples"][0]["snapshot"]["tests"] = ["tests/test_fee.py"]
        self.plan["flows"].append({"id": "other", "write_paths": ["other"]})
        self.plan["examples"].append(self.separate_example())
        self.plan["gates"] = [{"id": "fee-gate", "prerequisites": ["fee-99"], "consumers": []}]
        self.complete_existing_example()
        criterion = self.workspace / "tests" / "test_fee.py"
        historical_bytes = criterion.read_bytes()
        criterion.write_bytes(historical_bytes + b"\n# Formal candidate criterion version.\n")
        self.qualify("qualify-formal-version", {"gate": "fee-gate"})
        self.apply(
            "pending-formal-version", "prepare-formal", scope={"gate": "fee-gate"}, timeout_seconds=5,
        )
        before = self.cycle("inspect")
        criterion.write_bytes(historical_bytes)

        rejected = self.apply(
            "revise-during-formal-drift", "revise", examples=["other-example"],
            source="REQ-2 revision", reason="Only the separate behavior was named for revision.",
            expected_exit=2,
        )

        self.assertEqual(rejected["error"]["code"], "attempt-pending")
        after = self.cycle("inspect")
        for key in ("last_seq", "pending_attempts", "budget", "active_by_flow"):
            self.assertEqual(after[key], before[key])

    def test_apply_cannot_consume_the_record_identity_of_a_waiting_execution(self):
        """PERF-E14 (§3 rev1): a bound record identity is reserved through target execution.

        Public scenario provenance: STD-RECORD-ID-20261103.
        """
        request, controller, connection, marker, stdout_path = self.start_waiting_execute()
        before = self.cycle("inspect")

        rejected = self.apply(
            request["record_op_id"], "invocation", kind="resume", models=self.models, expected_exit=2,
        )

        self.assertEqual(rejected["error"]["code"], "op-id-conflict")
        self.assertEqual(self.cycle("inspect"), before)
        connection.sendall(b"X")
        self.assertEqual(controller.wait(timeout=15), 0)
        completed = json.loads(stdout_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertIs(completed["ok"], True)
        self.assertEqual(
            self.apply(request["record_op_id"], "record", attempt_id=completed["attempt_id"]),
            completed["record"],
        )
        self.assertEqual(self.execute(request), completed)
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")
        self.assertEqual(self.cycle("inspect")["budget"]["attempts_used"], 1)

    def test_batch_record_identity_conflict_preserves_prefix_and_original_execution(self):
        """PERF-E15 (§2/§3 rev1): a reserved-ID collision is a durable-prefix rejection."""
        request, controller, connection, marker, stdout_path = self.start_waiting_execute()
        before = self.cycle("inspect")
        suffix_models = {role: f"must-not-run-{role}" for role in fixtures.ROLES}

        rejected = self.batch([
            self.event("before-record-collision", "invocation", kind="resume", models=self.models),
            self.event(request["record_op_id"], "invocation", kind="resume", models=self.models),
            self.event("after-record-collision", "invocation", kind="resume", models=suffix_models),
        ], expected_exit=2)

        self.assertEqual(rejected["failed_index"], 1)
        self.assertEqual(len(rejected["results"]), 1)
        self.assertEqual(rejected["error"]["code"], "op-id-conflict")
        after = self.cycle("inspect")
        self.assertEqual(after["last_seq"], before["last_seq"] + 1)
        self.assertEqual(after["pending_attempts"], before["pending_attempts"])
        self.assertEqual(after["budget"], before["budget"])
        self.assertEqual(after["models"], self.models)
        connection.sendall(b"X")
        self.assertEqual(controller.wait(timeout=15), 0)
        completed = json.loads(stdout_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(self.execute(request), completed)
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")

    def test_another_execute_cannot_reserve_an_already_bound_record_identity(self):
        """PERF-E16 (§3 rev1): conflicting execute IDs reject before another preparation."""
        self.plan["flows"].append({"id": "other", "write_paths": ["other"]})
        self.plan["examples"].append(self.separate_example())
        original, controller, connection, marker, stdout_path = self.start_waiting_execute()
        self.open_example("other-example")
        before = self.cycle("inspect")
        forbidden_marker = self.root / "second-execute.txt"
        competing = {
            "schema": 1,
            "prepare": self.event(
                "prepare-competing-execution", "prepare", example="other-example", purpose="probe", timeout_seconds=5,
            ),
            "record_op_id": original["record_op_id"],
            "argv": [sys.executable, "-c", f"from pathlib import Path; Path({str(forbidden_marker)!r}).write_text('ran')"],
        }

        rejected = self.execute(competing, expected_exit=2)

        self.assertEqual(rejected["error"]["code"], "op-id-conflict")
        self.assertFalse(forbidden_marker.exists())
        self.assertEqual(self.cycle("inspect"), before)
        connection.sendall(b"X")
        self.assertEqual(controller.wait(timeout=15), 0)
        completed = json.loads(stdout_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(self.execute(original), completed)
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")

    def test_revise_detects_changed_inputs_of_an_unlisted_open_example_without_receipts(self):
        """PERF-S08 (§4): an opening snapshot protects active work before its first prepare."""
        self.install_fee_fixture("10")
        self.plan["flows"].append({"id": "other", "write_paths": ["other"]})
        self.plan["examples"].append(self.separate_example())
        self.initialize()
        self.open_example()
        before = self.cycle("inspect")
        criterion = self.workspace / "tests" / "test_fee.py"
        criterion.write_text(criterion.read_text(encoding="utf-8") + "\n# Changed open criterion.\n", encoding="utf-8")

        rejected = self.apply(
            "revise-omitting-open-change", "revise", examples=["other-example"],
            source="REQ-2 revision", reason="Revise only the separate example.", expected_exit=2,
        )

        self.assertEqual(rejected["error"]["code"], "active-work")
        after = self.cycle("inspect")
        for key in ("last_seq", "pending_attempts", "budget", "active_by_flow"):
            self.assertEqual(after[key], before[key])

    def test_revise_blocks_a_pending_ordinary_downstream_dependent(self):
        """PERF-S09 (§4): ordinary downstream closure protects pending consumer work."""
        self.plan["flows"].append({"id": "other", "write_paths": ["other"]})
        self.plan["examples"].append(self.separate_example(depends_on=["fee-99"]))
        self.complete_existing_example()
        self.open_example("other-example")
        self.apply(
            "pending-dependent", "prepare", example="other-example", purpose="probe", timeout_seconds=5,
        )
        before = self.cycle("inspect")

        rejected = self.apply(
            "revise-prerequisite", "revise", examples=["fee-99"],
            source="REQ-1 revision", reason="The prerequisite behavior changes.", expected_exit=2,
        )

        self.assertIn(rejected["error"]["code"], ("active-work", "attempt-pending"))
        self.assertEqual(self.cycle("inspect"), before)

    def test_revise_blocks_a_pending_gate_consumer_without_an_ordinary_dependency(self):
        """PERF-S10 (§4): gate edges propagate impact to their already admitted consumers."""
        self.plan["flows"].append({"id": "other", "write_paths": ["other"]})
        self.plan["examples"].append(self.separate_example())
        self.plan["gates"] = [{
            "id": "fee-gate", "prerequisites": ["fee-99"], "consumers": ["other-example"],
        }]
        self.git("init", "--quiet")
        self.complete_existing_example()
        self.commit_fixture()
        self.qualify("qualify-consumer-gate", {"gate": "fee-gate"})
        formal = self.apply(
            "prepare-consumer-gate", "prepare-formal", scope={"gate": "fee-gate"}, timeout_seconds=5,
        )
        self.run_prepared(formal, expected_exit=0, formal=True)
        self.record("record-consumer-gate", formal)
        self.apply("release-consumer-gate", "release", gate="fee-gate", attempt_id=formal["attempt_id"])
        self.open_example("other-example")
        self.apply(
            "pending-gate-consumer", "prepare", example="other-example", purpose="probe", timeout_seconds=5,
        )
        before = self.cycle("inspect")

        rejected = self.apply(
            "revise-gated-prerequisite", "revise", examples=["fee-99"],
            source="REQ-1 revision", reason="The gate prerequisite behavior changes.", expected_exit=2,
        )

        self.assertIn(rejected["error"]["code"], ("active-work", "attempt-pending"))
        self.assertEqual(self.cycle("inspect"), before)

    def test_extend_cannot_change_scope_while_a_final_attempt_is_pending(self):
        """PERF-S11 (§4): every pending final attempt protects final membership."""
        before = self.prepare_pending_final()
        added = self.separate_example("new-final-member")

        rejected = self.apply(
            "extend-during-final", "extend", source="REQ-2 new example",
            reason="Add a disjoint flow and final member.", examples=[added],
            flows=[{"id": "other", "write_paths": ["other"]}], gates=[], expected_exit=2,
        )

        self.assertEqual(rejected["error"]["code"], "attempt-pending")
        self.assertEqual(self.cycle("inspect"), before)

    def test_include_cannot_change_dependencies_while_a_final_attempt_is_pending(self):
        """PERF-S12 (§4): pending final evidence cannot receive a new dependency declaration."""
        before = self.prepare_pending_final()

        rejected = self.apply(
            "include-during-final", "include", source="REQ-1 dependency inventory",
            reason="The existing example omitted an additional dependency path.",
            items=[{"example": "fee-99", "tests": ["additional-helper.py"], "contract": [], "product": []}],
            expected_exit=2,
        )

        self.assertEqual(rejected["error"]["code"], "attempt-pending")
        self.assertEqual(self.cycle("inspect"), before)

    def test_revise_cannot_reset_completion_while_a_final_attempt_is_pending(self):
        """PERF-S13 (§4): pending final membership cannot be revised underneath its proof."""
        before = self.prepare_pending_final()

        rejected = self.apply(
            "revise-during-final", "revise", examples=["fee-99"],
            source="REQ-1 behavior revision", reason="The required behavior is being revised.", expected_exit=2,
        )

        self.assertEqual(rejected["error"]["code"], "attempt-pending")
        self.assertEqual(self.cycle("inspect"), before)

    def test_batch_unknown_envelope_field_rejects_without_consuming_any_event(self):
        """PERF-B05 (§2): malformed outer input rejects before all otherwise valid items."""
        self.initialize()
        before = self.cycle("inspect")
        path = self.root / "invalid-envelope.json"
        self.write_json(path, {"schema": 1, "events": [self.open_event()], "unexpected": True})

        rejected = self.cycle("batch", "--events", str(path), expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.assertEqual(rejected["results"], [])
        self.assertIsNone(rejected["failed_index"])
        self.assertTrue(rejected["error"]["code"])
        self.assertEqual(self.cycle("inspect"), before)
        accepted = self.batch([self.open_event()])
        self.assertEqual(accepted["results"][0]["seq"], before["last_seq"] + 1)

    def test_batch_changed_committed_event_rejects_at_its_index_and_keeps_new_prefix(self):
        """PERF-B06 (§2): changed replay content cannot replace an original durable event."""
        self.initialize()
        original_event = self.open_event()
        original = self.batch([original_event])
        before = self.cycle("inspect")
        changed_event = json.loads(json.dumps(original_event))
        changed_event["light_check"]["observation"] = "A different observation cannot replace the original."
        replacement_models = {role: f"suffix-not-run-{role}" for role in fixtures.ROLES}

        rejected = self.batch([
            self.event("prefix-before-changed-replay", "invocation", kind="resume", models=self.models),
            changed_event,
            self.event("suffix-after-changed-replay", "invocation", kind="resume", models=replacement_models),
        ], expected_exit=2)

        self.assertEqual(rejected["failed_index"], 1)
        self.assertEqual(len(rejected["results"]), 1)
        self.assertEqual(rejected["error"]["code"], "op-id-conflict")
        after = self.cycle("inspect")
        self.assertEqual(after["last_seq"], before["last_seq"] + 1)
        self.assertEqual(after["budget"], before["budget"])
        self.assertEqual(after["models"], self.models)
        self.assertEqual(after["active_by_flow"], before["active_by_flow"])
        self.assertEqual(self.batch([original_event]), original)
        self.assertEqual(self.cycle("inspect"), after)

    def test_revise_uses_a_successful_formal_refresh_before_preserving_unrelated_next_work(self):
        """PERF-S14 (§4): an adopted formal proof refreshes the completed example's baseline.

        Public scenario provenance: SPEC-ADOPTED-FORMAL-20261103.
        """
        self.plan["examples"][0]["snapshot"]["tests"] = ["tests/test_fee.py"]
        next_example = json.loads(json.dumps(self.plan["examples"][0]))
        next_example.update(id="next-main", requirement="REQ-1/next-main")
        self.plan["examples"].append(next_example)
        self.plan["flows"].append({"id": "other", "write_paths": ["other"]})
        self.plan["examples"].append(self.separate_example())
        self.plan["gates"] = [{"id": "fee-gate", "prerequisites": ["fee-99"], "consumers": []}]
        self.git("init", "--quiet")
        self.complete_existing_example()
        (self.workspace / "stable-helper.py").write_text("# Stable formal criterion dependency.\n", encoding="utf-8")
        self.apply(
            "include-before-formal-refresh", "include", source="REQ-1 dependency inventory",
            reason="Complete the closed example's stable dependency inventory.",
            items=[{"example": "fee-99", "tests": ["stable-helper.py"], "contract": [], "product": []}],
        )
        self.commit_fixture()
        self.qualify("qualify-formal-refresh", {"gate": "fee-gate"})
        formal = self.apply(
            "prepare-adopted-formal", "prepare-formal", scope={"gate": "fee-gate"}, timeout_seconds=5,
        )
        self.run_prepared(formal, expected_exit=0, formal=True)
        self.record("record-adopted-formal", formal)
        self.apply("release-adopted-formal", "release", gate="fee-gate", attempt_id=formal["attempt_id"])
        self.open_example("next-main")
        pending = self.apply(
            "prepare-next-after-formal", "prepare", example="next-main", purpose="probe", timeout_seconds=5,
        )
        before = self.cycle("inspect")
        request_bytes = Path(pending["request_path"]).read_bytes()

        revised = self.apply(
            "revise-independent-after-formal", "revise", examples=["other-example"],
            source="REQ-2 revision", reason="Only the independently scoped behavior changes.",
        )

        self.assertIs(revised["ok"], True)
        self.assertEqual(self.cycle("inspect")["examples"]["fee-99"]["state"], "closed")
        self.assert_original_attempt_unchanged_and_recordable(pending, before, request_bytes, example="next-main")

    def test_formal_refresh_with_hardlink_equivalent_test_paths_preserves_unrelated_next_work(self):
        """PERF-S15 (§4): refreshed proofs follow actual file identity across different path depths.

        Public scenario provenance: SPEC-FORMAL-HARDLINK-20261103.
        """
        self.install_fee_fixture("10")
        shallow_test = self.workspace / "tests" / "test_fee.py"
        deep_test = self.workspace / "nested" / "deep" / "test_fee.py"
        deep_test.parent.mkdir(parents=True)
        os.link(shallow_test, deep_test)
        self.assertTrue(os.path.samefile(shallow_test, deep_test))
        self.plan["examples"][0]["snapshot"]["tests"] = ["tests/test_fee.py"]
        self.plan["examples"][0]["snapshot"]["product"] = ["src/fee.txt"]
        deeper = json.loads(json.dumps(self.plan["examples"][0]))
        deeper.update(id="deeper-example", flow="deeper", requirement="REQ-2/deeper-example")
        deeper["snapshot"]["tests"] = ["nested/deep/test_fee.py"]
        next_deeper = json.loads(json.dumps(deeper))
        next_deeper.update(id="next-deeper", requirement="REQ-2/next-deeper")
        self.plan["examples"].extend([deeper, next_deeper, self.separate_example()])
        self.plan["flows"].extend([
            {"id": "deeper", "write_paths": ["deeper-product"]},
            {"id": "other", "write_paths": ["other"]},
        ])
        self.plan["gates"] = [{
            "id": "equivalent-tests", "prerequisites": ["fee-99", "deeper-example"], "consumers": [],
        }]
        self.git("init", "--quiet")
        self.initialize()
        self.complete_existing_example(start_run=False, label="shallow")
        self.open_example("deeper-example")
        probe = self.apply(
            "probe-deeper", "prepare", example="deeper-example", purpose="probe", timeout_seconds=5,
        )
        self.run_prepared(probe, expected_exit=0, test_file="nested/deep/test_fee.py")
        self.record("record-probe-deeper", probe)
        self.apply(
            "judge-deeper-existing", "judge", attempt_id=probe["attempt_id"], classification="existing",
            reason="The hardlink-equivalent criterion independently checks fee 99 equals 10.",
            evidence=[probe["receipt_path"]],
        )
        regression = self.apply(
            "regression-deeper", "prepare", example="deeper-example", purpose="regression", timeout_seconds=5,
        )
        self.run_prepared(regression, expected_exit=0, test_file="nested/deep/test_fee.py")
        self.record("record-regression-deeper", regression)
        self.apply("close-deeper", "close", example="deeper-example", regression_attempt_id=regression["attempt_id"])
        (self.workspace / "stable-helper.py").write_text("# Stable deeper criterion dependency.\n", encoding="utf-8")
        self.apply(
            "include-deeper-helper", "include", source="REQ-2 dependency inventory",
            reason="Complete the deeper example's stable dependency inventory.",
            items=[{"example": "deeper-example", "tests": ["stable-helper.py"], "contract": [], "product": []}],
        )
        self.commit_fixture()
        self.assertTrue(os.path.samefile(shallow_test, deep_test))
        self.qualify("qualify-equivalent-tests", {"gate": "equivalent-tests"})
        formal = self.apply(
            "prepare-equivalent-tests", "prepare-formal", scope={"gate": "equivalent-tests"}, timeout_seconds=5,
        )
        self.run_prepared(formal, expected_exit=0, formal=True)
        self.record("record-equivalent-tests", formal)
        self.apply("release-equivalent-tests", "release", gate="equivalent-tests", attempt_id=formal["attempt_id"])
        self.open_example("next-deeper")
        pending = self.apply(
            "prepare-next-deeper", "prepare", example="next-deeper", purpose="probe", timeout_seconds=5,
        )
        before = self.cycle("inspect")
        request_bytes = Path(pending["request_path"]).read_bytes()

        revised = self.apply(
            "revise-independent-after-equivalent-formal", "revise", examples=["other-example"],
            source="REQ-3 revision", reason="Only the independently scoped behavior changes.",
        )

        self.assertIs(revised["ok"], True)
        after = self.cycle("inspect")
        self.assertEqual(after["examples"]["deeper-example"]["state"], "closed")
        self.assertEqual(after["pending_attempts"], before["pending_attempts"])
        self.assertEqual(after["budget"], before["budget"])
        self.assertEqual(after["active_by_flow"]["deeper"], "next-deeper")
        self.assertEqual(Path(pending["request_path"]).read_bytes(), request_bytes)
        self.run_prepared(pending, expected_exit=0, test_file="nested/deep/test_fee.py")
        self.record("record-next-deeper", pending)
        final = self.cycle("inspect")
        self.assertEqual(final["pending_attempts"], [])
        self.assertEqual(final["budget"]["attempts_used"], before["budget"]["attempts_used"])
        self.assertEqual(final["budget"]["seconds_reserved"], 0)
        self.assertEqual(final["failures"], [])

    def test_execute_unknown_envelope_field_rejects_before_preparation_and_leaves_ids_usable(self):
        """PERF-E17 (§3): a malformed outer request cannot reserve or launch work."""
        self.install_fee_fixture("10")
        self.initialize()
        self.open_example()
        marker = self.root / "validated-envelope-launch.txt"
        target = (
            "from pathlib import Path; import runpy; "
            f"Path({str(marker)!r}).write_text('launched',encoding='utf-8'); "
            "runpy.run_path('tests/test_fee.py',run_name='__main__')"
        )
        request = self.execute_request("envelope-validation", argv=[sys.executable, "-B", "-c", target])
        invalid_request = {**request, "unexpected": True}
        before = self.cycle("inspect")

        rejected = self.execute(invalid_request, expected_exit=2)

        self.assertIs(rejected["ok"], False)
        self.assertTrue(rejected["error"]["code"])
        self.assertIsInstance(rejected["error"]["message"], str)
        self.assertFalse(marker.exists())
        self.assertEqual(self.cycle("inspect"), before)
        completed = self.execute(request)
        self.assertEqual((completed["outcome"], completed["exit_code"]), ("exited", 0))
        self.assertEqual(marker.read_text(encoding="utf-8"), "launched")
        after = self.cycle("inspect")
        self.assertEqual(after["last_seq"], before["last_seq"] + 2)
        self.assertEqual(after["budget"]["attempts_used"], 1)
        self.assertEqual(after["pending_attempts"], [])

    def test_execute_records_a_real_timeout_and_replays_without_relaunch(self):
        """PERF-E18 (§3): a published timeout receipt is a recorded failure, not helper failure."""
        self.initialize()
        self.open_example()
        marker = self.root / "timeout-launches.txt"
        target = (
            "from pathlib import Path; import time; "
            f"p=Path({str(marker)!r}); "
            "f=p.open('a',encoding='utf-8'); f.write('launch\\n'); f.close(); time.sleep(30)"
        )
        # The target's deliberate 30-second wait exceeds its three-second
        # execution allowance. The inherited 15-second harness cap covers
        # that allowance, the contract's five-second cleanup, and startup.
        request = self.execute_request(
            "real-timeout", argv=[sys.executable, "-B", "-c", target], timeout_seconds=3,
        )
        before = self.cycle("inspect")

        executed = self.execute(request)

        self.assertIs(executed["ok"], True)
        self.assertEqual(executed["outcome"], "timeout")
        self.assertIsNone(executed["exit_code"])
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")
        receipt = json.loads(Path(executed["prepare"]["receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["outcome"], "timeout")
        self.assertIsNone(receipt["exit_code"])
        self.assertIs(receipt["cleanup_complete"], True)
        after = self.cycle("inspect")
        self.assertEqual(after["last_seq"], before["last_seq"] + 2)
        self.assertEqual(after["pending_attempts"], [])
        self.assertEqual(after["budget"]["attempts_used"], 1)
        self.assertEqual(after["budget"]["seconds_reserved"], 0)
        self.assertAlmostEqual(after["budget"]["seconds_used"], receipt["duration_seconds"])
        self.assertEqual(after["failures"][0]["attempt_id"], executed["attempt_id"])
        self.assertEqual(after["failures"][0]["classification"], "unclassified")
        self.assertFalse(after["failures"][0]["resolved"])
        self.assertEqual(self.execute(request), executed)
        self.assertEqual(self.cycle("inspect"), after)
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")

    def test_execute_reaudits_old_receipt_bytes_after_the_acknowledged_target_finishes(self):
        """PERF-H02 (§1/§3): a pre-launch audit cannot authorize record after evidence changes."""
        self.install_fee_fixture("10")
        self.plan["budget"]["max_seconds"] = 180
        other = self.separate_example()
        other["snapshot"]["tests"] = ["tests/test_fee.py"]
        other["snapshot"]["product"] = ["src/fee.txt"]
        self.plan["flows"].append({"id": "other", "write_paths": ["other"]})
        self.plan["examples"].append(other)
        self.initialize()
        self.open_example("other-example")
        prior_request = self.execute_request("prior-adopted-receipt")
        prior_request["prepare"]["example"] = "other-example"
        prior = self.execute(prior_request)
        old_receipt_path = Path(prior["prepare"]["receipt_path"])
        old_receipt_bytes = old_receipt_path.read_bytes()
        request, controller, connection, marker, stdout_path = self.start_waiting_execute()
        before = self.cycle("inspect")
        pending = next(item for item in before["pending_attempts"] if item["example"] == "fee-99")
        # Whitespace preserves the receipt's JSON facts but changes its already
        # adopted bytes. The target is acknowledged alive before this change.
        old_receipt_path.write_bytes(old_receipt_bytes + b"\n")
        try:
            connection.sendall(b"X")
            self.assertEqual(controller.wait(timeout=15), 2)
            rejected = json.loads(stdout_path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertIs(rejected["ok"], False)
            self.assertTrue(rejected["error"]["code"])
            real_receipt = json.loads(Path(pending["receipt_path"]).read_text(encoding="utf-8"))
            self.assertEqual((real_receipt["outcome"], real_receipt["exit_code"]), ("exited", 0))
            self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")
        finally:
            old_receipt_path.write_bytes(old_receipt_bytes)

        self.assertEqual(self.cycle("inspect"), before)
        resumed = self.execute(request)
        self.assertEqual(resumed["attempt_id"], pending["attempt_id"])
        self.assertEqual((resumed["outcome"], resumed["exit_code"]), ("exited", 0))
        after = self.cycle("inspect")
        self.assertEqual(after["last_seq"], before["last_seq"] + 1)
        self.assertEqual(after["pending_attempts"], [])
        self.assertEqual(after["budget"]["attempts_used"], 2)
        self.assertEqual(marker.read_text(encoding="utf-8"), "launch\n")

    def test_revise_propagates_through_an_ordinary_then_gate_edge_to_pending_terminal_work(self):
        """PERF-S16 (§4): impact closure repeats across mixed edge kinds, not only one hop."""
        self.plan["examples"][0]["snapshot"]["tests"] = ["tests/test_fee.py"]
        self.plan["examples"][0]["snapshot"]["product"] = ["src/fee.txt"]
        middle = json.loads(json.dumps(self.plan["examples"][0]))
        middle.update(id="middle", flow="middle", requirement="REQ-2/middle", depends_on=["fee-99"])
        terminal = json.loads(json.dumps(self.plan["examples"][0]))
        terminal.update(id="terminal", flow="terminal", requirement="REQ-3/terminal")
        self.plan["examples"].extend([middle, terminal])
        self.plan["flows"].extend([
            {"id": "middle", "write_paths": ["middle-product"]},
            {"id": "terminal", "write_paths": ["terminal-product"]},
        ])
        self.plan["gates"] = [{"id": "middle-gate", "prerequisites": ["middle"], "consumers": ["terminal"]}]
        self.git("init", "--quiet")
        self.complete_existing_example()
        self.complete_existing_example("middle", start_run=False, label="middle")
        self.commit_fixture()
        self.qualify("qualify-mixed-chain", {"gate": "middle-gate"})
        formal = self.apply(
            "prepare-mixed-chain", "prepare-formal", scope={"gate": "middle-gate"}, timeout_seconds=5,
        )
        self.run_prepared(formal, expected_exit=0, formal=True)
        self.record("record-mixed-chain", formal)
        self.apply("release-mixed-chain", "release", gate="middle-gate", attempt_id=formal["attempt_id"])
        self.open_example("terminal")
        self.apply("pending-terminal", "prepare", example="terminal", purpose="probe", timeout_seconds=5)
        before = self.cycle("inspect")

        rejected = self.apply(
            "revise-upstream-of-mixed-chain", "revise", examples=["fee-99"],
            source="REQ-1 revision", reason="The first prerequisite behavior changes.", expected_exit=2,
        )

        self.assertIn(rejected["error"]["code"], ("active-work", "attempt-pending"))
        self.assertEqual(self.cycle("inspect"), before)

    def test_accepted_revision_preserves_downstream_history_but_requires_new_gate_proof_at_unchanged_bytes(self):
        """PERF-S17 (§4): affected gate evidence expires without resetting unlisted historical close."""
        self.plan["examples"][0]["snapshot"]["tests"] = ["tests/test_fee.py"]
        self.plan["examples"][0]["snapshot"]["product"] = ["src/fee.txt"]
        middle = json.loads(json.dumps(self.plan["examples"][0]))
        middle.update(id="middle", flow="middle", requirement="REQ-2/middle", depends_on=["fee-99"])
        terminal = json.loads(json.dumps(self.plan["examples"][0]))
        terminal.update(id="terminal", flow="terminal", requirement="REQ-3/terminal")
        self.plan["examples"].extend([middle, terminal])
        self.plan["flows"].extend([
            {"id": "middle", "write_paths": ["middle-product"]},
            {"id": "terminal", "write_paths": ["terminal-product"]},
        ])
        self.plan["gates"] = [{"id": "middle-gate", "prerequisites": ["middle"], "consumers": ["terminal"]}]
        self.git("init", "--quiet")
        self.complete_existing_example()
        self.complete_existing_example("middle", start_run=False, label="middle")
        original_head = self.commit_fixture()
        self.qualify("qualify-original-downstream-gate", {"gate": "middle-gate"})
        original_formal = self.apply(
            "prepare-original-downstream-gate", "prepare-formal", scope={"gate": "middle-gate"}, timeout_seconds=5,
        )
        self.run_prepared(original_formal, expected_exit=0, formal=True)
        self.record("record-original-downstream-gate", original_formal)
        self.apply(
            "release-original-downstream-gate", "release", gate="middle-gate", attempt_id=original_formal["attempt_id"],
        )
        before = self.cycle("inspect")
        original_receipt = Path(original_formal["receipt_path"]).read_bytes()

        self.apply(
            "revise-upstream-without-file-changes", "revise", examples=["fee-99"],
            source="REQ-1 revision authority", reason="Reassess the prerequisite while its current file bytes remain unchanged.",
        )

        revised = self.cycle("inspect")
        self.assertEqual(revised["examples"]["fee-99"]["state"], "planned")
        for key in ("state", "mode", "attempt_ids"):
            self.assertEqual(revised["examples"]["middle"][key], before["examples"]["middle"][key])
        self.assertEqual(revised["examples"]["middle"]["state"], "closed")
        self.assertEqual(revised["budget"], before["budget"])
        self.assertEqual(Path(original_formal["receipt_path"]).read_bytes(), original_receipt)
        self.apply(
            "open-revised-prerequisite", "open", example="fee-99", light_check=self.open_event()["light_check"],
        )
        probe = self.execute(self.execute_request("revised-prerequisite-probe"))
        self.apply(
            "judge-revised-prerequisite-existing", "judge", attempt_id=probe["attempt_id"], classification="existing",
            reason="The independently checked fee criterion already passes for this revision.",
            evidence=[probe["prepare"]["receipt_path"]],
        )
        regression = self.execute(self.execute_request("revised-prerequisite-regression", purpose="regression"))
        self.apply(
            "close-revised-prerequisite", "close", example="fee-99", regression_attempt_id=regression["attempt_id"],
        )
        refreshed = self.cycle("inspect")
        self.assertEqual(refreshed["examples"]["fee-99"]["state"], "closed")
        self.assertEqual(self.git("rev-parse", "HEAD"), original_head)
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all"), "")

        self.assertIs(self.apply(
            "reuse-old-downstream-release", "release", gate="middle-gate", attempt_id=original_formal["attempt_id"],
            expected_exit=2,
        )["ok"], False)
        self.assertIs(self.open_example("terminal", expected_exit=2)["ok"], False)
        self.assertEqual(self.cycle("inspect"), refreshed)
        self.qualify("qualify-refreshed-downstream-gate", {"gate": "middle-gate"})
        current_formal = self.apply(
            "prepare-refreshed-downstream-gate", "prepare-formal", scope={"gate": "middle-gate"}, timeout_seconds=5,
        )
        self.run_prepared(current_formal, expected_exit=0, formal=True)
        self.record("record-refreshed-downstream-gate", current_formal)
        self.apply(
            "release-refreshed-downstream-gate", "release", gate="middle-gate", attempt_id=current_formal["attempt_id"],
        )
        self.assertIs(self.open_example("terminal")["ok"], True)
        self.assertEqual(self.cycle("inspect")["examples"]["middle"]["state"], "closed")
        self.assertEqual(Path(original_formal["receipt_path"]).read_bytes(), original_receipt)


if __name__ == "__main__":
    unittest.main()
