"""Bounded, Linux-only acceptance execution with a trusted runner event adapter.

The adapter supplies semantic boundaries; this module supplies independent
monotonic deadlines and an invocation-owned process session. It never retries
product work or converts a harness interruption into a product verdict.
"""

import argparse
import copy
import ctypes
import errno
import gzip
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time


VERSION = 1
MAX_JSON = 256 * 1024
MAX_EVENT = 16 * 1024
MAX_WORKERS = 128
MAX_DIAGNOSTICS = 64
MAX_PROGRESS_TOKENS = 4096
PHASES = ("setup", "run", "cleanup")
ENV_ATTEMPT = "IMPLEMENT_SPEC_ATTEMPT_ID"
ENV_EVENTS = "IMPLEMENT_SPEC_EVENTS_PATH"
ENV_GATE = "IMPLEMENT_SPEC_EXECUTION_GATE"
ENV_NONCE = "IMPLEMENT_SPEC_GATE_NONCE"
ENV_SCENARIO = "IMPLEMENT_SPEC_GATE_SCENARIO"
_gate_context = threading.local()


class Refusal(ValueError):
    """The configured execution cannot be qualified safely."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            result.update(chunk)
    return result.hexdigest()


def _read(path, limit=MAX_JSON):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise Refusal("expected a bounded ordinary JSON file: " + str(path))
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise Refusal("invalid JSON: " + str(path)) from error


def _write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(6))
    try:
        with open(temporary, "x") as stream:
            json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _budget(value, name):
    if not isinstance(value, dict) or set(value) != {"seconds", "source"}:
        raise Refusal(name + " requires seconds and source")
    seconds = value["seconds"]
    try:
        finite = type(seconds) in (int, float) and math.isfinite(seconds)
    except OverflowError:
        finite = False
    if not finite or seconds <= 0:
        raise Refusal(name + " seconds must be finite and positive")
    if not isinstance(value["source"], str) or not value["source"].strip():
        raise Refusal(name + " requires a nonempty budget source")


def _contract(value):
    if not isinstance(value, dict) or type(value.get("version")) is not int or value.get("version") != VERSION:
        raise Refusal("unsupported execution contract version")
    required = {"version", "budgets", "adapter"}
    optional = {"long_cases", "case_profiles", "progress_kinds"}
    if not required <= set(value) or set(value) - required - optional:
        raise Refusal("execution contract has missing or unknown fields")
    budgets = value["budgets"]
    if not isinstance(budgets, dict) or set(budgets) != {"total", "shutdown", "case", "phase", "stall"}:
        raise Refusal("budgets require total, shutdown, case, phase and stall")
    for name in ("total", "shutdown", "case", "stall"):
        _budget(budgets[name], name)
    if budgets["shutdown"]["seconds"] >= budgets["total"]["seconds"]:
        raise Refusal("shutdown must be smaller than the inclusive total horizon")
    if not isinstance(budgets["phase"], dict) or set(budgets["phase"]) != set(PHASES):
        raise Refusal("phase budgets require setup, run and cleanup")
    for name in PHASES:
        _budget(budgets["phase"][name], "phase." + name)
    for name in ("long_cases", "case_profiles"):
        entries = value.get(name, {})
        if not isinstance(entries, dict):
            raise Refusal(name + " must be a budget map")
        for key, budget in entries.items():
            if not isinstance(key, str) or not key.strip():
                raise Refusal(name + " keys must be nonempty strings")
            _budget(budget, name + "." + key)
    kinds = value.get("progress_kinds", [])
    if not isinstance(kinds, list) or any(not isinstance(k, str) or not k.strip() for k in kinds) or len(set(kinds)) != len(kinds):
        raise Refusal("progress_kinds must contain distinct nonempty strings")
    adapter = value["adapter"]
    if not isinstance(adapter, dict) or set(adapter) != {"files", "environment"}:
        raise Refusal("adapter requires files and environment")
    for name in ("files", "environment"):
        entries = adapter[name]
        if not isinstance(entries, list) or any(not isinstance(v, str) or not v.strip() for v in entries) or len(set(entries)) != len(entries):
            raise Refusal("adapter." + name + " must contain distinct strings")
    if not adapter["files"]:
        raise Refusal("an adapter source fingerprint is required")
    if set(adapter["environment"]) & {ENV_ATTEMPT, ENV_EVENTS, ENV_GATE, ENV_NONCE, ENV_SCENARIO}:
        raise Refusal("injected execution variables cannot be adapter environment bindings")
    return copy.deepcopy(value)


def read_contract(path):
    """Read the public version-1 contract, retaining every budget's source."""
    return _contract(_read(path))


def _platform():
    if not sys.platform.startswith("linux") or not Path("/proc/self/stat").is_file():
        raise Refusal("Linux /proc process ownership is required; native-equivalent proofs are not supported here")
    if not hasattr(ctypes.CDLL(None), "prctl"):
        raise Refusal("Linux subreaper capability is unavailable")


def _identity(pid):
    try:
        raw = Path("/proc/{}/stat".format(pid)).read_text()
        fields = raw[raw.rindex(")") + 2:].split()
        return {"pid": int(pid), "parent": int(fields[1]), "group": int(fields[2]),
                "session": int(fields[3]), "start_ticks": int(fields[19]), "state": fields[0]}
    except (OSError, ValueError, IndexError):
        return None


def _same(first, second):
    return second is not None and first["pid"] == second["pid"] and first["start_ticks"] == second["start_ticks"]


def _scan(root, known):
    """The live subreaper keeps orphaned descendants attached to this root."""
    processes = {}
    errors = []
    try:
        for name in os.listdir("/proc"):
            if name.isdigit():
                identity = _identity(int(name))
                if identity:
                    processes[identity["pid"]] = identity
    except OSError as error:
        errors.append(str(error))
    owned = {pid for pid, old in known.items() if _same(old, processes.get(pid))}
    owned.add(root["pid"])
    changed = True
    while changed:
        changed = False
        for pid, item in processes.items():
            if item["parent"] in owned and pid not in owned:
                owned.add(pid)
                changed = True
    live, escaped = [], []
    for pid in owned:
        item = processes.get(pid)
        if item is None:
            continue
        if pid == root["pid"] and not _same(root, item):
            errors.append("root PID identity changed")
            continue
        known[pid] = item
        if item["state"] == "Z":
            continue
        if item["session"] != root["session"]:
            escaped.append(item)
        else:
            live.append(item)
    return live, escaped, errors


def _signal_owned(items, sig, root):
    errors = []
    # Signal identities individually, never a shared or recycled process group.
    for item in sorted(items, key=lambda x: x["pid"] == root["pid"]):
        current = _identity(item["pid"])
        if not _same(item, current) or current["session"] != root["session"]:
            continue
        try:
            os.kill(item["pid"], sig)
        except ProcessLookupError:
            pass
        except OSError as error:
            errors.append(str(error))
    return errors


class _Events:
    def __init__(self, contract, attempt, started, alert):
        self.contract, self.attempt, self.started, self.alert = contract, attempt, started, alert
        self.workers = {}
        self.errors = []
        self.ignored = 0
        self.gate_nonces = []
        self.offset = 0
        self.pending = b""
        self.file_identity = None
        self.case_count = 0

    def error(self, value):
        if value not in self.errors and len(self.errors) < MAX_DIAGNOSTICS:
            self.errors.append(value)

    def read(self, path, at):
        try:
            # A replaced FIFO/device or symlink must not block the supervisor.
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise Refusal("event channel is not an ordinary file")
                identity = (info.st_dev, info.st_ino)
                if self.file_identity is not None and self.file_identity != identity:
                    raise Refusal("event channel identity changed")
                self.file_identity = identity
                if info.st_size < self.offset:
                    raise Refusal("event channel was truncated")
                os.lseek(fd, self.offset, os.SEEK_SET)
                data = os.read(fd, 65536)
                self.offset += len(data)
            finally:
                os.close(fd)
            self.pending += data
            lines = self.pending.split(b"\n")
            self.pending = lines.pop()
            for line in lines:
                if len(line) > MAX_EVENT:
                    self.error("event exceeds bounded frame size")
                    continue
                try:
                    event = json.loads(line)
                    self.apply(event, at)
                except (ValueError, TypeError, KeyError, Refusal) as error:
                    self.error(str(error))
            if len(self.pending) > MAX_EVENT:
                self.error("unterminated event exceeds bounded frame size")
                self.pending = b""
        except FileNotFoundError:
            pass
        except (OSError, Refusal) as error:
            if str(error) not in self.errors:
                self.error(str(error))

    def apply(self, event, at):
        if not isinstance(event, dict) or type(event.get("version")) is not int or event.get("version") != VERSION:
            raise Refusal("unsupported event frame")
        if event.get("attempt_id") != self.attempt:
            self.ignored += 1
            return
        worker = event.get("worker_id")
        if not isinstance(worker, str) or not worker:
            raise Refusal("event requires worker_id")
        kind = event.get("kind")
        if kind == "gate_ready":
            item = self.workers.get(worker)
            if (item and not item["ended"] and item["phase"] == "run" and item["case_id"] and
                    item["completed_phases"] == ["setup"] and isinstance(event.get("nonce"), str)):
                if len(self.gate_nonces) < MAX_DIAGNOSTICS:
                    self.gate_nonces.append(event["nonce"])
            else:
                raise Refusal("gate_ready requires a current case after completed setup")
            return
        if kind == "worker_start":
            if worker in self.workers:
                raise Refusal("duplicate worker_start")
            if len(self.workers) >= MAX_WORKERS:
                raise Refusal("event worker inventory exceeds bounded capacity")
            self.workers[worker] = {"phase": None, "case_id": None, "completed_phases": [],
                "ended": False, "phase_at": at, "case_at": None, "last_progress_at": at,
                "progress_status": "unknown", "last_progress_evidence": None, "evidence_seen": set(),
                "stall_reported": False, "cases": 0}
            return
        if kind == "heartbeat":
            self.ignored += 1
            return
        item = self.workers.get(worker)
        if item is None or item["ended"]:
            self.ignored += 1
            return
        if kind == "phase_start":
            phase = event.get("phase")
            index = len(item["completed_phases"])
            if item["phase"] is not None or index >= len(PHASES) or phase != PHASES[index]:
                raise Refusal("phase boundary is missing, overlapping or out of order")
            item.update(phase=phase, phase_at=at, last_progress_at=at, stall_reported=False,
                        progress_status="unknown", last_progress_evidence=None)
        elif kind == "phase_end":
            if event.get("phase") != item["phase"] or item["phase"] is None or item["case_id"] is not None:
                raise Refusal("phase_end does not match the current phase")
            item["completed_phases"].append(item["phase"])
            item["phase"] = None
        elif kind == "case_start":
            case = event.get("case_id")
            profile = event.get("profile")
            if item["phase"] != "run" or item["case_id"] is not None or not isinstance(case, str) or not case:
                raise Refusal("case_start requires one current case within run")
            if profile is not None and profile not in self.contract.get("case_profiles", {}):
                raise Refusal("case profile is undeclared")
            budget = self.contract.get("long_cases", {}).get(case)
            if budget is None:
                budget = self.contract.get("case_profiles", {}).get(profile, self.contract["budgets"]["case"])
            item.update(case_id=case, case_at=at, case_seconds=budget["seconds"], case_budget=budget, last_progress_at=at,
                        progress_status="unknown", last_progress_evidence=None, stall_reported=False)
            item["cases"] += 1
            self.case_count += 1
        elif kind == "case_end":
            if item["case_id"] is None or event.get("case_id") != item["case_id"]:
                raise Refusal("case_end does not match current case")
            item.update(case_id=None, case_at=None)
        elif kind == "progress":
            evidence = event.get("evidence")
            progress_kind = event.get("progress_kind")
            token = (item["case_id"], progress_kind, evidence) if isinstance(evidence, str) else None
            if (item["case_id"] is None or event.get("case_id") != item["case_id"] or
                    progress_kind not in self.contract.get("progress_kinds", []) or
                    not isinstance(evidence, str) or not evidence.strip() or token in item["evidence_seen"]):
                self.ignored += 1
                return
            if len(item["evidence_seen"]) >= MAX_PROGRESS_TOKENS:
                raise Refusal("progress evidence inventory exceeds bounded capacity")
            item["evidence_seen"].add(token)
            item.update(last_progress_at=at, progress_status="observed", last_progress_evidence=evidence,
                        stall_reported=False)
        elif kind == "worker_end":
            if item["phase"] is not None or item["case_id"] is not None or item["completed_phases"] != list(PHASES):
                raise Refusal("worker_end requires completed setup/run/cleanup boundaries")
            item["ended"] = True
        else:
            self.ignored += 1

    def deadline(self, at, payload_deadline=None):
        # A delayed observation may cross several caps. Classify the first
        # absolute expiry, rather than whichever worker/category is visited first.
        deadlines = []
        if payload_deadline is not None:
            deadlines.append((payload_deadline, 0, "total_timeout", None))
        for worker, item in self.workers.items():
            if item["ended"]:
                continue
            if item["phase"] is not None:
                deadlines.append((item["phase_at"] + self.contract["budgets"]["phase"][item["phase"]]["seconds"],
                                  2, "phase_timeout", worker))
            if item["case_id"] is not None:
                deadlines.append((item["case_at"] + item["case_seconds"], 1, "case_timeout", worker))
        expired = [item for item in deadlines if item[0] <= at]
        if expired:
            first = min(expired, key=lambda item: item[:2])
            return first[2], first[3]
        for worker, item in self.workers.items():
            if item["ended"]:
                continue
            if item["phase"] is not None and not item["stall_reported"] and at >= item["last_progress_at"] + self.contract["budgets"]["stall"]["seconds"]:
                item["stall_reported"] = True
                self.alert({"kind": "execution-alert", "reason": "stall_suspected" if self.contract.get("progress_kinds") else "progress_unknown",
                    "worker_id": worker, "case_id": item["case_id"], "phase": item["phase"],
                    "progress_status": item["progress_status"], "action": "owner_diagnosis",
                    **self.context(worker),
                    "elapsed_seconds": at - self.started})
        return None, None

    def context(self, worker):
        item = self.workers.get(worker, {})
        case = item.get("case_id")
        case_budget = self.contract.get("long_cases", {}).get(case)
        if case_budget is None and case is not None:
            case_budget = item.get("case_budget", self.contract["budgets"]["case"])
        return {"case_id": case, "phase": item.get("phase"),
                "progress_status": item.get("progress_status", "unknown"),
                "last_progress_evidence": item.get("last_progress_evidence"),
                "case_budget": case_budget,
                "phase_budget": self.contract["budgets"]["phase"].get(item.get("phase")),
                "stall_budget": self.contract["budgets"]["stall"],
                "total_budget": self.contract["budgets"]["total"]}

    def qualified(self):
        return bool(self.workers) and self.case_count > 0 and not self.errors and not self.pending.strip() and all(
            item["ended"] and item["cases"] > 0 for item in self.workers.values())

    def report(self):
        return {"workers": {worker: {k: v for k, v in item.items() if k != "evidence_seen"}
                            for worker, item in self.workers.items()},
                "events_ignored": self.ignored, "event_errors": self.errors}


class _HashedFile:
    """Hash the compressed bytes as written, without a post-deadline reread."""
    def __init__(self, path):
        self.file = open(path, "xb")
        self.hash = hashlib.sha256()

    def write(self, value):
        written = self.file.write(value)
        self.hash.update(value[:written])
        return written

    def flush(self):
        self.file.flush()

    def close(self):
        self.file.close()


def _live_identity(item):
    current = _identity(item["pid"])
    return _same(item, current) and current["state"] != "Z"


def supervise(command, cwd, logs, contract, attempt_id, *, events_path, alerts_path, on_start=None):
    """Execute once. The total horizon includes a pre-reserved shutdown window."""
    _platform()
    contract = _contract(contract)
    if not isinstance(command, (list, tuple)) or not command or any(not isinstance(v, str) for v in command):
        raise Refusal("command must be a nonempty string argv")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise Refusal("attempt_id is required")
    if set(logs) != {"stdout", "stderr"}:
        raise Refusal("logs require stdout and stderr gzip paths")
    paths = {key: Path(value).absolute() for key, value in logs.items()}
    event_path, alert_path = Path(events_path).absolute(), Path(alerts_path).absolute()
    terminal_path = Path(str(event_path) + ".terminal.json")
    all_paths = [*paths.values(), event_path, alert_path, terminal_path]
    if len(set(all_paths)) != len(all_paths):
        raise Refusal("execution evidence paths must be distinct")
    for path in all_paths:
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            raise Refusal("evidence paths must be new and have existing parents: " + str(path))
    cwd = str(Path(cwd).resolve(strict=True))
    env = os.environ.copy()
    env[ENV_ATTEMPT], env[ENV_EVENTS] = attempt_id, str(event_path)
    # A leftover user environment flag cannot turn acceptance into a gate probe.
    nonce = getattr(_gate_context, "nonce", None)
    if nonce is None:
        env.pop(ENV_GATE, None)
        env.pop(ENV_NONCE, None)
        env.pop(ENV_SCENARIO, None)
    else:
        env[ENV_GATE], env[ENV_NONCE] = "1", nonce
        env[ENV_SCENARIO] = _gate_context.scenario
    started = time.monotonic()
    total = contract["budgets"]["total"]["seconds"]
    shutdown = contract["budgets"]["shutdown"]["seconds"]
    horizon, payload_deadline = started + total, started + total - shutdown
    capture_errors, identity_errors = [], []
    captured, targets, streams = {}, {}, {}
    selector = selectors.DefaultSelector()
    process, root = None, None
    known = {}
    escaped = []
    outcome, reason_worker = None, None
    stopping_at = None
    kill_sent = False
    alert_file = None
    registration_done = threading.Event()
    registration_errors = []

    def alert(value):
        value = dict(value, version=VERSION, attempt_id=attempt_id)
        alert_file.write(json.dumps(value, sort_keys=True) + "\n")
        alert_file.flush()

    observer = _Events(contract, attempt_id, started, alert)
    try:
        alert_file = open(alert_path, "x")
        for name, path in paths.items():
            targets[name] = _HashedFile(path)
            captured[name] = gzip.GzipFile(fileobj=targets[name], mode="wb", compresslevel=1)
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_worker", "--", *command],
            cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        root = _identity(process.pid)
        if root is None or root["session"] != process.pid or root["group"] != process.pid:
            raise Refusal("cannot verify the invocation-owned process session")
        known[root["pid"]] = root
        if on_start:
            def register():
                try:
                    on_start(copy.deepcopy(root))
                except BaseException as error:
                    registration_errors.append(str(error) or type(error).__name__)
                finally:
                    registration_done.set()
            threading.Thread(target=register, daemon=True).start()
        else:
            registration_done.set()
        for name in ("stdout", "stderr"):
            pipe = getattr(process, name)
            os.set_blocking(pipe.fileno(), False)
            streams[pipe.fileno()] = pipe
            selector.register(pipe, selectors.EVENT_READ, name)
        live = []
        while True:
            at = time.monotonic()
            # A late end frame cannot erase an expiry of an already observed
            # boundary. Save that deadline and its context before applying it.
            expired_before_read, worker_before_read = observer.deadline(at, payload_deadline)
            context_before_read = observer.context(worker_before_read) if expired_before_read else None
            observer.read(event_path, at)
            live, escaped_now, scan_errors = _scan(root, known)
            identity_errors.extend(error for error in scan_errors if error not in identity_errors)
            escaped.extend(item for item in escaped_now if not any(_same(item, old) for old in escaped))
            if escaped_now or identity_errors:
                outcome = "unknown"
            if registration_errors:
                capture_errors.extend(error for error in registration_errors if error not in capture_errors)
                outcome = "unknown"
            # Reading events and discovering descendants consume time too.
            at = time.monotonic()
            detected, detected_worker = observer.deadline(at, payload_deadline)
            if expired_before_read:
                detected, detected_worker = expired_before_read, worker_before_read
            if stopping_at is None and (outcome == "unknown" or detected or at >= payload_deadline):
                outcome = outcome or detected or "total_timeout"
                reason_worker = detected_worker if detected and outcome == detected else None
                stopping_at = at
                alert({"kind": "execution-alert", "reason": outcome, "worker_id": reason_worker,
                       **(context_before_read if expired_before_read and reason_worker == worker_before_read else
                          observer.context(reason_worker)),
                       "action": "capture_and_classify", "elapsed_seconds": at - started})
                identity_errors.extend(_signal_owned(live, signal.SIGTERM, root))
            if stopping_at is not None and not kill_sent and at >= min(stopping_at + shutdown / 2, horizon - shutdown / 4):
                identity_errors.extend(_signal_owned(live, signal.SIGKILL, root))
                kill_sent = True
            returncode = process.poll()
            if returncode is not None and not live and not selector.get_map() and registration_done.is_set():
                break
            if at >= horizon:
                if live:
                    identity_errors.extend(_signal_owned(live, signal.SIGKILL, root))
                break
            for key, _ in selector.select(min(0.025, max(0, horizon - at))):
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if chunk:
                        captured[key.data].write(chunk)
                    else:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                except OSError as error:
                    capture_errors.append(str(error))
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
        observer.read(event_path, time.monotonic())
    except BaseException as error:
        outcome = "unknown"
        capture_errors.append(str(error) or type(error).__name__)
        if root:
            live, escaped_now, _ = _scan(root, known)
            escaped.extend(escaped_now)
            _signal_owned(live, signal.SIGKILL, root)
    finally:
        incomplete_pipes = bool(selector.get_map())
        for key in list(selector.get_map().values()):
            try:
                key.fileobj.close()
            except OSError as error:
                capture_errors.append(str(error))
        selector.close()
        for stream in captured.values():
            try:
                stream.close()
            except OSError as error:
                capture_errors.append(str(error))
        for target in targets.values():
            try:
                target.close()
            except OSError as error:
                capture_errors.append(str(error))
        if alert_file:
            alert_file.close()
    live, escaped_now, scan_errors = _scan(root, known) if root else ([], [], ["process identity unavailable"])
    identity_errors.extend(scan_errors)
    escaped.extend(escaped_now)
    exit_code = process.poll() if process else None
    stopped = bool(root) and not live and not any(_live_identity(item) for item in escaped)
    capture_complete = not incomplete_pipes and not capture_errors
    coverage = observer.qualified() and not escaped and not identity_errors and not capture_errors
    if on_start and not registration_done.is_set():
        capture_errors.append("on_start registration did not finish within the total horizon")
        coverage = False
        outcome = "unknown"
        capture_complete = False
    if not stopped or escaped or identity_errors:
        outcome = "unknown"
    elif outcome is None:
        outcome = "completed" if coverage else "coverage_unverified"
    hashes = {name: target.hash.hexdigest() for name, target in targets.items()}
    result = {"exit_code": exit_code, "outcome": outcome, "stopped": stopped,
        "capture_complete": capture_complete, "capture_errors": capture_errors, "log_sha256": hashes,
        "process_identity": root, "owned_processes": list(known.values()), "escaped_processes": escaped,
        "identity_errors": identity_errors, "coverage_verified": coverage,
        "elapsed_seconds": time.monotonic() - started, "payload_seconds": total - shutdown,
        "total_horizon_seconds": total, "diagnostics": dict(observer.report(), deadline_reason=outcome, deadline_worker=reason_worker),
        "evidence_paths": {"events": str(event_path), "alerts": str(alert_path), "terminal": str(terminal_path)},
        "gate_nonces": observer.gate_nonces}
    _write(terminal_path, result)
    return result


def _worker(command):
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise Refusal("cannot establish an owned subreaper: " + str(ctypes.get_errno()))
    signal.signal(signal.SIGTERM, lambda *_: None)
    child = subprocess.Popen(command)
    code = child.wait()
    # An orphaned descendant remains our child, including one with a new session.
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                time.sleep(0.02)
        except ChildProcessError:
            return code if code >= 0 else 128 - code


def _binding(command, cwd, contract):
    cwd = str(Path(cwd).resolve(strict=True))
    files = []
    for name in contract["adapter"]["files"]:
        path = Path(name)
        path = path if path.is_absolute() else Path(cwd) / path
        if path.is_symlink() or not path.is_file():
            raise Refusal("adapter source is missing or not ordinary: " + str(path))
        files.append({"path": str(path.resolve()), "sha256": _sha(path)})
    environment = {name: hashlib.sha256(_canonical({"present": name in os.environ, "value": os.environ.get(name)})).hexdigest()
                   for name in contract["adapter"]["environment"]}
    return {"module_sha256": _sha(__file__), "contract_sha256": hashlib.sha256(_canonical(contract)).hexdigest(),
            "command": list(command), "cwd": cwd, "adapter_files": files,
            "environment": environment, "python": sys.version, "platform": sys.platform}


def _canary_code(mode):
    return """import json,os,subprocess,sys,time
p=os.environ['IMPLEMENT_SPEC_EVENTS_PATH']; a=os.environ['IMPLEMENT_SPEC_ATTEMPT_ID']
def event(kind,worker='main',**extra):
 with open(p,'a') as f: f.write(json.dumps(dict(version=1,attempt_id=a,worker_id=worker,kind=kind,**extra))+'\\n')
event('worker_start'); event('phase_start',phase='setup')
mode=%r
if mode=='setup_block':
 while True: time.sleep(.01)
event('phase_end',phase='setup'); event('phase_start',phase='run'); event('case_start',case_id='canary')
if mode=='heartbeat_block':
 while True:
  event('heartbeat'); print('alive',flush=True); time.sleep(.01)
if mode=='callback_block':
 time.sleep(60)
if mode=='parallel_progress':
 event('worker_start',worker='other'); event('phase_start',worker='other',phase='setup')
 event('phase_end',worker='other',phase='setup'); event('phase_start',worker='other',phase='run')
 event('case_start',worker='other',case_id='othercase')
 i=0
 while True:
  i+=1; event('progress',worker='other',case_id='othercase',progress_kind='gate_effect',evidence=str(i)); time.sleep(.01)
if mode=='bounded_progress':
 i=0
 while True:
  i+=1; event('progress',case_id='canary',progress_kind='gate_effect',evidence=str(i)); time.sleep(.01)
if mode=='noisy_events':
 while True:
  with open(p,'a') as f: f.write('x'*20000)
  print('log flood',flush=True); time.sleep(.001)
event('case_end',case_id='canary'); event('phase_end',phase='run'); event('phase_start',phase='cleanup')
if mode=='cleanup_block': time.sleep(60)
event('phase_end',phase='cleanup'); event('worker_end')
if mode=='pipe_descendant': subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
""" % mode


def _adapter_proof(terminal, contract, nonce, blocked):
    """The real adapter must reach its real run/callback boundary in both probes."""
    if (not terminal.get("stopped") or not terminal.get("capture_complete") or
            nonce not in terminal.get("gate_nonces", []) or
            terminal.get("diagnostics", {}).get("event_errors") or
            terminal.get("total_horizon_seconds") != contract["budgets"]["total"]["seconds"] or
            terminal.get("payload_seconds") != contract["budgets"]["total"]["seconds"] - contract["budgets"]["shutdown"]["seconds"] or
            terminal.get("elapsed_seconds", math.inf) > contract["budgets"]["total"]["seconds"] + .15):
        return False
    if not blocked:
        return (terminal.get("outcome") == "completed" and terminal.get("exit_code") == 0 and
                terminal.get("coverage_verified"))
    workers = terminal.get("diagnostics", {}).get("workers", {})
    return (terminal.get("outcome") in {"case_timeout", "phase_timeout", "total_timeout"} and
            any(item.get("phase") == "run" and item.get("case_id") and not item.get("ended") and
                item.get("completed_phases") == ["setup"] for item in workers.values()))


def _gate(command, cwd, contract, output):
    _platform()
    binding = _binding(command, cwd, contract)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise Refusal("gate receipt must be a new path")
    proof = output.with_name(output.name + ".evidence")
    proof.mkdir(mode=0o700)
    checks, evidence_files = {}, []

    def execute(name, argv, configuration):
        root = proof / name
        root.mkdir()
        result = supervise(argv, cwd, {key: str(root / (key + ".gz")) for key in ("stdout", "stderr")},
            configuration, "gate-" + secrets.token_hex(12), events_path=root / "events.jsonl", alerts_path=root / "alerts.jsonl")
        for path in root.iterdir():
            if path.is_file():
                evidence_files.append({"path": str(path), "sha256": _sha(path)})
        checks[name] = {"outcome": result["outcome"], "stopped": result["stopped"],
                       "capture_complete": result["capture_complete"], "coverage_verified": result["coverage_verified"],
                       "elapsed_seconds": result["elapsed_seconds"], "terminal": result["evidence_paths"]["terminal"],
                       "budgets": copy.deepcopy(configuration["budgets"]),
                       "long_cases": copy.deepcopy(configuration.get("long_cases", {}))}
        return result

    nonces = {}
    for name, scenario in (("adapter", "complete"), ("adapter_blocked", "blocked_callback")):
        nonce = secrets.token_hex(24)
        nonces[name] = nonce
        old = {key: getattr(_gate_context, key, None) for key in ("nonce", "scenario")}
        try:
            _gate_context.nonce, _gate_context.scenario = nonce, scenario
            actual = execute(name, command, contract)
        finally:
            for key, value in old.items():
                if value is None:
                    delattr(_gate_context, key)
                else:
                    setattr(_gate_context, key, value)
        checks[name]["nonce"] = nonce
        checks[name]["scenario"] = scenario
        if not _adapter_proof(actual, contract, nonce, name == "adapter_blocked"):
            raise Refusal("configured runner adapter did not prove " + scenario +
                          " through complete start boundaries and bounded supervision; evidence: " + str(proof))
    synthetic = copy.deepcopy(contract)
    # Five concurrent probe roles measured up to 1.27022s terminal latency on
    # the former 1.2s/.4s fixture. Reserve 1s for owned stop/reap/capture under
    # this load; retain its .8s active horizon and all case/phase thresholds.
    source = "Five-role concurrent gate proof measured 1.27022s terminal latency; 1s stop/reap/capture reserve, unchanged .8s active window"
    synthetic["budgets"] = {name: {"seconds": seconds, "source": source if name in {"total", "shutdown"} else "supervisor gate fixture"}
        for name, seconds in (("total", 1.8), ("shutdown", 1.0), ("case", .25), ("stall", .08))}
    synthetic["budgets"]["phase"] = {name: {"seconds": .35, "source": "supervisor gate fixture"} for name in PHASES}
    synthetic["long_cases"], synthetic["case_profiles"] = {}, {}
    synthetic["progress_kinds"] = ["gate_effect"]
    for name in ("callback_block", "heartbeat_block", "setup_block", "cleanup_block", "pipe_descendant",
                 "parallel_progress", "bounded_progress", "noisy_events"):
        configuration = copy.deepcopy(synthetic)
        expected_outcome = "case_timeout"
        if name in {"setup_block", "cleanup_block"}:
            expected_outcome = "phase_timeout"
        elif name in {"pipe_descendant", "bounded_progress"}:
            expected_outcome = "total_timeout"
        if name == "parallel_progress":
            configuration["long_cases"]["othercase"] = {"seconds": 2, "source": "parallel-worker gate fixture"}
        if name == "bounded_progress":
            configuration["budgets"]["case"] = {"seconds": 2, "source": "whole-horizon gate fixture"}
            configuration["budgets"]["phase"]["run"] = {"seconds": 2, "source": "whole-horizon gate fixture"}
        result = execute(name, [sys.executable, "-c", _canary_code(name)], configuration)
        if (result["outcome"] != expected_outcome or not result["stopped"] or not result["capture_complete"] or
                result["elapsed_seconds"] > synthetic["budgets"]["total"]["seconds"] + .15):
            raise Refusal("external supervisor canary failed: " + name + "; evidence: " + str(proof))
        if name == "parallel_progress" and result["diagnostics"]["deadline_worker"] != "main":
            raise Refusal("parallel progress masked the blocked worker; evidence: " + str(proof))
        if name == "bounded_progress" and result["diagnostics"]["workers"]["main"]["progress_status"] != "observed":
            raise Refusal("whole-horizon canary did not observe real declared progress")
    if binding != _binding(command, cwd, contract):
        raise Refusal("execution binding changed while gate ran")
    key = secrets.token_bytes(32)
    key_path = proof / ".gate-key"
    with open(key_path, "xb") as stream:
        stream.write(key)
    os.chmod(key_path, 0o600)
    receipt = {"version": VERSION, "binding": binding, "checks": checks,
               "evidence_files": evidence_files, "proof_root": str(proof), "nonces": nonces,
               "key_path": str(key_path)}
    receipt["signature"] = hmac.new(key, _canonical(receipt), hashlib.sha256).hexdigest()
    _write(output, receipt)
    return receipt


def validate_gate(path, command, cwd, contract):
    """Validate a gate receipt and its actual immutable execution evidence."""
    _platform()
    contract = _contract(contract)
    receipt = _read(path)
    if not isinstance(receipt, dict) or type(receipt.get("version")) is not int or receipt.get("version") != VERSION or receipt.get("binding") != _binding(command, cwd, contract):
        raise Refusal("gate receipt does not match this module, contract, runner or environment")
    required = {"adapter", "adapter_blocked", "callback_block", "heartbeat_block", "setup_block", "cleanup_block", "pipe_descendant",
                "parallel_progress", "bounded_progress", "noisy_events"}
    if set(receipt.get("checks", {})) != required:
        raise Refusal("gate receipt is missing real supervision checks")
    proof = Path(receipt.get("proof_root", ""))
    key_path = Path(receipt.get("key_path", ""))
    if key_path != proof / ".gate-key" or key_path.is_symlink() or not key_path.is_file():
        raise Refusal("gate authenticity evidence is unavailable")
    key = key_path.read_bytes()
    if len(key) != 32:
        raise Refusal("gate authentication key is invalid")
    unsigned = {key: value for key, value in receipt.items() if key != "signature"}
    expected = hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(receipt.get("signature", ""))):
        raise Refusal("gate receipt was modified")
    files = receipt.get("evidence_files", [])
    if not isinstance(files, list) or not files:
        raise Refusal("gate execution evidence is missing")
    for item in files:
        file = Path(item["path"])
        if proof not in file.parents or file.is_symlink() or not file.is_file() or _sha(file) != item["sha256"]:
            raise Refusal("gate execution evidence changed")
    for name, check in receipt["checks"].items():
        if check.get("terminal") not in {item["path"] for item in files}:
            raise Refusal("gate terminal is not bound to its evidence manifest")
        terminal = _read(check["terminal"])
        if not terminal.get("stopped") or not terminal.get("capture_complete"):
            raise Refusal("gate did not stop and fully capture its owned command")
        budgets = check.get("budgets", {})
        if (terminal.get("total_horizon_seconds") != budgets.get("total", {}).get("seconds") or
                terminal.get("payload_seconds") != budgets.get("total", {}).get("seconds", 0) - budgets.get("shutdown", {}).get("seconds", 0) or
                terminal.get("elapsed_seconds", math.inf) > budgets.get("total", {}).get("seconds", 0) + .15):
            raise Refusal("gate terminal disagrees with its declared fixed horizon")
        if name in {"adapter", "adapter_blocked"}:
            nonces = receipt.get("nonces", {})
            nonce = nonces.get(name)
            scenario = "blocked_callback" if name == "adapter_blocked" else "complete"
            if (not isinstance(nonce, str) or not nonce or check.get("nonce") != nonce or
                    check.get("scenario") != scenario or
                    not _adapter_proof(terminal, contract, nonce, name == "adapter_blocked")):
                raise Refusal("runner adapter gate evidence is unqualified")
        else:
            expected_outcome = ("phase_timeout" if name in {"setup_block", "cleanup_block"} else
                                "total_timeout" if name in {"pipe_descendant", "bounded_progress"} else "case_timeout")
            if terminal.get("outcome") != expected_outcome:
                raise Refusal("gate canary did not establish its independent deadline")
            if name == "parallel_progress" and terminal["diagnostics"].get("deadline_worker") != "main":
                raise Refusal("parallel-worker deadline evidence is unqualified")
            if name == "bounded_progress" and terminal["diagnostics"]["workers"]["main"].get("progress_status") != "observed":
                raise Refusal("whole-horizon evidence lacks legitimate declared progress")
    return receipt


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["_worker"]:
        command = arguments[1:]
        if command[:1] == ["--"]:
            command = command[1:]
        return _worker(command)
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    gate = subparsers.add_parser("gate")
    gate.add_argument("--contract", required=True)
    gate.add_argument("--cwd", required=True)
    gate.add_argument("--output", required=True)
    gate.add_argument("command", nargs=argparse.REMAINDER)
    validation = subparsers.add_parser("validate-gate")
    validation.add_argument("--contract", required=True)
    validation.add_argument("--receipt", required=True)
    validation.add_argument("--receipt-sha256", required=True)
    validation.add_argument("--cwd", required=True)
    validation.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(arguments)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise Refusal("gate requires the actual configured runner after --")
    if args.action == "validate-gate":
        path = Path(args.receipt)
        if path.is_symlink() or not path.is_file() or _sha(path) != args.receipt_sha256:
            raise Refusal("recorded gate receipt changed or is unavailable")
        receipt = validate_gate(path, command, args.cwd, read_contract(args.contract))
        print(json.dumps({"binding": receipt["binding"]}))
        return 0
    receipt = _gate(command, args.cwd, read_contract(args.contract), args.output)
    print(json.dumps({"receipt": str(Path(args.output).absolute()), "checks": sorted(receipt["checks"])}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Refusal, OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        raise SystemExit(2)
