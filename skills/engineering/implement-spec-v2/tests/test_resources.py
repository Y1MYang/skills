"""Exercise the public CLI in small, isolated repositories."""

import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


TOOL = Path(__file__).resolve().parents[1] / "scripts" / "resources.py"


class ResourceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="resource-helper-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Resource Helper Test")
        self.git("config", "user.email", "resource-helper@example.invalid")
        (self.repo / "source.txt").write_text("baseline\n")
        (self.repo / ".gitignore").write_text("generated/\n")
        self.git("add", ".")
        self.git("commit", "-m", "baseline")
        self.state = self.root / "state"
        self.cli("init", "--state-dir", self.state, "--repo", self.repo)

    def git(self, *args, cwd=None):
        result = subprocess.run(
            ["git", *map(str, args)], cwd=cwd or self.repo,
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def command(self, *args):
        args = list(args)
        if args and args[0] in ["create", "run"] and "--reservation" not in args:
            ledger = json.loads((self.state / "state.json").read_text())
            if ledger.get("capacity_protocol") and not ledger.get("sealed_at"):
                if "--owner" in args:
                    owner = str(args[args.index("--owner") + 1])
                elif args[0] == "create":
                    owner = str(args[args.index("--role") + 1])
                else:
                    name = str(args[args.index("--cwd-resource") + 1])
                    owner = ledger["resources"][name]["owner"]
                budget = "fixture-" + args[0] + "-" + str(args[args.index("--id") + 1])
                if budget not in ledger.get("reservations", {}):
                    self.cli("reserve", "--id", budget, "--path", self.root,
                             "--next-bytes", 1048576, "--reserve-bytes", 0, "--owner", owner)
                position = args.index("--") if "--" in args else len(args)
                args[position:position] = ["--reservation", budget]
        return [sys.executable, str(TOOL), *map(str, args)]

    def cli(self, subcommand, *args, ok=True):
        state_args = [] if subcommand == "init" else ["--state", str(self.state)]
        result = subprocess.run(
            self.command(subcommand, *state_args, *args),
            capture_output=True, text=True, timeout=20,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def tree(self, resource="ticket", role="implementer", branch=True):
        path = self.root / resource
        args = ["--id", resource, "--kind", "worktree", "--path", path,
                "--role", role, "--ref", "main"]
        if branch:
            args += ["--branch", "codex/" + resource]
        self.cli("create", *args)
        return path

    def data(self, resource="output", path=None, parent=None):
        path = path or self.root / resource
        args = ["--id", resource, "--kind", "data", "--path", path,
                "--role", "implementer"]
        if parent:
            args += ["--parent", parent]
        self.cli("create", *args)
        return path

    def run_test(self, run="attempt", failed=False, tree="ticket", output="output"):
        code = "print('diagnostic output'); raise SystemExit(%d)" % int(failed)
        return self.cli(
            "run", "--id", run, "--cwd-resource", tree,
            "--output-resource", output, "--test", "--",
            sys.executable, "-c", code, ok=not failed,
        )

    def record(self, run="attempt", failed=False):
        summary = self.root / (run + "-summary.json")
        summary.write_text(json.dumps({
            "tests": {"passed": int(not failed), "failed": int(failed),
                      "skipped": 0, "errors": 0, "total": 1},
            "acceptance": ["isolated fixture acceptance"],
            "reproduce": "Use the recorded revision and command; no external inputs.",
            "notes": "Uses the Python standard library only.",
        }))
        self.cli("record-test", "--run", run, "--summary", summary)
        return summary

    def release(self, resource, merged=None, ok=True):
        args = ["--resource", resource, "--idle-confirmed"]
        if merged:
            args += ["--merged-into", merged]
        return self.cli("release", *args, ok=ok)

    def cleanup_invocation(self):
        self.notes = self.root / "notes"
        self.state = self.notes / "ledger"
        self.index_root = self.root / "index"
        self.cli("init", "--state-dir", self.state, "--repo", self.repo,
                 "--notes-root", self.notes, "--index-root", self.index_root)

    def publish_pr(self):
        tree = self.tree("pr", role="merger")
        self.remote = self.root / "remote.git"
        self.git("init", "--bare", self.remote)
        self.cli("publish-branch", "--resource", "pr", "--remote-url", self.remote)
        oid = self.git("rev-parse", "codex/pr")
        repo = {"id": 7, "full_name": "team/project", "clone_url": str(self.remote)}
        self.pr_json = self.root / "pr.json"
        self.pr = {"id": 101, "number": 42, "html_url": "https://github.example/team/project/pull/42",
                   "base": {"repo": repo, "ref": "main", "sha": oid},
                   "head": {"repo": repo, "ref": "codex/pr", "sha": oid}}
        self.pr_json.write_text(json.dumps(self.pr))
        self.cli("bind-pr", "--pr-resource", "pr", "--pr-json", self.pr_json)
        return tree

    def test_notes_root_ownership_and_index_separation(self):
        self.cleanup_invocation()
        ledger = json.loads((self.state / "state.json").read_text())
        marker = json.loads((self.notes / ".implement-spec-notes").read_text())
        self.assertEqual(marker["invocation"], ledger["invocation"])
        self.assertEqual(marker, ledger["notes"]["marker"])
        self.assertEqual(ledger["cleanup_protocol"], "cleanup-spec-v2/1")
        foreign = self.root / "foreign-notes"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("not owned")
        self.cli("init", "--repo", self.repo, "--state-dir", foreign / "ledger",
                 "--notes-root", foreign, ok=False)
        self.assertEqual((foreign / "keep.txt").read_text(), "not owned")
        separate = self.root / "separate"
        self.cli("init", "--repo", self.repo, "--state-dir", separate / "ledger",
                 "--notes-root", separate, "--index-root", separate / "index", ok=False)
        self.assertFalse(separate.exists(), "invalid index allocation changed notes")

    def test_first_publication_cannot_overwrite_existing_remote_ref(self):
        self.cleanup_invocation()
        tree = self.tree("pr", role="merger")
        remote = self.root / "existing.git"
        self.git("init", "--bare", remote)
        baseline = self.git("rev-parse", "main")
        self.git("push", remote, "main:refs/heads/codex/pr")
        (tree / "source.txt").write_text("new delivery\n")
        self.git("add", "source.txt", cwd=tree)
        self.git("commit", "-m", "new delivery", cwd=tree)
        self.cli("publish-branch", "--resource", "pr", "--remote-url", remote, ok=False)
        self.assertEqual(self.git("rev-parse", "refs/heads/codex/pr", cwd=remote), baseline)
        ledger = json.loads((self.state / "state.json").read_text())
        self.assertNotIn("publication", ledger["resources"]["pr"])
        self.cli("publish-branch", "--resource", "pr", "--remote-url", remote, ok=False)

    def test_first_publication_cannot_adopt_existing_same_oid_remote_ref(self):
        self.cleanup_invocation()
        self.tree("pr", role="merger")
        remote = self.root / "same-oid.git"
        self.git("init", "--bare", remote)
        oid = self.git("rev-parse", "codex/pr")
        self.git("push", remote, "codex/pr")
        self.cli("publish-branch", "--resource", "pr", "--remote-url", remote, ok=False)
        self.assertEqual(self.git("rev-parse", "refs/heads/codex/pr", cwd=remote), oid)
        ledger = json.loads((self.state / "state.json").read_text())
        self.assertNotIn("publication", ledger["resources"]["pr"])

    def test_same_oid_noop_race_remains_uncertain_not_owned(self):
        self.cleanup_invocation()
        self.tree("pr", role="merger")
        remote = self.root / "racing.git"
        self.git("init", "--bare", remote)
        oid = self.git("rev-parse", "codex/pr")
        spec = importlib.util.spec_from_file_location("resource_publication_race_test", TOOL)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        inspect_remote = helper.remote_oid
        raced = []

        def competing_create(repo, destination, ref):
            if not raced:
                self.assertIsNone(inspect_remote(repo, destination, ref))
                # Another actor creates the identical ref after the absence read.
                self.git("push", remote, "codex/pr")
                raced.append(True)
                return None
            return inspect_remote(repo, destination, ref)

        with patch.object(helper, "remote_oid", side_effect=competing_create):
            with self.assertRaisesRegex(helper.Refusal, "did not confirm new remote reference creation"):
                helper.publish_branch(SimpleNamespace(state=str(self.state), resource="pr", remote_url=str(remote)))
        ledger = json.loads((self.state / "state.json").read_text())
        self.assertEqual(ledger["resources"]["pr"]["publication"]["status"], "creating")
        self.assertEqual(self.git("rev-parse", "refs/heads/codex/pr", cwd=remote), oid)

    def test_bind_and_seal_export_exact_delivery_and_owned_index(self):
        self.cleanup_invocation()
        tree = self.publish_pr()
        (self.notes / "architecture.md").write_text("one module\n")
        output = self.data("owned-output", path=self.notes / "output")
        (output / "raw.log").write_text("large project output not a notes record\n")
        self.release("pr", merged="codex/pr")
        self.cli("seal", "--pr-json", self.pr_json)
        ledger = json.loads((self.state / "state.json").read_text())
        handoff = json.loads((self.state / "handoff.json").read_text())
        index = json.loads(Path(ledger["index_path"]).read_text())
        self.assertEqual(index["handoff"], ledger["handoff"])
        self.assertEqual(index["pr"]["number"], 42)
        self.assertEqual(handoff["delivery_oid"], self.pr["head"]["sha"])
        self.assertEqual(handoff["branches"][0]["publication"]["expected_oid"], self.pr["head"]["sha"])
        self.assertEqual(handoff["internal_refs"][0]["expected_oid"], self.pr["head"]["sha"])
        paths = {entry["path"] for entry in handoff["notes_snapshot"]["entries"]}
        self.assertIn("architecture.md", paths)
        self.assertFalse(any(path.startswith("ledger/") or path.startswith("output/") for path in paths))
        self.assertFalse(tree.exists())
        self.cli("create", "--id", "late", "--kind", "data", "--role", "fixer",
                 "--path", self.root / "late", ok=False)
        self.assertFalse((self.root / "late").exists())
        # Safe release remains available after sealing.
        self.release("owned-output")

    def test_sealed_active_worktree_exports_future_anchor_and_blocks_new_runs(self):
        self.cleanup_invocation()
        self.publish_pr()
        self.data()
        self.cli("seal", "--pr-json", self.pr_json)
        handoff = json.loads((self.state / "handoff.json").read_text())
        self.assertEqual(handoff["worktrees"][0]["status"], "active")
        self.assertTrue(handoff["internal_refs"][0]["anticipated"])
        self.cli("run", "--id", "late-command", "--cwd-resource", "pr", "--output-resource", "output",
                 "--", sys.executable, "-c", "raise SystemExit(0)", ok=False)
        ledger = json.loads((self.state / "state.json").read_text())
        self.assertNotIn("late-command", ledger["runs"])
        self.release("pr", merged="codex/pr")
        self.assertEqual(self.git("rev-parse", handoff["internal_refs"][0]["ref"]), self.pr["head"]["sha"])

    def test_binding_rejects_wrong_native_pr_identity_and_notes_replacement(self):
        self.cleanup_invocation()
        self.tree("pr", role="merger")
        remote = self.root / "native.git"
        self.git("init", "--bare", remote)
        self.cli("publish-branch", "--resource", "pr", "--remote-url", remote)
        oid = self.git("rev-parse", "codex/pr")
        repo = {"id": 9, "full_name": "team/project", "clone_url": str(self.root / "foreign.git")}
        pr = {"id": 21, "number": 42, "html_url": "https://github.example/team/project/pull/42",
              "base": {"repo": repo, "ref": "main", "sha": oid},
              "head": {"repo": repo, "ref": "codex/pr", "sha": oid}}
        source = self.root / "wrong-pr.json"
        source.write_text(json.dumps(pr))
        self.cli("bind-pr", "--pr-resource", "pr", "--pr-json", source, ok=False)
        self.assertFalse(list(self.index_root.rglob("*.json")) if self.index_root.exists() else [])
        (self.notes / ".implement-spec-notes").write_text('{"foreign":true}')
        pr["head"]["repo"]["clone_url"] = str(remote)
        source.write_text(json.dumps(pr))
        self.cli("bind-pr", "--pr-resource", "pr", "--pr-json", source, ok=False)

    def test_seal_notes_symlink_is_a_blocker_and_never_followed(self):
        self.cleanup_invocation()
        self.publish_pr()
        foreign = self.root / "foreign"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("keep")
        try:
            (self.notes / "escape").symlink_to(foreign, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.cli("seal", "--pr-json", self.pr_json)
        handoff = json.loads((self.state / "handoff.json").read_text())
        self.assertEqual(handoff["notes_snapshot"]["blockers"][0]["path"], "escape")
        self.assertFalse(any(entry["path"].startswith("escape/") for entry in handoff["notes_snapshot"]["entries"]))
        self.assertEqual((foreign / "keep.txt").read_text(), "keep")

    def test_historical_ledger_is_compatible_but_cannot_publish_cleanup_handoff(self):
        self.tree("pr", role="merger")
        self.cli("publish-branch", "--resource", "pr", "--remote-url", self.root / "never-used.git", ok=False)
        self.assertFalse((self.root / "never-used.git").exists())

    def test_seal_uses_final_pushed_head_and_existing_runs_can_be_recorded(self):
        self.cleanup_invocation()
        tree = self.publish_pr()
        first = self.pr["head"]["sha"]
        (tree / "source.txt").write_text("final delivery\n")
        self.git("add", "source.txt", cwd=tree)
        self.git("commit", "-m", "final delivery", cwd=tree)
        final = self.git("rev-parse", "HEAD", cwd=tree)
        self.git("push", self.remote, "codex/pr")
        # A stale REST head cannot seal a later local/remote delivery.
        self.cli("seal", "--pr-json", self.pr_json, ok=False)
        self.pr["head"]["sha"] = final
        self.pr_json.write_text(json.dumps(self.pr))
        self.data()
        self.run_test(tree="pr")
        self.cli("seal", "--pr-json", self.pr_json)
        self.record()
        self.release("output")
        self.release("pr", merged="codex/pr")
        handoff = json.loads((self.state / "handoff.json").read_text())
        self.assertEqual(handoff["delivery_oid"], final)
        publication = handoff["branches"][0]["publication"]
        self.assertEqual(publication["created_oid"], first)
        self.assertEqual(publication["expected_oid"], final)

    def test_same_device_mount_is_blocked_before_data_deletion(self):
        owned = self.data()
        child = owned / "mounted"
        child.mkdir()
        sentinel = child / "keep.txt"
        sentinel.write_text("mounted data")
        spec = importlib.util.spec_from_file_location("resource_mount_test", TOOL)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        helper.check_data_tree(owned)
        # Mount metadata identifies a bind mount even though st_dev is unchanged.
        with patch.object(helper, "mount_points", return_value={child}):
            with self.assertRaises(helper.Refusal):
                helper.check_data_tree(owned)
            ledger = json.loads((self.state / "state.json").read_text())
            with self.assertRaises(helper.Refusal):
                helper.data_fingerprint(ledger, ledger["resources"]["output"])
        self.assertEqual(sentinel.read_text(), "mounted data")

    def test_sealed_data_fingerprint_detects_added_files_without_following_links(self):
        self.cleanup_invocation()
        self.publish_pr()
        output = self.data()
        (output / "owned.log").write_text("test output\n")
        foreign = self.root / "foreign-personal.txt"
        foreign.write_text("foreign contents\n")
        try:
            (output / "pointer").symlink_to(foreign)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.cli("seal", "--pr-json", self.pr_json)
        handoff = json.loads((self.state / "handoff.json").read_text())
        ledger = json.loads((self.state / "state.json").read_text())
        spec = importlib.util.spec_from_file_location("resource_data_fingerprint_test", TOOL)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        baseline = handoff["data"][0]["contents_sha256"]
        self.assertEqual(helper.data_fingerprint(ledger, ledger["resources"]["output"]), baseline)
        foreign.write_text("updated foreign contents\n")
        self.assertEqual(helper.data_fingerprint(ledger, ledger["resources"]["output"]), baseline,
                         "fingerprint followed a symlink into foreign data")
        (output / "personal.txt").write_text("new personal work\n")
        self.assertNotEqual(helper.data_fingerprint(ledger, ledger["resources"]["output"]), baseline)
        self.assertEqual(foreign.read_text(), "updated foreign contents\n")

    def test_data_fingerprint_excludes_registered_child_and_blocks_replacement(self):
        self.cleanup_invocation()
        self.publish_pr()
        output = self.data(path=self.notes / "output")
        child = self.data("child", path=output / "child", parent="output")
        (child / "child.log").write_text("child test output\n")
        self.cli("seal", "--pr-json", self.pr_json)
        handoff = json.loads((self.state / "handoff.json").read_text())
        rows = {row["resource"]: row for row in handoff["data"]}
        self.assertNotEqual(rows["output"]["contents_sha256"], rows["child"]["contents_sha256"])
        self.release("child")
        ledger = json.loads((self.state / "state.json").read_text())
        spec = importlib.util.spec_from_file_location("resource_nested_fingerprint_test", TOOL)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        self.assertEqual(helper.data_fingerprint(ledger, ledger["resources"]["output"]),
                         rows["output"]["contents_sha256"], "child release changed the parent baseline")
        child.mkdir()
        personal = child / "personal.txt"
        personal.write_text("replacement belongs to someone else\n")
        with self.assertRaises(helper.Refusal):
            helper.data_fingerprint(ledger, ledger["resources"]["output"])
        self.assertEqual(personal.read_text(), "replacement belongs to someone else\n")

    def test_data_fingerprint_blocker_does_not_prevent_other_seal_metadata(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("named pipes unavailable")
        self.cleanup_invocation()
        self.publish_pr()
        output = self.data()
        os.mkfifo(output / "active.pipe")
        self.cli("seal", "--pr-json", self.pr_json)
        handoff = json.loads((self.state / "handoff.json").read_text())
        self.assertIsNone(handoff["data"][0]["contents_sha256"])
        self.assertIn("special file", handoff["data"][0]["blocker"])
        self.assertEqual(handoff["delivery_oid"], self.pr["head"]["sha"])
        self.assertTrue(handoff["branches"])

    def test_existing_resources_and_state_cannot_be_adopted(self):
        existing = self.root / "old-data"
        existing.mkdir()
        sentinel = existing / "keep.txt"
        sentinel.write_text("historical data")
        self.cli("create", "--id", "old", "--kind", "data", "--role", "fixer",
                 "--path", existing, ok=False)
        self.cli("init", "--state-dir", self.state, "--repo", self.repo, ok=False)
        self.cli("release", "--resource", "unknown", "--idle-confirmed", ok=False)
        self.assertEqual(sentinel.read_text(), "historical data")

    def test_dangerous_paths_and_symlink_adoption_are_rejected(self):
        self.cli("create", "--id", "bad", "--kind", "data", "--role", "fixer",
                 "--path", self.repo, ok=False)
        self.cli("create", "--id", "bad", "--kind", "data", "--role", "fixer",
                 "--path", self.state, ok=False)
        link = self.root / "linked-data"
        try:
            link.symlink_to(self.repo, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.cli("create", "--id", "bad", "--kind", "data", "--role", "fixer",
                 "--path", link, ok=False)
        self.assertTrue((self.repo / "source.txt").exists())

    def test_data_cannot_be_created_in_unowned_primary_source_tree(self):
        raw = self.repo / "new-raw-output"
        self.cli("create", "--id", "raw", "--kind", "data", "--role", "fixer",
                 "--path", raw, ok=False)
        self.assertFalse(raw.exists())

    def test_record_then_release_success_and_keep_compact_evidence(self):
        tree = self.tree()
        output = self.data()
        self.run_test()
        self.release("output", ok=False)
        self.assertTrue(output.exists())
        self.record()
        self.release("output")
        self.assertFalse(output.exists())
        self.release("ticket", merged="main")
        self.assertFalse(tree.exists())
        records = [p for p in self.state.rglob("*.json")
                   if p.is_file() and "isolated fixture acceptance" in p.read_text()]
        self.assertTrue(records, "compact evidence was lost with raw data")
        self.cli("status")

    def test_failed_scene_requires_record_and_resolution(self):
        self.tree()
        output = self.data()
        self.run_test(failed=True)
        self.record(failed=True)
        self.release("output", ok=False)
        self.assertTrue(output.exists())
        self.cli("resolve", "--run", "attempt", "--reason",
                 "Fixture failure intentionally reproduced, diagnosed and verified.")
        self.release("output")
        self.assertFalse(output.exists())

    def test_invalid_summary_and_exit_count_mismatch_do_not_unlock_cleanup(self):
        self.tree()
        output = self.data()
        self.run_test()
        summary = self.root / "invalid.json"
        summary.write_text(json.dumps({
            "tests": {"passed": 1, "failed": 0, "skipped": 0, "errors": 0, "total": 7},
            "acceptance": ["fixture"], "reproduce": "recorded command",
        }))
        self.cli("record-test", "--run", "attempt", "--summary", summary, ok=False)
        summary.write_text(json.dumps({
            "tests": {"passed": 0, "failed": 1, "skipped": 0, "errors": 0, "total": 1},
            "acceptance": ["fixture"], "reproduce": "recorded command",
        }))
        self.cli("record-test", "--run", "attempt", "--summary", summary, ok=False)
        self.release("output", ok=False)
        self.assertTrue(output.exists())

    def test_corrupt_compact_record_blocks_raw_deletion(self):
        self.tree()
        output = self.data()
        self.run_test()
        self.record()
        ledger = json.loads((self.state / "state.json").read_text())
        record = self.state / "records" / ledger["runs"]["attempt"]["record_file"]
        record.write_text('{"tampered": true}')
        self.release("output", ok=False)
        self.assertTrue(output.exists())

    def test_unmerged_dirty_untracked_and_ignored_work_are_preserved(self):
        tree = self.tree()
        (tree / "source.txt").write_text("delivery\n")
        self.release("ticket", merged="main", ok=False)
        self.git("add", "source.txt", cwd=tree)
        self.git("commit", "-m", "ticket delivery", cwd=tree)
        self.release("ticket", merged="main", ok=False)
        self.git("merge", "--ff-only", "codex/ticket")
        untracked = tree / "unsaved.txt"
        untracked.write_text("unsaved")
        self.release("ticket", merged="main", ok=False)
        self.assertEqual(untracked.read_text(), "unsaved")
        untracked.unlink()
        generated = tree / "generated"
        generated.mkdir()
        (generated / "input.txt").write_text("unclassified ignored input")
        self.release("ticket", merged="main", ok=False)
        self.assertTrue((generated / "input.txt").exists())
        (generated / "input.txt").unlink()
        generated.rmdir()
        self.release("ticket", merged="main")

    def test_resource_replacement_is_not_deleted(self):
        owned = self.data()
        owned.rename(self.root / "original-owned")
        owned.mkdir()
        sentinel = owned / "foreign.txt"
        sentinel.write_text("foreign replacement")
        self.release("output", ok=False)
        self.assertEqual(sentinel.read_text(), "foreign replacement")

    def test_contained_data_blocks_parent_until_released(self):
        tree = self.tree()
        child = self.data("child", path=tree / "owned-output", parent="ticket")
        self.release("ticket", merged="main", ok=False)
        self.assertTrue(child.exists())
        self.release("child")
        self.release("ticket", merged="main")

    def test_nested_resource_measurement_does_not_double_count_child(self):
        tree = self.tree()
        child = self.data("child", path=tree / "owned-output", parent="ticket")
        (child / "sample.txt").write_bytes(b"sample\n" * 100)
        result = self.cli("status", "--measure")
        snapshot = json.loads(result.stdout)
        rows = {row["id"]: row for row in snapshot["resources"]}
        self.assertGreater(rows["child"]["logical_bytes"], 0)
        self.assertEqual(snapshot["remaining_bytes"], rows["ticket"]["logical_bytes"])

    def test_descendant_symlink_never_deletes_its_target(self):
        owned = self.data()
        foreign = self.root / "foreign"
        foreign.mkdir()
        sentinel = foreign / "keep.txt"
        sentinel.write_text("keep")
        try:
            (owned / "escape").symlink_to(foreign, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        result = subprocess.run(
            self.command("release", "--state", self.state,
                         "--resource", "output", "--idle-confirmed"),
            capture_output=True, text=True, timeout=10,
        )
        # Conservative refusal is valid; the target must survive either implementation.
        self.assertEqual(sentinel.read_text(), "keep", result.stdout + result.stderr)

    def test_parallel_registration_keeps_each_resource(self):
        def create_one(number):
            self.data("parallel-%d" % number)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(create_one, range(3)))
        for number in range(3):
            self.release("parallel-%d" % number)

    def test_scratch_revision_remains_reachable_after_checkout_release(self):
        tree = self.tree("checkpoint", role="checkpoint", branch=False)
        (tree / "source.txt").write_text("scratch union fixture\n")
        self.git("add", "source.txt", cwd=tree)
        self.git("commit", "-m", "scratch union fixture", cwd=tree)
        revision = self.git("rev-parse", "HEAD", cwd=tree)
        self.release("checkpoint")
        self.assertFalse(tree.exists())
        refs = self.git("for-each-ref", "--format=%(objectname)", "refs/implement-spec-runs/")
        self.assertIn(revision, refs.splitlines())

    def test_failed_checkpoint_releases_checkout_and_preserves_external_scene(self):
        tree = self.tree("checkpoint", role="checkpoint", branch=False)
        output = self.data()
        self.run_test(tree="checkpoint", failed=True)
        self.record(failed=True)
        self.release("checkpoint")
        self.assertFalse(tree.exists())
        self.assertTrue(output.exists())
        self.release("output", ok=False)
        self.cli("resolve", "--run", "attempt", "--reason",
                 "Checkpoint mismatch diagnosed and fixed on the responsible branch.")
        self.release("output")

    def test_failed_checkpoint_needs_intact_external_scene_before_release(self):
        tree = self.tree("checkpoint", role="checkpoint", branch=False)
        output = self.data()
        self.run_test(tree="checkpoint", failed=True)
        self.record(failed=True)
        (output / "attempt.stdout.gz").write_bytes(b"tampered diagnostic log")
        self.release("checkpoint", ok=False)
        self.assertTrue(tree.exists())
        self.assertTrue(output.exists())

    def wait_for_path(self, path, process, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                return
            if process.poll() is not None:
                out, err = process.communicate()
                self.fail("wrapper exited early: " + out + err)
            time.sleep(0.02)
        self.fail("fixture command did not become ready")

    def test_running_command_is_not_blocking_ledger_or_releasable(self):
        self.tree()
        output = self.data()
        ready, stop = output / "ready", output / "stop"
        code = (
            "from pathlib import Path; import sys,time; "
            "ready=Path(sys.argv[1]); stop=Path(sys.argv[2]); ready.write_text('ready'); "
            "\nwhile not stop.exists(): time.sleep(0.02)\n"
        )
        process = subprocess.Popen(
            self.command("run", "--state", self.state, "--id", "long-command",
                         "--cwd-resource", "ticket", "--output-resource", "output",
                         "--", sys.executable, "-c", code, ready, stop),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            self.wait_for_path(ready, process)
            self.cli("status")
            handoff = self.cli("handoff", "--resource", "ticket", "--owner", "replacement")
            receipt = json.loads(handoff.stdout)
            self.assertEqual(receipt["path"], str(self.root / "ticket"))
            self.assertEqual(receipt["owner"], "replacement")
            self.release("output", ok=False)
            self.release("ticket", merged="main", ok=False)
            self.assertTrue(output.exists())
        finally:
            stop.write_text("stop")
            out, err = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, out + err)
        self.release("output")

    def test_killed_wrapper_requires_explicit_recovery_and_failure_resolution(self):
        self.tree()
        output = self.data()
        ready, stop, done = output / "ready", output / "stop", output / "done"
        code = (
            "from pathlib import Path; import sys,time; "
            "ready=Path(sys.argv[1]); stop=Path(sys.argv[2]); done=Path(sys.argv[3]); "
            "ready.write_text('ready'); "
            "\nwhile not stop.exists(): time.sleep(0.02)\n"
            "done.write_text('stopped')\n"
        )
        process = subprocess.Popen(
            self.command("run", "--state", self.state, "--id", "interrupted",
                         "--cwd-resource", "ticket", "--output-resource", "output",
                         "--test", "--", sys.executable, "-c", code, ready, stop, done),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            self.wait_for_path(ready, process)
            process.kill()  # This wrapper belongs only to this isolated fixture.
            process.communicate(timeout=10)
            self.release("output", ok=False)
        finally:
            stop.write_text("stop")
            if process.poll() is None:
                process.communicate(timeout=10)
            deadline = time.monotonic() + 10
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(done.exists(), "fixture child did not finish")
        self.cli("recover-run", "--run", "interrupted", "--reason",
                 "Fixture wrapper and child confirmed stopped.", ok=False)
        self.cli("recover-run", "--run", "interrupted", "--stopped-confirmed",
                 "--reason", "Fixture wrapper and child confirmed stopped.")
        self.record(run="interrupted", failed=True)
        self.release("output", ok=False)
        self.cli("resolve", "--run", "interrupted", "--reason",
                 "Interrupted fixture diagnosed; required compact record verified.")
        self.release("output")

    def test_capacity_reports_pressure_without_mutating_resources(self):
        owned = self.data()
        result = subprocess.run(
            self.command("capacity", "--state", self.state,
                         "--next-bytes", 10**18, "--reserve-bytes", 1),
            capture_output=True, text=True, timeout=10,
        )
        self.assertIn(result.returncode, (0, 1, 2))
        response = json.loads(result.stdout)
        self.assertFalse(response["admit"], result.stdout)
        self.assertGreater(response["shortfall_bytes"], 0)
        self.assertTrue(owned.exists())


if __name__ == "__main__":
    unittest.main()
