#!/usr/bin/env python3
"""Plan and perform explicitly approved post-merge cleanup of one invocation.

Python standard library, Git, GitHub CLI, and the implement-spec-v2 resource
helper are required. Production approval belongs to the human displaying the
plan; the digest binds that approval to the exact inventory, not to a PR number.
"""

import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace
import urllib.parse
import uuid

PROTOCOL = "cleanup-spec-v2/1"


class Refusal(Exception):
    pass


def resource_tool(value=None):
    path = Path(value) if value else Path(__file__).resolve().parents[2] / "implement-spec-v2/scripts/resources.py"
    if not path.is_file():
        raise Refusal("implement-spec-v2 helper unavailable; supply --resource-tool with its installed path")
    spec = importlib.util.spec_from_file_location("implement_spec_resources", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = ["data_fingerprint", "mount_points", "is_mount_path"]
    if getattr(module, "CLEANUP_PROTOCOL", None) != PROTOCOL or any(not hasattr(module, name) for name in required):
        raise Refusal("implement-spec-v2 helper is outdated; update both skills before cleanup")
    return module


def file_identity(path):
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise Refusal("not an ordinary file: " + str(path))
    return [info.st_dev, info.st_ino]


def index_root(value=None):
    if value:
        return Path(value)
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "implement-spec-v2"


def repo_context(r, value):
    repo = r.plain_path(str(value))
    repo = Path(r.git_text(repo, "rev-parse", "--show-toplevel")).resolve()
    common = Path(r.git_text(repo, "rev-parse", "--git-common-dir"))
    common = (repo / common).resolve() if not common.is_absolute() else common.resolve()
    return repo, common


def gh_json(host, endpoint):
    result = subprocess.run(["gh", "api", "--hostname", host, endpoint],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise Refusal("GitHub query failed; retain resources: " + result.stderr.strip())
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise Refusal("GitHub returned invalid JSON")


def verify_pr(metadata):
    host = metadata["host"]
    fullname = metadata["base_repo"]["full_name"]
    if not host or any(c in host for c in "/\\\n\r") or fullname.count("/") != 1:
        raise Refusal("invalid registered GitHub identity")
    result = gh_json(host, "repos/{}/pulls/{}".format(fullname, metadata["number"]))
    if not isinstance(result, dict):
        raise Refusal("GitHub returned no PR identity")
    comparisons = [(result.get("id"), metadata["id"]),
                   (result.get("number"), metadata["number"]),
                   (result.get("base", {}).get("repo", {}).get("id"), metadata["base_repo"]["id"])]
    head_repo = result.get("head", {}).get("repo") or {}
    comparisons.append((head_repo.get("id"), metadata["head_repo"]["id"]))
    if any(left != right for left, right in comparisons):
        raise Refusal("live PR/repository identity differs from invocation handoff")
    url = urllib.parse.urlparse(result.get("html_url", ""))
    if url.hostname != host or result.get("head", {}).get("ref") != metadata["head_ref"]:
        raise Refusal("live PR host/head ref differs from invocation handoff")
    for side in ["head", "base"]:
        repository = result.get(side, {}).get("repo") or {}
        expected = metadata[side + "_repo"]
        if repository.get("full_name") != expected["full_name"] or repository.get("clone_url") != expected["clone_url"]:
            raise Refusal("repository destination changed; regenerate a verified handoff before deletion")
    if result.get("merged") is not True or not result.get("merged_at"):
        raise Refusal("PR has not been confirmed merged; closed/queued is insufficient")
    return result


def ref_oid(r, repo, ref):
    result = r.git(repo, "rev-parse", "--verify", "--quiet", ref, check=False)
    if result.returncode == 1:
        return None
    if result.returncode:
        raise Refusal("cannot inspect ref " + ref + ": " + result.stderr.decode(errors="replace").strip())
    return result.stdout.decode().strip()


def remote_oid(r, repo, remote, ref):
    result = r.git(repo, "ls-remote", "--refs", "--", remote, ref)
    rows = [line.split("\t") for line in result.stdout.decode().splitlines()]
    values = [row[0] for row in rows if len(row) == 2 and row[1] == ref]
    if len(values) > 1:
        raise Refusal("remote ref is not unique")
    return values[0] if values else None


def used_branches(r, repo):
    rows = r.git_text(repo, "worktree", "list", "--porcelain").splitlines()
    return {row[7:] for row in rows if row.startswith("branch ")}


def processes_using(r, paths):
    """Linux visibility is supplementary; independent owner idle proof is required."""
    matches = []
    proc = Path("/proc")
    if not proc.is_dir():
        return matches
    paths = [Path(p) for p in paths]
    for directory in proc.iterdir():
        if not directory.name.isdigit():
            continue
        probes = [directory / "cwd"]
        try:
            probes.extend((directory / "fd").iterdir())
        except OSError:
            pass
        for probe in probes:
            try:
                value = os.readlink(probe)
                observed = Path(value.removesuffix(" (deleted)"))
                if observed.is_absolute() and any(r.within(observed, p) for p in paths):
                    matches.append({"pid": int(directory.name), "path": str(observed)})
                    break
            except OSError:
                continue
    return matches


def tree_snapshot(r, root, excludes=()):
    root = r.plain_path(str(root))
    device = os.lstat(root).st_dev
    excluded = [Path(x) for x in excludes]
    entries = []
    mounts = r.mount_points()
    for current, dirs, files in os.walk(root, followlinks=False):
        current = Path(current)
        keep = []
        for name in sorted(dirs + files):
            path = current / name
            if any(r.within(path, skip) for skip in excluded):
                continue
            info = os.lstat(path)
            if info.st_dev != device or r.is_mount_path(path, mounts):
                raise Refusal("directory contains nested mount: " + str(path))
            if stat.S_ISLNK(info.st_mode):
                raise Refusal("unclassified symlink in records: " + str(path))
            row = {"path": str(path.relative_to(root)), "identity": [info.st_dev, info.st_ino]}
            if stat.S_ISDIR(info.st_mode):
                row["type"] = "directory"
                keep.append(name)
            elif stat.S_ISREG(info.st_mode):
                row.update(type="file", sha256=r.digest(path))
            else:
                raise Refusal("unclassified special file in records: " + str(path))
            entries.append(row)
        dirs[:] = keep
    return sorted(entries, key=lambda row: row["path"])


def snapshot_matches(r, root, expected, excludes=(), allow_missing=False):
    actual = tree_snapshot(r, root, excludes)
    known = {row["path"]: row for row in expected}
    if any(row != known.get(row["path"]) for row in actual):
        raise Refusal("record contents/identity changed or unregistered files were added")
    if not allow_missing and len(actual) != len(known):
        raise Refusal("registered record files disappeared")


def checked_notes(r, state, handoff):
    notes = handoff["notes"]
    root = r.plain_path(notes["path"])
    if r.identity(root) != notes["identity"]:
        raise Refusal("notes directory identity changed")
    if r.load_json(root / ".implement-spec-notes", 4096) != notes["marker"]:
        raise Refusal("notes ownership marker changed")
    exclusions = [state["state_path"]]
    exclusions.extend(item["path"] for item in state["resources"].values() if item["status"] != "released")
    snapshot = handoff["notes_snapshot"]
    if snapshot.get("blockers"):
        raise Refusal("notes contained unclassified material when sealed")
    snapshot_matches(r, root, snapshot["entries"], exclusions)
    # Only ledger-owned record generations and protocol files belong here.
    state_path = Path(state["state_path"])
    allowed = {"lock", "state.json", "handoff.json", "records"}
    for entry in state_path.iterdir():
        if entry.name not in allowed or entry.is_symlink():
            raise Refusal("unregistered material in resource state: " + str(entry))
    generations = set()
    for run in state["runs"].values():
        for number in range(1, run.get("record_generation", 0) + 1):
            generations.add("{}.{}.json".format(run["id"], number))
    for entry in (state_path / "records").iterdir():
        if entry.name not in generations or entry.is_symlink() or not entry.is_file():
            raise Refusal("unregistered material in compact records: " + str(entry))
    r.check_data_tree(root)
    return root


def load_handoff(r, index, common):
    if index.get("protocol") != PROTOCOL or index.get("common_git") != str(common):
        raise Refusal("index is not a new-protocol invocation for this repository")
    state_path = r.plain_path(index["state"]["path"])
    with r.locked(state_path) as (_, state):
        state = copy.deepcopy(state)
    if state["common_git"] != str(common) or state["invocation"] != index["invocation"]:
        raise Refusal("ledger/index repository identity mismatch")
    pointer = index.get("handoff")
    if not pointer:
        raise Refusal("invocation is not sealed; preserve its resources")
    handoff_path = r.plain_path(pointer["path"])
    if handoff_path != state_path / "handoff.json" or file_identity(handoff_path) != pointer["identity"]:
        raise Refusal("handoff file identity changed")
    if r.digest(handoff_path) != pointer["sha256"]:
        raise Refusal("handoff file contents changed")
    handoff = r.load_json(handoff_path)
    if handoff.get("protocol") != PROTOCOL or handoff.get("invocation") != state["invocation"]:
        raise Refusal("handoff protocol/invocation mismatch")
    if handoff.get("state_identity") != state["identity"] or handoff.get("common_git") != str(common):
        raise Refusal("handoff state/repository identity mismatch")
    return state, handoff


def row(kind, item_id, resource=None, **values):
    return dict(id=item_id, kind=kind, resource=resource, status="ready", reasons=[], **values)


def block(item, error):
    item["status"] = "blocked"
    item["reasons"].append(str(error))


def ancestor(r, repo, head, target):
    return r.git(repo, "merge-base", "--is-ancestor", head, target, check=False).returncode == 0


def clean_worktree(r, path, removable_children):
    raw = r.git(path, "status", "--porcelain", "-z", "--untracked-files=all").stdout
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        status = entry[:2]
        filename = entry[3:].decode(errors="surrogateescape")
        candidate = Path(path) / filename
        if status == b"??" and any(r.within(candidate, p) for p in removable_children):
            continue
        raise Refusal("worktree has dirty/untracked files")
    raw = r.git(path, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").stdout
    for entry in raw.split(b"\0"):
        if entry and not any(r.within(Path(path) / entry.decode(errors="surrogateescape"), p) for p in removable_children):
            raise Refusal("worktree contains unclassified ignored files")


def inventory(r, repo, state, handoff, live_pr, idle_resources, notes_idle):
    items = []
    worktrees = {item["resource"]: item for item in handoff["worktrees"]}
    sealed_data = {item["resource"]: item for item in handoff.get("data", [])}
    delivery = handoff["delivery_oid"]
    delivered = live_pr.get("head", {}).get("sha") == delivery
    projected = copy.deepcopy(state)
    resources = sorted(state["resources"].values(), key=lambda item: len(Path(item["path"]).parts), reverse=True)
    for resource in resources:
        name = resource["id"]
        item = row(resource["kind"], "resource:" + name, name, path=resource["path"],
                   identity=resource.get("identity"), expected_oid=worktrees.get(name, {}).get("expected_oid"))
        items.append(item)
        path = Path(resource["path"])
        try:
            if resource["status"] == "released":
                if os.path.lexists(path):
                    raise Refusal("released resource path was recreated; preserve replacement")
                item["status"] = "absent"
                continue
            reasons = r.release_blockers(Path(state["state_path"]), projected, name)
            if reasons:
                raise Refusal("; ".join(reasons))
            if resource["status"] not in ["active", "releasing"]:
                raise Refusal("resource has an incomplete creation/operation")
            if not os.path.lexists(path):
                if resource["kind"] == "worktree" and "worktree " + str(path) in r.git_text(repo, "worktree", "list", "--porcelain").splitlines():
                    raise Refusal("missing worktree remains registered; investigate manually")
                item["status"] = "absent"
                projected["resources"][name]["status"] = "released"
                continue
            r.verify_resource(state, dict(resource, status="active"))
            if name not in idle_resources:
                raise Refusal("external inactivity not independently confirmed")
            active = processes_using(r, [path])
            if active:
                item["processes"] = active
                raise Refusal("resource is still in use by a process")
            if resource["kind"] == "worktree":
                if not delivered:
                    raise Refusal("live PR head does not match sealed delivery; merge proof incomplete")
                if r.git_text(path, "rev-parse", "HEAD") != item["expected_oid"]:
                    raise Refusal("worktree gained commits after sealing")
                if resource["role"] not in ["scratch", "checkpoint"] and not ancestor(r, repo, item["expected_oid"], delivery):
                    raise Refusal("worktree revision is outside the delivered PR history")
                children = [Path(c["path"]) for c in resources if c.get("parent") == name and projected["resources"][c["id"]]["status"] == "released"]
                clean_worktree(r, path, children)
            else:
                r.check_data_tree(path)
                if not shutil.rmtree.avoids_symlink_attacks:
                    raise Refusal("safe directory deletion is unavailable")
                baseline = sealed_data.get(name)
                if not baseline or not baseline.get("contents_sha256"):
                    raise Refusal("data has no verified sealed contents; return it to its owner")
                item["contents_sha256"] = r.data_fingerprint(state, resource)
                if item["contents_sha256"] != baseline["contents_sha256"]:
                    raise Refusal("data changed since the development handoff; preserve new work")
            projected["resources"][name]["status"] = "released"
        except (r.Refusal, Refusal, OSError, KeyError) as error:
            block(item, error)
    pending = any(item["status"] == "blocked" for item in items)
    branches_in_use = used_branches(r, repo)
    for branch in handoff["branches"]:
        item = row("local_branch", "branch:" + branch["ref"], branch["resource"],
                   ref=branch["ref"], expected_oid=branch["expected_oid"])
        items.append(item)
        try:
            oid = ref_oid(r, repo, item["ref"])
            if oid is None:
                item["status"] = "absent"
            elif oid != item["expected_oid"]:
                raise Refusal("local branch changed after sealing")
            elif not delivered:
                raise Refusal("live PR head differs from sealed delivery")
            if oid is not None:
                source = state["resources"][branch["resource"]]
                if oid != worktrees[branch["resource"]]["expected_oid"]:
                    raise Refusal("branch differs from its recorded worktree delivery")
                if source["role"] not in ["scratch", "checkpoint"] and not ancestor(r, repo, oid, delivery):
                    raise Refusal("branch contains work outside the delivered PR history")
            if oid is not None and item["ref"] in branches_in_use:
                # Owned removable worktrees will be gone before this operation.
                owned = {"refs/heads/" + c["branch"] for c in resources if c.get("branch") and projected["resources"][c["id"]]["status"] == "released"}
                other_worktrees = r.git_text(repo, "worktree", "list", "--porcelain").split("\n\n")
                for tree in other_worktrees:
                    if "branch " + item["ref"] in tree.splitlines():
                        location = next(line[9:] for line in tree.splitlines() if line.startswith("worktree "))
                        if not any(str(c["path"]) == location and projected["resources"][c["id"]]["status"] == "released" for c in resources):
                            raise Refusal("branch is checked out in a retained/shared worktree")
                if item["ref"] not in owned:
                    raise Refusal("branch remains checked out")
            if oid is not None and pending and item["ref"] == "refs/heads/" + handoff["pr"]["head_ref"]:
                raise Refusal("delivery branch is still needed by retained resources")
        except (r.Refusal, Refusal, OSError) as error:
            block(item, error)
        publication = branch.get("publication")
        if publication:
            remote = row("remote_branch", "remote:" + publication["remote_ref"], branch["resource"],
                         ref=publication["remote_ref"], remote_url=publication["remote_url"],
                         expected_oid=publication.get("expected_oid"))
            items.append(remote)
            try:
                if publication.get("status") != "created" or not remote["expected_oid"]:
                    raise Refusal("remote branch creation/delivery was not recorded")
                if remote["remote_url"] != handoff["pr"]["head_repo"]["clone_url"] or remote["ref"] != branch["ref"]:
                    raise Refusal("remote destination is outside the registered PR head repository")
                oid = remote_oid(r, repo, remote["remote_url"], remote["ref"])
                if oid is None:
                    remote["status"] = "absent"
                elif oid != remote["expected_oid"]:
                    raise Refusal("remote branch changed after sealing")
                elif item["status"] == "blocked":
                    raise Refusal("paired local branch has unverified work or is still in use")
                elif not delivered:
                    raise Refusal("live PR head differs from sealed delivery")
                elif pending:
                    raise Refusal("remote branch retained until owned resources are released")
            except (r.Refusal, Refusal, OSError) as error:
                block(remote, error)
    # A guarded release can create this anchor after the plan was displayed.
    refs = {x["ref"]: x for x in handoff["internal_refs"]}
    for tree in handoff["worktrees"]:
        ref = "refs/implement-spec-runs/{}/{}".format(handoff["invocation"], tree["resource"])
        refs.setdefault(ref, dict(resource=tree["resource"], ref=ref, expected_oid=tree["expected_oid"]))
    for expected in refs.values():
        item = row("internal_ref", "ref:" + expected["ref"], expected["resource"],
                   ref=expected["ref"], expected_oid=expected["expected_oid"])
        items.append(item)
        try:
            actual = ref_oid(r, repo, item["ref"])
            if actual is not None and actual != item["expected_oid"]:
                raise Refusal("recovery ref changed after sealing")
            if pending:
                raise Refusal("recovery refs retained for blocked resources")
            # Expected-to-be-created refs are included in the approved inventory.
            if actual is None and not any(i["kind"] == "worktree" and i["resource"] == item["resource"] and i["status"] == "ready" for i in items):
                item["status"] = "absent"
        except (r.Refusal, Refusal, OSError) as error:
            block(item, error)
    notes = row("notes", "notes", path=handoff["notes"]["path"], identity=handoff["notes"]["identity"])
    try:
        checked_notes(r, state, handoff)
        if not notes_idle:
            raise Refusal("notes inactivity not independently confirmed")
        active = processes_using(r, [notes["path"]])
        if active:
            notes["processes"] = active
            raise Refusal("notes are still in use by a process")
        for run in state["runs"].values():
            if run["status"] != "completed":
                raise Refusal("ledger contains active/unknown command " + run["id"])
        if any(i["status"] == "blocked" for i in items):
            raise Refusal("records needed to resume blocked resources/refs")
    except (r.Refusal, Refusal, OSError) as error:
        block(notes, error)
    items.append(notes)
    return items


def find_index(r, root, common, number):
    directory = r.plain_path(str(root)) / hashlib.sha256(str(common).encode()).hexdigest()
    if not directory.is_dir():
        return directory, None
    matches = []
    for path in directory.glob("*.json"):
        candidate = r.load_json(path)
        if candidate.get("protocol") == PROTOCOL and "state" in candidate and candidate.get("pr", {}).get("number") == number:
            matches.append((path, candidate))
    if len(matches) > 1:
        raise Refusal("PR number matches multiple invocations; supply the intended repository context")
    return directory, matches[0] if matches else None


def journal_digest(r, plan):
    return hashlib.sha256(r.encode(plan)).hexdigest()


def write_journal(r, path, journal):
    r.atomic_json(path, journal)


@contextlib.contextmanager
def execution_lock(directory):
    """Lock the stable index directory, without creating a residual lock file."""
    try:
        import fcntl
    except ImportError:
        raise Refusal("platform lacks directory locking; retain resources")
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refusal("another cleanup is using this index; retain resources")
        yield
    finally:
        os.close(descriptor)


def plan_command(args, r):
    repo, common = repo_context(r, args.repo)
    directory, match = find_index(r, index_root(args.index_root), common, args.number)
    if match is None:
        if directory.is_dir():
            journals = []
            for candidate in directory.glob("cleanup-*.json"):
                value = r.load_json(candidate)
                if value.get("stage") == "purging_records" and value.get("plan", {}).get("pr", {}).get("number") == args.number:
                    journals.append((candidate, value))
            if len(journals) > 1:
                raise Refusal("multiple recovery journals match this PR number")
            if journals:
                with execution_lock(directory):
                    return resume_plan(args, r, *journals[0], repo, common)
        return {"audit_only": True, "items": [], "pr_number": args.number,
                "repository": str(repo), "reasons": ["No unique new-protocol handoff. Historical tasks are audit-only; no resources are adopted or deleted."],
                "observed_worktrees": r.git_text(repo, "worktree", "list", "--porcelain")}
    with execution_lock(directory):
        return indexed_plan(args, r, repo, common, directory, match)


def indexed_plan(args, r, repo, common, directory, match):
    path, index = match
    journal_path = directory / ("cleanup-" + index["invocation"] + ".json")
    if journal_path.exists():
        prior = r.load_json(journal_path)
        if prior.get("stage") == "purging_records":
            return resume_plan(args, r, journal_path, prior, repo, common)
    state, handoff = load_handoff(r, index, common)
    live = verify_pr(handoff["pr"])
    items = inventory(r, repo, state, handoff, live, set(args.idle_resource), args.notes_idle)
    index_item = row("index", "index", path=str(path), identity=file_identity(path), sha256=r.digest(path))
    journal_item = row("journal", "journal", path=str(journal_path))
    if any(item["status"] == "blocked" for item in items):
        block(index_item, "index retained to locate unfinished cleanup")
        block(journal_item, "journal retained to resume unfinished cleanup")
    items.extend([index_item, journal_item])
    plan = {"protocol": PROTOCOL, "nonce": uuid.uuid4().hex, "created_at": r.now(),
            "invocation": handoff["invocation"], "repo": str(repo), "common_git": str(common),
            "common_git_identity": r.identity(common), "index_path": str(path), "index": index,
            "journal_path": str(journal_path), "journal_parent_identity": r.identity(directory),
            "handoff": handoff, "handoff_pointer": index["handoff"], "pr": handoff["pr"],
            "merged_at": live["merged_at"], "items": items,
            "idle_resources": sorted(set(args.idle_resource)), "notes_idle": args.notes_idle}
    journal = {"plan": plan, "progress": {}, "stage": "resources"}
    write_journal(r, journal_path, journal)
    return dict(plan, plan_path=str(journal_path), plan_sha256=journal_digest(r, plan))


def resume_plan(args, r, path, journal, repo, common):
    plan = journal["plan"]
    if plan["common_git"] != str(common) or plan["common_git_identity"] != r.identity(common):
        raise Refusal("recovery journal repository identity changed")
    verify_pr(plan["pr"])
    root = Path(plan["handoff"]["notes"]["path"])
    if root.exists():
        if r.identity(root) != plan["handoff"]["notes"]["identity"]:
            raise Refusal("partially purged notes path was replaced")
        snapshot_matches(r, root, journal["purge_snapshot"], allow_missing=True)
        if not args.notes_idle or processes_using(r, [root]):
            raise Refusal("remaining notes are not independently confirmed idle")
    journal.setdefault("original_items", copy.deepcopy(plan["items"]))
    remaining = recovery_inventory(r, plan, journal, repo)
    plan.update(nonce=uuid.uuid4().hex, created_at=r.now(), items=remaining, notes_idle=args.notes_idle)
    journal.pop("attempt_started_at", None)
    journal["progress"] = {}
    write_journal(r, path, journal)
    return dict(plan, plan_path=str(path), plan_sha256=journal_digest(r, plan))


def recovery_inventory(r, plan, journal, repo):
    result = []
    for original in journal["original_items"]:
        item = copy.deepcopy(original)
        item.update(status="absent", reasons=[])
        result.append(item)
        try:
            if item["kind"] in ["data", "worktree"]:
                if os.path.lexists(item["path"]):
                    raise Refusal("previously released resource path reappeared; preserve new work")
            elif item["kind"] in ["local_branch", "internal_ref", "remote_branch"]:
                actual = remote_oid(r, repo, item["remote_url"], item["ref"]) if item["kind"] == "remote_branch" else ref_oid(r, repo, item["ref"])
                if actual is not None:
                    if item["kind"] == "internal_ref" and actual == item["expected_oid"]:
                        item["status"] = "ready"
                    else:
                        raise Refusal("previously released ref reappeared or changed; ownership must be re-established")
            elif item["kind"] == "index":
                if os.path.lexists(item["path"]):
                    if file_identity(Path(item["path"])) != item["identity"] or r.digest(Path(item["path"])) != item["sha256"]:
                        raise Refusal("cleanup index was replaced")
                    item["status"] = "ready"
            else:
                if item["kind"] == "journal" or os.path.lexists(item["path"]):
                    item["status"] = "ready"
        except (r.Refusal, Refusal, OSError) as error:
            block(item, error)
    if any(item["status"] == "blocked" for item in result):
        for item in result:
            if item["kind"] in ["notes", "index", "journal"] and item["status"] != "absent":
                block(item, "records remain needed by reappeared/changed objects")
    return result


def verify_released_objects(r, plan, journal, repo):
    for item in journal.get("original_items", plan["items"]):
        if item["kind"] in ["data", "worktree"] and os.path.lexists(item["path"]):
            raise Refusal("released resource reappeared: " + item["path"])
        if item["kind"] in ["local_branch", "internal_ref", "remote_branch"]:
            actual = remote_oid(r, repo, item["remote_url"], item["ref"]) if item["kind"] == "remote_branch" else ref_oid(r, repo, item["ref"])
            if actual is not None:
                raise Refusal("released ref remains present: " + item["ref"])


def validate_plan(r, path, journal, approved):
    plan = journal["plan"]
    if plan.get("protocol") != PROTOCOL or journal_digest(r, plan) != approved:
        raise Refusal("approval digest does not match the displayed plan")
    if str(path) != plan["journal_path"] or r.identity(path.parent) != plan["journal_parent_identity"]:
        raise Refusal("cleanup journal location/identity changed")
    repo, common = repo_context(r, plan["repo"])
    if str(common) != plan["common_git"] or r.identity(common) != plan["common_git_identity"]:
        raise Refusal("repository Git identity changed")
    verify_pr(plan["pr"])
    return plan, repo, common


def save_result(r, path, journal, item, status, reason=None):
    result = {"id": item["id"], "kind": item["kind"], "status": status}
    if reason:
        result["reason"] = str(reason)
    journal["progress"][item["id"]] = result
    write_journal(r, path, journal)
    return result


def apply_resource(r, plan, item):
    with r.locked(plan["handoff"]["state_path"]) as (state_path, state):
        source = state["resources"][item["resource"]]
        if source["status"] == "released":
            if os.path.lexists(source["path"]):
                raise Refusal("released resource path has been recreated")
            return "already_absent"
        if not os.path.lexists(source["path"]):
            blockers = r.release_blockers(state_path, state, item["resource"])
            if blockers:
                raise Refusal("; ".join(blockers))
            if source["kind"] == "worktree" and "worktree " + source["path"] in r.git_text(plan["repo"], "worktree", "list", "--porcelain").splitlines():
                raise Refusal("missing worktree remains registered")
            source["status"] = "released"
            source["released_at"] = r.now()
            r.save(state_path, state)
            return "already_absent"
        if source.get("identity") != item["identity"]:
            raise Refusal("resource differs from the approved inventory")
        r.verify_resource(state, dict(source, status="active"))
        if source["status"] != "active":
            raise Refusal("resource has a transitional operation; retain and investigate")
        if processes_using(r, [source["path"]]):
            raise Refusal("resource became active after confirmation")
        if item["kind"] == "worktree" and r.git_text(source["path"], "rev-parse", "HEAD") != item["expected_oid"]:
            raise Refusal("worktree HEAD changed after confirmation")
        if item["kind"] == "data" and r.data_fingerprint(state, source) != item.get("contents_sha256"):
            raise Refusal("data contents changed after confirmation; display a fresh plan")
    scratch = source["kind"] == "worktree" and source["role"] in ["scratch", "checkpoint"]
    r.release(SimpleNamespace(state=plan["handoff"]["state_path"], resource=item["resource"],
                              idle_confirmed=True, merged_into=plan["handoff"]["delivery_oid"] if item["kind"] == "worktree" and not scratch else None))
    return "deleted"


def apply_ref(r, plan, repo, item, recovering=False):
    pending = False
    if not recovering:
        with r.locked(plan["handoff"]["state_path"]) as (_, state):
            pending = any(resource["status"] != "released" for resource in state["resources"].values())
    delivery_branch = item.get("ref") == "refs/heads/" + plan["pr"]["head_ref"]
    if pending and (item["kind"] in ["remote_branch", "internal_ref"] or delivery_branch):
        raise Refusal("ref remains needed by resources that were not released")
    if item["kind"] == "remote_branch":
        actual = remote_oid(r, repo, item["remote_url"], item["ref"])
        if actual is None:
            return "already_absent"
        if item["status"] == "absent":
            raise Refusal("remote ref appeared after the displayed plan")
        if actual != item["expected_oid"]:
            raise Refusal("remote branch changed after confirmation")
        r.git(repo, "push", "--porcelain", "--force-with-lease={}:{}".format(item["ref"], item["expected_oid"]),
              "--", item["remote_url"], ":" + item["ref"])
    else:
        actual = ref_oid(r, repo, item["ref"])
        if actual is None:
            return "already_absent"
        if item["status"] == "absent":
            raise Refusal("ref appeared after the displayed plan")
        if actual != item["expected_oid"]:
            raise Refusal("ref changed after confirmation")
        if item["kind"] == "local_branch" and item["ref"] in used_branches(r, repo):
            raise Refusal("branch became checked out after confirmation")
        r.git(repo, "update-ref", "-d", item["ref"], item["expected_oid"])
    return "deleted"


def purge_records(r, path, journal, repo):
    plan = journal["plan"]
    if any(result["status"] == "retained" for result in journal["progress"].values()):
        return False
    if any(item["status"] == "blocked" for item in plan["items"]):
        return False
    root = r.plain_path(plan["handoff"]["notes"]["path"])
    if journal["stage"] != "purging_records":
        with r.locked(plan["handoff"]["state_path"]) as (_, state):
            if any(item["status"] != "released" for item in state["resources"].values()):
                raise Refusal("remaining resources still need their ledger")
            checked_notes(r, state, plan["handoff"])
        for item in plan["items"]:
            if item["kind"] in ["local_branch", "internal_ref"] and ref_oid(r, repo, item["ref"]) is not None:
                raise Refusal("local refs remain; retain records")
            if item["kind"] == "remote_branch" and remote_oid(r, repo, item["remote_url"], item["ref"]) is not None:
                raise Refusal("remote branch remains; retain records")
        if not plan["notes_idle"] or processes_using(r, [root]):
            raise Refusal("notes became active after confirmation")
        journal["purge_snapshot"] = tree_snapshot(r, root)
        journal["stage"] = "purging_records"
        write_journal(r, path, journal)
    notes_item = next(item for item in plan["items"] if item["kind"] == "notes")
    verify_released_objects(r, plan, journal, repo)
    if os.path.lexists(root):
        if r.identity(root) != plan["handoff"]["notes"]["identity"]:
            raise Refusal("notes root was replaced after confirmation")
        snapshot_matches(r, root, journal["purge_snapshot"], allow_missing=True)
        r.check_data_tree(root)
        if processes_using(r, [root]) or not shutil.rmtree.avoids_symlink_attacks:
            raise Refusal("notes are in use or safe directory deletion is unavailable")
        shutil.rmtree(root)
        save_result(r, path, journal, notes_item, "deleted")
    else:
        save_result(r, path, journal, notes_item, "already_absent")
    index_item = next(item for item in plan["items"] if item["kind"] == "index")
    index_path = r.plain_path(index_item["path"])
    if index_path.exists():
        if file_identity(index_path) != index_item["identity"] or r.digest(index_path) != index_item["sha256"]:
            raise Refusal("index was replaced; retain it")
        index_path.unlink()
        save_result(r, path, journal, index_item, "deleted")
    else:
        save_result(r, path, journal, index_item, "already_absent")
    return True


def apply_command(args, r):
    path = r.plain_path(args.plan)
    with execution_lock(path.parent):
        return locked_apply(args, r, path)


def locked_apply(args, r, path):
    journal = r.load_json(path)
    plan, repo, common = validate_plan(r, path, journal, args.approved_digest)
    if journal.get("attempt_started_at"):
        raise Refusal("this plan was already attempted; generate and confirm a fresh plan")
    if journal["stage"] != "purging_records":
        approved_index = next(item for item in plan["items"] if item["kind"] == "index")
        index_path = Path(approved_index["path"])
        if file_identity(index_path) != approved_index["identity"] or r.digest(index_path) != approved_index["sha256"]:
            raise Refusal("index changed after confirmation")
    journal["attempt_started_at"] = r.now()
    write_journal(r, path, journal)
    results = []
    if journal["stage"] == "purging_records":
        current = {item["id"]: item for item in recovery_inventory(r, plan, journal, repo)}
        for item in plan["items"]:
            if item["kind"] in ["notes", "index", "journal"]:
                continue
            try:
                checked = current[item["id"]]
                if item["status"] == "blocked" or checked["status"] == "blocked":
                    raise Refusal("; ".join(item["reasons"] + checked["reasons"]))
                if item["kind"] == "internal_ref" and item["status"] == "ready":
                    status = apply_ref(r, plan, repo, item, recovering=True)
                elif checked["status"] == "absent":
                    status = "already_absent"
                else:
                    raise Refusal("object appeared after the displayed recovery plan")
                results.append(save_result(r, path, journal, item, status))
            except (r.Refusal, Refusal, OSError) as error:
                results.append(save_result(r, path, journal, item, "retained", error))
    else:
        index = r.load_json(Path(plan["index_path"]))
        state, handoff = load_handoff(r, index, common)
        if handoff != plan["handoff"]:
            raise Refusal("handoff changed after plan approval")
        fresh = inventory(r, repo, state, handoff, verify_pr(plan["pr"]), set(plan["idle_resources"]), plan["notes_idle"])
        current = {item["id"]: item for item in fresh}
        for item in plan["items"]:
            if item["kind"] in ["notes", "index", "journal"]:
                continue
            try:
                if item["status"] == "blocked":
                    raise Refusal("; ".join(item["reasons"]))
                checked = current.get(item["id"])
                if not checked or checked["status"] == "blocked":
                    raise Refusal("; ".join(checked["reasons"]) if checked else "resource disappeared from inventory")
                if item["kind"] in ["worktree", "data"]:
                    status = apply_resource(r, plan, item)
                else:
                    status = apply_ref(r, plan, repo, item)
                results.append(save_result(r, path, journal, item, status))
            except (r.Refusal, Refusal, OSError) as error:
                results.append(save_result(r, path, journal, item, "retained", error))
    try:
        complete = purge_records(r, path, journal, repo)
    except (r.Refusal, Refusal, OSError) as error:
        complete = False
        notes_item = next(item for item in plan["items"] if item["kind"] == "notes")
        results.append(save_result(r, path, journal, notes_item, "retained", error))
    if complete:
        results = list(journal["progress"].values())
        results.append({"id": "journal", "kind": "journal", "status": "deleted"})
        path.unlink()
        # Empty index grouping directories contain no other invocation's records.
        try:
            path.parent.rmdir()
        except OSError:
            pass
    else:
        known = {result["id"] for result in results}
        for item in plan["items"]:
            if item["kind"] in ["notes", "index", "journal"] and item["id"] not in known:
                results.append({"id": item["id"], "kind": item["kind"], "status": "retained", "reason": "needed to resume partial cleanup"})
    return {"complete": complete, "pr": plan["pr"], "results": results,
            "remaining_journal": None if complete else str(path)}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="action", required=True)
    command = commands.add_parser("plan")
    command.add_argument("number", type=int)
    command.add_argument("--repo", default=".")
    command.add_argument("--index-root")
    command.add_argument("--resource-tool")
    command.add_argument("--idle-resource", action="append", default=[])
    command.add_argument("--notes-idle", action="store_true")
    command = commands.add_parser("apply")
    command.add_argument("--plan", required=True)
    command.add_argument("--approved-digest", required=True)
    command.add_argument("--resource-tool")
    return result


def main():
    args = parser().parse_args()
    r = None
    try:
        r = resource_tool(args.resource_tool)
        if args.action == "plan" and args.number < 1:
            raise Refusal("PR number must be positive")
        result = plan_command(args, r) if args.action == "plan" else apply_command(args, r)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if args.action == "apply" and not result["complete"] else 0
    except Exception as error:
        expected = (Refusal, OSError, ValueError, KeyError, subprocess.TimeoutExpired)
        if r is not None:
            expected += (r.Refusal,)
        if not isinstance(error, expected):
            raise
        print(json.dumps({"error": str(error), "resources_retained": True}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
