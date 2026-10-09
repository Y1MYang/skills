"""Reservation admission with simulated disk capacity and real ledger locking."""

import concurrent.futures
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("capacity_test_resources", SCRIPTS / "resources.py")
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)
import resource_capacity as capacity


class CapacityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="resource-capacity-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.state_path = self.root / "ledger"
        self.state_path.mkdir()
        (self.state_path / "lock").write_bytes(b"0")
        self.state = {"version": resources.VERSION, "state_path": str(self.state_path),
                      "identity": resources.identity(self.state_path), "resources": {}, "runs": {}}
        capacity.initialize(self.state)
        resources.save(self.state_path, self.state)
        self.free = 100
        self.h = SimpleNamespace(**vars(resources))
        self.h.shutil = SimpleNamespace(disk_usage=Mock(side_effect=lambda path: SimpleNamespace(free=self.free)))

    def read(self):
        return json.loads((self.state_path / "state.json").read_text())

    def save(self, state):
        resources.save(self.state_path, state)

    def reserve(self, name="ticket", amount=40, floor=10, path=None, owner="implementer"):
        return capacity.dispatch("reserve", SimpleNamespace(state=str(self.state_path), id=name,
            next_bytes=amount, reserve_bytes=floor, path=str(path or self.root), owner=owner), self.h)

    def edit(self, name="ticket", remaining=None, release=False, owner="implementer", idle=True, reason="measured footprint and remaining work", transfer_to=None):
        return capacity.dispatch("reservation", SimpleNamespace(state=str(self.state_path), id=name,
            remaining_bytes=remaining, release=release, owner=owner, idle_confirmed=idle, reason=reason,
            transfer_to=transfer_to), self.h)

    def admit(self, names=None, paths=None, kind="run", name="build", owner="implementer"):
        with self.h.locked(self.state_path) as (path, state):
            result = capacity.claim(state, names if names is not None else ["ticket"],
                                    paths or [self.root], kind, name, self.h, owner=owner)
            self.h.save(path, state)
            return result

    def finish(self, kind="run", name="build"):
        with self.h.locked(self.state_path) as (path, state):
            capacity.finish(state, kind, name, self.h)
            self.h.save(path, state)

    def check(self, next_bytes=0, floor=0, path=None):
        return capacity.dispatch("capacity", SimpleNamespace(state=str(self.state_path),
            path=str(path or self.root), next_bytes=next_bytes, reserve_bytes=floor), self.h)

    def test_existing_growth_and_single_shared_safety_floor(self):
        self.reserve("first", 30, 10)
        self.reserve("second", 40, 20)
        result = self.check(5, 15)
        self.assertEqual(result["required_bytes"], 95)
        self.assertEqual(result["reserved_growth_bytes"], 70)
        self.assertEqual(result["reserve_bytes"], 20)
        self.assertTrue(result["admit"])
        self.assertFalse(self.check(11)["admit"])

    def test_parallel_reservations_cannot_both_spend_the_same_free_bytes(self):
        barrier = threading.Barrier(2)

        def reserve(name):
            barrier.wait()
            try:
                self.reserve(name, 60, 10)
                return "admitted"
            except resources.Refusal:
                return "refused"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ["first", "second"]))
        self.assertCountEqual(results, ["admitted", "refused"])
        self.assertEqual(len(self.read()["reservations"]), 1)

    def test_claim_is_required_and_respects_owner_and_single_claimant(self):
        self.reserve()
        for names, owner in [([], "implementer"), (["ticket", "ticket"], "implementer"),
                             (["ticket"], "someone-else"), (["missing"], "implementer")]:
            with self.subTest(names=names, owner=owner), self.assertRaises(resources.Refusal):
                self.admit(names=names, owner=owner)
        self.admit()
        with self.assertRaisesRegex(resources.Refusal, "active claimant"):
            self.admit(name="second-build")

    def test_completion_retains_future_growth_and_unknown_activity_cannot_release(self):
        self.reserve()
        self.admit(kind="create", name="tree")
        self.finish(kind="create", name="tree")
        self.assertEqual(self.read()["reservations"]["ticket"]["remaining_bytes"], 40)
        self.admit()
        for change in [{"remaining": 5}, {"release": True}]:
            with self.assertRaisesRegex(resources.Refusal, "active claimant"):
                self.edit(**change)
        self.assertEqual(self.read()["reservations"]["ticket"]["claimant"]["id"], "build")
        # The caller invokes finish only after known completion or stopped recovery.
        self.finish()
        result = self.edit(remaining=5)
        self.assertEqual(result["reservation"]["remaining_bytes"], 5)
        self.assertEqual(result["reservation"]["last_claim"]["id"], "build")

    def test_actual_free_is_rechecked_before_each_new_claim(self):
        self.reserve("first", 30)
        self.reserve("second", 30)
        self.admit(names=["first"])
        self.finish()
        self.free = 60  # Other work and completed writes consumed real capacity.
        with self.assertRaisesRegex(resources.Refusal, "insufficient unreserved"):
            self.admit(names=["second"], name="next")
        self.edit("first", remaining=10)
        self.admit(names=["second"], name="next")

    def test_updates_require_owner_confirmation_and_do_not_double_count_self(self):
        self.reserve("first", 30)
        self.reserve("second", 30)
        for values in [{"owner": "other"}, {"idle": False}, {"reason": ""}]:
            with self.assertRaises(resources.Refusal):
                self.edit("first", remaining=20, **values)
        self.edit("first", remaining=60)
        self.assertEqual(self.check()["required_bytes"], 100)
        with self.assertRaisesRegex(resources.Refusal, "insufficient unreserved"):
            self.edit("first", remaining=61)
        self.assertEqual(self.read()["reservations"]["first"]["remaining_bytes"], 60)

    def test_released_ids_are_never_reused(self):
        self.reserve()
        with self.assertRaisesRegex(resources.Refusal, "ID already used"):
            self.reserve()
        self.edit(release=True)
        self.assertEqual(self.check()["reserved_growth_bytes"], 0)
        with self.assertRaisesRegex(resources.Refusal, "ID already used"):
            self.reserve()
        with self.assertRaisesRegex(resources.Refusal, "released reservation"):
            self.admit()

    def test_sealed_invocation_allows_only_existing_budget_reduction_or_release(self):
        self.reserve()
        state = self.read()
        state["sealed_at"] = resources.now()
        self.save(state)
        with self.assertRaisesRegex(resources.Refusal, "sealed"):
            self.reserve("new")
        with self.assertRaisesRegex(resources.Refusal, "sealed"):
            self.edit(remaining=41)
        with self.assertRaisesRegex(resources.Refusal, "sealed"):
            self.admit()
        self.edit(remaining=20)
        self.edit(release=True)

    def test_legacy_ledgers_keep_old_behavior_and_report_disabled(self):
        state = self.read()
        del state["capacity_protocol"]
        del state["reservations"]
        self.save(state)
        self.assertEqual(self.admit(names=[]), [])
        result = self.check(50, 10)
        self.assertEqual(result["required_bytes"], 60)
        self.assertFalse(result["admission_enabled"])
        self.assertIn("disabled", result["legacy_notice"])
        with self.assertRaisesRegex(resources.Refusal, "disabled"):
            self.reserve()
        state["capacity_protocol"] = "future/unknown"
        self.save(state)
        with self.assertRaisesRegex(resources.Refusal, "unsupported"):
            self.admit(names=[])

    def test_missing_anchor_and_old_timestamp_do_not_expire_a_reservation(self):
        destination = self.root / "destination"
        destination.mkdir()
        self.reserve(path=destination)
        state = self.read()
        state["reservations"]["ticket"]["updated_at"] = "2000-01-01T00:00:00+00:00"
        self.save(state)
        destination.rmdir()
        self.assertEqual(self.check()["reserved_growth_bytes"], 40)
        with self.assertRaisesRegex(resources.Refusal, "existing destination"):
            self.admit()
        report = capacity.report(self.read())
        self.assertFalse(report["automatic_expiry"])
        self.assertEqual(report["reservations"][0]["updated_at"], "2000-01-01T00:00:00+00:00")
        self.edit(release=True)

    def test_destination_identity_change_is_not_silently_accepted(self):
        self.reserve()
        original = self.h.identity
        self.h.identity = lambda path: [original(path)[0], original(path)[1] + 1]
        with self.assertRaisesRegex(resources.Refusal, "identity changed"):
            self.admit()

    def test_filesystems_are_accounted_separately_and_claimed_atomically(self):
        second = self.root / "second-filesystem"
        second.mkdir()
        original = self.h.identity
        device = original(self.root)[0]
        self.h.identity = lambda path: [device + int(Path(path) == second), original(path)[1]]
        self.reserve("first", 80, path=self.root)
        self.reserve("second", 80, path=second)
        self.assertEqual(self.check(path=self.root)["reserved_growth_bytes"], 80)
        self.assertEqual(self.check(path=second)["reserved_growth_bytes"], 80)
        with self.assertRaisesRegex(resources.Refusal, "cover exactly"):
            self.admit(names=["first"], paths=[self.root, second])
        self.h.shutil.disk_usage.side_effect = lambda path: SimpleNamespace(free=50 if Path(path) == second else 100)
        with self.assertRaisesRegex(resources.Refusal, "insufficient unreserved"):
            self.admit(names=["first", "second"], paths=[self.root, second])
        self.assertTrue(all(not item["claimant"] for item in self.read()["reservations"].values()))
        self.h.shutil.disk_usage.side_effect = lambda path: SimpleNamespace(free=100)
        self.admit(names=["first", "second"], paths=[self.root, second])
        self.assertTrue(all(item["claimant"] for item in self.read()["reservations"].values()))

    def test_negative_estimates_are_rejected_without_allocating(self):
        for amount, floor in [(-1, 0), (0, -1)]:
            with self.assertRaisesRegex(resources.Refusal, "nonnegative"):
                self.reserve(amount=amount, floor=floor)
        self.assertEqual(self.read()["reservations"], {})

    def test_idle_budget_transfers_without_allocation_even_when_sealed_or_disk_full(self):
        self.reserve()
        original = self.read()["reservations"]["ticket"]
        state = self.read()
        state["sealed_at"] = resources.now()
        self.save(state)
        self.free = 0
        result = self.edit(transfer_to="merger", reason="merger accepted the resource handoff")
        changed = result["reservation"]
        self.assertEqual(changed["owner"], "merger")
        for key in ["remaining_bytes", "reserve_bytes", "identity", "filesystem", "created_at", "status"]:
            self.assertEqual(changed[key], original[key])
        self.assertEqual(changed["last_transfer"]["from"], "implementer")
        self.assertEqual(changed["last_transfer"]["to"], "merger")
        self.assertEqual(changed["last_transfer"]["reason"], "merger accepted the resource handoff")
        self.assertIn("at", changed["last_transfer"])
        self.assertEqual(len(self.read()["reservations"]), 1)
        self.assertEqual(self.edit(owner=None)["reservation"]["owner"], "merger")
        with self.assertRaisesRegex(resources.Refusal, "owner mismatch"):
            self.edit(release=True)
        self.edit(owner="merger", release=True)

    def test_transfer_requires_idle_current_owner_and_does_not_accept_resource_handoff(self):
        self.reserve()
        for options in [{"idle": False}, {"owner": "other"}, {"reason": ""}]:
            with self.assertRaises(resources.Refusal):
                self.edit(transfer_to="merger", **options)
        for destination in ["", "implementer"]:
            with self.assertRaises(resources.Refusal):
                self.edit(transfer_to=destination)
        self.admit()
        with self.assertRaisesRegex(resources.Refusal, "active claimant"):
            self.edit(transfer_to="merger")
        self.assertEqual(self.read()["reservations"]["ticket"]["owner"], "implementer")
        self.finish()
        self.edit(transfer_to="merger")
        self.assertEqual(self.read()["resources"], {})
        with self.assertRaisesRegex(resources.Refusal, "owner mismatch"):
            self.admit()
        self.admit(owner="merger")


if __name__ == "__main__":
    unittest.main()
