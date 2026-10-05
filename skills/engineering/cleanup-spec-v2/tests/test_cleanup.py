"""Black-box cleanup checks against isolated Git repositories and a fake REST API.

The remote is a temporary bare repository. No test contacts GitHub, changes a
user's repository, or relies on a production bypass for the merged check.
"""

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
from types import SimpleNamespace
import unittest
from unittest import mock


ENGINEERING = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parents[1] / "scripts" / "cleanup.py"
RESOURCE_TOOL = ENGINEERING / "implement-spec-v2" / "scripts" / "resources.py"
PR_NUMBER = 71
BRANCH = "codex/cleanup-fixture"


class CleanupBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cleanup-spec-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.remote = self.root / "remote.git"
        self.head_remote = self.remote
        self.notes = self.root / "notes"
        self.state = self.notes / "ledger"
        self.index = self.root / "index"
        self.pr_tree = self.root / "pr-worktree"
        self.output = self.root / "test-output"
        self.api_file = self.root / "api.json"
        self.api_log = self.root / "gh-calls.jsonl"
        self.env = dict(os.environ)
        # A real user configuration, credential helper or environment override
        # must not select the repository/host or change the test's Git behavior.
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                        GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1")
        for name in ["GH_REPO", "GH_HOST", "GIT_DIR", "GIT_WORK_TREE",
                     "GIT_INDEX_FILE", "GIT_CONFIG_COUNT"]:
            self.env.pop(name, None)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Cleanup Fixture")
        self.git("config", "user.email", "cleanup@example.invalid")
        (self.repo / "source.txt").write_text("baseline\n")
        (self.repo / ".gitignore").write_text("generated/\n")
        self.git("add", ".")
        self.git("commit", "-m", "baseline")
        self.git("init", "--bare", self.remote)
        self.git("remote", "add", "origin", self.remote)
        self.git("push", "origin", "main")
        self.install_fake_gh()

    def install_fake_gh(self):
        binary_dir = self.root / "bin"
        binary_dir.mkdir()
        fake = binary_dir / "gh"
        fake.write_text("#!" + sys.executable + "\n" + textwrap.dedent("""\
            import json, os, sys
            from pathlib import Path
            args = sys.argv[1:]
            with open(os.environ['CLEANUP_TEST_API_LOG'], 'a') as log:
                log.write(json.dumps(args) + '\\n')
            def reject(message):
                print(message, file=sys.stderr)
                raise SystemExit(91)
            if not args or args[0] != 'api':
                reject('fixture expects the native REST API')
            if '--hostname' not in args or args[args.index('--hostname') + 1] != 'github.com':
                reject('GitHub host must be selected explicitly')
            for flag in ['--method', '-X']:
                if flag in args and args[args.index(flag) + 1] != 'GET':
                    reject('fixture allows only read-only GitHub requests')
            endpoints = [arg.lstrip('/') for arg in args if arg.lstrip('/').startswith('repos/')]
            if len(endpoints) != 1 or '{' in endpoints[0]:
                reject('repository must be explicit in the REST endpoint')
            endpoint = endpoints[0]
            pr = json.loads(Path(os.environ['CLEANUP_TEST_API_JSON']).read_text())
            base = 'repos/' + pr['base']['repo']['full_name']
            if endpoint == base + '/pulls/' + str(pr['number']):
                result = pr
            elif endpoint == base + '/pulls/' + str(pr['number']) + '/merge':
                if not pr['merged']:
                    raise SystemExit(1)
                if '--include' in args or '-i' in args:
                    print('HTTP/2.0 204 No Content\\n')
                raise SystemExit(0)
            elif endpoint in ['repos/' + pr[side]['repo']['full_name'] for side in ['base', 'head']]:
                result = next(pr[side]['repo'] for side in ['base', 'head']
                              if endpoint == 'repos/' + pr[side]['repo']['full_name'])
            else:
                reject('unexpected endpoint: ' + endpoint)
            print(json.dumps(result))
        """))
        fake.chmod(0o755)
        self.env["PATH"] = str(binary_dir) + os.pathsep + self.env.get("PATH", "")
        self.env["CLEANUP_TEST_API_JSON"] = str(self.api_file)
        self.env["CLEANUP_TEST_API_LOG"] = str(self.api_log)

    def process(self, command, cwd=None, expected=0):
        result = subprocess.run(list(map(str, command)), cwd=cwd or self.repo,
                                env=self.env, capture_output=True, text=True,
                                timeout=30)
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def git(self, *args, cwd=None):
        return self.process(["git", *args], cwd=cwd).stdout.strip()

    def producer(self, action, *args, expected=0):
        state_args = [] if action == "init" else ["--state", self.state]
        result = self.process([sys.executable, RESOURCE_TOOL, action, *state_args,
                               *args], expected=expected)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def cleanup(self, action, *args, expected=0):
        result = self.process([sys.executable, TOOL, action, *args,
                               "--resource-tool", RESOURCE_TOOL], expected=expected)
        text = result.stdout if result.stdout.strip() else result.stderr
        return json.loads(text)

    def write_api(self, value):
        self.api_file.write_text(json.dumps(value))

    def fixture(self, method="merge", fork=False, seal=True):
        self.producer("init", "--state-dir", self.state, "--repo", self.repo,
                      "--notes-root", self.notes, "--index-root", self.index)
        (self.notes / "architecture.md").write_text("Disposable invocation notes.\n")
        self.producer("create", "--id", "pr", "--kind", "worktree", "--role", "merger",
                      "--path", self.pr_tree, "--ref", "main", "--branch", BRANCH)
        (self.pr_tree / "source.txt").write_text("delivered implementation\n")
        self.git("add", "source.txt", cwd=self.pr_tree)
        self.git("commit", "-m", "delivery", cwd=self.pr_tree)
        self.delivered = self.git("rev-parse", "HEAD", cwd=self.pr_tree)
        self.producer("create", "--id", "output", "--kind", "data", "--role", "merger",
                      "--path", self.output)
        self.producer("run", "--id", "acceptance", "--cwd-resource", "pr",
                      "--output-resource", "output", "--test", "--", sys.executable,
                      "-c", "print('one passing acceptance case')")
        summary = self.notes / "acceptance.json"
        summary.write_text(json.dumps({
            "tests": {"passed": 1, "failed": 0, "skipped": 0, "errors": 0, "total": 1},
            "acceptance": ["independent cleanup fixture"],
            "reproduce": "Run the recorded standard-library command at the delivered revision.",
            "notes": "No external data or dependencies.",
        }))
        self.producer("record-test", "--run", "acceptance", "--summary", summary)
        if fork:
            self.head_remote = self.root / "fork.git"
            self.git("clone", "--bare", self.remote, self.head_remote)
        self.producer("publish-branch", "--resource", "pr", "--remote-url", self.head_remote)
        head_repo = {"id": 101, "node_id": "REPO_base", "full_name": "acme/project",
                     "clone_url": str(self.remote), "ssh_url": str(self.remote),
                     "html_url": "https://github.com/acme/project", "default_branch": "main"}
        base_repo = copy.deepcopy(head_repo)
        if fork:
            head_repo.update(id=202, node_id="REPO_fork", full_name="contributor/project",
                             clone_url=str(self.head_remote), ssh_url=str(self.head_remote),
                             html_url="https://github.com/contributor/project")
        self.pr = {"id": 7001, "node_id": "PR_fixture", "number": PR_NUMBER,
                   "html_url": "https://github.com/acme/project/pull/71", "state": "open",
                   "merged": False, "merged_at": None, "merge_commit_sha": None,
                   "head": {"ref": BRANCH, "sha": self.delivered, "repo": head_repo},
                   "base": {"ref": "main", "sha": self.git("rev-parse", "main"),
                            "repo": base_repo}}
        self.write_api(self.pr)
        self.producer("bind-pr", "--pr-json", self.api_file, "--pr-resource", "pr",
                      "--index-root", self.index)
        if seal:
            self.producer("seal", "--pr-json", self.api_file)
        (self.repo / "base-only.txt").write_text("Base advanced before merge.\n")
        self.git("add", "base-only.txt")
        self.git("commit", "-m", "advance base")
        if method == "merge":
            self.git("merge", "--no-ff", "--no-edit", BRANCH)
        elif method == "squash":
            self.git("merge", "--squash", BRANCH)
            self.git("commit", "-m", "squashed delivery")
        elif method == "rebase":
            self.git("cherry-pick", self.delivered)
        else:
            self.fail("Unknown fixture merge method")
        self.git("push", "origin", "main")
        self.pr.update(state="closed", merged=True, merged_at="2026-10-05T00:00:00Z",
                       merge_commit_sha=self.git("rev-parse", "main"))
        self.write_api(self.pr)

    def plan(self, idle=("pr", "output"), notes_idle=True):
        args = [PR_NUMBER, "--repo", self.repo, "--index-root", self.index]
        for resource in idle:
            args += ["--idle-resource", resource]
        if notes_idle:
            args += ["--notes-idle"]
        return self.cleanup("plan", *args)

    def apply(self, plan, expected=0):
        return self.cleanup("apply", "--plan", plan["plan_path"],
                            "--approved-digest", plan["plan_sha256"], expected=expected)

    def remote_tip(self):
        return self.git("ls-remote", self.head_remote, "refs/heads/" + BRANCH).split()

    def assert_fully_cleaned(self, result, plan):
        self.assertTrue(result["complete"], result)
        for path in [self.pr_tree, self.output, self.notes, Path(plan["plan_path"])]:
            self.assertFalse(path.exists(), "Invocation residue: " + str(path))
        self.assertEqual(self.remote_tip(), [])
        self.assertEqual(self.git("for-each-ref", "--format=%(refname)",
                                  "refs/heads/" + BRANCH), "")
        self.assertEqual(self.git("for-each-ref", "--format=%(refname)",
                                  "refs/implement-spec-runs/"), "")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("show", "main:source.txt"), "delivered implementation")
        self.assertEqual(self.git("show", "main:base-only.txt"), "Base advanced before merge.")
        self.assertEqual([path for path in self.index.rglob("*")
                          if path.is_file() or path.is_symlink()], [])

    def test_normal_merge_cleans_owned_resources_and_keeps_delivered_code(self):
        self.fixture("merge")
        plan = self.plan()
        self.assertTrue(any(item["kind"] == "remote_branch" for item in plan["items"]))
        self.assertTrue(any(item["kind"] == "notes" for item in plan["items"]))
        self.assertTrue(all(item["status"] in ["ready", "absent"] for item in plan["items"]), plan)
        self.assert_fully_cleaned(self.apply(plan), plan)

    def test_squash_does_not_require_source_commit_ancestry(self):
        self.fixture("squash")
        ancestry = self.process(["git", "merge-base", "--is-ancestor", self.delivered, "main"],
                                expected=None)
        self.assertNotEqual(ancestry.returncode, 0)
        plan = self.plan()
        self.assert_fully_cleaned(self.apply(plan), plan)

    def test_rebased_delivery_can_be_cleaned(self):
        self.fixture("rebase")
        self.assertNotEqual(self.git("rev-parse", "main"), self.delivered)
        plan = self.plan()
        self.assert_fully_cleaned(self.apply(plan), plan)

    def test_fork_pr_uses_base_identity_and_deletes_registered_head_remote(self):
        self.fixture(fork=True)
        plan = self.plan()
        self.assertIn("contributor/project", json.dumps(plan["pr"]))
        self.assertIn("acme/project", json.dumps(plan["pr"]))
        self.assert_fully_cleaned(self.apply(plan), plan)
        self.assertEqual(self.git("ls-remote", self.remote, "refs/heads/" + BRANCH), "")
        self.assertTrue(self.git("ls-remote", self.remote, "refs/heads/main"))
        calls = [json.loads(line) for line in self.api_log.read_text().splitlines()]
        self.assertTrue(any("repos/acme/project/pulls/71" in call for call in calls), calls)

    def test_not_merged_and_wrong_pr_identity_never_remove_resources(self):
        self.fixture()
        for change in [{"merged": False, "merged_at": None}, {"id": 9999}]:
            with self.subTest(change=change):
                response = copy.deepcopy(self.pr)
                response.update(change)
                self.write_api(response)
                error = self.cleanup("plan", PR_NUMBER, "--repo", self.repo,
                                     "--index-root", self.index, expected=2)
                self.assertIn("error", error)
                self.assertTrue(self.pr_tree.exists())
                self.assertTrue(self.notes.exists())
                self.assertEqual(self.remote_tip()[0], self.delivered)

    def test_digest_is_the_authorization_boundary(self):
        self.fixture()
        plan = self.plan()
        error = self.cleanup("apply", "--plan", plan["plan_path"],
                             "--approved-digest", "0" * 64, expected=2)
        self.assertIn("error", error)
        self.assertTrue(self.pr_tree.exists())
        self.assertTrue(self.output.exists())
        self.assertEqual(self.remote_tip()[0], self.delivered)

    def test_plan_tampering_does_not_reuse_a_prior_approval(self):
        self.fixture()
        plan = self.plan()
        path = Path(plan["plan_path"])
        document = json.loads(path.read_text())
        foreign = self.root / "foreign-data"
        foreign.mkdir()
        sentinel = foreign / "source.txt"
        sentinel.write_text("Outside the approved cleanup inventory.\n")
        # The mutable journal envelope may legitimately hold progress. Change
        # an actual approved deletion target, rather than irrelevant metadata.
        document["plan"]["items"][0]["path"] = str(foreign)
        path.write_text(json.dumps(document))
        self.apply(plan, expected=2)
        self.assertTrue(self.pr_tree.exists())
        self.assertEqual(self.remote_tip()[0], self.delivered)
        self.assertEqual(sentinel.read_text(), "Outside the approved cleanup inventory.\n")

    def test_remote_drift_after_approval_is_not_deleted_and_can_be_replanned(self):
        self.fixture()
        plan = self.plan()
        # Another actor advances only the remote ref after this plan was shown.
        newer = self.git("rev-parse", "main")
        self.git("push", self.remote, newer + ":refs/heads/" + BRANCH)
        result = self.apply(plan, expected=1)
        self.assertFalse(result["complete"])
        self.assertEqual(self.remote_tip()[0], newer)
        self.assertTrue(self.notes.exists(), "Ledger must survive a partial cleanup")
        self.git("push", "--force-with-lease=refs/heads/" + BRANCH + ":" + newer,
                 self.remote, self.delivered + ":refs/heads/" + BRANCH)
        fresh_plan = self.plan()
        self.assert_fully_cleaned(self.apply(fresh_plan), fresh_plan)

    def test_absent_local_branch_does_not_hide_a_remaining_remote_branch(self):
        self.fixture()
        self.producer("release", "--resource", "pr", "--merged-into", self.delivered,
                      "--idle-confirmed")
        self.git("update-ref", "-d", "refs/heads/" + BRANCH, self.delivered)
        self.assertEqual(self.remote_tip()[0], self.delivered)
        plan = self.plan()
        local = [item for item in plan["items"] if item["kind"] == "local_branch"]
        remote = [item for item in plan["items"] if item["kind"] == "remote_branch"]
        self.assertEqual(len(local), 1, plan)
        self.assertEqual(local[0]["status"], "absent")
        self.assertEqual(len(remote), 1, plan)
        self.assertEqual(remote[0]["status"], "ready")
        self.assert_fully_cleaned(self.apply(plan), plan)

    def test_data_added_after_approval_is_preserved(self):
        self.fixture()
        plan = self.plan()
        new_input = self.output / "new-input.txt"
        new_input.write_text("This input appeared after the inventory was approved.\n")
        result = self.apply(plan, expected=1)
        self.assertFalse(result["complete"])
        self.assertEqual(new_input.read_text(),
                         "This input appeared after the inventory was approved.\n")
        self.assertTrue((self.state / "state.json").exists())

    def test_data_added_after_sealing_is_not_adopted_by_a_new_inventory(self):
        self.fixture()
        personal = self.output / "personal-input.csv"
        personal.write_text("Subsequent personal work,retain\n")
        plan = self.plan()
        data = [item for item in plan["items"] if item["kind"] == "data"
                and item.get("resource") == "output"]
        self.assertEqual(len(data), 1, plan)
        self.assertEqual(data[0]["status"], "blocked", data)
        result = self.apply(plan, expected=1)
        self.assertFalse(result["complete"])
        self.assertEqual(personal.read_text(), "Subsequent personal work,retain\n")
        self.assertTrue((self.state / "state.json").exists())

    def test_interrupted_record_purge_does_not_forget_a_recreated_recovery_ref(self):
        self.fixture()
        plan = self.plan()
        spec = importlib.util.spec_from_file_location("cleanup_fault_injection", TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        helper = module.resource_tool(RESOURCE_TOOL)
        original_rmtree = module.shutil.rmtree
        injected = {"hit": False}

        def fail_first_notes_removal(path, *args, **kwargs):
            if Path(path) == self.notes and not injected["hit"]:
                injected["hit"] = True
                raise OSError("Fixture disk failure before final notes removal")
            return original_rmtree(path, *args, **kwargs)

        fail_first_notes_removal.avoids_symlink_attacks = original_rmtree.avoids_symlink_attacks
        args = SimpleNamespace(plan=plan["plan_path"], approved_digest=plan["plan_sha256"])
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(module.shutil, "rmtree", fail_first_notes_removal):
            first = module.apply_command(args, helper)
        self.assertTrue(injected["hit"])
        self.assertFalse(first["complete"], first)
        journal_path = Path(plan["plan_path"])
        journal = json.loads(journal_path.read_text())
        self.assertEqual(journal["stage"], "purging_records")
        ref = next(item["ref"] for item in plan["items"] if item["kind"] == "internal_ref")
        self.assertEqual(self.git("for-each-ref", "--format=%(objectname)", ref), "")
        self.git("update-ref", ref, self.delivered)
        # Recovery must revisit original objects, even though the previous
        # attempt had already reached final record removal.
        fresh = self.cleanup("plan", PR_NUMBER, "--repo", self.repo,
                             "--index-root", self.index, "--idle-resource", "pr",
                             "--idle-resource", "output", "--notes-idle", expected=None)
        if "error" in fresh:
            self.assertIn(ref, fresh["error"], fresh)
        else:
            refs = [item for item in fresh["items"] if item.get("ref") == ref]
            self.assertEqual(len(refs), 1, fresh)
            self.assertIn(refs[0]["status"], ["ready", "blocked"], refs)
            if refs[0]["status"] == "ready":
                # A recreated ref at the registered OID may be explicitly
                # approved again. Completion requires deleting it in reality.
                self.assertEqual(refs[0]["expected_oid"], self.delivered)
                self.assert_fully_cleaned(self.apply(fresh), fresh)
                self.assertEqual(self.git("for-each-ref", "--format=%(objectname)", ref), "")
                return
            resumed = self.apply(fresh, expected=1)
            self.assertFalse(resumed["complete"], resumed)
        self.assertEqual(self.git("rev-parse", ref), self.delivered)
        self.assertTrue((self.state / "state.json").exists())
        self.assertTrue(journal_path.exists())

    def test_failed_plan_cannot_be_applied_again_with_its_old_approval(self):
        self.fixture()
        plan = self.plan()
        newer = self.git("rev-parse", "main")
        self.git("push", self.remote, newer + ":refs/heads/" + BRANCH)
        first = self.apply(plan, expected=1)
        self.assertFalse(first["complete"])
        self.assertEqual(self.remote_tip()[0], newer)
        # Restoring the old ref value does not make a previously used approval
        # valid again. Only a fresh displayed inventory can authorize retries.
        self.git("push", "--force-with-lease=refs/heads/" + BRANCH + ":" + newer,
                 self.remote, self.delivered + ":refs/heads/" + BRANCH)
        second = self.apply(plan, expected=2)
        self.assertIn("error", second)
        self.assertEqual(self.remote_tip()[0], self.delivered)
        self.assertTrue(self.notes.exists())
        fresh_plan = self.plan()
        self.assert_fully_cleaned(self.apply(fresh_plan), fresh_plan)

    def test_dirty_untracked_and_ignored_content_is_preserved(self):
        self.fixture()
        (self.pr_tree / "source.txt").write_text("unsaved work\n")
        (self.pr_tree / "personal.txt").write_text("private untracked work\n")
        generated = self.pr_tree / "generated"
        generated.mkdir()
        (generated / "secret.env").write_text("valuable ignored input\n")
        plan = self.plan()
        matching = [item for item in plan["items"] if item.get("resource") == "pr"
                    and item["kind"] == "worktree"]
        self.assertEqual(len(matching), 1, plan)
        self.assertEqual(matching[0]["status"], "blocked", matching)
        self.apply(plan, expected=1)
        self.assertEqual((self.pr_tree / "source.txt").read_text(), "unsaved work\n")
        self.assertEqual((self.pr_tree / "personal.txt").read_text(), "private untracked work\n")
        self.assertEqual((generated / "secret.env").read_text(), "valuable ignored input\n")
        self.assertTrue(self.notes.exists())

    def test_foreign_resource_at_owned_path_is_not_adopted_or_deleted(self):
        self.fixture()
        old_output = self.root / "retained-original-output"
        self.output.rename(old_output)
        self.output.mkdir()
        sentinel = self.output / "foreign.txt"
        sentinel.write_text("belongs to another task\n")
        plan = self.plan()
        self.apply(plan, expected=1)
        self.assertEqual(sentinel.read_text(), "belongs to another task\n")
        self.assertTrue(old_output.exists())
        self.assertTrue(self.notes.exists())

    def test_unsaved_work_added_after_approval_is_preserved(self):
        self.fixture()
        plan = self.plan()
        sentinel = self.pr_tree / "new-work.txt"
        sentinel.write_text("Created after the cleanup list was approved.\n")
        result = self.apply(plan, expected=1)
        self.assertFalse(result["complete"])
        self.assertEqual(sentinel.read_text(), "Created after the cleanup list was approved.\n")
        self.assertTrue(self.notes.exists())

    def test_new_local_commit_after_approval_is_preserved(self):
        self.fixture()
        plan = self.plan()
        (self.pr_tree / "next-task.txt").write_text("A new local delivery.\n")
        self.git("add", "next-task.txt", cwd=self.pr_tree)
        self.git("commit", "-m", "next task", cwd=self.pr_tree)
        newer = self.git("rev-parse", "HEAD", cwd=self.pr_tree)
        self.apply(plan, expected=1)
        self.assertTrue(self.pr_tree.exists())
        self.assertEqual(self.git("rev-parse", BRANCH), newer)
        self.assertEqual(self.git("show", BRANCH + ":next-task.txt"), "A new local delivery.")

    def test_files_added_to_notes_after_sealing_block_final_note_deletion(self):
        self.fixture()
        foreign = self.notes / "another-task.txt"
        foreign.write_text("This was not sealed invocation evidence.\n")
        plan = self.plan()
        notes = [item for item in plan["items"] if item["kind"] == "notes"]
        self.assertEqual(len(notes), 1, plan)
        self.assertEqual(notes[0]["status"], "blocked", notes)
        result = self.apply(plan, expected=1)
        self.assertFalse(result["complete"])
        self.assertEqual(foreign.read_text(), "This was not sealed invocation evidence.\n")
        self.assertFalse(self.output.exists(), "Independent eligible data should still be released")

    def test_missing_idle_confirmation_retains_resources_and_allows_safe_items(self):
        self.fixture()
        plan = self.plan(idle=("output",), notes_idle=False)
        tree = [item for item in plan["items"] if item["kind"] == "worktree"]
        self.assertEqual(tree[0]["status"], "blocked", tree)
        result = self.apply(plan, expected=1)
        self.assertFalse(result["complete"])
        self.assertTrue(self.pr_tree.exists())
        self.assertTrue(self.notes.exists())
        self.assertFalse(self.output.exists())
        fresh_plan = self.plan()
        self.assert_fully_cleaned(self.apply(fresh_plan), fresh_plan)

    def test_a_running_command_is_not_stopped_by_cleanup(self):
        self.fixture(seal=False)
        ready, stop = self.root / "ready", self.root / "stop"
        code = ("from pathlib import Path; import sys,time; "
                "ready=Path(sys.argv[1]); stop=Path(sys.argv[2]); ready.write_text('ready'); "
                "\nwhile not stop.exists(): time.sleep(0.02)\n")
        command = [sys.executable, RESOURCE_TOOL, "run", "--state", self.state,
                   "--id", "active", "--cwd-resource", "pr", "--output-resource", "output",
                   "--", sys.executable, "-c", code, ready, stop]
        process = subprocess.Popen(list(map(str, command)), cwd=self.repo, env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "Fixture command failed to start")
            self.producer("seal", "--pr-json", self.api_file)
            # The wrapper marks both resources active. A cleanup invocation may
            # report them, but its idle flags must never authorize killing them.
            plan = self.plan()
            self.apply(plan, expected=1)
            self.assertIsNone(process.poll(), "Cleanup stopped the running command")
            self.assertTrue(self.pr_tree.exists())
            self.assertTrue(self.output.exists())
            self.assertTrue((self.state / "state.json").exists())
            ledger = self.producer("status")
            active = [run for run in ledger["runs"] if run["id"] == "active"]
            self.assertEqual(active[0]["status"], "running", ledger)
        finally:
            stop.write_text("stop")
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stdout + stderr)

    def test_unregistered_historical_pr_is_audit_only(self):
        self.fixture()
        # Move the disposable registry out of discovery; no other artifact is
        # allowed to become implicitly owned just because its name matches.
        self.index.rename(self.root / "hidden-index")
        plan = self.plan()
        self.assertTrue(plan["audit_only"], plan)
        self.assertEqual(plan["items"], [])
        self.assertTrue(self.pr_tree.exists())
        self.assertTrue(self.notes.exists())
        self.assertEqual(self.remote_tip()[0], self.delivered)


if __name__ == "__main__":
    unittest.main()
