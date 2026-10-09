"""Audit behavior with ledger fixtures and simulated clocks; no real watcher."""

import argparse
import contextlib
import copy
import datetime
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "resource_audit.py"
SPEC = importlib.util.spec_from_file_location("resource_audit_test_module", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.state = {"invocation": "invocation-7", "resources": {"output": {"id": "output", "kind": "data", "status": "active",
                                              "owner": "implementer-7", "role": "implementer"}},
                      "runs": {}}
        self.at = "2026-10-09T08:00:00+00:00"
        self.saved = 0
        self.parser = argparse.ArgumentParser()
        audit.add_commands(self.parser.add_subparsers(dest="action", required=True))

        @contextlib.contextmanager
        def locked(unused):
            yield Path("/not-used"), self.state

        def save(path, state):
            self.saved += 1

        self.h = SimpleNamespace(locked=locked, save=save, now=lambda: self.at,
                                 checked_id=lambda value: value, Refusal=ValueError,
                                 resource=lambda state, name: state["resources"][name])

    def advance(self, seconds=1800):
        self.at = (datetime.datetime.fromisoformat(self.at) + datetime.timedelta(seconds=seconds)).isoformat()

    def due(self, event="passed-1", resource="output"):
        return audit.mark_due(self.state, resource, event, "test-recorded", "record:" + event, at=self.at)

    def check(self, check="check-1", trigger=None):
        return audit.audit_state(self.state, check, self.at, trigger=trigger)

    def row(self, result, resource="output"):
        return next(row for row in result["rows"] if row["resource"] == resource)

    def cli(self, *args):
        args = self.parser.parse_args([args[0], "--state", "/not-used", *args[1:]])
        return audit.dispatch(args.action, args, self.h)

    def retain(self, **changes):
        args = {"resource": "output", "event_id": "passed-1", "kind": "retained", "reason": "needed by command",
                "evidence": "run:build-1", "recheck_at": "2026-10-09T09:00:00+00:00",
                "recheck_event": None, "owner": None}
        args.update(changes)
        return audit._disposition(self.state, SimpleNamespace(**args), self.at)

    def test_legacy_ledger_has_no_invented_due_phase(self):
        result = self.check()
        row = self.row(result)
        self.assertEqual(row["category"], "phase_unrecorded")
        self.assertNotIn("due", self.state["resources"]["output"].get("resource_audit", {}))

    def test_first_omission_routes_owner_second_independent_routes_merger(self):
        self.due()
        report = self.check()
        self.assertEqual(report["invocation"], "invocation-7")
        first = self.row(report)
        self.assertEqual(first["evidence"], "record:passed-1")
        self.assertEqual(first["first_due_at"], self.at)
        self.assertEqual(first["action"], "dispatch_current_owner")
        self.assertEqual(first["owner"], "implementer-7")
        self.assertEqual(first["category"], "verification_required")
        self.advance()
        second = self.row(self.check("check-2"))
        self.assertEqual(second["action"], "escalate_existing_merger")
        self.assertFalse(second["deletion_authorized"])

    def test_same_id_or_immediate_new_id_cannot_accumulate(self):
        self.due()
        self.check()
        self.advance()
        repeated = self.check()
        self.assertTrue(repeated["duplicate"])
        self.assertEqual(self.row(repeated)["unhandled_checks"], 1)
        self.check("check-2")
        self.assertEqual(self.row(self.check("check-3"))["unhandled_checks"], 2)
        self.assertFalse(self.row(self.check("check-4"))["independent_check"])

    def test_new_registered_phase_is_independent_but_arbitrary_trigger_is_not(self):
        self.due()
        self.check()
        with self.assertRaisesRegex(ValueError, "registered phase"):
            self.check("bogus-check", trigger="invented-event")
        self.state["resources"]["ticket"] = {"id": "ticket", "kind": "worktree", "status": "active", "owner": "merger"}
        self.due("ticket-merged", "ticket")
        report = self.check("phase-check", trigger="ticket-merged")
        self.assertEqual(self.row(report)["unhandled_checks"], 2)
        self.assertFalse(self.row(self.check("phase-replayed", trigger="ticket-merged"))["independent_check"])

    def test_new_due_cannot_erase_an_existing_missed_obligation(self):
        self.due()
        original = self.state["resources"]["output"]["resource_audit"]["first_due_at"]
        audit.record_assessment(self.state, "output", {"machine_blockers": [], "owner_checks_required": ["idle"]}, at=self.at)
        self.check()
        self.advance(10)
        self.due("passed-2")
        report = self.check("new-stage", trigger="passed-2")
        self.assertEqual(self.row(report)["unhandled_checks"], 2)
        self.assertEqual(self.row(report)["first_due_at"], original)
        self.assertEqual(self.state["resources"]["output"]["resource_audit"]["first_due_at"], original)

    def test_event_id_is_idempotent_and_cannot_change_evidence(self):
        self.due()
        before = copy.deepcopy(self.state)
        self.due()
        self.assertEqual(self.state, before)
        with self.assertRaisesRegex(ValueError, "different obligation"):
            audit.mark_due(self.state, "output", "passed-1", "test-recorded", "other-evidence", at=self.at)

    def test_stale_receipt_and_old_due_cannot_replace_current_event(self):
        self.due()
        self.due("passed-2")
        with self.assertRaisesRegex(ValueError, "current obligation"):
            self.retain()
        with self.assertRaisesRegex(ValueError, "current obligation"):
            audit.record_release(self.state, "output", "released", event_id="passed-1")
        with self.assertRaisesRegex(ValueError, "old event"):
            self.due("passed-1")

    def test_retention_is_explicit_and_review_is_latched(self):
        self.due()
        self.retain(recheck_at=None, recheck_event="integration-done")
        self.assertEqual(self.row(self.check())["category"], "retained")
        self.state["resources"]["ticket"] = {"id": "ticket", "kind": "worktree", "status": "active", "owner": "merger"}
        self.due("integration-done", "ticket")
        first_review = self.row(self.check("review-1", trigger="integration-done"))
        self.assertEqual(first_review["category"], "retention_review_due")
        self.advance()
        next_review = self.row(self.check("review-2"))
        self.assertEqual(next_review["category"], "retention_review_due")
        self.assertEqual(next_review["action"], "escalate_existing_merger")

    def test_periodic_audit_observes_registered_recheck_event_without_trigger(self):
        self.due()
        self.retain(recheck_at=None, recheck_event="integration-done")
        self.state["resources"]["ticket"] = {"id": "ticket", "kind": "worktree", "status": "active", "owner": "merger"}
        self.due("integration-done", "ticket")
        self.assertEqual(self.row(self.check())["category"], "retention_review_due")

    def test_recheck_event_survives_another_stage_before_the_next_watch(self):
        self.due()
        self.retain(recheck_at=None, recheck_event="review-finished")
        self.state["resources"]["pr"] = {"id": "pr", "kind": "worktree", "status": "active", "owner": "merger"}
        self.due("review-finished", "pr")
        self.due("final-handoff", "pr")
        row = self.row(self.check())
        self.assertEqual(row["category"], "retention_review_due")
        self.assertEqual(row["action"], "dispatch_current_owner")

    def test_retention_cannot_wait_for_an_event_that_already_happened(self):
        self.due()
        self.state["resources"]["pr"] = {"id": "pr", "kind": "worktree", "status": "active", "owner": "merger"}
        self.due("review-finished", "pr")
        self.due("final-handoff", "pr")
        with self.assertRaisesRegex(ValueError, "already occurred"):
            self.retain(recheck_at=None, recheck_event="review-finished")

    def test_repeated_statement_does_not_postpone_or_reset_miss_count(self):
        self.due()
        self.check()
        self.retain()
        with self.assertRaisesRegex(ValueError, "cannot postpone"):
            self.retain(recheck_at="2026-10-09T10:00:00+00:00")
        with self.assertRaisesRegex(ValueError, "cannot postpone"):
            self.retain(reason="same fact phrased differently", recheck_at="2026-10-09T10:00:00+00:00")
        self.retain()
        self.advance(3601)
        row = self.row(self.check("review"))
        self.assertEqual(row["unhandled_checks"], 2)

    def test_handoff_keeps_original_owner_until_matching_acceptance(self):
        self.due()
        common = ["--resource", "output", "--event-id", "passed-1"]
        self.cli("disposition", *common, "--kind", "handoff", "--owner", "merger-2",
                 "--reason", "delivery completed", "--evidence", "commit:123")
        self.assertEqual(self.state["resources"]["output"]["owner"], "implementer-7")
        self.assertEqual(self.row(self.check())["category"], "handoff_unaccepted")
        with self.assertRaises(ValueError):
            self.cli("disposition", *common, "--kind", "accept", "--owner", "other")
        self.cli("disposition", *common, "--kind", "accept", "--owner", "merger-2")
        self.assertEqual(self.state["resources"]["output"]["owner"], "merger-2")
        self.advance()
        self.assertEqual(self.row(self.check("after-handoff"))["unhandled_checks"], 1)

    def test_new_use_invalidates_assessment_and_retention(self):
        self.due()
        self.retain()
        audit.record_assessment(self.state, "output", {"machine_blockers": [], "owner_checks_required": []}, at=self.at)
        audit.note_usage(self.state, ["output"], "build-2", at=self.at)
        row = self.row(self.check())
        self.assertEqual(row["category"], "verification_required")
        self.assertNotIn("assessment", self.state["resources"]["output"]["resource_audit"])
        with self.assertRaisesRegex(ValueError, "predates"):
            audit.record_assessment(self.state, "output", {"machine_blockers": [], "owner_checks_required": [], "usage_generation": 0})

    def test_new_machine_facts_are_progress_but_repeated_assessment_is_not(self):
        self.due()
        assessment = {"machine_blockers": [], "owner_checks_required": ["idle"]}
        audit.record_assessment(self.state, "output", assessment, at=self.at)
        self.check()
        self.advance()
        audit.record_assessment(self.state, "output", assessment, at=self.at)
        self.assertEqual(self.row(self.check("check-2"))["unhandled_checks"], 2)
        self.state["runs"]["build-1"] = {"id": "build-1", "uses": ["output"], "status": "completed", "exit_code": 0,
                                           "record_sha256": "new-record"}
        self.advance()
        self.assertEqual(self.row(self.check("check-3"))["unhandled_checks"], 1)

    def test_changed_assessment_is_progress_and_latest_report_is_recoverable(self):
        self.due()
        audit.record_assessment(self.state, "output", {"machine_blockers": ["dirty"], "owner_checks_required": ["idle"]}, at=self.at)
        self.check()
        self.advance()
        self.check("check-2")
        audit.record_assessment(self.state, "output", {"machine_blockers": [], "owner_checks_required": ["idle"]}, at=self.at)
        self.advance()
        report = self.check("check-3")
        self.assertEqual(self.row(report)["unhandled_checks"], 1)
        self.assertEqual(self.state["resource_audit"]["last_report"], report)

    def test_missing_pid_never_proves_completion(self):
        self.due()
        self.state["runs"]["run"] = {"id": "run", "uses": ["output"], "status": "unknown", "pid": None}
        row = self.row(self.check())
        self.assertEqual(row["category"], "blocked_needs_disposition")
        self.assertEqual(row["machine_metadata_blockers"][0]["code"], "command_outcome_unconfirmed")
        self.assertFalse(row["deletion_authorized"])

    def test_assessment_without_blockers_is_still_not_deletion_permission(self):
        self.due()
        audit.record_assessment(self.state, "output", {"machine_blockers": [], "owner_checks_required": []}, at=self.at)
        row = self.row(self.check())
        self.assertEqual(row["category"], "release_attempt_missing")
        self.assertFalse(row["deletion_authorized"])

    def test_direct_release_attempt_does_not_invent_obligation(self):
        audit.record_release(self.state, "output", "blocked", reason="idle not confirmed", at=self.at)
        book = self.state["resources"]["output"]["resource_audit"]
        self.assertNotIn("due", book)
        self.assertNotIn("receipt", book)
        self.assertEqual(book["last_attempt"]["outcome"], "blocked")
        self.due()
        audit.record_release(self.state, "output", "released", at=self.at)
        self.assertEqual(book["receipt"]["event_id"], "passed-1")

    def test_state_growth_and_miss_counter_are_bounded(self):
        self.due()
        for number in range(200):
            self.check("check-" + str(number))
            self.advance()
        book = self.state["resources"]["output"]["resource_audit"]
        self.assertEqual(book["checks"]["unhandled_checks"], 2)
        self.assertEqual(len(book["counted_check_ids"]), 64)
        self.assertEqual(len(self.state["resource_audit"]["checks_seen"]), 64)
        self.assertLess(len(json.dumps(self.state)), 9000)

    def test_watch_runs_immediately_then_stops_cooperatively_with_no_scan(self):
        self.due()
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            self.cli("watch-stop")

        output = io.StringIO()
        with patch.object(audit.time, "sleep", side_effect=sleep), contextlib.redirect_stdout(output):
            result = self.cli("watch")
        self.assertEqual(result["reason"], "stop requested")
        self.assertEqual(self.state["resource_audit"]["watch"]["status"], "stopped")
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertTrue(json.loads(output.getvalue())["metadata_only"])
        self.assertEqual(sleeps, [5])

    def test_registered_watch_requires_explicit_stop_even_with_missing_pid(self):
        self.state["resource_audit"] = {"watch": {"id": "old", "status": "running", "pid": None}}
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.cli("watch")
        self.cli("watch-stop")
        self.assertEqual(self.state["resource_audit"]["watch"]["status"], "stop_requested")
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.cli("watch")
        with self.assertRaises(ValueError):
            self.cli("watch-stop", "--stopped-confirmed")
        self.cli("watch-stop", "--stopped-confirmed", "--reason", "owned watcher terminal confirmed stopped")
        self.assertEqual(self.state["resource_audit"]["watch"]["status"], "stopped")

    def test_watch_only_emits_changes_but_saves_every_report(self):
        self.due()
        elapsed = [0]
        sleeps = []

        def sleep(seconds):
            elapsed[0] += 1800
            self.advance()
            sleeps.append(seconds)
            if len(sleeps) == 3:
                self.cli("watch-stop")

        output = io.StringIO()
        with patch.object(audit.time, "sleep", side_effect=sleep), \
                patch.object(audit.time, "monotonic", side_effect=lambda: elapsed[0]), \
                contextlib.redirect_stdout(output):
            self.cli("watch")
        reports = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(reports), 2)  # First owner request, then escalation.
        self.assertEqual(self.state["resource_audit"]["last_report"]["checked_at"], "2026-10-09T09:00:00+00:00")

    def test_capacity_reports_latest_bytes_but_notifies_only_class_changes(self):
        self.due()
        self.h.capacity_snapshot = lambda state: {"filesystems": [{"filesystem": 1, "action": "none", "free_bytes": 100}]}
        first = self.cli("audit", "--check-id", "capacity-1")
        self.assertEqual(first["capacity"], self.state["resource_audit"]["last_report"]["capacity"])
        second = copy.deepcopy(first)
        second["capacity"]["filesystems"][0]["free_bytes"] = 90
        self.assertEqual(audit._action_signature(first), audit._action_signature(second))
        second["capacity"]["filesystems"][0]["action"] = "reconcile_owned_capacity"
        self.assertNotEqual(audit._action_signature(first), audit._action_signature(second))

    def test_watcher_exception_is_not_reported_as_normal_stop(self):
        with patch.object(audit.time, "sleep", side_effect=KeyboardInterrupt), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            self.cli("watch")
        watcher = self.state["resource_audit"]["watch"]
        self.assertEqual(watcher["status"], "failed")
        self.assertEqual(watcher["failure"]["type"], "KeyboardInterrupt")

    def test_sealed_invocation_cannot_start_watch_and_running_watch_exits(self):
        self.state["sealed_at"] = self.at
        self.assertEqual(self.cli("watch")["watch"], "not_started")
        self.state.pop("sealed_at")

        def seal(seconds):
            self.state["sealed_at"] = self.at

        with patch.object(audit.time, "sleep", side_effect=seal), contextlib.redirect_stdout(io.StringIO()):
            result = self.cli("watch")
        self.assertEqual(result["reason"], "sealed")
        self.assertEqual(self.state["resource_audit"]["watch"]["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
