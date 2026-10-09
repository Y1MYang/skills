"""Forward acceptance tests of the resource CLI in disposable Git repositories.

Only clock reads are replaced where a thirty-minute interval is needed. Commands,
ledger locking, worktrees, process capture and cooperative watcher stops are real.
"""

import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


TOOL = Path(__file__).resolve().parents[1] / "scripts" / "resources.py"
CLOCK_ENTRY = """
import importlib.util, sys
tool, instant, *arguments = sys.argv[1:]
spec = importlib.util.spec_from_file_location('acceptance_resources', tool)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.now = lambda: instant
sys.argv = [tool, *arguments]
raise SystemExit(module.main())
"""


class ResourceIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="resource-integration-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Acceptance Test")
        self.git("config", "user.email", "acceptance@example.invalid")
        (self.repo / "source.txt").write_text("baseline\n")
        self.git("add", "source.txt")
        self.git("commit", "-m", "baseline")
        self.state = self.root / "state"
        self.owner = "agent-ticket"
        self.cli("init", "--state-dir", self.state, "--repo", self.repo)

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.repo), *map(str, args)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def command(self, action, *args, at=None):
        arguments = [action] + ([] if action == "init" else ["--state", str(self.state)]) + list(map(str, args))
        if at:
            return [sys.executable, "-c", CLOCK_ENTRY, str(TOOL), at, *arguments]
        return [sys.executable, str(TOOL), *arguments]

    def cli(self, action, *args, code=0, at=None):
        result = subprocess.run(self.command(action, *args, at=at),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return json.loads(result.stderr if code == 2 else result.stdout)

    def ledger(self):
        return json.loads((self.state / "state.json").read_text())

    def budget(self):
        self.cli("reserve", "--id", "growth", "--path", self.root, "--next-bytes", 1048576,
                 "--reserve-bytes", 0, "--owner", self.owner)

    def create(self, name, kind="data", role="implementer", reserved=True):
        arguments = ["--id", name, "--kind", kind, "--path", self.root / name,
                     "--role", role, "--owner", self.owner]
        if reserved:
            arguments += ["--reservation", "growth"]
        if kind == "worktree":
            arguments += ["--ref", "main"]
        self.cli("create", *arguments)
        return self.root / name

    def run_args(self, name, cwd, output, code="print('evidence')", test=False, reserved=True):
        arguments = ["--id", name, "--cwd-resource", cwd, "--output-resource", output]
        if reserved:
            arguments += ["--reservation", "growth"]
        if test:
            arguments += ["--test"]
        return [*arguments, "--", sys.executable, "-c", code]

    def record(self, name, failed=False):
        summary = self.root / (name + "-summary.json")
        summary.write_text(json.dumps({"tests": {"passed": int(not failed), "failed": int(failed),
            "skipped": 0, "errors": 0, "total": 1}, "reproduce": "Run the recorded command at the recorded revision",
            "acceptance": ["acceptance/resource-lifecycle"]}))
        return self.cli("record-test", "--run", name, "--summary", summary)

    def due(self, resource, event="checkpoint", stage="checkpoint-complete"):
        return self.cli("due", "--resource", resource, "--event-id", event,
                        "--stage", stage, "--evidence", "acceptance/completed", "--owner", self.owner)

    def row(self, result, resource):
        return next(row for row in result["rows"] if row["resource"] == resource)

    def wait_for(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("temporary acceptance process did not reach its expected state")

    def gated_run(self, name="busy"):
        ready, gate = self.root / "output" / (name + "-ready"), self.root / "output" / (name + "-continue")
        code = ("from pathlib import Path\nimport time\n"
                "ready, gate = Path({!r}), Path({!r})\nready.touch()\n"
                "deadline = time.monotonic() + 30\n"
                "while not gate.exists() and time.monotonic() < deadline: time.sleep(0.02)\n"
                "raise SystemExit(0 if gate.exists() else 7)\n").format(str(ready), str(gate))
        process = subprocess.Popen(self.command("run", *self.run_args(name, "tree", "output", code)),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def unblock():
            gate.touch()
            process.communicate(timeout=35)

        self.addCleanup(unblock)
        self.wait_for(ready.exists)
        return process, gate

    def test_new_cli_requires_reservations_and_rejects_parallel_borrowing(self):
        refused = self.cli("create", "--id", "unbudgeted", "--kind", "data", "--path", self.root / "unbudgeted",
                           "--role", "implementer", code=2)
        self.assertIn("requires --reservation", refused["error"])
        self.assertFalse((self.root / "unbudgeted").exists())
        self.budget()
        self.create("tree", "worktree")
        self.create("output")
        refused = self.cli("run", *self.run_args("no-budget", "tree", "output", reserved=False), code=2)
        self.assertIn("requires --reservation", refused["error"])
        process, gate = self.gated_run()
        refused = self.cli("run", *self.run_args("parallel", "tree", "output"), code=2)
        self.assertIn("active claimant", refused["error"])
        refused = self.cli("release", "--resource", "output", "--idle-confirmed", code=2)
        self.assertIn("running", refused["error"])
        attempt = self.ledger()["resources"]["output"]["resource_audit"]["last_attempt"]
        self.assertEqual(attempt["outcome"], "blocked")
        self.assertIsNone(process.poll())
        gate.touch()
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(self.ledger()["reservations"]["growth"]["remaining_bytes"], 1048576)
        self.cli("run", *self.run_args("after-completion", "tree", "output"))

    def test_recorded_tests_create_obligations_and_every_release_attempt_has_a_receipt(self):
        self.budget()
        tree = self.create("tree", "worktree")
        output = self.create("output")
        self.cli("run", *self.run_args("passing", "tree", "output", test=True))
        self.record("passing")
        due = self.ledger()["resources"]["output"]["resource_audit"]["due"]
        self.assertEqual(due["stage"], "test-record-validated")
        refused = self.cli("release", "--resource", "output", code=2)
        self.assertIn("idle", refused["error"])
        self.assertEqual(self.ledger()["resources"]["output"]["resource_audit"]["last_attempt"]["outcome"], "blocked")
        self.cli("release", "--resource", "output", "--idle-confirmed")
        receipt = self.ledger()["resources"]["output"]["resource_audit"]["receipt"]
        self.assertEqual((receipt["event_id"], receipt["kind"]), (due["event_id"], "released"))
        self.assertFalse(output.exists())
        self.assertEqual(self.row(self.cli("audit", "--check-id", "closed"), "output")["action"], "none")
        self.due("tree", "merged", "ticket-merged")
        (tree / "source.txt").write_text("local changes\n")
        refused = self.cli("release", "--resource", "tree", "--idle-confirmed", "--merged-into", "main", code=2)
        self.assertIn("dirty", refused["error"])
        self.assertEqual(self.ledger()["resources"]["tree"]["resource_audit"]["last_attempt"]["outcome"], "blocked")
        (tree / "source.txt").write_text("baseline\n")
        self.cli("release", "--resource", "tree", "--idle-confirmed", "--merged-into", "main")
        self.assertFalse(tree.exists())

    def test_retention_deadline_and_independent_audits_route_to_existing_roles(self):
        self.budget()
        self.create("cache")
        self.due("cache")
        base = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
        at = lambda minutes: (base + datetime.timedelta(minutes=minutes)).isoformat()
        self.cli("disposition", "--resource", "cache", "--event-id", "checkpoint", "--kind", "retained",
                 "--reason", "next verifier needs this input", "--evidence", "acceptance/next-verifier",
                 "--recheck-at", at(30), at=at(0))
        self.assertEqual(self.row(self.cli("audit", "--check-id", "before", at=at(1)), "cache")["category"], "retained")
        first = self.row(self.cli("audit", "--check-id", "first", at=at(31)), "cache")
        self.assertEqual(first["category"], "retention_review_due")
        self.assertEqual(first["action"], "dispatch_current_owner")
        duplicate = self.row(self.cli("audit", "--check-id", "first", at=at(62)), "cache")
        self.assertEqual(duplicate["unhandled_checks"], 1)
        second = self.row(self.cli("audit", "--check-id", "second", at=at(62)), "cache")
        self.assertEqual(second["action"], "escalate_existing_merger")
        self.assertFalse(second["deletion_authorized"])
        self.cli("disposition", "--resource", "cache", "--event-id", "checkpoint", "--kind", "handoff",
                 "--owner", "existing-merger", "--reason", "needs shared disposition review",
                 "--evidence", "acceptance/escalation", at=at(63))
        row = self.row(self.cli("audit", "--check-id", "handoff", at=at(64)), "cache")
        self.assertEqual(row["category"], "handoff_unaccepted")
        self.assertEqual(row["owner"], self.owner)
        self.cli("disposition", "--resource", "cache", "--event-id", "checkpoint", "--kind", "accept",
                 "--owner", "existing-merger", at=at(65))
        self.assertEqual(self.ledger()["resources"]["cache"]["owner"], "existing-merger")

    def test_failed_checkpoint_releases_scratch_but_preserves_external_failure_scene(self):
        self.budget()
        scratch = self.create("scratch", "worktree", "checkpoint")
        output = self.create("output")
        self.cli("run", *self.run_args("failure", "scratch", "output", "print('diagnostic'); raise SystemExit(1)", test=True), code=1)
        self.record("failure", failed=True)
        self.due("scratch")
        self.cli("release", "--resource", "scratch", "--idle-confirmed")
        self.assertFalse(scratch.exists())
        refused = self.cli("release", "--resource", "output", "--idle-confirmed", code=2)
        self.assertIn("unresolved failure", refused["error"])
        self.assertTrue((output / "failure.stdout.gz").is_file())
        self.assertTrue((output / "failure.stderr.gz").is_file())
        self.assertEqual(self.ledger()["resources"]["output"]["status"], "active")

    def test_historical_ledger_still_runs_without_new_reservation_flags(self):
        state = self.ledger()
        state.pop("capacity_protocol")
        state.pop("reservations")
        (self.state / "state.json").write_text(json.dumps(state))
        self.create("tree", "worktree", reserved=False)
        self.create("output", reserved=False)
        self.cli("run", *self.run_args("legacy", "tree", "output", reserved=False))
        result = self.cli("capacity", "--path", self.root, "--next-bytes", 0, "--reserve-bytes", 0)
        self.assertFalse(result["admission_enabled"])
        self.assertIn("disabled", result["legacy_notice"])
        self.cli("release", "--resource", "output", "--idle-confirmed")

    def test_accepted_owner_can_continue_after_idle_budget_transfer_without_new_allocation(self):
        self.budget()
        self.create("tree", "worktree")
        self.create("output")
        business, gate = self.gated_run()
        self.due("tree", "transfer", "ticket-handoff")
        self.cli("disposition", "--resource", "tree", "--event-id", "transfer", "--kind", "handoff",
                 "--owner", "existing-merger", "--reason", "merger continues the accepted work",
                 "--evidence", "acceptance/merger-handoff")
        self.cli("disposition", "--resource", "tree", "--event-id", "transfer", "--kind", "accept",
                 "--owner", "existing-merger")
        transfer = ["--id", "growth", "--owner", self.owner, "--transfer-to", "existing-merger",
                    "--idle-confirmed", "--reason", "accepted handoff; existing command has now finished"]
        refused = self.cli("reservation", *transfer, code=2)
        self.assertIn("active claimant", refused["error"])
        self.assertIsNone(business.poll())
        gate.touch()
        stdout, stderr = business.communicate(timeout=10)
        self.assertEqual(business.returncode, 0, stdout + stderr)
        refused = self.cli("run", *self.run_args("not-transferred", "tree", "output"), code=2)
        self.assertIn("owner mismatch", refused["error"])
        before = self.ledger()["reservations"]["growth"]
        self.cli("reservation", *transfer)
        after = self.ledger()
        self.assertEqual(len(after["reservations"]), 1)
        self.assertEqual(after["reservations"]["growth"]["remaining_bytes"], before["remaining_bytes"])
        self.assertEqual(after["resources"]["output"]["owner"], self.owner)
        self.assertEqual(self.cli("reservation", "--id", "growth")["reservation"]["owner"], "existing-merger")
        self.cli("run", *self.run_args("accepted-owner-continues", "tree", "output"))
        self.assertEqual(self.ledger()["runs"]["accepted-owner-continues"]["owner"], "existing-merger")

    def test_default_watch_is_30_minutes_and_cooperative_stop_leaves_business_running(self):
        self.budget()
        self.create("tree", "worktree")
        self.create("output")
        business, gate = self.gated_run()
        watcher = subprocess.Popen(self.command("watch"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def stop_watcher():
            self.cli("watch-stop")
            watcher.communicate(timeout=10)

        self.addCleanup(stop_watcher)
        self.wait_for(lambda: self.ledger().get("resource_audit", {}).get("watch", {}).get("last_check_at"))
        self.assertEqual(self.ledger()["resource_audit"]["watch"]["interval_seconds"], 1800)
        stopped = self.cli("watch-stop")
        self.assertFalse(stopped["business_commands_stopped"])
        stdout, stderr = watcher.communicate(timeout=10)
        self.assertEqual(watcher.returncode, 0, stdout + stderr)
        self.assertTrue(json.loads(stdout.splitlines()[0])["metadata_only"])
        self.assertIsNone(business.poll())
        self.assertEqual(self.ledger()["runs"]["busy"]["status"], "running")
        gate.touch()
        stdout, stderr = business.communicate(timeout=10)
        self.assertEqual(business.returncode, 0, stdout + stderr)


if __name__ == "__main__":
    unittest.main()
