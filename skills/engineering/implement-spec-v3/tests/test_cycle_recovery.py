"""Real Windows recovery checks against runtime-contract sections 2 and 3.3.

This file is implementation blind: only public CLI output, published files,
test-owned socket handshakes, and native process handles are observations.
The socket wait (10 s), CLI cap (15 s), and native exit wait (5 s) are finite
harness/evidence bounds, not product latency requirements. The 120 s runner
reservation covers six 15 s CLI calls, the 10 s handshake and observation
margin while the acknowledged fixture must remain alive.
"""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest


CYCLE = Path(__file__).resolve().parents[1] / "scripts" / "cycle.py"
RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "run_command.py"
ROLES = (
    "exploration", "architect", "test_author", "implementer", "runner",
    "integrator", "coverage_audit", "spec_reviewer", "standards_reviewer", "expert",
)
RESERVATION_SECONDS = 120


@unittest.skipUnless(os.name == "nt", "Windows native identity and Job recovery contract")
class CycleRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="v3-recovery-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "tests").mkdir()
        (self.workspace / "src").mkdir()
        (self.workspace / "spec.md").write_text("REQ-1: recover owned work.\n", encoding="utf-8")
        self.state = self.root / "state"
        self.models = {role: f"explicit-recovery-{role}" for role in ROLES}
        self.plan = {
            "schema": 1, "run_id": "native-recovery", "workspace": str(self.workspace),
            "spec_sources": ["spec.md"], "models": self.models,
            "budget": {"max_attempts": 4, "max_formal_failures": 2, "max_seconds": 480},
            "flows": [{"id": "main", "write_paths": ["src"]}],
            "examples": [{
                "id": "owned-work", "flow": "main", "requirement": "REQ-1/recovery",
                "depends_on": [],
                "snapshot": {
                    "schema": 1, "root": str(self.workspace), "tests": ["tests"],
                    "contract": ["spec.md"], "product": ["src"], "binding": None,
                },
            }],
            "gates": [],
        }

    def write_json(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def cycle(self, *arguments, expected_exit=0):
        result = subprocess.run(
            [sys.executable, str(CYCLE), "--state", str(self.state), *arguments],
            cwd=self.root, capture_output=True, text=True, encoding="utf-8",
            timeout=15, check=False,
        )
        self.assertEqual(
            result.returncode, expected_exit,
            f"Public cycle {arguments[0]!r} returned {result.returncode}; "
            f"expected {expected_exit}. Raw implementation diagnostics are withheld.",
        )
        lines = result.stdout.splitlines()
        self.assertTrue(lines, "The public CLI must return JSON.")
        try:
            output = json.loads(lines[-1])
        except json.JSONDecodeError:
            self.fail("The public CLI's final line must be JSON.")
        self.assertIsInstance(output, dict)
        return output

    def apply(self, op_id, operation, *, expected_exit=0, **fields):
        event_path = self.root / "event.json"
        self.write_json(event_path, {"schema": 1, "op_id": op_id, "op": operation, **fields})
        return self.cycle("apply", "--event", str(event_path), expected_exit=expected_exit)

    def prepare_probe(self):
        plan_path = self.root / "plan.json"
        self.write_json(plan_path, self.plan)
        self.cycle("init", "--plan", str(plan_path))
        self.apply(
            "open-owned-work", "open", example="owned-work",
            light_check={
                "source": "spec.md / REQ-1", "observation": "Owned execution is recoverable",
                "expected_failure": "An interrupted execution must retain its budget cost",
                "independent_context": "implementation-blind-recovery-fixture",
            },
        )
        prepared = self.apply(
            "prepare-owned-work", "prepare", example="owned-work", purpose="probe",
            timeout_seconds=RESERVATION_SECONDS,
        )
        self.apply("resume-call", "invocation", kind="resume", models=self.models)
        return prepared

    def native_process(self, pid, expected_birth=None):
        """Capture only this test's Popen process or its acknowledged target."""
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000 | 0x1000 | 0x0001, False, pid)
        self.assertTrue(handle, "The acknowledged fixture must have a native process handle.")
        self.addCleanup(kernel.CloseHandle, handle)
        times = [wintypes.FILETIME() for _ in range(4)]
        self.assertTrue(kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)))
        birth_token = str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        if expected_birth is not None:
            self.assertEqual(birth_token, expected_birth,
                             "A handshake PID must retain its birth identity before any cleanup is authorized.")

        def cleanup():
            if kernel.WaitForSingleObject(handle, 0) == 258:
                kernel.TerminateProcess(handle, 97)
                kernel.WaitForSingleObject(handle, 5000)

        self.addCleanup(cleanup)
        return kernel, handle, birth_token

    def start_owned_target(self, prepared):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        self.addCleanup(listener.close)
        address = listener.getsockname()
        marker = self.root / "target-launches.txt"
        target = (
            "import ctypes,json,os,socket; from ctypes import wintypes; from pathlib import Path; "
            "k=ctypes.WinDLL('kernel32',use_last_error=True); "
            "k.GetCurrentProcess.restype=wintypes.HANDLE; "
            "k.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4; "
            "k.GetProcessTimes.restype=wintypes.BOOL; "
            "times=[wintypes.FILETIME() for _ in range(4)]; "
            "assert k.GetProcessTimes(k.GetCurrentProcess(),*(ctypes.byref(t) for t in times)); "
            "birth=str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime); "
            f"p=Path({str(marker)!r}); "
            "f=p.open('a',encoding='utf-8'); f.write('target\\n'); f.close(); "
            f"s=socket.create_connection({address!r}); "
            "s.sendall((json.dumps({'pid':os.getpid(),'birth_token':birth})+'\\n').encode()); "
            "s.recv(1)"
        )
        controller = subprocess.Popen(
            [sys.executable, str(RUNNER), "--receipt", prepared["receipt_path"],
             "--cwd", str(self.workspace), "--timeout", str(RESERVATION_SECONDS),
             "--snapshot", prepared["request_path"], "--", sys.executable, "-c", target],
            cwd=self.root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        def cleanup_controller():
            if controller.poll() is None:
                controller.kill()
            controller.communicate(timeout=5)

        self.addCleanup(cleanup_controller)
        controller_native = self.native_process(controller.pid)
        # One monotonic evidence interval covers accept plus the entire message.
        handshake_deadline = time.monotonic() + 10
        listener.settimeout(max(0.001, handshake_deadline - time.monotonic()))
        connection, _ = listener.accept()
        self.addCleanup(connection.close)
        message = b""
        while not message.endswith(b"\n"):
            remaining = handshake_deadline - time.monotonic()
            self.assertGreater(remaining, 0, "The complete startup handshake exceeded its evidence wait.")
            connection.settimeout(remaining)
            part = connection.recv(4096)
            self.assertTrue(part, "The target must acknowledge its own live process.")
            message += part
            self.assertLessEqual(len(message), 4096, "A startup identity must be one bounded message.")
        identity = json.loads(message)
        target_native = self.native_process(identity["pid"], identity["birth_token"])
        claim_path = Path(prepared["receipt_path"] + ".claim.json")
        claim = json.loads(claim_path.read_text(encoding="utf-8"))
        self.assertEqual(claim["controller"], {
            "platform": "windows", "pid": controller.pid,
            "birth_token": controller_native[2],
        })
        self.assertEqual(Path(claim["receipt_path"]), Path(prepared["receipt_path"]))
        self.assertTrue(claim["token"])
        for kernel, handle, _ in (controller_native, target_native):
            self.assertEqual(kernel.WaitForSingleObject(handle, 0), 258)
        return controller, controller_native, target_native, connection, marker

    def assert_reserved(self, observed, prepared, state):
        self.assertEqual(observed["budget"], {
            "attempts_used": 1, "formal_failures_used": 0,
            "seconds_used": 0, "seconds_reserved": RESERVATION_SECONDS,
        })
        self.assertEqual(observed["failures"], [])
        self.assertEqual(len(observed["pending_attempts"]), 1)
        pending = observed["pending_attempts"][0]
        self.assertEqual(pending["attempt_id"], prepared["attempt_id"])
        self.assertEqual(pending["state"], state)
        self.assertEqual(pending["timeout_seconds"], RESERVATION_SECONDS)

    def test_recover_keeps_a_live_native_runner_reserved_without_restarting_it(self):
        prepared = self.prepare_probe()
        _, controller_native, target_native, _, marker = self.start_owned_target(prepared)

        recovered = self.apply("recover-live", "recover", invocation_id="resume-call")

        self.assertEqual({key: recovered[key] for key in ("ok", "status", "reason", "attempt_ids")}, {
            "ok": True, "status": "blocked", "reason": "running",
            "attempt_ids": [prepared["attempt_id"]],
        })
        observed = self.cycle("inspect")
        self.assert_reserved(observed, prepared, "running")
        self.assertEqual(observed["status"], "blocked")
        self.assertEqual(
            self.apply("recover-live", "recover", invocation_id="resume-call"), recovered,
        )
        self.assertEqual(self.cycle("inspect"), observed, "An identical op_id replay cannot append or charge.")
        for kernel, handle, _ in (controller_native, target_native):
            self.assertEqual(kernel.WaitForSingleObject(handle, 0), 258,
                             "Recovery must leave this owned live execution running.")
        self.assertFalse(Path(prepared["receipt_path"]).exists())
        self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["target"])

    def test_recover_charges_a_dead_controller_without_receipt_once(self):
        prepared = self.prepare_probe()
        controller, controller_native, target_native, _, marker = self.start_owned_target(prepared)
        kernel, handle, _ = controller_native
        self.assertTrue(kernel.TerminateProcess(handle, 98), "Terminate only the runner created by this test.")
        self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0,
                         "The test-owned controller must be observably terminated.")
        target_kernel, target_handle, _ = target_native
        self.assertEqual(target_kernel.WaitForSingleObject(target_handle, 5000), 0,
                         "The runner's Job must clean its acknowledged target after controller death.")
        controller.communicate(timeout=5)
        self.assertFalse(Path(prepared["receipt_path"]).exists(), "The interruption precedes any completed receipt.")

        recovered = self.apply("recover-dead", "recover", invocation_id="resume-call")

        self.assertIs(recovered["ok"], True)
        self.assertEqual(recovered["status"], "active")
        self.assertEqual(recovered["reconciled_attempts"], [prepared["attempt_id"]])
        observed = self.cycle("inspect")
        self.assertEqual(observed["budget"], {
            "attempts_used": 1, "formal_failures_used": 0,
            "seconds_used": RESERVATION_SECONDS, "seconds_reserved": 0,
        })
        self.assertEqual(observed["pending_attempts"], [])
        self.assertEqual(len(observed["failures"]), 1)
        failure = observed["failures"][0]
        self.assertEqual(failure["attempt_id"], prepared["attempt_id"])
        self.assertEqual(failure["classification"], "interrupted")
        self.assertIs(failure["resolved"], False)
        self.assertEqual(failure["diagnoses"], [])
        self.assertEqual(
            self.apply("recover-dead", "recover", invocation_id="resume-call"), recovered,
        )
        self.assertEqual(self.cycle("inspect"), observed)
        again = self.apply("recover-dead-again", "recover", invocation_id="resume-call")
        self.assertEqual(again["reconciled_attempts"], [])
        repeated = self.cycle("inspect")
        self.assertEqual(repeated["budget"], observed["budget"])
        self.assertEqual(repeated["failures"], observed["failures"])
        self.assertEqual(repeated["pending_attempts"], [])
        self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["target"])
        self.assertIs(self.cycle("verify")["valid"], True)

    def test_new_recover_observes_a_completed_real_receipt_and_settles_it_once(self):
        prepared = self.prepare_probe()
        controller, controller_native, target_native, connection, marker = self.start_owned_target(prepared)
        live_result = self.apply("recover-before-completion", "recover", invocation_id="resume-call")
        self.assertEqual(live_result["reason"], "running")
        self.assertEqual(live_result["attempt_ids"], [prepared["attempt_id"]])
        connection.sendall(b"x")
        controller.communicate(timeout=15)
        self.assertEqual(controller.returncode, 0, "The acknowledged target must complete through the real runner.")
        for kernel, handle, _ in (controller_native, target_native):
            self.assertEqual(kernel.WaitForSingleObject(handle, 0), 0)
        receipt = json.loads(Path(prepared["receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["outcome"], "exited")
        self.assertEqual(receipt["exit_code"], 0)
        self.assertIs(receipt["cleanup_complete"], True)
        before_settlement = self.cycle("inspect")
        self.assert_reserved(before_settlement, prepared, "running")
        self.assertEqual(
            self.apply("recover-before-completion", "recover", invocation_id="resume-call"), live_result,
            "An old op_id must replay its old observation even though the runner has now completed.",
        )
        self.assertEqual(self.cycle("inspect"), before_settlement)

        recovered = self.apply("recover-completed", "recover", invocation_id="resume-call")

        self.assertIs(recovered["ok"], True)
        self.assertEqual(recovered["status"], "active")
        self.assertEqual(recovered["reconciled_attempts"], [prepared["attempt_id"]])
        observed = self.cycle("inspect")
        self.assertEqual(observed["pending_attempts"], [])
        self.assertEqual(observed["failures"], [])
        self.assertEqual(observed["budget"], {
            "attempts_used": 1, "formal_failures_used": 0,
            "seconds_used": receipt["duration_seconds"], "seconds_reserved": 0,
        })
        self.assertEqual(
            self.apply("recover-completed", "recover", invocation_id="resume-call"), recovered,
        )
        self.assertEqual(self.cycle("inspect"), observed)
        again = self.apply("recover-completed-again", "recover", invocation_id="resume-call")
        self.assertEqual(again["reconciled_attempts"], [])
        repeated = self.cycle("inspect")
        self.assertEqual(repeated["budget"], observed["budget"])
        self.assertEqual(repeated["failures"], [])
        self.assertEqual(repeated["pending_attempts"], [])
        self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["target"])
        self.assertIs(self.cycle("verify")["valid"], True)

    def test_recover_preserves_reservation_and_processes_when_claim_identity_is_missing(self):
        prepared = self.prepare_probe()
        _, controller_native, target_native, _, marker = self.start_owned_target(prepared)
        claim_path = Path(prepared["receipt_path"] + ".claim.json")
        claim = json.loads(claim_path.read_text(encoding="utf-8"))
        # Damage only the native identity in an actual runner-created claim.
        # This is an invalid-evidence fixture, never a fabricated valid receipt.
        claim["controller"]["birth_token"] = None
        self.write_json(claim_path, claim)

        recovered = self.apply("recover-unknown", "recover", invocation_id="resume-call")

        self.assertEqual({key: recovered[key] for key in ("ok", "status", "reason", "attempt_ids")}, {
            "ok": True, "status": "blocked", "reason": "ownership-unknown",
            "attempt_ids": [prepared["attempt_id"]],
        })
        observed = self.cycle("inspect")
        self.assertEqual(observed["status"], "blocked")
        self.assert_reserved(observed, prepared, "ownership-unknown")
        self.assertEqual(
            self.apply("recover-unknown", "recover", invocation_id="resume-call"), recovered,
        )
        self.assertEqual(self.cycle("inspect"), observed)
        again = self.apply("recover-unknown-again", "recover", invocation_id="resume-call")
        self.assertEqual(again["status"], "blocked")
        self.assertEqual(again["reason"], "ownership-unknown")
        self.assertEqual(again["attempt_ids"], [prepared["attempt_id"]])
        self.assert_reserved(self.cycle("inspect"), prepared, "ownership-unknown")
        for kernel, handle, _ in (controller_native, target_native):
            self.assertEqual(kernel.WaitForSingleObject(handle, 0), 258,
                             "Insufficient claim identity never authorizes killing even the stored PID.")
        self.assertFalse(Path(prepared["receipt_path"]).exists())
        self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["target"])

    def test_cancelled_formal_attempt_consumes_the_formal_failure_limit(self):
        """Section 3.3 counts every formal interruption, even before launch."""
        self.plan["budget"]["max_formal_failures"] = 1
        (self.workspace / "spec.md").write_text("REQ-1: The fixture value must be 10.\n", encoding="utf-8")
        (self.workspace / "src" / "value.txt").write_text("10", encoding="utf-8")
        (self.workspace / "tests" / "test_value.py").write_text(
            "from pathlib import Path\n"
            "import unittest\n"
            "class ValueExample(unittest.TestCase):\n"
            "    def test_value_is_10(self):\n"
            "        self.assertEqual(Path('src/value.txt').read_text(), '10')\n"
            "unittest.main()\n",
            encoding="utf-8",
        )
        plan_path = self.root / "plan.json"
        self.write_json(plan_path, self.plan)
        self.cycle("init", "--plan", str(plan_path))
        self.apply(
            "open-formal-fixture", "open", example="owned-work",
            light_check={
                "source": "spec.md / REQ-1", "observation": "The stored fixture value is 10",
                "expected_failure": "Any different stored value violates REQ-1",
                "independent_context": "implementation-blind-formal-budget-fixture",
            },
        )
        for purpose in ("probe", "regression"):
            prepared = self.apply(
                f"prepare-fixture-{purpose}", "prepare", example="owned-work",
                purpose=purpose, timeout_seconds=5,
            )
            result = subprocess.run(
                [sys.executable, str(RUNNER), "--receipt", prepared["receipt_path"],
                 "--cwd", str(self.workspace), "--timeout", "5", "--snapshot", prepared["request_path"],
                 "--", sys.executable, "-B", "tests/test_value.py"],
                cwd=self.root, capture_output=True, timeout=15, check=False,
            )
            self.assertEqual(result.returncode, 0,
                             "The real fixture assertion must pass; raw runner diagnostics are withheld.")
            self.assertTrue(Path(prepared["receipt_path"]).is_file())
            self.apply(f"record-fixture-{purpose}", "record", attempt_id=prepared["attempt_id"])
            if purpose == "probe":
                self.apply(
                    "judge-fixture-existing", "judge", attempt_id=prepared["attempt_id"],
                    classification="existing",
                    reason="The independent assertion compares the real stored value against required value 10.",
                    evidence=[prepared["receipt_path"]],
                )
        closed = self.apply(
            "close-formal-fixture", "close", example="owned-work",
            regression_attempt_id=prepared["attempt_id"],
        )
        self.assertEqual(closed["mode"], "existing")
        # Explicit qualification inputs exercise this CLI boundary; these are
        # fixture declarations, not claims about reviews of production code.
        self.apply(
            "qualify-formal-fixture", "qualify", scope={"final": True},
            spec_review={"review_id": "fixture-spec", "source": "spec.md / REQ-1",
                         "independent_context": "fixture-spec-context", "verdict": "pass"},
            standards_review={"review_id": "fixture-standards", "source": "tests/test_value.py",
                              "independent_context": "fixture-standards-context", "verdict": "pass"},
        )
        before = self.cycle("inspect")
        self.assertEqual(before["budget"]["attempts_used"], 2)
        self.assertEqual(before["budget"]["formal_failures_used"], 0)
        formal = self.apply(
            "prepare-unstarted-formal", "prepare-formal", scope={"final": True}, timeout_seconds=5,
        )
        claim_path = Path(formal["receipt_path"] + ".claim.json")
        self.assertFalse(claim_path.exists())
        self.assertFalse(Path(formal["receipt_path"]).exists())
        self.apply("resume-formal-call", "invocation", kind="resume", models=self.models)

        recovered = self.apply("recover-unstarted-formal", "recover", invocation_id="resume-formal-call")

        self.assertEqual(recovered["reconciled_attempts"], [formal["attempt_id"]])
        claim = json.loads(claim_path.read_text(encoding="utf-8"))
        self.assertEqual(claim["cancelled_attempt"], formal["attempt_id"])
        observed = self.cycle("inspect")
        self.assertEqual(observed["budget"]["formal_failures_used"], 1)
        self.assertEqual(observed["budget"]["attempts_used"], 3)
        self.assertEqual(observed["budget"]["seconds_used"], before["budget"]["seconds_used"] + 5)
        self.assertEqual(observed["budget"]["seconds_reserved"], 0)
        self.assertEqual(observed["pending_attempts"], [])
        self.assertEqual(len(observed["failures"]), 1)
        self.assertEqual(observed["failures"][0]["attempt_id"], formal["attempt_id"])
        self.assertEqual(observed["failures"][0]["classification"], "interrupted")
        self.apply(
            "diagnose-cancelled-formal", "diagnose", attempt_id=formal["attempt_id"],
            reason="The invocation ended after preparation; recovery exclusively cancelled the unstarted formal run.",
            evidence=[str(claim_path)], next_action="Retain the failure and stop because the formal failure limit is exhausted.",
        )
        diagnosed = self.cycle("inspect")
        self.assertEqual(diagnosed["budget"], observed["budget"])
        self.assertEqual(diagnosed["failures"][0]["diagnoses"][0]["evidence"], [str(claim_path)])
        self.assertLess(diagnosed["budget"]["attempts_used"], self.plan["budget"]["max_attempts"])
        self.assertLess(diagnosed["budget"]["seconds_used"] + 5, self.plan["budget"]["max_seconds"])

        rejected = self.apply(
            "retry-after-formal-limit", "prepare-formal", scope={"final": True},
            timeout_seconds=5, expected_exit=2,
        )

        self.assertIs(rejected["ok"], False)
        self.assertEqual(self.cycle("inspect"), diagnosed, "A rejected retry cannot consume or reset any allowance.")
        self.assertIs(self.cycle("verify")["valid"], True)


if __name__ == "__main__":
    unittest.main()
