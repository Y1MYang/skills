"""Implementation-blind CLI checks for the published v3 runtime contract."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest


RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "run_command.py"


class RunCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="v3-runner-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self.receipt_path = self.base / "receipt.json"

    def runner_args(self, argv, *, timeout=5, extra=(), receipt_path=None):
        receipt_path = receipt_path or self.receipt_path
        return [sys.executable, str(RUNNER), "--receipt", str(receipt_path),
                "--cwd", str(self.workspace), "--timeout", str(timeout),
                *extra, "--", *argv]

    def run_command(self, argv, *, timeout=5, extra=(), receipt_path=None):
        return subprocess.run(
            self.runner_args(argv, timeout=timeout, extra=extra, receipt_path=receipt_path),
            capture_output=True,
            timeout=timeout + 10,
            check=False,
        )

    def receipt(self):
        self.assertTrue(self.receipt_path.is_file(), "CLI must publish a receipt")
        return json.loads(self.receipt_path.read_text(encoding="utf-8"))

    def snapshot_request(self):
        (self.workspace / "tests" / "empty").mkdir(parents=True)
        (self.workspace / "src").mkdir()
        contents = {
            "tests/test_case.py": b"assert 1 == 1\n",
            "tests/\u00e9.txt": b"unicode-path\n",
            "spec.md": b"A public requirement.\n",
            "src/main.py": b"print('fixture')\n",
        }
        for relative, content in contents.items():
            (self.workspace / relative).write_bytes(content)
        request = {
            "schema": 1, "root": str(self.workspace),
            "tests": ["tests"], "contract": ["spec.md"],
            "product": ["src", "absent.py"], "binding": None,
        }
        request_path = self.base / "snapshot.json"
        request_bytes = (json.dumps(request, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        request_path.write_bytes(request_bytes)
        expected = {
            "tests": [{"path": "tests", "kind": "directory"},
                      {"path": "tests/empty", "kind": "directory"}],
            "contract": [],
            "product": [{"path": "absent.py", "kind": "missing"},
                        {"path": "src", "kind": "directory"}],
        }
        for relative, content in contents.items():
            group = "tests" if relative.startswith("tests/") else "product" if relative.startswith("src/") else "contract"
            expected[group].append({"path": relative, "kind": "file",
                                    "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)})
        captures = {}
        for group, entries in expected.items():
            entries.sort(key=lambda entry: entry["path"])
            canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            captures[group] = {"entries": entries, "sha256": hashlib.sha256(canonical).hexdigest()}
        return request_path, request_bytes, captures

    def start_process(self, argv, *, start_new_session=False):
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=start_new_session)

        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

        self.addCleanup(cleanup)
        return process

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.workspace, capture_output=True,
                                timeout=10, check=False)
        self.assertEqual(result.returncode, 0, "Git fixture setup must succeed")
        return result.stdout.decode("utf-8").strip()

    def commit_fixture(self):
        self.git("init", "--quiet")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.hooksPath", str(self.base / "no-hooks"))
        self.git("add", "--all")
        self.git("-c", "user.name=V3 Test", "-c", "user.email=v3@example.invalid",
                 "-c", "commit.gpgSign=false", "commit", "--quiet", "-m", "fixture")
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all"), "")
        return self.git("rev-parse", "HEAD")

    def windows_process_handle(self, pid):
        # Native handles preserve identity even if a PID is later reused.
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000 | 0x1000 | 0x0001, False, pid)
        self.assertTrue(handle, f"Fixture process {pid} must be alive to capture its identity")

        def cleanup():
            if kernel.WaitForSingleObject(handle, 0) == 258:
                kernel.TerminateProcess(handle, 97)
                kernel.WaitForSingleObject(handle, 5000)
            kernel.CloseHandle(handle)

        self.addCleanup(cleanup)
        return kernel, handle

    def posix_exit_watch(self, pid):
        import errno
        import select

        if hasattr(os, "pidfd_open"):
            try:
                descriptor = os.pidfd_open(pid)
            except OSError as error:
                if error.errno not in (errno.ENOSYS, errno.EPERM):
                    raise
            else:
                self.addCleanup(os.close, descriptor)
                return lambda seconds: bool(select.select([descriptor], [], [], seconds)[0])
        if hasattr(select, "kqueue"):
            queue = select.kqueue()
            self.addCleanup(queue.close)
            queue.control([select.kevent(pid, filter=select.KQ_FILTER_PROC,
                                        flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                                        fflags=select.KQ_NOTE_EXIT)], 0, 0)
            return lambda seconds: bool(queue.control(None, 1, seconds))
        self.skipTest("No native stable process-exit observer on this POSIX platform")

    def start_signalled_tree(self, timeout, *, finish_parent=False, on_start=None):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(3)
        listener.settimeout(5)
        self.addCleanup(listener.close)
        address = listener.getsockname()

        def waiter(role):
            return (
                "import json,os,socket; "
                f"s=socket.create_connection({address!r}); "
                f"s.sendall((json.dumps({{'role':{role!r},'pid':os.getpid()}})+'\\n').encode()); "
                "s.recv(1)"
            )

        outsider = self.start_process([sys.executable, "-c", waiter("outsider")])
        child = waiter("child")
        parent = "import subprocess,sys; " + f"subprocess.Popen([sys.executable,'-c',{child!r}]); " + waiter("parent")
        controller_started = time.monotonic()
        controller = self.start_process(self.runner_args([sys.executable, "-c", parent], timeout=timeout))
        if on_start is not None:
            on_start(controller)
        identities = {}
        connections = {}
        for _ in range(3):
            connection, _ = listener.accept()
            connection.settimeout(5)
            self.addCleanup(connection.close)
            message = b""
            while not message.endswith(b"\n"):
                part = connection.recv(4096)
                self.assertTrue(part, "Fixture must send its startup identity before closing")
                message += part
            identity = json.loads(message)
            self.assertNotIn(identity["role"], identities)
            identities[identity["role"]] = self.windows_process_handle(identity["pid"])
            connections[identity["role"]] = connection
        self.assertEqual(set(identities), {"parent", "child", "outsider"})
        for kernel, handle in identities.values():
            self.assertEqual(kernel.WaitForSingleObject(handle, 0), 258,
                             "Fixture process must be alive after its startup signal")
        if finish_parent:
            connections["parent"].sendall(b"x")
        return controller, outsider, identities, controller_started

    def test_real_success_publishes_exit_receipt(self):
        # Runtime contract §2: a real target exit 0 is a successful owned run.
        marker = self.workspace / "executed.txt"
        argv = [sys.executable, "-c",
                "from pathlib import Path; Path('executed.txt').write_text('ran')"]

        result = self.run_command(argv)

        self.assertEqual(
            result.returncode, 0,
            f"Expected successful CLI execution; public CLI present={RUNNER.is_file()}",
        )
        self.assertEqual(marker.read_text(encoding="utf-8"), "ran")
        self.assertEqual(json.loads(result.stdout.splitlines()[-1]), {
            "ok": True, "receipt_path": str(self.receipt_path),
            "outcome": "exited", "exit_code": 0,
        })
        receipt = self.receipt()
        self.assertIs(type(receipt["schema"]), int)
        self.assertEqual(receipt["schema"], 1)
        self.assertEqual(receipt["argv"], argv)
        self.assertEqual(Path(receipt["cwd"]), self.workspace)
        self.assertEqual(receipt["outcome"], "exited")
        self.assertEqual(receipt["exit_code"], 0)
        self.assertIs(receipt["cleanup_complete"], True)

    def test_real_nonzero_keeps_target_code_and_returns_failure(self):
        # Runtime contract §2 distinguishes the wrapper code from target code.
        result = self.run_command([sys.executable, "-c", "raise SystemExit(7)"])

        self.assertEqual(result.returncode, 1)
        receipt = self.receipt()
        self.assertEqual(receipt["outcome"], "exited")
        self.assertEqual(receipt["exit_code"], 7)
        self.assertIs(receipt["cleanup_complete"], True)

    def test_binary_logs_preserve_bytes_and_publish_independent_hashes(self):
        # Runtime contract §2 binds each closed log to its actual bytes.
        expected = {
            "stdout": b"private-stdout\x00\xff\r\n",
            "stderr": b"private-stderr\x00\xfe\n",
        }
        target = (
            "import os; "
            f"os.write(1, bytes.fromhex('{expected['stdout'].hex()}')); "
            f"os.write(2, bytes.fromhex('{expected['stderr'].hex()}'))"
        )

        result = self.run_command([sys.executable, "-c", target])

        self.assertEqual(result.returncode, 0)
        receipt = self.receipt()
        for stream, content in expected.items():
            with self.subTest(stream=stream):
                log = receipt["logs"][stream]
                path = Path(log["path"])
                self.assertTrue(path.is_absolute())
                self.assertEqual(path, Path(str(self.receipt_path) + f".{stream}.log"))
                self.assertEqual(path.read_bytes(), content)
                self.assertEqual(log["size"], len(content))
                self.assertEqual(log["sha256"], hashlib.sha256(content).hexdigest())
                self.assertNotIn(content, result.stdout)
                self.assertNotIn(content, result.stderr)
                self.assertNotIn(content.split(b"\x00")[0], result.stdout)
                self.assertNotIn(content.split(b"\x00")[0], result.stderr)

    def test_snapshot_hashes_actual_files_directories_and_missing_paths(self):
        # Runtime contract §2 specifies entries and canonical group digests.
        request_path, request_bytes, expected = self.snapshot_request()

        result = self.run_command([sys.executable, "-c", "pass"],
                                  extra=["--snapshot", str(request_path)])

        self.assertEqual(result.returncode, 0)
        snapshot = self.receipt()["snapshot"]
        self.assertIsInstance(snapshot, dict, "A supplied snapshot request must be captured")
        self.assertEqual(snapshot["request_sha256"], hashlib.sha256(request_bytes).hexdigest())
        self.assertIsNone(snapshot["binding"])
        self.assertEqual(snapshot["before"], expected)
        self.assertEqual(snapshot["after"], expected)

    def test_snapshot_records_empty_directory_added_during_execution(self):
        # A directory change alone must invalidate the previously captured group.
        request_path, _, expected_before = self.snapshot_request()
        target = "from pathlib import Path; Path('src/new-empty').mkdir()"

        result = self.run_command([sys.executable, "-c", target],
                                  extra=["--snapshot", str(request_path)])

        self.assertEqual(result.returncode, 0)
        snapshot = self.receipt()["snapshot"]
        self.assertEqual(snapshot["before"], expected_before)
        entries = [*expected_before["product"]["entries"],
                   {"path": "src/new-empty", "kind": "directory"}]
        entries.sort(key=lambda entry: entry["path"])
        canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        expected_after = {**expected_before, "product": {
            "entries": entries, "sha256": hashlib.sha256(canonical).hexdigest(),
        }}
        self.assertEqual(snapshot["after"], expected_after)

    def test_second_call_cannot_replace_receipt_or_repeat_target(self):
        # Published evidence and its claim remain immutable even after failure.
        first = self.run_command([sys.executable, "-c", "raise SystemExit(9)"])
        self.assertEqual(first.returncode, 1)
        artifacts = [self.receipt_path] + [
            Path(str(self.receipt_path) + suffix)
            for suffix in (".stdout.log", ".stderr.log", ".claim.json")
        ]
        original = {path: path.read_bytes() for path in artifacts}
        repeated_marker = self.workspace / "repeated.txt"
        target = "from pathlib import Path; Path('repeated.txt').write_text('ran')"

        repeated = self.run_command([sys.executable, "-c", target])

        self.assertEqual(repeated.returncode, 2)
        self.assertFalse(repeated_marker.exists(), "A reused receipt must reject before target launch")
        self.assertEqual({path: path.read_bytes() for path in artifacts}, original)

    def test_existing_companion_log_prevents_target_launch(self):
        # A partial old attempt is protected even when no receipt exists yet.
        existing_log = Path(str(self.receipt_path) + ".stdout.log")
        original = b"previous attempt evidence\x00\xff"
        existing_log.write_bytes(original)
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = self.run_command([sys.executable, "-c", target])

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())
        self.assertEqual(existing_log.read_bytes(), original)

    def test_missing_executable_is_launch_error_not_target_failure(self):
        # The target never starts, so it has no actual exit code.
        missing_executable = self.workspace / "does-not-exist.exe"

        result = self.run_command([str(missing_executable)])

        self.assertEqual(result.returncode, 2)
        receipt = self.receipt()
        self.assertEqual(receipt["outcome"], "launch_error")
        self.assertIsNone(receipt["exit_code"])
        self.assertIs(receipt["cleanup_complete"], True)

    def test_cycle_request_preserves_binding_and_reserved_timeout(self):
        # Runtime contract §3.1 extends the request at its root, not its binding.
        request_path, _, _ = self.snapshot_request()
        request = json.loads(request_path.read_text(encoding="utf-8"))
        binding = {
            "run_id": "run-fixture", "example": "current-example", "gate": None,
            "attempt_id": "attempt-fixture", "purpose": "probe", "prepared_seq": 3,
            "prepared_at": datetime.now(timezone.utc).isoformat(),
        }
        request.update(binding=binding, timeout_seconds=5)
        request_path.write_text(json.dumps(request), encoding="utf-8")

        result = self.run_command([sys.executable, "-c", "raise SystemExit(1)"],
                                  extra=["--snapshot", str(request_path)])

        self.assertEqual(result.returncode, 1)
        receipt = self.receipt()
        self.assertEqual(receipt["snapshot"]["binding"], binding)
        self.assertEqual(receipt["timeout_seconds"], 5)

    def test_request_timeout_mismatch_rejects_before_target_launch(self):
        request_path, _, _ = self.snapshot_request()
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["binding"] = {
            "run_id": "run-fixture", "example": "current-example", "gate": None,
            "attempt_id": "attempt-fixture", "purpose": "probe", "prepared_seq": 3,
            "prepared_at": datetime.now(timezone.utc).isoformat(),
        }
        request["timeout_seconds"] = 4
        request_path.write_text(json.dumps(request), encoding="utf-8")
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = self.run_command([sys.executable, "-c", target], timeout=5,
                                  extra=["--snapshot", str(request_path)])

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())

    def test_binding_unknown_field_is_rejected_before_target_launch(self):
        request_path, _, _ = self.snapshot_request()
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request.update(timeout_seconds=5, binding={
            "run_id": "run-fixture", "example": "current-example", "gate": None,
            "attempt_id": "attempt-fixture", "purpose": "probe", "prepared_seq": 3,
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "caller_exit_code": 0,
        })
        request_path.write_text(json.dumps(request), encoding="utf-8")
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = self.run_command([sys.executable, "-c", target],
                                  extra=["--snapshot", str(request_path)])

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())
        response = json.loads(result.stdout.splitlines()[-1])
        self.assertIs(response["ok"], False)
        self.assertTrue(response["error"]["code"].strip())
        self.assertTrue(response["error"]["message"].strip())

    @unittest.skipUnless(os.name == "nt", "Native Windows process identity check")
    def test_timeout_stops_owned_tree_and_preserves_unrelated_process(self):
        # Handshakes prove both owned processes existed before testing cleanup.
        timeout = 3
        controller, outsider, identities, started = self.start_signalled_tree(timeout)

        controller.communicate(timeout=timeout + 6)

        self.assertEqual(controller.returncode, 124)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, timeout)
        # The external timer also includes Python CLI startup and scheduling.
        self.assertLessEqual(elapsed, timeout + 5.5)
        for role in ("parent", "child"):
            kernel, handle = identities[role]
            self.assertEqual(kernel.WaitForSingleObject(handle, 0), 0,
                             f"Owned {role} must have stopped before the receipt is accepted")
        kernel, handle = identities["outsider"]
        self.assertEqual(kernel.WaitForSingleObject(handle, 0), 258)
        self.assertIsNone(outsider.poll())
        receipt = self.receipt()
        self.assertEqual(receipt["outcome"], "timeout")
        self.assertIsNone(receipt["exit_code"])
        self.assertIs(receipt["cleanup_complete"], True)
        self.assertEqual(receipt["owner"]["platform"], "windows")
        self.assertEqual(receipt["owner"]["kind"], "job")

    @unittest.skipUnless(os.name == "nt", "Windows kill-on-job-close contract")
    def test_controller_death_stops_its_tree_without_harming_other_processes(self):
        controller, outsider, identities, started = self.start_signalled_tree(timeout=30)

        deadline = time.monotonic() + 5
        self.assertLess(deadline, started + 30, "Cleanup observation must precede natural timeout")
        controller.kill()
        controller.communicate(timeout=max(0, deadline - time.monotonic()))

        for role in ("parent", "child"):
            kernel, handle = identities[role]
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            self.assertEqual(kernel.WaitForSingleObject(handle, remaining_ms), 0,
                             f"Owned {role} must stop when its controller dies")
        kernel, handle = identities["outsider"]
        self.assertEqual(kernel.WaitForSingleObject(handle, 0), 258)
        self.assertIsNone(outsider.poll())

    @unittest.skipUnless(os.name == "nt", "Windows native claim identity")
    def test_claim_binds_actual_controller_birth_time_and_receipt_owner(self):
        import ctypes
        from ctypes import wintypes

        controller, _, _, _ = self.start_signalled_tree(timeout=2)
        kernel, handle = self.windows_process_handle(controller.pid)
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetProcessTimes.restype = wintypes.BOOL
        creation, exit_time, kernel_time, user_time = [wintypes.FILETIME() for _ in range(4)]
        self.assertTrue(kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time),
                                               ctypes.byref(kernel_time), ctypes.byref(user_time)))
        birth_token = str((creation.dwHighDateTime << 32) | creation.dwLowDateTime)

        claim = json.loads(Path(str(self.receipt_path) + ".claim.json").read_text(encoding="utf-8"))

        self.assertEqual(set(claim), {"schema", "receipt_path", "token", "controller", "created_at"})
        self.assertIs(type(claim["schema"]), int)
        self.assertEqual(claim["schema"], 1)
        self.assertEqual(claim["receipt_path"], str(self.receipt_path))
        self.assertEqual(claim["controller"], {
            "platform": "windows", "pid": controller.pid, "birth_token": birth_token,
        })
        self.assertTrue(claim["token"].strip())
        self.assertEqual(datetime.fromisoformat(claim["created_at"]).utcoffset().total_seconds(), 0)
        controller.communicate(timeout=7)
        self.assertEqual(claim["token"], self.receipt()["owner"]["token"])

    def test_formal_success_records_actual_clean_committed_head(self):
        request_path, _, expected_snapshot = self.snapshot_request()
        head = self.commit_fixture()

        result = self.run_command([sys.executable, "-c", "pass"],
                                  extra=["--snapshot", str(request_path), "--formal"])

        self.assertEqual(result.returncode, 0)
        receipt = self.receipt()
        self.assertEqual(receipt["formal"], {
            "requested": True, "head_before": head, "head_after": head,
            "clean_before": True, "clean_after": True,
        })
        self.assertEqual(receipt["snapshot"]["before"], expected_snapshot)
        self.assertEqual(receipt["snapshot"]["after"], expected_snapshot)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all"), "")

    def test_formal_dirty_worktree_is_rejected_before_target_launch(self):
        request_path, _, _ = self.snapshot_request()
        self.commit_fixture()
        (self.workspace / "untracked.txt").write_text("dirty", encoding="utf-8")
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = self.run_command([sys.executable, "-c", target],
                                  extra=["--snapshot", str(request_path), "--formal"])

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())

    def test_formal_receipt_exposes_head_change_during_execution(self):
        request_path, _, _ = self.snapshot_request()
        head_before = self.commit_fixture()
        target = ["git", "-c", "user.name=V3 Test", "-c", "user.email=v3@example.invalid",
                  "-c", "commit.gpgSign=false", "commit", "--quiet", "--allow-empty", "-m", "changed"]

        result = self.run_command(target, extra=["--snapshot", str(request_path), "--formal"])

        self.assertEqual(result.returncode, 0)
        head_after = self.git("rev-parse", "HEAD")
        self.assertNotEqual(head_after, head_before, "Fixture must actually change HEAD")
        self.assertEqual(self.receipt()["formal"], {
            "requested": True, "head_before": head_before, "head_after": head_after,
            "clean_before": True, "clean_after": True,
        })

    def test_formal_receipt_exposes_worktree_dirtied_by_target(self):
        request_path, _, _ = self.snapshot_request()
        head = self.commit_fixture()
        target = "from pathlib import Path; Path('src/main.py').write_bytes(b'changed\\n')"

        result = self.run_command([sys.executable, "-c", target],
                                  extra=["--snapshot", str(request_path), "--formal"])

        self.assertEqual(result.returncode, 0)
        receipt = self.receipt()
        self.assertEqual(receipt["formal"], {
            "requested": True, "head_before": head, "head_after": head,
            "clean_before": True, "clean_after": False,
        })
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertNotEqual(self.git("status", "--porcelain", "--untracked-files=all"), "")
        self.assertNotEqual(receipt["snapshot"]["before"]["product"],
                            receipt["snapshot"]["after"]["product"])

    @unittest.skipUnless(os.name == "nt", "Native Windows descendant lifecycle")
    def test_normal_target_exit_cleans_still_running_descendant(self):
        controller, outsider, identities, started = self.start_signalled_tree(timeout=30, finish_parent=True)
        self.assertLess(time.monotonic() + 5.5, started + 30,
                        "Cleanup observation must precede natural timeout")

        controller.communicate(timeout=5.5)

        self.assertEqual(controller.returncode, 0)
        for role in ("parent", "child"):
            kernel, handle = identities[role]
            self.assertEqual(kernel.WaitForSingleObject(handle, 0), 0,
                             f"Owned {role} must be finished when success is published")
        self.assertIsNone(outsider.poll())
        receipt = self.receipt()
        self.assertEqual(receipt["outcome"], "exited")
        self.assertEqual(receipt["exit_code"], 0)
        self.assertIs(receipt["cleanup_complete"], True)

    def test_snapshot_unknown_field_is_rejected_before_launch(self):
        request_path, _, _ = self.snapshot_request()
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["supplied_sha256"] = "0" * 64
        request_path.write_text(json.dumps(request), encoding="utf-8")
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = self.run_command([sys.executable, "-c", target],
                                  extra=["--snapshot", str(request_path)])

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())

    def test_boolean_snapshot_schema_is_not_accepted_as_integer_one(self):
        request_path, _, _ = self.snapshot_request()
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["schema"] = True
        request_path.write_text(json.dumps(request), encoding="utf-8")
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = self.run_command([sys.executable, "-c", target],
                                  extra=["--snapshot", str(request_path)])

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())

    def test_boolean_reserved_timeout_is_rejected_before_target_launch(self):
        request_path, _, _ = self.snapshot_request()
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request.update(timeout_seconds=1, binding={
            "run_id": "run-fixture", "example": "current-example", "gate": None,
            "attempt_id": "attempt-fixture", "purpose": "probe", "prepared_seq": 3,
            "prepared_at": datetime.now(timezone.utc).isoformat(),
        })
        request_path.write_text(json.dumps(request), encoding="utf-8")
        accepted = self.run_command(
            [sys.executable, "-c", "from pathlib import Path; Path('accepted.txt').write_text('ran')"],
            timeout=1, extra=["--snapshot", str(request_path)],
            receipt_path=self.base / "valid-timeout-receipt.json",
        )
        self.assertEqual(accepted.returncode, 0, "Numeric timeout_seconds=1 remains valid")
        self.assertTrue((self.workspace / "accepted.txt").is_file())
        request["timeout_seconds"] = True
        request_path.write_text(json.dumps(request), encoding="utf-8")
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = self.run_command([sys.executable, "-c", target], timeout=1,
                                  extra=["--snapshot", str(request_path)])

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())
        response = json.loads(result.stdout.splitlines()[-1])
        self.assertIs(response["ok"], False)
        self.assertTrue(response["error"]["code"].strip())
        self.assertTrue(response["error"]["message"].strip())

    @unittest.skipUnless(os.name == "nt", "Windows same-file path aliases")
    def test_snapshot_rejects_duplicate_file_identity_with_different_case(self):
        request_path, _, _ = self.snapshot_request()
        source = self.workspace / "spec.md"
        alias = self.workspace / "SPEC.MD"
        if not alias.exists() or not source.samefile(alias):
            self.skipTest("This directory treats the two spellings as distinct file identities")
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["contract"] = ["SPEC.MD"]
        request_path.write_text(json.dumps(request), encoding="utf-8")
        accepted = self.run_command(
            [sys.executable, "-c", "from pathlib import Path; Path('accepted.txt').write_text('ran')"],
            extra=["--snapshot", str(request_path)], receipt_path=self.base / "valid-alias-receipt.json",
        )
        self.assertEqual(accepted.returncode, 0, "A single equivalent spelling remains a valid path")
        self.assertTrue((self.workspace / "accepted.txt").is_file())
        request["contract"] = ["spec.md", "SPEC.MD"]
        request_path.write_text(json.dumps(request), encoding="utf-8")
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = self.run_command([sys.executable, "-c", target],
                                  extra=["--snapshot", str(request_path)])

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())
        response = json.loads(result.stdout.splitlines()[-1])
        self.assertIs(response["ok"], False)
        self.assertTrue(response["error"]["code"].strip())
        self.assertTrue(response["error"]["message"].strip())

    @unittest.skipUnless(os.name == "nt", "Windows missing-path identity follows its existing parent")
    def test_snapshot_rejects_duplicate_missing_paths_with_different_case(self):
        request_path, _, _ = self.snapshot_request()
        source = self.workspace / "spec.md"
        alias = self.workspace / "SPEC.MD"
        if not alias.exists() or not source.samefile(alias):
            self.skipTest("The existing parent directory does not equate these case spellings")
        missing_paths = [self.workspace / name for name in ("missing.py", "MISSING.PY")]
        self.assertFalse(any(path.exists() for path in missing_paths))
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["product"] = ["MISSING.PY"]
        request_path.write_text(json.dumps(request), encoding="utf-8")
        accepted = self.run_command(
            [sys.executable, "-c", "from pathlib import Path; Path('accepted.txt').write_text('ran')"],
            extra=["--snapshot", str(request_path)], receipt_path=self.base / "valid-missing-receipt.json",
        )
        self.assertEqual(accepted.returncode, 0, "A single missing path remains valid")
        self.assertTrue((self.workspace / "accepted.txt").is_file())
        self.assertFalse(any(path.exists() for path in missing_paths))
        request["product"] = ["missing.py", "MISSING.PY"]
        request_path.write_text(json.dumps(request), encoding="utf-8")
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = self.run_command([sys.executable, "-c", target],
                                  extra=["--snapshot", str(request_path)])

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())
        response = json.loads(result.stdout.splitlines()[-1])
        self.assertIs(response["ok"], False)
        self.assertTrue(response["error"]["code"].strip())
        self.assertTrue(response["error"]["message"].strip())

    def test_snapshot_parent_path_is_rejected_before_launch(self):
        request_path, _, _ = self.snapshot_request()
        (self.base / "outside.txt").write_text("outside root", encoding="utf-8")
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["product"] = ["../outside.txt"]
        request_path.write_text(json.dumps(request), encoding="utf-8")
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = self.run_command([sys.executable, "-c", target],
                                  extra=["--snapshot", str(request_path)])

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())

    def test_invalid_timeout_cli_returns_json_error_without_launch(self):
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = subprocess.run(
            self.runner_args([sys.executable, "-c", target], timeout="not-a-number"),
            capture_output=True, timeout=10, check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())
        self.assertTrue(result.stdout.splitlines(), "Rejected CLI input still returns a JSON object")
        response = json.loads(result.stdout.splitlines()[-1])
        self.assertIs(response["ok"], False)
        self.assertTrue(response["error"]["code"].strip())
        self.assertTrue(response["error"]["message"].strip())

    @unittest.skipUnless(os.name == "nt", "Windows running-tree progress fixture")
    def test_progress_is_observable_while_the_command_is_still_running(self):
        observed = []
        observer = None

        def begin_observing(controller):
            nonlocal observer

            def observe():
                for line in iter(controller.stderr.readline, b""):
                    command_running = controller.poll() is None
                    observed.append((time.monotonic(), line, command_running))

            observer = threading.Thread(target=observe, daemon=True)
            observer.start()

        controller, _, _, started = self.start_signalled_tree(timeout=3, on_start=begin_observing)
        controller.wait(timeout=9)
        observer.join(timeout=1)

        self.assertFalse(observer.is_alive(), "Progress stream must close with the controller")
        self.assertEqual(controller.returncode, 124)
        progress = []
        for stamp, line, command_running in observed:
            try:
                event = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(event, dict) and event.get("event") == "progress":
                progress.append((stamp, event, command_running))
        self.assertTrue(progress, "A run lasting several periods must publish a progress event")
        self.assertTrue(any(command_running for _, _, command_running in progress),
                        "Progress must be received while the command is still running")
        for stamp, event, _ in progress:
            self.assertEqual(event["receipt_path"], str(self.receipt_path.resolve()))
            elapsed = event["elapsed_seconds"]
            self.assertIn(type(elapsed), (int, float))
            self.assertTrue(math.isfinite(elapsed))
            self.assertGreaterEqual(elapsed, 0)
            # The external clock starts before the runner. Reception can be late,
            # so it supplies only an upper bound, with the public <1s representation error.
            self.assertLess(elapsed, stamp - started + 1)

    @unittest.skipUnless(os.name == "nt", "Windows raw DWORD exit status")
    def test_windows_native_high_exit_code_is_preserved_without_truncation(self):
        expected = 0xC0000005
        target = (
            "import ctypes; exit_process=ctypes.windll.kernel32.ExitProcess; "
            "exit_process.argtypes=[ctypes.c_uint32]; exit_process(0xC0000005)"
        )
        direct = subprocess.run([sys.executable, "-c", target],
                                capture_output=True, timeout=5, check=False)
        self.assertEqual(direct.returncode, expected, "The independent OS fixture must expose the DWORD")

        result = self.run_command([sys.executable, "-c", target])

        self.assertEqual(result.returncode, 1)
        receipt = self.receipt()
        self.assertEqual(receipt["outcome"], "exited")
        self.assertEqual(receipt["exit_code"], expected)

    def test_lost_snapshot_root_returns_structured_error_and_keeps_logs(self):
        root = self.base / "empty-snapshot-root"
        root.mkdir()
        request = {
            "schema": 1, "root": str(root), "tests": ["tests/missing.py"],
            "contract": ["spec.md"], "product": ["src/missing.py"], "binding": None,
        }
        request_path = self.base / "snapshot.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        target = (
            "import os; from pathlib import Path; "
            "os.write(1,b'original stdout'); os.write(2,b'original stderr'); "
            f"Path({str(root)!r}).rmdir()"
        )

        result = self.run_command([sys.executable, "-c", target],
                                  extra=["--snapshot", str(request_path)])

        self.assertFalse(root.exists(), "The target must actually remove the snapshot root")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stdout.splitlines(), "Failure to finish evidence still returns JSON")
        response = json.loads(result.stdout.splitlines()[-1])
        self.assertIs(response["ok"], False)
        self.assertTrue(response["error"]["code"].strip())
        self.assertTrue(response["error"]["message"].strip())
        self.assertEqual(Path(str(self.receipt_path) + ".stdout.log").read_bytes(), b"original stdout")
        self.assertEqual(Path(str(self.receipt_path) + ".stderr.log").read_bytes(), b"original stderr")

    @unittest.skipUnless(os.name == "posix", "POSIX TERM then forced group cleanup")
    def test_posix_timeout_forces_exit_after_term_without_harming_other_group(self):
        import select

        if not hasattr(os, "pidfd_open") and not hasattr(select, "kqueue"):
            self.skipTest("Native process-exit observation is unavailable")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(3)
        listener.settimeout(5)
        self.addCleanup(listener.close)
        address = listener.getsockname()

        def waiter(role, child=None):
            spawn = "" if child is None else f"subprocess.Popen([sys.executable,'-c',{child!r}])\n"
            return (
                "import json,os,signal,socket,subprocess,sys\n"
                f"sock=socket.create_connection({address!r})\n"
                "def on_term(signum,frame):\n"
                "    sock.sendall(b'term\\n')\n"
                "signal.signal(signal.SIGTERM,on_term)\n" + spawn +
                f"sock.sendall((json.dumps({{'role':{role!r},'pid':os.getpid(),"
                "'pgid':os.getpgrp(),'sid':os.getsid(0)})+'\\n').encode())\n"
                "sock.recv(1)\n"
            )

        outsider = self.start_process([sys.executable, "-c", waiter("outsider")], start_new_session=True)
        timeout = 3
        started = time.monotonic()
        controller = self.start_process(self.runner_args(
            [sys.executable, "-c", waiter("parent", waiter("child"))], timeout=timeout),
            start_new_session=True)
        deadline = started + timeout + 5.5
        connections, identities, watches = {}, {}, {}
        for _ in range(3):
            connection, _ = listener.accept()
            connection.settimeout(5)
            self.addCleanup(connection.close)
            message = b""
            while not message.endswith(b"\n"):
                part = connection.recv(1)
                self.assertTrue(part, "Fixture must identify itself before exit")
                message += part
            identity = json.loads(message)
            role = identity["role"]
            self.assertNotIn(role, identities)
            identities[role], connections[role] = identity, connection
            watches[role] = self.posix_exit_watch(identity["pid"])
            self.assertFalse(watches[role](0), "Fixture must still be alive after its signal")
        self.assertEqual(set(identities), {"parent", "child", "outsider"})
        parent, child, outside = (identities[role] for role in ("parent", "child", "outsider"))
        self.assertEqual((parent["sid"], parent["pgid"]), (child["sid"], child["pgid"]))
        self.assertEqual(parent["sid"], parent["pgid"])
        self.assertNotEqual(parent["pgid"], outside["pgid"])

        controller.communicate(timeout=max(0, deadline - time.monotonic()))

        self.assertEqual(controller.returncode, 124)
        self.assertGreaterEqual(time.monotonic() - started, timeout)
        self.assertLessEqual(time.monotonic(), deadline)
        for role in ("parent", "child"):
            self.assertTrue(watches[role](0), f"Owned {role} must have actually exited")
            connection = connections[role]
            connection.settimeout(max(0.001, deadline - time.monotonic()))
            observed = b""
            while True:
                part = connection.recv(4096)
                if not part:
                    break
                observed += part
            self.assertIn(b"term\n", observed, f"No TERM signal was observed by {role}")
        self.assertIsNone(outsider.poll())
        self.assertFalse(watches["outsider"](0))
        self.assertFalse(select.select([connections["outsider"]], [], [], 0)[0])
        receipt = self.receipt()
        self.assertEqual(receipt["outcome"], "timeout")
        self.assertIsNone(receipt["exit_code"])
        self.assertIs(receipt["cleanup_complete"], True)
        self.assertEqual(receipt["owner"]["platform"], "posix")
        self.assertEqual(receipt["owner"]["kind"], "session")

    def test_active_receipt_claim_rejects_overlapping_target_execution(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)
        self.addCleanup(listener.close)
        target = (
            "import socket; from pathlib import Path; "
            "f=Path('executions.bin').open('ab'); f.write(b'X'); f.close(); "
            f"s=socket.create_connection({listener.getsockname()!r}); s.sendall(b'ready'); s.recv(1)"
        )
        first = self.start_process(self.runner_args([sys.executable, "-c", target], timeout=10))
        connection, _ = listener.accept()
        connection.settimeout(5)
        self.addCleanup(connection.close)
        ready = b""
        ready_deadline = time.monotonic() + 5
        while len(ready) < 5:
            connection.settimeout(max(0.001, ready_deadline - time.monotonic()))
            part = connection.recv(5 - len(ready))
            self.assertTrue(part, "The first target must finish its startup signal")
            ready += part
        self.assertEqual(ready, b"ready")
        self.assertIsNone(first.poll(), "The first command must still own its active claim")
        self.assertFalse(self.receipt_path.exists(), "The first target has not finished")
        repeated = "from pathlib import Path; f=Path('executions.bin').open('ab'); f.write(b'Y'); f.close()"

        second = self.start_process(self.runner_args([sys.executable, "-c", repeated]))
        second.communicate(timeout=5)

        self.assertEqual(second.returncode, 2)
        self.assertIsNone(first.poll(), "The second invocation must finish while the first is active")
        connection.sendall(b"x")
        first.communicate(timeout=5)

        self.assertEqual(sorted([first.returncode, second.returncode]), [0, 2])
        self.assertEqual((self.workspace / "executions.bin").read_bytes(), b"X")
        receipt = self.receipt()
        self.assertEqual(receipt["outcome"], "exited")
        self.assertEqual(receipt["exit_code"], 0)
        claim = json.loads(Path(str(self.receipt_path) + ".claim.json").read_text(encoding="utf-8"))
        self.assertEqual(claim["token"], receipt["owner"]["token"])

    @unittest.skipUnless(os.name == "nt", "Windows directory-junction boundary")
    def test_snapshot_rejects_nested_directory_junction_before_launch(self):
        request_path, _, _ = self.snapshot_request()
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "content.txt").write_text("outside snapshot root", encoding="utf-8")
        junction = self.workspace / "src" / "external"
        created = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
                                 capture_output=True, timeout=5, check=False)
        self.assertEqual(created.returncode, 0, "Directory junction fixture must be created")
        self.assertTrue(junction.is_junction())
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = self.run_command([sys.executable, "-c", target],
                                  extra=["--snapshot", str(request_path)])

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())
        self.assertEqual((outside / "content.txt").read_text(encoding="utf-8"), "outside snapshot root")

    def test_target_arguments_keep_shell_metacharacters_literal(self):
        arguments = ["with spaces", "& echo expanded > unexpected.txt", "%COMSPEC%",
                     "$HOME", "quote\"inside", "semi;colon", "line\nbreak"]
        target = (
            "import json,sys; from pathlib import Path; "
            "Path('arguments.json').write_text(json.dumps(sys.argv[1:]),encoding='utf-8')"
        )

        result = self.run_command([sys.executable, "-c", target, *arguments])

        self.assertEqual(result.returncode, 0)
        actual = json.loads((self.workspace / "arguments.json").read_text(encoding="utf-8"))
        self.assertEqual(actual, arguments)
        self.assertFalse((self.workspace / "unexpected.txt").exists())

    @unittest.skipUnless(os.name == "nt", "Windows owned-bootstrap interruption")
    def test_bootstrap_exit_zero_is_not_misreported_as_target_success(self):
        import ctypes
        from ctypes import wintypes

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)
        self.addCleanup(listener.close)
        target = (
            "import ctypes,json,os,socket\n"
            "from ctypes import wintypes\n"
            "kernel=ctypes.WinDLL('kernel32',use_last_error=True)\n"
            "kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]\n"
            "kernel.OpenProcess.restype=wintypes.HANDLE\n"
            "kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]\n"
            "kernel.TerminateProcess.restype=wintypes.BOOL\n"
            f"sock=socket.create_connection({listener.getsockname()!r})\n"
            "sock.sendall((json.dumps({'pid':os.getpid(),'parent':os.getppid()})+'\\n').encode())\n"
            "sock.recv(1)\n"
            "handle=kernel.OpenProcess(1,False,os.getppid())\n"
            "if not handle or not kernel.TerminateProcess(handle,0): raise SystemExit(91)\n"
            "sock.recv(1)\n"
        )
        controller = self.start_process(self.runner_args([sys.executable, "-c", target], timeout=5))
        connection, _ = listener.accept()
        connection.settimeout(5)
        self.addCleanup(connection.close)
        message = b""
        while not message.endswith(b"\n"):
            part = connection.recv(1)
            self.assertTrue(part, "Target must identify its own parent before the fixture acts")
            message += part
        identity = json.loads(message)
        target_kernel, target_handle = self.windows_process_handle(identity["pid"])
        parent_kernel, parent_handle = self.windows_process_handle(identity["parent"])
        self.assertEqual(parent_kernel.WaitForSingleObject(parent_handle, 0), 258)

        connection.sendall(b"x")
        stdout, _ = controller.communicate(timeout=10)

        self.assertEqual(parent_kernel.WaitForSingleObject(parent_handle, 0), 0)
        parent_kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        parent_kernel.GetExitCodeProcess.restype = wintypes.BOOL
        parent_exit = wintypes.DWORD()
        self.assertTrue(parent_kernel.GetExitCodeProcess(parent_handle, ctypes.byref(parent_exit)))
        self.assertEqual(parent_exit.value, 0, "Fixture must actually terminate its own parent with zero")
        self.assertEqual(target_kernel.WaitForSingleObject(target_handle, 0), 0)
        self.assertEqual(controller.returncode, 2)
        self.assertTrue(stdout.splitlines(), "Lost target-result evidence must return structured JSON")
        response = json.loads(stdout.splitlines()[-1])
        if self.receipt_path.exists():
            receipt = self.receipt()
            self.assertNotEqual(receipt["outcome"], "exited")
            self.assertIsNone(receipt["exit_code"])
            self.assertIs(response["ok"], True)
            self.assertEqual(response["outcome"], receipt["outcome"])
            self.assertIsNone(response["exit_code"])
        else:
            self.assertIs(response["ok"], False)
            self.assertTrue(response["error"]["code"].strip())
            self.assertTrue(response["error"]["message"].strip())

    def test_import_has_no_execution_side_effects_and_exposes_main(self):
        before = set(self.base.rglob("*"))
        importer = (
            f"import sys; sys.path.insert(0,{str(RUNNER.parent)!r}); "
            "import run_command; assert callable(run_command.main)"
        )

        result = subprocess.run([sys.executable, "-B", "-c", importer], cwd=self.workspace,
                                capture_output=True, timeout=5, check=False)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")
        self.assertEqual(set(self.base.rglob("*")), before)

    def test_nonfinite_timeout_is_rejected_before_launch(self):
        target = "from pathlib import Path; Path('unexpected.txt').write_text('ran')"

        result = subprocess.run(self.runner_args([sys.executable, "-c", target], timeout="NaN"),
                                capture_output=True, timeout=10, check=False)

        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.workspace / "unexpected.txt").exists())
        self.assertIs(json.loads(result.stdout.splitlines()[-1])["ok"], False)

    def run_in_windows_fixture_job(self, argv, *, env, timeout, on_completion=None):
        """Own every fixture process independently of the runner's cleanup."""
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_working", ctypes.c_size_t),
                        ("max_working", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", IoCounters),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        job = kernel.CreateJobObjectW(None, None)
        self.assertTrue(job, "The test must establish independent ownership before launching the CLI")
        process = None
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            self.assertTrue(kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            launcher = (
                "import subprocess,sys; "
                "authorization=sys.stdin.buffer.read(1); "
                "raise SystemExit(subprocess.call(sys.argv[1:],stdin=subprocess.DEVNULL) "
                "if authorization==b'x' else 98)"
            )
            process = subprocess.Popen([sys.executable, "-c", launcher, *argv], env=env,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            handle = kernel.OpenProcess(0x0101, False, process.pid)
            self.assertTrue(handle)
            try:
                self.assertTrue(kernel.AssignProcessToJobObject(job, handle))
            finally:
                kernel.CloseHandle(handle)
            stdout, stderr = process.communicate(input=b"x", timeout=timeout)
            result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
            if on_completion is not None:
                on_completion(result)
            return result
        finally:
            try:
                terminated = kernel.TerminateJobObject(job, 97)
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=5)
                self.assertTrue(terminated, "The fixture must terminate its entire Job")
            finally:
                kernel.CloseHandle(job)

    def delayed_git_proxy(self, delay_ms, *, delay_after=None):
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git)
        framework = Path(os.environ["WINDIR"]) / "Microsoft.NET"
        compilers = [framework / family / "v4.0.30319" / "csc.exe"
                     for family in ("Framework64", "Framework")]
        compiler = next((path for path in compilers if path.is_file()), None)
        if compiler is None:
            self.skipTest("A native Windows proxy compiler is unavailable")
        proxy_directory = self.base / "git-proxy"
        proxy_directory.mkdir()
        source = proxy_directory / "Proxy.cs"
        source.write_text(r'''
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
class Program {
    static string Quote(string value) {
        var output = new StringBuilder("\"");
        int slashes = 0;
        foreach (char ch in value) {
            if (ch == '\\') { slashes++; continue; }
            if (ch == '"') { output.Append('\\', slashes * 2 + 1); output.Append(ch); }
            else { output.Append('\\', slashes); output.Append(ch); }
            slashes = 0;
        }
        output.Append('\\', slashes * 2); output.Append('"');
        return output.ToString();
    }
    static int Main(string[] args) {
        string id = Guid.NewGuid().ToString("N");
        string logs = Environment.GetEnvironmentVariable("V3_GIT_CALL_LOG");
        File.WriteAllText(Path.Combine(logs, id + ".start"), String.Join("\n", args));
        string delayAfter = Environment.GetEnvironmentVariable("V3_GIT_DELAY_AFTER");
        bool delay = String.IsNullOrEmpty(delayAfter);
        if (!delay && File.Exists(delayAfter)) {
            int targetPid;
            if (Int32.TryParse(File.ReadAllText(delayAfter), out targetPid)) {
                try { using (var target = Process.GetProcessById(targetPid)) { delay = target.HasExited; } }
                catch (ArgumentException) { delay = true; }
            }
        }
        using (var gate = new Mutex(false, Environment.GetEnvironmentVariable("V3_GIT_MUTEX"))) {
            try { gate.WaitOne(); }
            catch (AbandonedMutexException) { }
            try {
                if (delay) {
                    File.AppendAllText(Path.Combine(logs, "delay-order.txt"), id + "\n");
                    Thread.Sleep(Int32.Parse(Environment.GetEnvironmentVariable("V3_GIT_DELAY_MS")));
                }
                var quoted = new string[args.Length];
                for (int i = 0; i < args.Length; i++) quoted[i] = Quote(args[i]);
                var start = new ProcessStartInfo(Environment.GetEnvironmentVariable("V3_REAL_GIT"), String.Join(" ", quoted));
                start.UseShellExecute = false;
                start.RedirectStandardOutput = true;
                start.RedirectStandardError = true;
                using (var process = Process.Start(start)) {
                    string stdout = process.StandardOutput.ReadToEnd();
                    string stderr = process.StandardError.ReadToEnd();
                    process.WaitForExit();
                    File.WriteAllText(Path.Combine(logs, id + ".stdout"), stdout);
                    Console.Out.Write(stdout);
                    Console.Error.Write(stderr);
                    File.WriteAllText(Path.Combine(logs, id + ".end"), process.ExitCode.ToString());
                    string helper = Environment.GetEnvironmentVariable("V3_GIT_HELPER_CODE");
                    bool spawnHelper = false;
                    string helperStarted = Path.Combine(logs, "helper-started");
                    if (!String.IsNullOrEmpty(helper) && !File.Exists(helperStarted)) {
                        File.WriteAllText(helperStarted, id);
                        spawnHelper = true;
                    }
                    if (spawnHelper) {
                        var helperStart = new ProcessStartInfo(Environment.GetEnvironmentVariable("V3_GIT_HELPER_PYTHON"), "-c " + Quote(helper));
                        helperStart.UseShellExecute = false;
                        using (Process.Start(helperStart)) { }
                        var wait = Stopwatch.StartNew();
                        while (!File.Exists(Path.Combine(logs, "helper-ready")) && wait.ElapsedMilliseconds < 5000) Thread.Sleep(10);
                        if (!File.Exists(Path.Combine(logs, "helper-ready"))) return 92;
                    }
                    return process.ExitCode;
                }
            }
            finally { gate.ReleaseMutex(); }
        }
    }
}
''', encoding="utf-8")
        proxy = proxy_directory / "git.exe"
        compiled = subprocess.run([str(compiler), "/nologo", "/target:exe", "/out:" + str(proxy), str(source)],
                                  capture_output=True, timeout=15, check=False)
        self.assertEqual(compiled.returncode, 0, "The external Git proxy fixture must compile")
        call_logs = self.base / "git-calls"
        call_logs.mkdir()
        environment = os.environ.copy()
        environment.update(V3_REAL_GIT=real_git, V3_GIT_DELAY_MS=str(delay_ms),
                           V3_GIT_DELAY_AFTER="" if delay_after is None else str(delay_after),
                           V3_GIT_MUTEX="Local\\v3-git-" + hashlib.sha256(str(self.base).encode()).hexdigest(),
                           V3_GIT_CALL_LOG=str(call_logs),
                           PATH=str(proxy_directory) + os.pathsep + environment["PATH"])
        return proxy, environment, call_logs

    @unittest.skipUnless(os.name == "nt", "Windows real-Git cumulative timeout fixture")
    def test_formal_git_preflight_shares_one_startup_deadline(self):
        request_path, _, _ = self.snapshot_request()
        self.commit_fixture()
        proxy, environment, call_logs = self.delayed_git_proxy(900)
        smoke_logs = self.base / "smoke-calls"
        smoke_logs.mkdir()
        environment["V3_GIT_CALL_LOG"] = str(smoke_logs)
        timeout = 1.5
        smoke_started = time.monotonic()
        smoke = self.run_in_windows_fixture_job(
            [str(proxy), "-C", str(self.workspace), "rev-parse", "HEAD"], env=environment, timeout=5)
        smoke_elapsed = time.monotonic() - smoke_started
        self.assertEqual(smoke.returncode, 0, "The proxy must actually forward real Git successfully")
        self.assertEqual(smoke.stdout.decode().strip(), self.git("rev-parse", "HEAD"))
        self.assertLess(smoke_elapsed, timeout, "A single delayed read must fit the declared budget")
        environment["V3_GIT_CALL_LOG"] = str(call_logs)
        marker = self.workspace / "unexpected.json"
        target = (
            "import json; from pathlib import Path; "
            f"calls=len(list(Path({str(call_logs)!r}).glob('*.start'))); "
            "Path('unexpected.json').write_text(json.dumps({'preflight_calls':calls}))"
        )

        started = time.monotonic()
        result = self.run_in_windows_fixture_job(
            self.runner_args([sys.executable, "-c", target], timeout=timeout,
                             extra=["--snapshot", str(request_path), "--formal"]),
            env=environment, timeout=timeout + 6,
        )
        elapsed = time.monotonic() - started

        calls_before_target = (json.loads(marker.read_text())["preflight_calls"]
                               if marker.exists() else len(list(call_logs.glob("*.start"))))
        if calls_before_target < 2:
            self.skipTest("This preflight did not trigger two delayed reads; cumulative-timeout scenario unverified")
        # The fixture's cross-process mutex serializes each 900ms delay even if
        # the runner overlaps Git reads. Two completed reads require >=1.8s.
        self.assertFalse(marker.exists(), "Cumulative Git preflight time exhausted the startup budget")
        self.assertEqual(result.returncode, 124)
        self.assertLessEqual(elapsed, timeout + 5.5)
        response = json.loads(result.stdout.splitlines()[-1])
        if self.receipt_path.exists():
            receipt = self.receipt()
            self.assertEqual(receipt["outcome"], "timeout")
            self.assertIsNone(receipt["exit_code"])
            self.assertIs(response["ok"], True)
            self.assertEqual(response["receipt_path"], str(self.receipt_path.resolve()))
            self.assertEqual(response["outcome"], "timeout")
            self.assertIsNone(response["exit_code"])
        else:
            self.assertIs(response["ok"], False)
            self.assertEqual(response["error"]["code"], "timeout")
            self.assertTrue(response["error"]["message"].strip())

    @unittest.skipUnless(os.name == "nt", "Windows real-Git shared finalization budget")
    def test_timed_out_formal_command_shares_five_seconds_for_git_finalization(self):
        request_path, _, _ = self.snapshot_request()
        self.commit_fixture()
        target_started = self.base / "target-started"
        _, environment, call_logs = self.delayed_git_proxy(3000, delay_after=target_started)
        target = (
            "import os,time; from pathlib import Path; "
            f"Path({str(target_started)!r}).write_text(str(os.getpid())); time.sleep(30)"
        )
        timeout = 1.5

        started = time.monotonic()
        result = self.run_in_windows_fixture_job(
            self.runner_args([sys.executable, "-c", target], timeout=timeout,
                             extra=["--snapshot", str(request_path), "--formal"]),
            env=environment, timeout=timeout + 8,
        )
        elapsed = time.monotonic() - started

        delay_order_path = call_logs / "delay-order.txt"
        delay_order = delay_order_path.read_text().splitlines() if delay_order_path.exists() else []
        # Each Git read has a serialized 3s delay. Finishing multiple reads must
        # share the published 5s tail allowance, not acquire a fresh 5s each.
        # The external launch/observation allowance is 0.5s, as in tree cleanup.
        self.assertLessEqual(elapsed, timeout + 5.5)
        self.assertIn(result.returncode, (2, 124))
        response = json.loads(result.stdout.splitlines()[-1])
        if self.receipt_path.exists():
            self.assertEqual(self.receipt()["outcome"], "timeout")
            self.assertIsNone(self.receipt()["exit_code"])
            self.assertIs(response["ok"], True)
            self.assertEqual(result.returncode, 124)
        else:
            self.assertIs(response["ok"], False)
            self.assertTrue(response["error"]["code"].strip())
            self.assertTrue(response["error"]["message"].strip())
        if not target_started.is_file():
            self.assertEqual(result.returncode, 124)
            if not self.receipt_path.exists():
                self.assertEqual(response["error"]["code"], "timeout")
            self.skipTest("The startup budget expired before the target; finalization scenario unverified")
        first_completed = call_logs / (delay_order[0] + ".end") if delay_order else None
        if (len(delay_order) < 2 or not first_completed.is_file()
                or first_completed.read_text().strip() != "0"):
            self.skipTest("Two serial Git finalization delays were not exercised; cumulative-tail scenario unverified")

    @unittest.skipUnless(os.name == "nt", "Windows inherited Git streams and independent fixture ownership")
    def test_git_helper_holding_inherited_streams_is_bounded_and_cleaned(self):
        import ctypes
        from ctypes import wintypes

        request_path, _, _ = self.snapshot_request()
        self.commit_fixture()
        _, environment, call_logs = self.delayed_git_proxy(0)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        listener.settimeout(5)
        self.addCleanup(listener.close)
        address = listener.getsockname()

        def waiter(role, ready_file=None):
            ready = ("" if ready_file is None else
                     f"Path({str(ready_file)!r}).write_text('observed'); ")
            return (
                "import json,os,socket; from pathlib import Path; "
                f"sock=socket.create_connection({address!r}); "
                f"sock.sendall((json.dumps({{'role':{role!r},'pid':os.getpid(),'parent':os.getppid()}})+'\\n').encode()); "
                "sock.recv(1); " + ready + "sock.recv(1)"
            )

        def receive_identity():
            connection, _ = listener.accept()
            connection.settimeout(5)
            self.addCleanup(connection.close)
            message = b""
            while not message.endswith(b"\n"):
                part = connection.recv(4096)
                self.assertTrue(part, "The fixture must identify itself before closing")
                message += part
            return connection, json.loads(message)

        outsider = self.start_process([sys.executable, "-c", waiter("outsider")])
        outside_connection, outside = receive_identity()
        self.assertEqual(outside["role"], "outsider")
        outside_kernel, outside_handle = self.windows_process_handle(outside["pid"])
        outside_connection.sendall(b"x")
        environment.update(V3_GIT_HELPER_PYTHON=sys.executable,
                           V3_GIT_HELPER_CODE=waiter("helper", call_logs / "helper-ready"))
        identities, completed, failures = {}, {}, []
        timeout = 1.5

        def observe_completion(result):
            completed["finished"] = time.monotonic()
            completed["result"] = result
            for role, (kernel, handle) in identities.items():
                completed[role + "_exited"] = kernel.WaitForSingleObject(handle, 0) == 0
                kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
                kernel.GetExitCodeProcess.restype = wintypes.BOOL
                code = wintypes.DWORD()
                self.assertTrue(kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
                completed[role + "_exit_code"] = code.value
            completed["outsider_alive"] = outside_kernel.WaitForSingleObject(outside_handle, 0) == 258

        def invoke():
            try:
                completed["started"] = time.monotonic()
                self.run_in_windows_fixture_job(
                    self.runner_args([sys.executable, "-c", "raise SystemExit(0)"], timeout=timeout,
                                     extra=["--snapshot", str(request_path), "--formal"]),
                    env=environment, timeout=timeout + 6, on_completion=observe_completion,
                )
            except BaseException as error:
                failures.append(error)

        worker = threading.Thread(target=invoke, daemon=True)
        worker.start()
        self.addCleanup(worker.join, timeout + 12)
        connection, helper = receive_identity()
        self.assertEqual(helper["role"], "helper")
        identities["helper"] = self.windows_process_handle(helper["pid"])
        identities["proxy"] = self.windows_process_handle(helper["parent"])
        for kernel, handle in identities.values():
            self.assertEqual(kernel.WaitForSingleObject(handle, 0), 258)
        connection.sendall(b"x")
        worker.join(timeout + 12)
        self.assertFalse(worker.is_alive(), "The independent fixture Job must bound failure cleanup")
        # Establish the external scenario even when the CLI exceeds the harness cap.
        call_id = (call_logs / "helper-started").read_text()
        self.assertEqual((call_logs / (call_id + ".end")).read_text(), "0")
        forwarded_args = (call_logs / (call_id + ".start")).read_text().splitlines()
        self.assertEqual((call_logs / (call_id + ".stdout")).read_text().strip(), self.git(*forwarded_args))
        proxy_kernel, proxy_handle = identities["proxy"]
        proxy_kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        proxy_kernel.GetExitCodeProcess.restype = wintypes.BOOL
        proxy_code = wintypes.DWORD()
        self.assertTrue(proxy_kernel.GetExitCodeProcess(proxy_handle, ctypes.byref(proxy_code)))
        self.assertEqual(proxy_code.value, 0, "The Git proxy must itself have exited normally")
        self.assertIsNone(outsider.poll())
        self.assertEqual(outside_kernel.WaitForSingleObject(outside_handle, 0), 258)
        if failures:
            raise failures[0]

        # Observe product cleanup before the independent fixture Job is terminated.
        self.assertLessEqual(completed["finished"] - completed["started"], timeout + 5.5)
        self.assertIs(completed["proxy_exited"], True)
        self.assertEqual(completed["proxy_exit_code"], 0)
        self.assertIs(completed["helper_exited"], True)
        self.assertIs(completed["outsider_alive"], True)
        self.assertIsNone(outsider.poll())
        self.assertEqual(outside_kernel.WaitForSingleObject(outside_handle, 0), 258)
        result = completed["result"]
        self.assertIn(result.returncode, (0, 2, 124))
        response = json.loads(result.stdout.splitlines()[-1])
        if self.receipt_path.exists():
            receipt = self.receipt()
            self.assertIs(response["ok"], True)
            self.assertEqual(response["outcome"], receipt["outcome"])
            self.assertEqual(response["exit_code"], receipt["exit_code"])
            if receipt["outcome"] == "timeout":
                self.assertEqual(result.returncode, 124)
            if result.returncode == 0:
                self.assertEqual(receipt["outcome"], "exited")
                self.assertEqual(receipt["exit_code"], 0)
                self.assertIs(receipt["cleanup_complete"], True)
            else:
                self.assertNotEqual(receipt["outcome"], "exited")
                self.assertIsNone(receipt["exit_code"])
                if result.returncode == 124:
                    self.assertEqual(receipt["outcome"], "timeout")
        else:
            self.assertIn(result.returncode, (2, 124))
            self.assertIs(response["ok"], False)
            self.assertTrue(response["error"]["code"].strip())
            self.assertTrue(response["error"]["message"].strip())
            if result.returncode == 124:
                self.assertEqual(response["error"]["code"], "timeout")

    def test_public_main_accepts_explicit_argv_and_runs_the_target(self):
        target = "from pathlib import Path; Path('main-called.txt').write_text('ran')"
        arguments = self.runner_args([sys.executable, "-c", target])[2:]
        driver = (
            f"import sys; sys.path.insert(0,{str(RUNNER.parent)!r}); import run_command; "
            f"result=run_command.main({arguments!r}); assert type(result) is int; raise SystemExit(result)"
        )

        result = subprocess.run([sys.executable, "-B", "-c", driver], cwd=self.workspace,
                                capture_output=True, timeout=10, check=False)

        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.workspace / "main-called.txt").read_text(), "ran")
        self.assertEqual(self.receipt()["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
