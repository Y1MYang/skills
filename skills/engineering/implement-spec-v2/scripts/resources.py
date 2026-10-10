#!/usr/bin/env python3
"""Own, record and release resources created by one implement-spec invocation.

Requires Python 3 and Git only. Nothing imports or adopts pre-existing resources.
This wrapper tracks its commands; --idle-confirmed is the owner's separate check
that no external command, editor, database or descendant process still uses them.
"""

import argparse
import contextlib
import datetime
import gzip
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from types import SimpleNamespace
from urllib.parse import urlparse


VERSION = 1
MARKER = ".implement-spec-resource"
MAX_SUMMARY = 65536
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
CLEANUP_PROTOCOL = "cleanup-spec-v2/1"
NOTES_MARKER = ".implement-spec-notes"
OID_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_COMPANIONS = {}


def companion(name):
    """Load bundled helpers by location, including when cleanup imports this file."""
    if name not in _COMPANIONS:
        path = Path(__file__).with_name(name + ".py")
        spec = importlib.util.spec_from_file_location("implement_spec_" + name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _COMPANIONS[name] = module
    return _COMPANIONS[name]


def helper_api():
    return SimpleNamespace(**globals())


class Refusal(Exception):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def checked_id(value):
    if not ID_PATTERN.fullmatch(value):
        raise Refusal("IDs must be 1-64 letters, digits, underscores or hyphens")
    return value


def git(repo, *args, check=True):
    result = subprocess.run(["git", "-C", str(repo), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise Refusal("git {}: {}".format(" ".join(args),
                      result.stderr.decode(errors="replace").strip()))
    return result


def git_text(repo, *args):
    return git(repo, *args).stdout.decode(errors="replace").strip()


def execution_source(repo, timeout, evidence_root):
    """Check the committed candidate without adding an unbounded post-run wait."""
    deadline = time.monotonic() + timeout
    supervisor = companion("execution_supervisor")
    evidence = Path(tempfile.mkdtemp(prefix="source-identity-", dir=str(evidence_root)))
    values = []
    for index, arguments in enumerate([("rev-parse", "HEAD"), ("status", "--porcelain", "--untracked-files=normal")]):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Refusal("source identity check exceeded its finite allowance; evidence: " + str(evidence))
        allowance = {"seconds": remaining, "source": "Declared finite source identity allowance"}
        configuration = {"version": 1, "budgets": {
            "total": allowance, "shutdown": {"seconds": remaining / 3, "source": allowance["source"]},
            "case": allowance, "phase": {phase: allowance for phase in ["setup", "run", "cleanup"]},
            "stall": allowance}, "long_cases": {}, "case_profiles": {}, "progress_kinds": [],
            "adapter": {"files": [__file__], "environment": []}}
        logs = {name: str(evidence / (str(index) + "." + name + ".gz")) for name in ["stdout", "stderr"]}
        try:
            result = supervisor.supervise(["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
                "-C", str(repo), *arguments], repo, logs, configuration, "source-" + uuid.uuid4().hex,
                events_path=evidence / (str(index) + ".events.jsonl"),
                alerts_path=evidence / (str(index) + ".alerts.jsonl"))
        except (OSError, ValueError, supervisor.Refusal) as error:
            raise Refusal("source identity check failed; retained evidence: {}: {}".format(evidence, error))
        if (result["exit_code"] != 0 or not result["stopped"] or not result["capture_complete"] or
                result["outcome"] not in ["completed", "coverage_unverified"]):
            raise Refusal("cannot verify acceptance source identity; retained evidence: " + str(evidence))
        with gzip.open(logs["stdout"], "rb") as stream:
            output = stream.read(MAX_SUMMARY + 1)
        if len(output) > MAX_SUMMARY:
            raise Refusal("source metadata exceeds bounded output; retained evidence: " + str(evidence))
        values.append(output.decode(errors="replace").strip())
    shutil.rmtree(evidence)
    return {"revision": values[0], "clean": not values[1]}


def execution_failed(run):
    observed = run.get("supervision", {})
    return (run.get("exit_code") != 0 or observed.get("outcome") != "completed" or
            not observed.get("coverage_verified") or not observed.get("capture_complete") or
            not observed.get("stopped") or
            (run.get("formal_acceptance") and not run.get("acceptance_qualified")))


def execution_policy(contract):
    return {key: contract.get(key) for key in ["budgets", "long_cases", "case_profiles", "progress_kinds"]}


def identity(path):
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode):
        raise Refusal("not an ordinary directory: {}".format(path))
    return [info.st_dev, info.st_ino]


def within(path, parent):
    return path == parent or parent in path.parents


def plain_path(value):
    """Do not normalize a symlink into a deletion authorization."""
    path = Path(os.path.abspath(os.path.expanduser(value)))
    if any(ord(char) < 32 for char in str(path)):
        raise Refusal("resource/state paths cannot contain control characters")
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise Refusal("symlink path component: {}".format(part))
    return path


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       indent=2) + "\n").encode("utf-8")


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with open(temporary, "xb") as stream:
            stream.write(encode(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def digest(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            result.update(chunk)
    return result.hexdigest()


def load_json(path, limit=None):
    if path.is_symlink() or not path.is_file():
        raise Refusal("missing or unsafe JSON file: {}".format(path))
    with open(path, "rb") as stream:
        raw = stream.read(limit + 1) if limit is not None else stream.read()
    if limit is not None and len(raw) > limit:
        raise Refusal("JSON exceeds {} bytes".format(limit))
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise Refusal("invalid JSON: {}".format(error))


@contextlib.contextmanager
def locked(state_dir, timeout=None):
    if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
        raise Refusal("ledger lock allowance must be positive and finite")
    path = plain_path(state_dir)
    lock_path = path / "lock"
    if not path.is_dir() or lock_path.is_symlink():
        raise Refusal("missing or unsafe state directory/lock")
    with open(lock_path, "r+b") as lock:
        deadline = time.monotonic() + timeout if timeout is not None else None
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            acquire = lambda: (lock.seek(0), msvcrt.locking(lock.fileno(),
                msvcrt.LK_LOCK if deadline is None else msvcrt.LK_NBLCK, 1))
            unlock = lambda: (lock.seek(0), msvcrt.locking(
                lock.fileno(), msvcrt.LK_UNLCK, 1))
        else:
            try:
                import fcntl
            except ImportError:
                raise Refusal("platform has no supported advisory lock")
            acquire = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_EX |
                                        (fcntl.LOCK_NB if deadline is not None else 0))
            unlock = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        while True:
            try:
                acquire()
                break
            except BlockingIOError:
                if deadline is None or time.monotonic() >= deadline:
                    raise Refusal("ledger lock deadline exceeded; terminal evidence and resources retained")
                time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        try:
            state = load_json(path / "state.json")
            if state.get("version") != VERSION or state.get("state_path") != str(path):
                raise Refusal("unsupported or relocated state")
            if state.get("identity") != identity(path):
                raise Refusal("state directory identity changed")
            yield path, state
        finally:
            unlock()


def save(path, state):
    atomic_json(path / "state.json", state)


def require_open(state):
    if state.get("sealed_at"):
        raise Refusal("invocation is sealed; reuse or release existing resources without new allocations")


def require_cleanup_protocol(state):
    if state.get("cleanup_protocol") != CLEANUP_PROTOCOL or not state.get("notes"):
        raise Refusal("historical ledger has no cleanup handoff protocol; audit only")


def verify_notes(state):
    require_cleanup_protocol(state)
    notes = state["notes"]
    path = plain_path(notes["path"])
    if identity(path) != notes["identity"] or load_json(path / NOTES_MARKER, 4096) != notes["marker"]:
        raise Refusal("invocation notes ownership changed")
    return path


def default_index_root():
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return plain_path(str(Path(base) / "implement-spec-v2"))


def validate_index_root(value, state):
    path = plain_path(value)
    for value in [state["repo"], state["common_git"], state["notes"]["path"]]:
        protected = Path(value)
        if within(path, protected) or within(protected, path):
            raise Refusal("index root must be separate from notes, repository and Git metadata")
    return path


def file_identity(path):
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise Refusal("not an ordinary file: {}".format(path))
    return [info.st_dev, info.st_ino]


def refresh_index(state, override=None):
    root = validate_index_root(override or state["index_root"], state)
    if override and str(root) != state["index_root"] and state.get("index_path"):
        raise Refusal("bound invocation index cannot be relocated")
    group = hashlib.sha256(state["common_git"].encode("utf-8")).hexdigest()
    directory = root / group
    directory.mkdir(parents=True, exist_ok=True)
    plain_path(str(directory))
    target = directory / (state["invocation"] + ".json")
    if target.exists():
        previous = load_json(target)
        if previous.get("invocation") != state["invocation"] or previous.get("protocol") != CLEANUP_PROTOCOL:
            raise Refusal("index entry ownership changed")
    value = {"protocol": CLEANUP_PROTOCOL, "invocation": state["invocation"],
             "repo": state["repo"], "common_git": state["common_git"], "pr": state["pr"],
             "state": {"path": state["state_path"], "identity": state["identity"]},
             "notes": state["notes"], "handoff": state.get("handoff")}
    atomic_json(target, value)
    state["index_root"], state["index_path"] = str(root), str(target)
    return target


def checked_oid(value):
    if not isinstance(value, str) or not OID_PATTERN.fullmatch(value):
        raise Refusal("expected a full Git object ID")
    return value


def native_pr(value):
    """Select stable identity fields from a fresh native REST PR response."""
    if not isinstance(value, dict):
        raise Refusal("PR input must be a native REST object")
    try:
        number, pr_id, url = value["number"], value["id"], value["html_url"]
        if type(number) is not int or number <= 0 or type(pr_id) is not int or pr_id <= 0:
            raise Refusal("PR id/number must be positive integers")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise Refusal("PR html_url must be an HTTPS repository URL")
        repos = {}
        for side in ["base", "head"]:
            source = value[side]["repo"]
            item = {key: source[key] for key in ["id", "full_name", "clone_url"]}
            if type(item["id"]) is not int or item["id"] <= 0:
                raise Refusal("PR repository id must be a positive integer")
            if not isinstance(item["full_name"], str) or not re.fullmatch(r"[^/\s]+/[^/\s]+", item["full_name"]):
                raise Refusal("PR repository full_name must be owner/name")
            if not isinstance(item["clone_url"], str) or not item["clone_url"].strip():
                raise Refusal("PR repository clone_url is required")
            if not isinstance(value[side]["ref"], str) or not value[side]["ref"].strip():
                raise Refusal("PR branch ref is required")
            checked_oid(value[side]["sha"])
            repos[side] = item
        expected_path = "/{}/pull/{}".format(repos["base"]["full_name"], number)
        if parsed.path.rstrip("/").casefold() != expected_path.casefold():
            raise Refusal("PR URL disagrees with base repository or number")
        return {"id": pr_id, "number": number, "url": url, "host": parsed.hostname.lower(),
                "base_repo": repos["base"], "head_repo": repos["head"],
                "base_ref": value["base"]["ref"], "base_oid": value["base"]["sha"],
                "head_ref": value["head"]["ref"], "head_oid": value["head"]["sha"],
                "draft": value.get("draft") if type(value.get("draft")) is bool else None}
    except (KeyError, TypeError, ValueError) as error:
        raise Refusal("incomplete native REST PR object: {}".format(error))


def remote_oid(repo, destination, ref):
    output = git_text(repo, "ls-remote", "--refs", "--", destination, ref)
    rows = [line.split("\t") for line in output.splitlines() if line]
    if not rows:
        return None
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref:
        raise Refusal("remote reference result is ambiguous")
    return checked_oid(rows[0][0])


def publish_branch(args):
    with locked(args.state) as (state_path, state):
        require_cleanup_protocol(state)
        verify_notes(state)
        require_open(state)
        item = resource(state, args.resource)
        if item["kind"] != "worktree" or not item.get("branch"):
            raise Refusal("publication requires an invocation-created worktree branch")
        verify_resource(state, item)
        if item.get("publication"):
            raise Refusal("publication was already attempted; retain uncertain outcomes for audit")
        ref = "refs/heads/" + item["branch"]
        oid = git_text(state["repo"], "rev-parse", "--verify", ref + "^{commit}")
        destination = args.remote_url
        if not destination.strip() or any(ord(char) < 32 for char in destination):
            raise Refusal("remote URL must be a nonempty destination without control characters")
        if remote_oid(state["repo"], destination, ref) is not None:
            raise Refusal("remote branch already exists; first publication cannot adopt it")
        publication = {"status": "creating", "remote_url": destination, "remote_ref": ref,
                       "created_oid": oid, "created_at": now()}
        item["publication"] = publication
        save(state_path, state)
        repo = state["repo"]
    try:
        # An empty lease expectation means the destination ref must not exist.
        result = git(repo, "push", "--porcelain", "--force-with-lease=" + ref + ":", "--", destination, ref + ":" + ref)
        updates = [line.split("\t") for line in result.stdout.decode(errors="replace").splitlines()]
        if not any(len(fields) == 3 and fields[0] == "*" and fields[1] == ref + ":" + ref for fields in updates):
            raise Refusal("push did not confirm new remote reference creation; retain uncertain publication")
        if remote_oid(repo, destination, ref) != oid:
            raise Refusal("published branch changed during creation; retain uncertain publication")
    except BaseException as error:
        with locked(args.state) as (state_path, state):
            state["resources"][args.resource]["publication"]["error"] = str(error) or type(error).__name__
            save(state_path, state)
        raise
    with locked(args.state) as (state_path, state):
        publication = state["resources"][args.resource]["publication"]
        if publication["status"] != "creating":
            raise Refusal("publication changed during creation; retain and investigate")
        publication.update(status="created", published_at=now())
        save(state_path, state)
        return {"resource": args.resource, "publication": publication}


def bind_pr(args):
    pr = native_pr(load_json(plain_path(args.pr_json), 1048576))
    with locked(args.state) as (state_path, state):
        require_cleanup_protocol(state)
        verify_notes(state)
        require_open(state)
        if state.get("pr"):
            raise Refusal("invocation is already bound to a PR")
        item = resource(state, args.pr_resource)
        verify_resource(state, item)
        publication = item.get("publication", {})
        if item["kind"] != "worktree" or publication.get("status") != "created":
            raise Refusal("PR branch must have a completed first publication")
        if item.get("branch") != pr["head_ref"] or publication["remote_ref"] != "refs/heads/" + pr["head_ref"]:
            raise Refusal("PR head branch disagrees with owned publication")
        if publication["remote_url"] != pr["head_repo"]["clone_url"]:
            raise Refusal("publish using the native head repository clone_url before binding")
        current = git_text(state["repo"], "rev-parse", "--verify", publication["remote_ref"] + "^{commit}")
        if current != pr["head_oid"] or publication["created_oid"] != pr["head_oid"]:
            raise Refusal("fresh PR head does not match the first owned publication")
        pr["resource"] = args.pr_resource
        state["pr"] = pr
        target = refresh_index(state, getattr(args, "index_root", None))
        save(state_path, state)
        return {"pr": pr, "index": str(target)}


def mount_points():
    """Include same-device bind mounts, which st_dev and ismount can miss."""
    if not sys.platform.startswith("linux"):
        return set()
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="surrogateescape") as stream:
            rows = [line.split() for line in stream]
    except OSError as error:
        raise Refusal("cannot inspect Linux mount ownership; retain directories: {}".format(error))
    result = set()
    for row in rows:
        if len(row) < 6:
            raise Refusal("incomplete mount ownership information")
        decoded = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), row[4])
        result.add(Path(decoded))
    return result


def is_mount_path(path, mounts):
    return Path(path) in mounts or os.path.ismount(path)


def data_fingerprint(state, item):
    """Fingerprint owned contents without following links or absorbing children."""
    if item["kind"] != "data":
        raise Refusal("contents fingerprint requires an owned data resource")
    root = verify_resource(state, item)
    excluded = []
    for other in state["resources"].values():
        path = Path(other["path"])
        if path != root and within(path, root):
            if other["status"] == "released" and os.path.lexists(path):
                raise Refusal("released child resource path is present; retain unknown replacement: " + str(path))
            excluded.append(path)
    device = os.lstat(root).st_dev
    mounts = mount_points()
    entries = []

    def visit(directory):
        for path in directory.iterdir():
            if any(within(path, parent) for parent in excluded):
                continue
            info = os.lstat(path)
            entry = {"path": str(path.relative_to(root)), "identity": [info.st_dev, info.st_ino]}
            if stat.S_ISLNK(info.st_mode):
                entry.update(type="symlink", sha256=hashlib.sha256(os.readlink(os.fsencode(path))).hexdigest())
            elif info.st_dev != device or is_mount_path(path, mounts):
                raise Refusal("data contains a nested mount; retain and review manually")
            elif stat.S_ISDIR(info.st_mode):
                entry["type"] = "directory"
                visit(path)
            elif stat.S_ISREG(info.st_mode):
                entry.update(type="file", sha256=digest(path))
            else:
                raise Refusal("data contains a special file; retain and review manually")
            entries.append(entry)
    visit(root)
    return hashlib.sha256(encode(sorted(entries, key=lambda entry: entry["path"]))).hexdigest()


def notes_snapshot(state):
    root = verify_notes(state)
    excluded = [Path(state["state_path"])]
    excluded += [Path(item["path"]) for item in state["resources"].values() if item["status"] != "released"]
    entries, blockers = [], []
    device = os.lstat(root).st_dev
    mounts = mount_points()

    def visit(directory):
        for path in sorted(directory.iterdir()):
            if any(within(path, value) for value in excluded):
                continue
            relative = str(path.relative_to(root))
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode):
                blockers.append({"path": relative, "reason": "notes contain a symlink"})
            elif info.st_dev != device or is_mount_path(path, mounts):
                blockers.append({"path": relative, "reason": "notes contain a nested mount"})
            elif stat.S_ISDIR(info.st_mode):
                entries.append({"path": relative, "type": "directory", "identity": [info.st_dev, info.st_ino]})
                visit(path)
            elif stat.S_ISREG(info.st_mode):
                entries.append({"path": relative, "type": "file", "identity": [info.st_dev, info.st_ino],
                                "sha256": digest(path)})
            else:
                blockers.append({"path": relative, "reason": "notes contain a special file"})
    visit(root)
    return {"entries": entries, "blockers": blockers}


def seal(args):
    pr = native_pr(load_json(plain_path(args.pr_json), 1048576))
    required_scope = acceptance_scope(getattr(args, "acceptance_scope", None))
    with locked(args.state) as (state_path, state):
        require_cleanup_protocol(state)
        verify_notes(state)
        require_open(state)
        watcher = state.get("resource_audit", {}).get("watch", {})
        if watcher and watcher.get("status") != "stopped":
            raise Refusal("stop the invocation watcher and confirm its completion before sealing")
        bound = state.get("pr")
        if not bound:
            raise Refusal("bind the PR before sealing")
        for key in ["id", "number", "url", "host", "base_repo", "head_repo", "base_ref", "head_ref"]:
            if pr[key] != bound[key]:
                raise Refusal("fresh PR identity disagrees with bound invocation: " + key)
        assessment = acceptance_assessment(state_path, state,
            final_run=getattr(args, "acceptance_run", None), revision=pr["head_oid"],
            required_scope=required_scope, final=True)
        if assessment["status"] != "verified" and pr["draft"] is not True:
            raise Refusal("unverified acceptance requires fresh native REST draft: true before sealing")
        pr["resource"] = bound["resource"]
        branches, anchors, worktrees, data = [], [], [], []
        for item in state["resources"].values():
            if item["kind"] == "data":
                snapshot = {"resource": item["id"], "path": item["path"],
                            "status": item["status"], "contents_sha256": None}
                if item["status"] == "active":
                    try:
                        snapshot["contents_sha256"] = data_fingerprint(state, item)
                    except (OSError, Refusal, ValueError) as error:
                        snapshot["blocker"] = str(error)
                data.append(snapshot)
            if item["kind"] != "worktree":
                continue
            if item["status"] == "active":
                path = verify_resource(state, item)
                head = git_text(path, "rev-parse", "HEAD")
            else:
                head = item.get("preserved_revision") or item.get("revision")
            worktrees.append({"resource": item["id"], "path": item["path"],
                              "expected_oid": head, "status": item["status"]})
            if item.get("branch"):
                ref = "refs/heads/" + item["branch"]
                oid = git_text(state["repo"], "rev-parse", "--verify", ref + "^{commit}")
                publication = item.get("publication")
                if publication:
                    if publication["status"] != "created":
                        raise Refusal("uncertain publication must be investigated before sealing")
                    if remote_oid(state["repo"], publication["remote_url"], publication["remote_ref"]) != oid:
                        raise Refusal("owned remote branch does not match final local branch")
                    publication["expected_oid"] = oid
                branches.append({"resource": item["id"], "ref": ref, "expected_oid": oid,
                                 "publication": publication})
                if item["id"] == bound["resource"] and oid != pr["head_oid"]:
                    raise Refusal("final PR head differs from delivered local branch")
            if item.get("preserved_ref"):
                ref = item["preserved_ref"]
                oid = git_text(state["repo"], "rev-parse", "--verify", ref + "^{commit}")
                if oid != item["preserved_revision"]:
                    raise Refusal("preserved revision anchor changed")
                anchors.append({"resource": item["id"], "ref": ref, "expected_oid": oid})
            elif item["status"] == "active":
                # release() creates this anchor, even when cleanup performs the release.
                anchors.append({"resource": item["id"],
                                "ref": "refs/implement-spec-runs/{}/{}".format(state["invocation"], item["id"]),
                                "expected_oid": head, "anticipated": True})
        sealed_at = now()
        handoff = {"protocol": CLEANUP_PROTOCOL, "invocation": state["invocation"], "sealed_at": sealed_at,
                   "repo": state["repo"], "common_git": state["common_git"],
                   "state_path": state["state_path"], "state_identity": state["identity"],
                   "notes": state["notes"], "pr": pr, "delivery_oid": pr["head_oid"],
                   "branches": branches, "internal_refs": anchors, "worktrees": worktrees, "data": data,
                   "acceptance": assessment,
                   "notes_snapshot": notes_snapshot(state)}
        path = state_path / "handoff.json"
        if path.exists():
            raise Refusal("handoff already exists; investigate an interrupted seal")
        atomic_json(path, handoff)
        state.update(sealed_at=sealed_at, pr=pr, delivery_oid=pr["head_oid"],
                     handoff={"path": str(path), "identity": file_identity(path), "sha256": digest(path)})
        save(state_path, state)
        target = refresh_index(state)
        save(state_path, state)
        return {"sealed_at": sealed_at, "handoff": state["handoff"], "index": str(target),
                "blockers": handoff["notes_snapshot"]["blockers"] +
                    [{"resource": item["resource"], "path": item["path"], "reason": item["blocker"]}
                     for item in data if item.get("blocker")]}


def resource(state, name):
    checked_id(name)
    if name not in state["resources"]:
        raise Refusal("unknown resource: {}".format(name))
    item = state["resources"][name]
    if item["status"] != "active":
        raise Refusal("resource is not active: {}".format(name))
    return item


def guard_scope(state, path):
    protected_paths = [state["repo"], state["common_git"], state["state_path"]]
    if state.get("notes"):
        protected_paths.append(state["notes"]["path"])
    for value in protected_paths:
        protected = Path(value)
        if within(protected, path):
            raise Refusal("resource would contain protected path: {}".format(protected))
    for value in [state["common_git"], state["state_path"]]:
        if within(path, Path(value)):
            raise Refusal("resource is inside protected state/Git directory")


def verify_resource(state, item):
    path = plain_path(item["path"])
    guard_scope(state, path)
    if item["identity"] != identity(path):
        raise Refusal("resource directory identity changed: {}".format(path))
    if item["kind"] == "data":
        if load_json(path / MARKER, 4096) != item["marker"]:
            raise Refusal("resource ownership marker changed: {}".format(path))
    else:
        pointer = path / ".git"
        if pointer.is_symlink() or not pointer.is_file():
            raise Refusal("worktree Git pointer is missing or unsafe")
        info = pointer.stat()
        if [info.st_dev, info.st_ino] != item["git_identity"] or digest(pointer) != item["git_pointer_sha256"]:
            raise Refusal("worktree Git pointer identity changed")
        common = Path(git_text(path, "rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = path / common
        if str(common.resolve()) != state["common_git"]:
            raise Refusal("worktree now belongs to another repository")
        registered = git_text(state["repo"], "-c", "core.quotePath=false", "worktree", "list", "--porcelain")
        if "worktree " + str(path) not in registered.splitlines():
            raise Refusal("worktree is no longer registered with Git")
    return path


def record_path(state_path, run):
    expected = "{}.{}.json".format(checked_id(run["id"]), run["record_generation"])
    if run.get("record_file") != expected:
        raise Refusal("compact record filename disagrees with ledger")
    return state_path / "records" / expected


def check_record(state_path, run):
    path = record_path(state_path, run)
    if path.is_symlink() or not path.is_file() or digest(path) != run.get("record_sha256"):
        raise Refusal("compact evidence is missing or corrupt: {}".format(run["id"]))
    record = load_json(path)
    expected = {k: v for k, v in run.items() if k != "record_sha256"}
    if record != expected:
        raise Refusal("compact evidence disagrees with ledger: {}".format(run["id"]))


def write_record(state_path, run):
    run["record_generation"] = run.get("record_generation", 0) + 1
    run["record_file"] = "{}.{}.json".format(run["id"], run["record_generation"])
    path = record_path(state_path, run)
    atomic_json(path, {k: v for k, v in run.items() if k != "record_sha256"})
    run["record_sha256"] = digest(path)


def release_blockers(state_path, state, name, allow_scratch_failure=False):
    reasons = []
    for other in state["resources"].values():
        if other.get("parent") == name and other["status"] != "released":
            reasons.append("child resource still present: " + other["id"])
    for run in state["runs"].values():
        if name not in run["uses"]:
            continue
        if run["status"] != "completed":
            reasons.append("command {} is {}; owner must investigate".format(run["id"], run["status"]))
            continue
        try:
            check_record(state_path, run)
        except Refusal as error:
            reasons.append(str(error))
        if run["test"] and "summary" not in run:
            reasons.append("test summary not recorded: " + run["id"])
        failed = (bool(run.get("execution_contract")) and execution_failed(run)) or run["exit_code"] != 0 or (
            "summary" in run and (run["summary"]["tests"]["failed"] or
                                 run["summary"]["tests"]["errors"]))
        if failed and not run.get("resolution") and not allow_scratch_failure:
            reasons.append("unresolved failure: " + run["id"])
    return reasons


def tree_size(path):
    """Logical bytes; no traversal of links or nested mounts."""
    total = 0
    device = os.lstat(path).st_dev
    for current, dirs, files in os.walk(path, followlinks=False):
        kept = []
        for name in dirs:
            info = os.lstat(Path(current) / name)
            if stat.S_ISLNK(info.st_mode):
                total += info.st_size
            elif info.st_dev == device:
                kept.append(name)
        dirs[:] = kept
        for name in files:
            total += os.lstat(Path(current) / name).st_size
    return total


def init(args):
    repo = plain_path(args.repo)
    repo = Path(git_text(repo, "rev-parse", "--show-toplevel")).resolve()
    common = Path(git_text(repo, "rev-parse", "--git-common-dir"))
    common = (repo / common).resolve() if not common.is_absolute() else common.resolve()
    path = plain_path(args.state_dir)
    if within(path, repo) or within(repo, path) or within(path, common) or within(common, path):
        raise Refusal("state must be outside repository and Git metadata")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise Refusal("init requires a new or empty state directory")
    notes = None
    invocation = uuid.uuid4().hex
    if getattr(args, "notes_root", None):
        notes_path = plain_path(args.notes_root)
        if not within(path, notes_path) or path == notes_path:
            raise Refusal("state directory must be a child of the invocation notes root")
        for protected in [repo, common]:
            if within(notes_path, protected) or within(protected, notes_path):
                raise Refusal("notes root must be outside repository and Git metadata")
        if notes_path.exists() and (not notes_path.is_dir() or any(notes_path.iterdir())):
            raise Refusal("notes root must be new or empty; historical notes cannot be adopted")
        marker = {"protocol": CLEANUP_PROTOCOL, "invocation": invocation, "nonce": uuid.uuid4().hex}
        # Check index separation before creating any notes-owned files.
        index_root = validate_index_root(getattr(args, "index_root", None) or str(default_index_root()),
                                         {"repo": str(repo), "common_git": str(common),
                                          "notes": {"path": str(notes_path)}})
        notes_path.mkdir(parents=True, exist_ok=True)
        with open(notes_path / NOTES_MARKER, "xb") as stream:
            stream.write(encode(marker))
        notes = {"path": str(notes_path), "identity": identity(notes_path), "marker": marker}
    elif getattr(args, "index_root", None):
        raise Refusal("--index-root requires --notes-root")
    path.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents two initializers adopting the same directory.
    with open(path / "lock", "xb") as lock:
        lock.write(b"0")
    (path / "records").mkdir()
    state = {"version": VERSION, "invocation": invocation,
             "created_at": now(), "state_path": str(path), "identity": identity(path),
             "repo": str(repo), "common_git": str(common), "resources": {}, "runs": {}}
    companion("resource_capacity").initialize(state)
    if notes:
        state.update(cleanup_protocol=CLEANUP_PROTOCOL, notes=notes, index_root=str(index_root))
    save(path, state)
    return {"state": str(path), "invocation": state["invocation"]}


def create(args):
    checked_id(args.id)
    with locked(args.state) as (state_path, state):
        require_open(state)
        if args.id in state["resources"]:
            raise Refusal("resource ID already used")
        path = plain_path(args.path)
        guard_scope(state, path)
        if os.path.lexists(path):
            raise Refusal("create refuses every pre-existing path")
        if not path.parent.is_dir():
            raise Refusal("create parent directory first; it must already exist")
        parent = resource(state, args.parent) if args.parent else None
        if parent:
            verify_resource(state, parent)
            if args.kind != "data" or not within(path, Path(parent["path"])):
                raise Refusal("only data can be nested under an explicit owned parent")
        if args.kind == "data" and within(path, Path(state["repo"])):
            ancestor = parent
            while ancestor and ancestor["kind"] != "worktree":
                ancestor = state["resources"].get(ancestor.get("parent"))
            if not ancestor:
                raise Refusal("data in the primary repository requires an explicitly owned worktree parent")
        for other in state["resources"].values():
            if other["status"] == "released":
                continue
            other_path = Path(other["path"])
            if within(other_path, path):
                raise Refusal("new resource would contain an existing resource")
            if within(path, other_path):
                ancestor = parent
                while ancestor and ancestor["id"] != other["id"]:
                    ancestor = state["resources"].get(ancestor.get("parent"))
                if not ancestor:
                    raise Refusal("nested resource requires its explicit parent")
        if args.kind == "data" and (args.ref or args.branch):
            raise Refusal("--ref/--branch apply only to worktrees")
        marker = {"invocation": state["invocation"], "resource": args.id,
                  "nonce": uuid.uuid4().hex}
        pending = {"id": args.id, "kind": args.kind, "path": str(path),
                   "role": args.role, "owner": getattr(args, "owner", None) or args.role, "parent": args.parent,
                   "created_at": now(), "marker": marker, "status": "creating",
                   "release_condition": ("merged into target, clean, evidence complete, idle"
                       if args.kind == "worktree" else "evidence complete, failures resolved, idle")}
        pending["reservations"] = companion("resource_capacity").claim(
            state, getattr(args, "reservation", []) or [], [path.parent],
            "create", args.id, helper_api(), owner=pending["owner"])
        # Persist before Git/filesystem mutation: a crash leaves an explicit refusal,
        # never an automatically adoptable or deletable resource.
        state["resources"][args.id] = pending
        save(state_path, state)
        repo = state["repo"]
    try:
        if args.kind == "worktree":
            command = ["worktree", "add"]
            command += ["-b", args.branch] if args.branch else ["--detach"]
            command += ["--", str(path), args.ref or "HEAD"]
            git(repo, *command)
        else:
            path.mkdir()
        pending["identity"] = identity(path)
        if args.kind == "data":
            with open(path / MARKER, "xb") as stream:
                stream.write(encode(marker))
        pending["status"] = "active"
        if args.kind == "worktree":
            pending["revision"] = git_text(path, "rev-parse", "HEAD")
            pending["branch"] = args.branch
            info = (path / ".git").stat()
            pending["git_identity"] = [info.st_dev, info.st_ino]
            pending["git_pointer_sha256"] = digest(path / ".git")
    except BaseException as error:
        with locked(args.state) as (state_path, state):
            state["resources"][args.id]["creation_error"] = str(error) or type(error).__name__
            save(state_path, state)
        raise
    with locked(args.state) as (state_path, state):
        state["resources"][args.id] = pending
        companion("resource_capacity").finish(state, "create", args.id, helper_api())
        save(state_path, state)
        return pending


def run_command(args):
    checked_id(args.id)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise Refusal("run requires a command after --")
    formal = getattr(args, "acceptance", False)
    contract_path = getattr(args, "execution_contract", None)
    gate_path = getattr(args, "execution_gate", None)
    retry_of = getattr(args, "retry_of", None)
    validate_after = getattr(args, "validate_after", None)
    failure_key = getattr(args, "failure_key", None)
    if formal and (not args.test or not contract_path or not gate_path or not failure_key):
        raise Refusal("formal acceptance requires --test --execution-contract --execution-gate --failure-key")
    if gate_path and not contract_path:
        raise Refusal("--execution-gate requires --execution-contract")
    if retry_of and validate_after:
        raise Refusal("automatic recovery and repair validation are separate actions")
    if (retry_of or validate_after) and not formal:
        raise Refusal("recovery and repair validation require a formal acceptance configuration")
    if not validate_after and (getattr(args, "repair_round", None) is not None or
                               getattr(args, "repair_evidence", None)):
        raise Refusal("repair round/evidence requires --validate-after")
    if not retry_of and getattr(args, "recovery_evidence", None):
        raise Refusal("recovery evidence requires --retry-of")
    if getattr(args, "contract_change_evidence", None) and not validate_after:
        raise Refusal("contract adjudication requires --validate-after")
    if contract_path:
        contract_path = plain_path(contract_path)
        supervisor = companion("execution_supervisor")
        contract = supervisor.read_contract(contract_path)
    else:
        contract = None
    extra = [item for group in args.uses for item in group]
    uses = list(dict.fromkeys([args.cwd_resource, args.output_resource, *extra]))
    with locked(args.state, timeout=contract["budgets"]["shutdown"]["seconds"] if contract else None) as (state_path, state):
        require_open(state)
        if args.id in state["runs"]:
            raise Refusal("command ID already used")
        for name in uses:
            verify_resource(state, resource(state, name))
        cwd_item = resource(state, args.cwd_resource)
        output = resource(state, args.output_resource)
        if output["kind"] != "data":
            raise Refusal("output resource must be owned data")
        cwd = Path(cwd_item["path"])
        source = None
        if formal:
            if cwd_item["kind"] != "worktree":
                raise Refusal("formal acceptance requires a committed owned worktree")
            source = execution_source(cwd, contract["budgets"]["shutdown"]["seconds"], output["path"])
            if not source["clean"]:
                raise Refusal("formal acceptance requires a clean committed worktree")
        gate = supervisor.validate_gate(plain_path(gate_path), command, cwd, contract) if gate_path else None
        chain = None
        if formal:
            checked_id(failure_key)
            chains = state.setdefault("execution_chains", {})
            chain = chains.get(failure_key)
            predecessor = retry_of or validate_after
            if predecessor:
                previous = state["runs"].get(predecessor)
                if not previous or previous.get("failure_key") != failure_key or not chain:
                    raise Refusal("recovery must reference the existing failure chain")
                if chain["attempts"][-1] != predecessor:
                    raise Refusal("continuation must reference the latest attempt in this failure chain")
                if retry_of and chain.get("recovery_used"):
                    raise Refusal("this failure chain already used its one automatic recovery")
                if getattr(args, "repair_limit", None) not in [None, chain.get("repair_limit", 3)]:
                    raise Refusal("continuation cannot change the original round limit")
                previous_policy = chain.get("execution_policy", execution_policy(previous["execution_contract"]["value"]))
                if execution_policy(contract) != previous_policy:
                    if not validate_after or not (getattr(args, "contract_change_evidence", "") or "").strip():
                        raise Refusal("execution policy changed; retain the original contract or record adjudication evidence")
                check_record(state_path, previous)
                observed = previous.get("supervision", {})
                classification = previous.get("classification", {})
                recovered = previous.get("recovery", {}).get("stopped_confirmed_at")
                if (previous["status"] != "completed" or
                        (not (observed.get("stopped") and observed.get("capture_complete")) and
                         not (validate_after and recovered)) or
                        (retry_of and not execution_failed(previous))):
                    raise Refusal("verify stopped owned processes and preserved first failure before recovery")
                if execution_failed(previous) and classification.get("kind") not in ["business", "evidence", "harness", "environment"]:
                    raise Refusal("classify the first interruption before automatic recovery")
                if retry_of and not (getattr(args, "recovery_evidence", "") or "").strip():
                    raise Refusal("recovery requires evidence of isolation, fixture reset and repeatability")
                if validate_after:
                    limit = chain.get("repair_limit", 3)
                    if getattr(args, "repair_limit", None) not in [None, limit]:
                        raise Refusal("repair validation cannot change the original round limit")
                    round_number = getattr(args, "repair_round", None)
                    if round_number != chain.get("repair_rounds", 0) + 1 or round_number > limit:
                        raise Refusal("repair round must advance once within the original fixed limit")
                    if not (getattr(args, "repair_evidence", "") or "").strip():
                        raise Refusal("repair validation requires evidence of a new justified repair")
            elif chain:
                raise Refusal("failure key already exists; changing run IDs does not reset recovery")
        revision = source["revision"] if source else (git_text(cwd, "rev-parse", "HEAD") if cwd_item["kind"] == "worktree" else None)
        logs = {name: str(Path(output["path"]) / (args.id + "." + name + ".gz"))
                for name in ["stdout", "stderr"]}
        if any(os.path.lexists(value) for value in logs.values()):
            raise Refusal("raw output path already exists")
        owner = getattr(args, "owner", None) or cwd_item["owner"]
        reservations = companion("resource_capacity").claim(
            state, getattr(args, "reservation", []) or [],
            [Path(state["resources"][name]["path"]) for name in uses],
            "run", args.id, helper_api(), owner=owner)
        companion("resource_audit").note_usage(state, uses, args.id)
        run = {"id": args.id, "status": "running", "uses": uses,
               "owner": owner, "reservations": reservations,
               "cwd_resource": args.cwd_resource, "output_resource": args.output_resource,
               "command": command, "cwd": str(cwd), "started_at": now(),
               "pid": None, "wrapper_pid": os.getpid(), "test": args.test, "revision": revision,
               "environment": {"python": platform.python_version(), "os": platform.platform(),
                               "git": git_text(state["repo"], "--version")}, "logs": logs}
        if contract:
            run["execution_contract"] = {"path": str(contract_path), "sha256": digest(contract_path),
                                         "value": contract}
            run["formal_acceptance"] = formal
            if gate:
                run["execution_gate"] = {"path": str(plain_path(gate_path)),
                                         "sha256": digest(plain_path(gate_path)), "value": gate}
        if formal:
            if chain is None:
                chain = {"attempts": [], "recovery_used": False, "repair_rounds": 0,
                         "repair_limit": getattr(args, "repair_limit", None) or 3,
                         "execution_policy": execution_policy(contract)}
                state["execution_chains"][failure_key] = chain
            chain["attempts"].append(args.id)
            if retry_of:
                chain["recovery_used"] = True
                run["retry_of"] = retry_of
                run["recovery_evidence"] = args.recovery_evidence
            if validate_after:
                chain["repair_rounds"] = args.repair_round
                run.update(validate_after=validate_after, repair_round=args.repair_round,
                           repair_evidence=args.repair_evidence)
                if execution_policy(contract) != previous_policy:
                    change = {"run": args.id, "before": previous_policy, "after": execution_policy(contract),
                              "evidence": args.contract_change_evidence}
                    chain.setdefault("policy_history", []).append(change)
                    chain["execution_policy"] = execution_policy(contract)
                    run["contract_adjudication"] = change
            run["failure_key"] = failure_key
            run["source_initial"] = source
        state["runs"][args.id] = run
        save(state_path, state)
    if contract:
        return run_supervised(args, command, cwd, logs, contract, supervisor,
                              run.get("execution_gate", {}).get("sha256"))
    errors = []

    def copy_pipe(pipe, filename):
        try:
            with pipe, open(filename, "xb") as target, gzip.GzipFile(fileobj=target, mode="wb", compresslevel=1) as zipped:
                for chunk in iter(lambda: pipe.read(65536), b""):
                    zipped.write(chunk)
        except Exception as error:
            errors.append(str(error))

    try:
        process = subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        with locked(args.state) as (state_path, state):
            state["runs"][args.id]["pid"] = process.pid
            save(state_path, state)
        threads = [threading.Thread(target=copy_pipe, args=(pipe, logs[name]), daemon=True)
                   for name, pipe in [("stdout", process.stdout), ("stderr", process.stderr)]]
        for thread in threads:
            thread.start()
        exit_code = process.wait()
        for thread in threads:
            thread.join()
        log_hashes = {name: digest(Path(filename)) for name, filename in logs.items()} if not errors else {}
    except BaseException as error:
        with locked(args.state) as (state_path, state):
            run = state["runs"][args.id]
            run.update(status="unknown", interruption=str(error) or type(error).__name__,
                       last_event_at=now())
            save(state_path, state)
        if isinstance(error, KeyboardInterrupt):
            raise Refusal("interrupted; command status unknown, resources retained")
        raise Refusal("command did not complete reliably: {}".format(error))
    with locked(args.state) as (state_path, state):
        run = state["runs"][args.id]
        if run["status"] != "running":
            raise Refusal("command ledger changed during execution; retain and investigate")
        run.update(status="unknown" if errors else "completed", ended_at=now(), exit_code=exit_code)
        if errors:
            run["capture_errors"] = errors
        else:
            run["log_sha256"] = log_hashes
            write_record(state_path, run)
            companion("resource_capacity").finish(state, "run", args.id, helper_api())
        save(state_path, state)
        return {"run": args.id, "status": run["status"], "exit_code": exit_code,
                "record": str(record_path(state_path, run)) if not errors else None,
                "capture_errors": errors}


def run_supervised(args, command, cwd, logs, contract, supervisor, gate_sha256=None):
    output = Path(logs["stdout"]).parent
    lock_budget = contract["budgets"]["shutdown"]["seconds"]

    def started(process_identity):
        with locked(args.state, timeout=lock_budget) as (state_path, state):
            state["runs"][args.id].update(pid=process_identity.get("pid"),
                                         process_identity=process_identity)
            save(state_path, state)

    try:
        result = supervisor.supervise(command, cwd, logs, contract, args.id,
            events_path=output / (args.id + ".events.jsonl"),
            alerts_path=output / (args.id + ".alerts.jsonl"), on_start=started)
    except BaseException as error:
        with locked(args.state, timeout=lock_budget) as (state_path, state):
            run = state["runs"][args.id]
            run.update(status="unknown", interruption=str(error) or type(error).__name__, last_event_at=now())
            save(state_path, state)
        raise Refusal("supervision did not return reliable terminal evidence; retain resources: {}".format(error))
    source_final = None
    gate_final = None
    if getattr(args, "acceptance", False):
        try:
            source_final = execution_source(cwd, lock_budget, output)
        except Refusal as error:
            source_final = {"clean": False, "error": str(error)}
        verification_started = time.monotonic()
        try:
            verification = subprocess.run([sys.executable, str(supervisor.__file__), "validate-gate",
                "--contract", str(args.execution_contract), "--receipt", str(args.execution_gate),
                "--receipt-sha256", gate_sha256, "--cwd", str(cwd), "--", *command],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=lock_budget)
            gate_final = {"verified": verification.returncode == 0,
                          "reason": "" if verification.returncode == 0 else
                                    "execution proof or bound inputs changed or could not be verified"}
        except (subprocess.TimeoutExpired, OSError) as error:
            gate_final = {"verified": False, "reason": str(error)[:1024]}
        gate_final["elapsed_seconds"] = time.monotonic() - verification_started
    with locked(args.state, timeout=lock_budget) as (state_path, state):
        run = state["runs"][args.id]
        if run["status"] != "running":
            raise Refusal("command ledger changed during supervision; retain and investigate")
        reliable = result["stopped"] and result["capture_complete"]
        run.update(status="completed" if reliable else "unknown", ended_at=now(),
                   exit_code=result["exit_code"], outcome=result["outcome"], supervision=result,
                   log_sha256=result.get("log_sha256", {}))
        run["acceptance_qualified"] = bool(run.get("formal_acceptance") and reliable and
            result["exit_code"] == 0 and result["outcome"] == "completed" and result["coverage_verified"])
        if run.get("formal_acceptance"):
            run["source_final"] = source_final
            run["gate_final"] = gate_final
            run["acceptance_qualified"] = bool(run["acceptance_qualified"] and source_final.get("clean") and
                                               source_final.get("revision") == run["revision"] and gate_final["verified"])
        write_record(state_path, run)
        if reliable:
            companion("resource_capacity").finish(state, "run", args.id, helper_api())
        save(state_path, state)
        return {"run": args.id, "status": run["status"], "exit_code": run["exit_code"],
                "outcome": run["outcome"], "acceptance_qualified": run["acceptance_qualified"],
                "source_final": source_final, "gate_final": gate_final,
                "record": str(record_path(state_path, run)),
                "alerts": str(output / (args.id + ".alerts.jsonl")),
                "capture_errors": result.get("capture_errors", [])}


def classify_run(args):
    if not args.evidence.strip():
        raise Refusal("classification needs neutral evidence pointers")
    with locked(args.state) as (state_path, state):
        run = completed_run(state_path, state, args.run)
        if not run.get("execution_contract") or not execution_failed(run):
            raise Refusal("classify-run requires an interrupted or failed supervised attempt")
        if run.get("classification"):
            run.setdefault("classification_history", []).append(run["classification"])
        run["classification"] = {"kind": args.classification, "evidence": args.evidence, "at": now()}
        write_record(state_path, run)
        save(state_path, state)
        return {"run": args.run, "classification": run["classification"]}


def acceptance_scope(path):
    if path is None:
        return None
    scope = load_json(plain_path(path), MAX_SUMMARY)
    if (not isinstance(scope, dict) or set(scope) != {"acceptance", "source"} or
            not isinstance(scope["source"], str) or not scope["source"].strip() or
            not isinstance(scope["acceptance"], list) or not scope["acceptance"] or
            any(not isinstance(item, str) or not item.strip() for item in scope["acceptance"])):
        raise Refusal("acceptance scope requires approved source and nonempty acceptance pointers")
    return scope


def acceptance_assessment(state_path, state, final_run=None, revision=None, required_scope=None, final=False):
    qualified, blockers, stale = [], [], []
    for run in state["runs"].values():
        if not run.get("execution_contract"):
            continue
        if run["status"] != "completed":
            blockers.append({"run": run["id"], "reason": "execution state is unknown or still active"})
            continue
        try:
            check_record(state_path, run)
        except Refusal as error:
            blockers.append({"run": run["id"], "reason": str(error)})
            continue
        if execution_failed(run) and not run.get("resolution"):
            blockers.append({"run": run["id"], "reason": "first failure needs classification and validation"})
        if run.get("acceptance_qualified") and run.get("summary"):
            expected = revision
            if expected is None:
                item = state["resources"][run["cwd_resource"]]
                if item["kind"] == "worktree" and item["status"] == "active":
                    try:
                        expected = git_text(verify_resource(state, item), "rev-parse", "HEAD")
                    except (Refusal, OSError):
                        expected = "unverified-source"
                else:
                    expected = item.get("preserved_revision") or item.get("revision")
            if not expected or run.get("revision") != expected:
                stale.append({"run": run["id"], "reason": "recorded source differs from candidate revision"})
            else:
                qualified.append(run["id"])
    if final:
        if final_run not in qualified:
            blockers.append({"run": final_run, "reason": "designate a qualified final run at the delivery revision"})
        if required_scope is None:
            blockers.append({"run": final_run, "reason": "approved final acceptance scope is missing"})
        elif final_run in qualified and not set(required_scope["acceptance"]).issubset(
                state["runs"][final_run]["summary"]["acceptance"]):
            blockers.append({"run": final_run, "reason": "selected run does not cover the approved final scope"})
    return {"status": "verified" if qualified and not blockers else "unverified",
            "qualified_runs": qualified, "blockers": blockers, "qualification_gaps": stale,
            "final_run": final_run, "delivery_revision": revision, "required_scope": required_scope,
            "limits": "qualified runs cover only their recorded acceptance scope and source revision"}


def acceptance_status(args):
    with locked(args.state) as (state_path, state):
        return acceptance_assessment(state_path, state)


def execution_status(args):
    """Bounded ledger-only owner metadata; qualification uses acceptance-status."""
    if not math.isfinite(args.lock_timeout) or not 0 < args.lock_timeout <= 60:
        raise Refusal("execution-status lock allowance must be positive, finite and at most 60 seconds")
    with locked(args.state, timeout=args.lock_timeout) as (_, state):
        checked_id(args.run)
        if args.run not in state["runs"]:
            raise Refusal("unknown command ID")
        run = state["runs"][args.run]
        if not run.get("execution_contract"):
            raise Refusal("execution-status requires a supervised attempt")
        output = Path(run["logs"]["stdout"]).parent
        return {"invocation": state["invocation"], "snapshot_at": now(),
                **{key: run.get(key) for key in ["id", "owner", "status", "pid", "wrapper_pid",
                   "started_at", "ended_at", "process_identity", "outcome", "exit_code",
                   "acceptance_qualified", "failure_key", "retry_of", "validate_after", "repair_round"]},
                "budgets": run["execution_contract"]["value"]["budgets"],
                "events": str(output / (args.run + ".events.jsonl")),
                "alerts": str(output / (args.run + ".alerts.jsonl")),
                "terminal": str(output / (args.run + ".events.jsonl.terminal.json")),
                "limits": "registered metadata only; no process or evidence inspection"}


def completed_run(state_path, state, name):
    checked_id(name)
    if name not in state["runs"]:
        raise Refusal("unknown command ID")
    run = state["runs"][name]
    if run["status"] != "completed":
        raise Refusal("command is not known completed; investigate and retain resources")
    check_record(state_path, run)
    return run


def record_test(args):
    summary = load_json(plain_path(args.summary), MAX_SUMMARY)
    if not isinstance(summary, dict) or not isinstance(summary.get("tests"), dict):
        raise Refusal("summary needs a tests object")
    counts = summary["tests"]
    keys = {"passed", "failed", "skipped", "errors", "total"}
    if set(counts) != keys or any(type(counts[k]) is not int or counts[k] < 0 for k in keys):
        raise Refusal("tests requires nonnegative integer passed/failed/skipped/errors/total")
    if counts["total"] != sum(counts[k] for k in keys if k != "total"):
        raise Refusal("total must equal passed + failed + skipped + errors")
    if not isinstance(summary.get("reproduce"), str) or not summary["reproduce"].strip():
        raise Refusal("summary needs a nonempty reproduce string")
    acceptance = summary.get("acceptance")
    if not isinstance(acceptance, list) or not acceptance or any(
            not isinstance(item, str) or not item.strip() for item in acceptance):
        raise Refusal("summary needs nonempty acceptance pointers")
    if "notes" in summary and not isinstance(summary["notes"], str):
        raise Refusal("notes must be a string")
    if set(summary) - {"tests", "reproduce", "acceptance", "notes"}:
        raise Refusal("summary supports only tests, reproduce, acceptance and optional notes")
    with locked(args.state) as (state_path, state):
        run = completed_run(state_path, state, args.run)
        if not run["test"] or "summary" in run:
            raise Refusal("command is not an unrecorded --test run")
        if run["exit_code"] == 0 and (counts["failed"] or counts["errors"]):
            raise Refusal("zero-exit command contradicts failed/error test counts")
        if run.get("formal_acceptance") and run.get("acceptance_qualified"):
            if not counts["passed"] or counts["failed"] or counts["errors"]:
                raise Refusal("qualified acceptance requires observed passing tests")
        if run.get("execution_contract") and execution_failed(run) and not counts["failed"] and not counts["errors"]:
            summary.setdefault("notes", "Execution interrupted; no product failure asserted by the supervisor.")
        run["summary"] = summary
        run["summary_recorded_at"] = now()
        write_record(state_path, run)
        due = None
        if run["exit_code"] == 0 and not (run.get("execution_contract") and execution_failed(run)):
            due = companion("resource_audit").mark_due(
                state, run["output_resource"], "record-" + hashlib.sha256(args.run.encode()).hexdigest()[:32],
                "test-record-validated", str(record_path(state_path, run)),
                owner=run.get("owner"))
        save(state_path, state)
        return {"run": args.run, "summary_recorded": True, "release_due": due}


def resolve(args):
    if not args.reason.strip():
        raise Refusal("resolution needs a nonempty reason")
    with locked(args.state) as (state_path, state):
        run = completed_run(state_path, state, args.run)
        if run["test"] and "summary" not in run:
            raise Refusal("record test evidence before resolving failure")
        if run.get("resolution"):
            raise Refusal("failure already resolved; evidence is immutable")
        if run.get("execution_contract"):
            classification = run.get("classification", {})
            if classification.get("kind") not in ["business", "evidence", "harness", "environment"]:
                raise Refusal("classify the interruption before resolving its acceptance blocker")
            if not (getattr(args, "validation", "") or "").strip():
                raise Refusal("supervised failures require --validation evidence before resolution")
        if (run["exit_code"] == 0 and not (run.get("execution_contract") and execution_failed(run)) and
                not ("summary" in run and (run["summary"]["tests"]["failed"] or run["summary"]["tests"]["errors"]))):
            raise Refusal("command has no recorded failure to resolve")
        run["resolution"] = {"reason": args.reason, "at": now()}
        if run.get("execution_contract"):
            run["resolution"]["validation"] = args.validation
        write_record(state_path, run)
        due = companion("resource_audit").mark_due(
            state, run["output_resource"], "resolve-" + hashlib.sha256(args.run.encode()).hexdigest()[:32],
            "failure-resolved", str(record_path(state_path, run)), owner=run.get("owner"))
        save(state_path, state)
        return {"run": args.run, "resolved": True, "release_due": due}


def recover_run(args):
    if not args.stopped_confirmed or not args.reason.strip():
        raise Refusal("owner must verify wrapper, child and descendants stopped and give --stopped-confirmed --reason")
    with locked(args.state) as (state_path, state):
        checked_id(args.run)
        if args.run not in state["runs"]:
            raise Refusal("unknown command ID")
        run = state["runs"][args.run]
        if run["status"] not in ["running", "unknown", "recovering"]:
            raise Refusal("recover-run is only for uncertain commands")
        run["recovery"] = {"previous_status": run["status"], "reason": args.reason,
                           "stopped_confirmed_at": now()}
        run["status"] = "recovering"
        save(state_path, state)
    try:
        log_hashes = {}
        for name, filename in run["logs"].items():
            path = plain_path(filename)
            if path.is_file():
                log_hashes[name] = digest(path)
    except BaseException as error:
        with locked(args.state) as (state_path, state):
            state["runs"][args.run]["recovery_error"] = str(error) or type(error).__name__
            save(state_path, state)
        raise
    with locked(args.state) as (state_path, state):
        run = state["runs"][args.run]
        if run["status"] != "recovering":
            raise Refusal("command changed during recovery; retain and investigate")
        run.update(status="completed", outcome="interrupted", exit_code=130, ended_at=now())
        run["log_sha256"] = log_hashes
        run["logs_may_be_incomplete"] = True
        write_record(state_path, run)
        companion("resource_capacity").finish(state, "run", args.run, helper_api())
        save(state_path, state)
        return {"run": args.run, "status": "completed", "outcome": "interrupted",
                "next": "record-test if applicable, then resolve before release"}


def handoff(args):
    if not args.owner.strip():
        raise Refusal("owner cannot be empty")
    with locked(args.state) as (state_path, state):
        item = resource(state, args.resource)
        verify_resource(state, item)
        if item.get("resource_audit", {}).get("due"):
            raise Refusal("resource has a release obligation; use disposition handoff and accept for that event")
        item.setdefault("handoffs", []).append({"from": item["owner"], "to": args.owner, "at": now()})
        item["owner"] = args.owner
        save(state_path, state)
        return {"resource": args.resource, "owner": args.owner, "path": item["path"]}


def check_data_tree(path):
    device = os.lstat(path).st_dev
    mounts = mount_points()
    for current, dirs, files in os.walk(path, followlinks=False):
        for name in [*dirs, *files]:
            info = os.lstat(Path(current) / name)
            if not stat.S_ISLNK(info.st_mode) and (info.st_dev != device or is_mount_path(Path(current) / name, mounts)):
                raise Refusal("data contains a nested mount; retain and review manually")


def check_external_failure_scenes(state, item):
    """A disposable scratch checkout may go; its unresolved evidence may not."""
    scratch = Path(item["path"])
    for run in state["runs"].values():
        if item["id"] not in run["uses"] or run.get("resolution"):
            continue
        failed = (bool(run.get("execution_contract")) and execution_failed(run)) or run["exit_code"] != 0 or ("summary" in run and (
            run["summary"]["tests"]["failed"] or run["summary"]["tests"]["errors"]))
        if not failed:
            continue
        for name in run["uses"]:
            data = state["resources"][name]
            if data["kind"] == "data":
                data = resource(state, name)
                path = verify_resource(state, data)
                if within(path, scratch):
                    raise Refusal("unresolved failure input/output is inside scratch; preserve it outside first")
        output = resource(state, run["output_resource"])
        output_path = verify_resource(state, output)
        if set(run.get("log_sha256", {})) != {"stdout", "stderr"}:
            raise Refusal("failed scratch run has incomplete capture; retain checkout or resolve diagnosis")
        for name, expected_hash in run["log_sha256"].items():
            filename = output_path / (run["id"] + "." + name + ".gz")
            if str(filename) != run["logs"][name] or filename.is_symlink() or not filename.is_file():
                raise Refusal("failed scratch evidence path is missing or unsafe")
            if digest(filename) != expected_hash:
                raise Refusal("failed scratch raw evidence hash changed; retain checkout")


def release_preflight(state_path, state, name, merged_into=None,
                      idle_confirmed=False, evidence_confirmed=False):
    """One checker for explicit inspection and deletion; no deletion permission is cached."""
    result = {"resource": name, "checked_at": now(), "machine_blockers": [],
              "owner_checks_required": [], "merged_into": merged_into}
    if not idle_confirmed:
        result["owner_checks_required"].append("confirm all external users and descendant processes are idle")
    if not evidence_confirmed:
        result["owner_checks_required"].append("validate saved delivery and sufficient diagnostic/reproduction evidence")
    try:
        item = resource(state, name)
        path = verify_resource(state, item)
        scratch = item["kind"] == "worktree" and item["role"] in ["scratch", "checkpoint"]
        result["machine_blockers"].extend(release_blockers(
            state_path, state, name, allow_scratch_failure=scratch))
        result["usage_generation"] = item.get("resource_audit", {}).get("usage_generation", 0)
        if result["machine_blockers"]:
            return result
        if scratch:
            check_external_failure_scenes(state, item)
        if item["kind"] == "worktree":
            if git(path, "status", "--porcelain", "--untracked-files=all").stdout:
                raise Refusal("worktree has dirty/untracked files; save them before release")
            ignored = git(path, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").stdout
            if any(entry for entry in ignored.split(b"\0")):
                raise Refusal("worktree has ignored files; review and clean exact generated paths first")
            head = git_text(path, "rev-parse", "HEAD")
            result["head"] = head
            if merged_into:
                target = git_text(state["repo"], "rev-parse", "--verify", merged_into + "^{commit}")
                if git(state["repo"], "merge-base", "--is-ancestor", head, target, check=False).returncode:
                    raise Refusal("worktree HEAD is not an ancestor of --merged-into")
                result["target_revision"] = target
            elif not scratch:
                raise Refusal("non-scratch worktree requires --merged-into")
        else:
            if merged_into:
                raise Refusal("--merged-into applies only to worktrees")
            check_data_tree(path)
            if not shutil.rmtree.avoids_symlink_attacks:
                raise Refusal("platform lacks safe descriptor-relative deletion; retain data")
    except (Refusal, OSError, ValueError) as error:
        result["machine_blockers"].append(str(error))
    return result


def preflight(args):
    with locked(args.state) as (state_path, state):
        checked_id(args.resource)
        if args.resource not in state["resources"]:
            raise Refusal("unknown resource: " + args.resource)
        assessment = release_preflight(state_path, state, args.resource,
            getattr(args, "merged_into", None), getattr(args, "idle_confirmed", False),
            getattr(args, "evidence_confirmed", False))
        companion("resource_audit").record_assessment(state, args.resource, assessment)
        save(state_path, state)
        return assessment


def release(args):
    with locked(args.state) as (state_path, state):
        checked_id(args.resource)
        if args.resource not in state["resources"]:
            raise Refusal("unknown resource: " + args.resource)
        audit = companion("resource_audit")
        assessment = release_preflight(state_path, state, args.resource,
            args.merged_into, args.idle_confirmed, evidence_confirmed=True)
        audit.record_assessment(state, args.resource, assessment)
        reasons = assessment["machine_blockers"] + assessment["owner_checks_required"]
        if reasons:
            audit.record_release(state, args.resource, "blocked", reason="; ".join(reasons))
            save(state_path, state)
            raise Refusal("; ".join(reasons))
        item = state["resources"][args.resource]
        path = Path(item["path"])
        item["status"] = "releasing"
        item["release_started_at"] = now()
        save(state_path, state)
    try:
        # Wrapped users cannot start once the resource is marked releasing.
        verify_resource(state, item)
        released_bytes = tree_size(path)
        if item["kind"] == "worktree":
            head = assessment["head"]
            if args.merged_into:
                item["merged_into"] = {"ref": args.merged_into, "revision": assessment["target_revision"]}
            anchor = "refs/implement-spec-runs/{}/{}".format(state["invocation"], item["id"])
            git(state["repo"], "update-ref", anchor, head)
            item["preserved_revision"] = head
            item["preserved_ref"] = anchor
            with locked(args.state) as (state_path, latest):
                item["resource_audit"] = latest["resources"][args.resource].get("resource_audit", {})
                latest["resources"][args.resource] = item
                save(state_path, latest)
            git(state["repo"], "worktree", "remove", "--", str(path))
        else:
            check_data_tree(path)
            # CPython uses descriptor-relative traversal where the OS supports it;
            # refuse destructive operation when it cannot resist symlink swaps.
            if not shutil.rmtree.avoids_symlink_attacks:
                raise Refusal("platform lacks safe descriptor-relative deletion; retain data")
            shutil.rmtree(path)
    except BaseException as error:
        with locked(args.state) as (state_path, latest):
            current = latest["resources"][args.resource]
            current["status"] = "releasing" if isinstance(error, KeyboardInterrupt) else "active"
            current["release_error"] = str(error) or type(error).__name__
            audit.record_release(latest, args.resource, "error", reason=current["release_error"])
            save(state_path, latest)
        raise
    with locked(args.state) as (state_path, state):
        item = state["resources"][args.resource]
        item.update(status="released", released_at=now(), released_bytes=released_bytes,
                    idle_confirmed_at=now())
        item.pop("release_error", None)
        state["resources"][args.resource] = item
        audit.record_release(state, args.resource, "released")
        save(state_path, state)
        return {"resource": args.resource, "released": True, "logical_bytes": released_bytes}


def status(args):
    with locked(args.state) as (state_path, state):
        snapshot_at = now()
    output = []
    for item in state["resources"].values():
        row = {key: item.get(key) for key in ["id", "kind", "path", "role", "owner", "status", "parent", "resource_audit", "reservations"]}
        scratch = item["kind"] == "worktree" and item["role"] in ["scratch", "checkpoint"]
        row["reasons"] = release_blockers(state_path, state, item["id"], allow_scratch_failure=scratch) if item["status"] != "released" else []
        for field in ["creation_error", "release_error"]:
            if item.get(field) and item["status"] != "released":
                row["reasons"].append(item[field])
        row["logical_bytes"] = 0 if item["status"] == "released" else None
        if item["status"] == "active":
            try:
                path = verify_resource(state, item)
                if args.measure:
                    row["logical_bytes"] = tree_size(path)
            except (OSError, Refusal) as error:
                row["reasons"].append(str(error))
        elif item["status"] != "released":
            row["reasons"].append("incomplete {} operation; retain and investigate".format(item["status"]))
        if item["status"] == "active" and not row["reasons"]:
            row["reasons"] = ["owner must confirm external processes idle; worktree also needs clean/merge checks"]
        output.append(row)
    top_level = [row for row in output if not row["parent"] or
                 state["resources"][row["parent"]]["status"] == "released"]
    complete_measurement = args.measure and all(row["logical_bytes"] is not None for row in top_level)
    return {"invocation": state["invocation"], "snapshot_at": snapshot_at, "resources": output,
            "remaining_bytes": sum(row["logical_bytes"] or 0 for row in top_level) if complete_measurement else None,
            "released_bytes": sum(item.get("released_bytes", 0) for item in state["resources"].values()),
            "runs": [{key: run.get(key) for key in ["id", "status", "pid", "exit_code", "test",
                       "formal_acceptance", "outcome", "acceptance_qualified", "failure_key", "retry_of"]}
                     for run in state["runs"].values()], "bytes_are": "logical, not allocated blocks",
            "acceptance": acceptance_assessment(state_path, state),
            "capacity": companion("resource_capacity").report(state),
            "audit": state.get("resource_audit", {}),
            "release_checks": "reasons are partial ledger checks; use preflight for an explicit shared release check"}


def capacity(args):
    return companion("resource_capacity").dispatch("capacity", args, helper_api())


def capacity_snapshot(state):
    """At most one free-space probe per registered filesystem, without tree scans."""
    module = companion("resource_capacity")
    summary = module.report(state)
    samples = []
    seen = set()
    for item in state.get("reservations", {}).values():
        if item["status"] != "open" or item["filesystem"] in seen:
            continue
        seen.add(item["filesystem"])
        try:
            path = plain_path(item["path"])
            if identity(path) != item["identity"]:
                raise Refusal("reservation destination identity changed")
            sample = module._capacity(state, path, 0, 0, helper_api())
            sample["action"] = "none" if sample["admit"] else "reconcile_owned_capacity"
        except (Refusal, OSError, ValueError) as error:
            sample = {"filesystem": item["filesystem"], "action": "verify_capacity", "error": str(error)}
        samples.append(sample)
    return {"enabled": summary["enabled"], "filesystems": samples,
            "scope": "registered destinations in this invocation; no global reservation or quota"}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="action", required=True)
    command = commands.add_parser("init")
    command.add_argument("--state-dir", required=True)
    command.add_argument("--repo", required=True)
    command.add_argument("--notes-root", help="new or empty invocation notes root containing the state directory")
    command.add_argument("--index-root", help="cleanup discovery index outside the notes root")
    for name in ["create", "run", "record-test", "resolve", "classify-run", "acceptance-status", "execution-status", "recover-run", "handoff", "release", "preflight", "status", "capacity", "publish-branch", "bind-pr", "seal"]:
        commands.add_parser(name).add_argument("--state", required=True)
    command = commands.choices["publish-branch"]
    command.add_argument("--resource", required=True)
    command.add_argument("--remote-url", required=True, help="exact native REST head.repo.clone_url")
    command = commands.choices["bind-pr"]
    command.add_argument("--pr-json", required=True, help="fresh native REST PR JSON")
    command.add_argument("--pr-resource", required=True)
    command.add_argument("--index-root")
    commands.choices["seal"].add_argument("--pr-json", required=True, help="fresh native REST PR JSON with final head")
    commands.choices["seal"].add_argument("--acceptance-run", help="qualified run at the delivered revision")
    commands.choices["seal"].add_argument("--acceptance-scope", help="approved complete acceptance scope JSON")
    command = commands.choices["create"]
    command.add_argument("--id", required=True)
    command.add_argument("--kind", choices=["worktree", "data"], required=True)
    command.add_argument("--path", required=True)
    command.add_argument("--role", required=True)
    command.add_argument("--owner", help="concrete agent/task owner; defaults to role for older callers")
    command.add_argument("--ref")
    command.add_argument("--branch")
    command.add_argument("--parent")
    command = commands.choices["run"]
    command.add_argument("--id", required=True)
    command.add_argument("--cwd-resource", required=True)
    command.add_argument("--output-resource", required=True)
    command.add_argument("--uses", action="append", nargs="+", default=[])
    command.add_argument("--test", action="store_true")
    command.add_argument("--acceptance", action="store_true", help="formal acceptance; requires verified external supervision")
    command.add_argument("--execution-contract", help="sourced finite execution budgets and adapter contract")
    command.add_argument("--execution-gate", help="verified supervisor and actual runner gate receipt")
    command.add_argument("--failure-key", help="stable logical failure chain; survives run IDs and agent replacement")
    command.add_argument("--retry-of", help="prior classified run; at most one automatic recovery per failure chain")
    command.add_argument("--recovery-evidence", help="proof pointers for isolation, fixture reset and repeatability")
    command.add_argument("--validate-after", help="latest attempt followed by a justified repair and new verification")
    command.add_argument("--repair-evidence", help="new repair/review findings supporting this validation")
    command.add_argument("--repair-round", type=int, help="next consecutive repair round in the original budget")
    command.add_argument("--repair-limit", type=int, choices=[1, 2, 3], help="fixed initial repair budget; checkpoint 1-2, final default 3")
    command.add_argument("--contract-change-evidence", help="authoritative adjudication and test-review pointers for a changed execution policy")
    command.add_argument("--owner", help="reservation owner for this command; defaults to cwd resource owner")
    command.add_argument("command", nargs=argparse.REMAINDER)
    command = commands.choices["record-test"]
    command.add_argument("--run", required=True)
    command.add_argument("--summary", required=True)
    command = commands.choices["resolve"]
    command.add_argument("--run", required=True)
    command.add_argument("--reason", required=True)
    command.add_argument("--validation", help="required validation evidence for supervised failure resolution")
    command = commands.choices["classify-run"]
    command.add_argument("--run", required=True)
    command.add_argument("--classification", choices=["business", "evidence", "harness", "environment", "unknown"], required=True)
    command.add_argument("--evidence", required=True)
    command = commands.choices["execution-status"]
    command.add_argument("--run", required=True)
    command.add_argument("--lock-timeout", type=float, default=5, help="finite metadata lock allowance, default 5 seconds")
    command = commands.choices["recover-run"]
    command.add_argument("--run", required=True)
    command.add_argument("--stopped-confirmed", action="store_true")
    command.add_argument("--reason", required=True)
    command = commands.choices["handoff"]
    command.add_argument("--resource", required=True)
    command.add_argument("--owner", required=True)
    command = commands.choices["release"]
    command.add_argument("--resource", required=True)
    command.add_argument("--idle-confirmed", action="store_true")
    command.add_argument("--merged-into")
    command = commands.choices["preflight"]
    command.add_argument("--resource", required=True)
    command.add_argument("--merged-into")
    command.add_argument("--idle-confirmed", action="store_true")
    command.add_argument("--evidence-confirmed", action="store_true")
    command = commands.choices["capacity"]
    command.add_argument("--next-bytes", type=int, required=True)
    command.add_argument("--reserve-bytes", type=int, required=True)
    command.add_argument("--path", help="existing parent directory on the next resource's filesystem")
    commands.choices["status"].add_argument("--measure", action="store_true", help="measure owned directories once; logical bytes")
    companion("resource_capacity").add_commands(commands)
    companion("resource_audit").add_commands(commands)
    return result


def main():
    args = parser().parse_args()
    actions = {"init": init, "create": create, "run": run_command,
               "record-test": record_test, "resolve": resolve, "classify-run": classify_run,
               "acceptance-status": acceptance_status, "execution-status": execution_status,
               "recover-run": recover_run, "handoff": handoff,
               "release": release, "preflight": preflight, "status": status, "capacity": capacity,
               "publish-branch": publish_branch, "bind-pr": bind_pr, "seal": seal}
    try:
        if args.action in ["reserve", "reservation"]:
            result = companion("resource_capacity").dispatch(args.action, args, helper_api())
        elif args.action in companion("resource_audit").ACTIONS:
            result = companion("resource_audit").dispatch(args.action, args, helper_api())
        else:
            result = actions[args.action](args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.action == "run":
            return 1 if (result["status"] != "completed" or result["exit_code"] != 0 or
                         (getattr(args, "acceptance", False) and not result.get("acceptance_qualified"))) else 0
        return 0
    except (Refusal, OSError, ValueError) as error:
        print(json.dumps({"error": str(error), "ledger_not_released": True}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
