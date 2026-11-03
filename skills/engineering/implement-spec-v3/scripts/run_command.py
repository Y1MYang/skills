"""Run one command with bounded lifetime and an immutable local receipt."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from path_identity import unique_paths


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("The shared execution or cleanup deadline expired")
    return value


@contextmanager
def progress(receipt_path: Path, started: float):
    stopped = threading.Event()

    def report() -> None:
        while not stopped.is_set():
            print(json.dumps({"event": "progress", "elapsed_seconds": time.monotonic() - started,
                              "receipt_path": str(receipt_path)}), file=sys.stderr, flush=True)
            stopped.wait(0.5)

    reporter = threading.Thread(target=report, daemon=True)
    reporter.start()
    try:
        yield
    finally:
        stopped.set()
        reporter.join(timeout=0.1)


def file_record(path: Path, deadline: float) -> dict:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            remaining(deadline)
            content = stream.read(1024 * 1024)
            if not content:
                break
            digest.update(content)
            size += len(content)
    remaining(deadline)
    return {"path": str(path), "sha256": digest.hexdigest(), "size": size}


def git_candidate(cwd: Path, deadline: float, hard_deadline: float) -> tuple[str, bool]:
    def git(*arguments: str) -> bytes:
        with tempfile.TemporaryDirectory(prefix="v3-git-", ignore_cleanup_errors=True) as temporary:
            stdout_path, stderr_path = Path(temporary) / "stdout", Path(temporary) / "stderr"
            result = run_owned(["git", "-C", str(cwd), *arguments], cwd, stdout_path, stderr_path,
                               min(deadline, hard_deadline - 0.25), uuid.uuid4().hex,
                               hard_deadline=hard_deadline)
            if result["outcome"] == "timeout":
                raise TimeoutError("Git candidate inspection exceeded the shared deadline")
            remaining(deadline)
            if (result["outcome"] != "exited" or result["exit_code"] != 0
                    or not result["cleanup_complete"]):
                raise ValueError("formal execution requires an owned Git command and a committed worktree")
            output = stdout_path.read_bytes()
            remaining(deadline)
            return output
    head = git("rev-parse", "HEAD").decode("ascii").strip()
    return head, not git("status", "--porcelain", "--untracked-files=all").strip()


def capture(request: dict, deadline: float) -> dict:
    root = Path(request["root"])
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("snapshot root must be an existing absolute directory")
    groups = {}
    for group in ("tests", "contract", "product"):
        declared = request[group]
        if not isinstance(declared, list) or not declared:
            raise ValueError(f"snapshot {group} must be a nonempty path list")
        entries = {}

        def visit(path: Path) -> None:
            remaining(deadline)
            relative = path.relative_to(root).as_posix()
            try:
                info = path.lstat()
            except FileNotFoundError:
                entries[relative] = {"path": relative, "kind": "missing"}
                return
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("snapshot paths cannot be symbolic links or directory junctions")
            if stat.S_ISDIR(info.st_mode):
                entries[relative] = {"path": relative, "kind": "directory"}
                for child in path.iterdir():
                    visit(child)
            elif stat.S_ISREG(info.st_mode):
                record = file_record(path, deadline)
                entries[relative] = {"path": relative, "kind": "file",
                                     "sha256": record["sha256"], "size": record["size"]}
            else:
                raise ValueError("snapshot paths must be regular files or directories")

        normalized = []
        for value in declared:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("snapshot paths must be nonempty strings")
            relative = value.replace("\\", "/")
            if (PureWindowsPath(relative).drive or relative.startswith("/")
                    or ".." in relative.split("/") or any(char in relative for char in "*?[]")):
                raise ValueError("snapshot paths must stay inside root and cannot contain globs")
            relative = Path(relative).as_posix()
            normalized.append(relative)
        normalized = unique_paths(root, normalized, check=lambda: remaining(deadline))
        for relative in normalized:
            path = root / relative
            for parent in (root, *path.parents):
                if parent == root or root in parent.parents:
                    if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
                        raise ValueError("snapshot parent cannot be a link or junction")
            visit(path)
        ordered = sorted(entries.values(), key=lambda entry: entry["path"])
        groups[group] = {"entries": ordered, "sha256": hashlib.sha256(canonical(ordered)).hexdigest()}
        remaining(deadline)
    return groups


def cleanup_posix(process: subprocess.Popen, deadline: float) -> bool:
    """Signal only the unreaped session anchor's group; never reuse its PID."""
    complete = False

    def live_members() -> bool:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("owned process cleanup", 0)
        result = subprocess.run(["ps", "-A", "-o", "pgid=", "-o", "stat="],
                                capture_output=True, text=True, timeout=min(remaining, 0.5), check=True)
        for row in result.stdout.splitlines():
            group, state = row.split()
            if int(group) == process.pid and not state.startswith("Z"):
                return True
        return False

    def group_signal(signum: int) -> None:
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    try:
        group_signal(signal.SIGTERM)
        grace = min(deadline, time.monotonic() + 0.5)
        while time.monotonic() < grace:
            if not live_members():
                complete = True
                break
            time.sleep(0.02)
        if not complete:
            group_signal(signal.SIGKILL)
            while time.monotonic() < deadline:
                if not live_members():
                    complete = True
                    break
                time.sleep(0.02)
    except (OSError, ValueError, subprocess.SubprocessError):
        group_signal(signal.SIGKILL)
    finally:
        # No poll/wait/communicate before the final group signal and observation:
        # retaining this child (even as a zombie) prevents group-ID reuse.
        try:
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            complete = False
    return complete


def bootstrap(status_path: str, hold: bool = False) -> int:
    # The parent releases this line only after assigning this process to its Job.
    authorization = sys.stdin.buffer.readline()
    if not authorization:
        return 2
    argv = json.loads(authorization)
    try:
        target = subprocess.Popen(argv, stdin=subprocess.DEVNULL, shell=False)
    except OSError:
        result = {"outcome": "launch_error", "exit_code": None}
    else:
        result = {"outcome": "exited", "exit_code": target.wait()}
    temporary = Path(status_path + ".result")
    temporary.write_bytes(canonical(result))
    os.replace(temporary, status_path)
    if hold:
        sys.stdin.buffer.read(1)
    return 0


def read_target_result(path: Path) -> dict:
    result = json.loads(path.read_bytes())
    if not isinstance(result, dict) or set(result) != {"outcome", "exit_code"}:
        raise ValueError("Missing or invalid target completion result")
    if not ((result["outcome"] == "exited" and type(result["exit_code"]) is int)
            or (result["outcome"] == "launch_error" and result["exit_code"] is None)):
        raise ValueError("Missing or invalid target completion result")
    return result


def run_owned(command: list[str], cwd: Path, stdout_path: Path, stderr_path: Path,
              deadline: float, token: str, *, hard_deadline: float | None = None) -> dict:
    """Use the same lifetime boundary for the target and auxiliary commands."""
    process = None
    job = None
    launch_status_path = None
    outcome, exit_code, cleanup_complete = "launch_error", None, True
    owner = {"platform": "windows" if os.name == "nt" else "posix",
             "kind": "job" if os.name == "nt" else "session", "token": token, "pid": os.getpid()}
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            remaining(deadline)
            launch_status_path = stdout_path.parent / f".{token}.launch.tmp"
            launch_status_path.touch(exist_ok=False)
            if os.name == "nt":
                from windows_job import Job
                outcome = "ownership_error"
                job = Job(token)
                process = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--bootstrap", str(launch_status_path)],
                    cwd=cwd, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW, shell=False,
                )
                owner["pid"] = process.pid
                job.assign(process.pid)
                remaining(deadline)
                process.stdin.write(canonical(command) + b"\n")
                process.stdin.close()
            else:
                process = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--bootstrap-posix", str(launch_status_path)],
                    cwd=cwd, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                    start_new_session=True, shell=False,
                )
                owner["pid"] = process.pid
                remaining(deadline)
                process.stdin.write(canonical(command) + b"\n")
                process.stdin.flush()
            outcome = "exited"
            while os.name != "nt" or process.poll() is None:
                if os.name != "nt" and launch_status_path.read_bytes():
                    break
                if time.monotonic() >= deadline:
                    outcome = "timeout"
                    break
                time.sleep(min(0.05, remaining(deadline)))
            if outcome == "exited":
                remaining(deadline)
                outcome = "interrupted"
                result = read_target_result(launch_status_path)
                outcome, exit_code = result["outcome"], result["exit_code"]
    except TimeoutError:
        outcome, exit_code = "timeout", None
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"runner: {error}", file=sys.stderr)
        if outcome == "exited":
            outcome = "launch_error"
        exit_code = None
    finally:
        finish_deadline = min(deadline, time.monotonic()) + 5
        if hard_deadline is not None:
            finish_deadline = min(finish_deadline, hard_deadline)
        if os.name != "nt" and process is not None:
            cleanup_complete = cleanup_posix(process, min(finish_deadline, time.monotonic() + 4))
            process.stdin.close()
        if job is not None:
            try:
                job.terminate()
                cleanup_deadline = min(finish_deadline, time.monotonic() + 4)
                while job.active() and time.monotonic() < cleanup_deadline:
                    time.sleep(0.02)
                cleanup_complete = job.active() == 0
            except OSError:
                cleanup_complete = False
            finally:
                job.close()
        if process is not None and process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=min(0.5, max(0.001, finish_deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                cleanup_complete = False
        if launch_status_path is not None:
            launch_status_path.unlink(missing_ok=True)
            Path(str(launch_status_path) + ".result").unlink(missing_ok=True)
    remaining(finish_deadline)
    if process is None:
        raise ValueError("No owned command process was started")
    return {"outcome": outcome, "exit_code": exit_code, "owner": owner,
            "cleanup_complete": cleanup_complete, "finish_deadline": finish_deadline}


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--timeout", required=True, type=float)
    parser.add_argument("--snapshot")
    parser.add_argument("--formal", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        if error.code:
            print(json.dumps({"ok": False, "error": {"code": "usage", "message": "Invalid command arguments"}}))
        return int(error.code)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    receipt_path = Path(args.receipt).resolve()
    cwd = Path(args.cwd).resolve()
    started_at = utc_now()
    started = time.monotonic()
    with progress(receipt_path, started):
        return execute(args, command, receipt_path, cwd, started_at, started)


def execute(args, command: list[str], receipt_path: Path, cwd: Path,
            started_at: str, started: float) -> int:
    deadline = started + args.timeout
    try:
        if not command or not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("A command and a finite positive timeout are required")
        if not cwd.is_dir():
            raise ValueError("cwd must be an existing directory")
        if os.name != "nt" and signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise ValueError("owned POSIX execution requires default SIGCHLD handling")
        formal = {"requested": args.formal, "head_before": None, "head_after": None,
                  "clean_before": None, "clean_after": None}
        if args.formal:
            formal["head_before"], formal["clean_before"] = git_candidate(cwd, deadline, deadline + 5)
            if not formal["clean_before"]:
                raise ValueError("formal execution requires a clean Git candidate before launch")
        snapshot_request = None
        snapshot = None
        if args.snapshot:
            request_bytes = Path(args.snapshot).read_bytes()
            snapshot_request = json.loads(request_bytes)
            fields = {"schema", "root", "tests", "contract", "product", "binding"}
            if set(snapshot_request) not in (fields, fields | {"timeout_seconds"}):
                raise ValueError("snapshot request has missing or unknown fields")
            if type(snapshot_request["schema"]) is not int or snapshot_request["schema"] != 1:
                raise ValueError("snapshot schema must be the integer 1")
            binding = snapshot_request["binding"]
            if binding is not None:
                binding_fields = {"run_id", "example", "gate", "attempt_id", "purpose", "prepared_seq", "prepared_at"}
                if not isinstance(binding, dict) or set(binding) != binding_fields:
                    raise ValueError("snapshot binding has missing or unknown fields")
            if "timeout_seconds" in snapshot_request:
                reserved_timeout = snapshot_request["timeout_seconds"]
                if type(reserved_timeout) not in (int, float) or reserved_timeout != args.timeout:
                    raise ValueError("snapshot timeout_seconds must be numeric and match the command timeout")
            snapshot = {"request_sha256": hashlib.sha256(request_bytes).hexdigest(),
                        "binding": snapshot_request["binding"],
                        "before": capture(snapshot_request, deadline), "after": None}
        stdout_path = Path(str(receipt_path) + ".stdout.log")
        stderr_path = Path(str(receipt_path) + ".stderr.log")
        claim_path = Path(str(receipt_path) + ".claim.json")
        if any(path.exists() for path in (receipt_path, stdout_path, stderr_path, claim_path)):
            raise ValueError("Receipt and companion paths must not already exist")
        token = uuid.uuid4().hex
        birth_token = None
        if os.name == "nt":
            from windows_job import current_process_birth_token
            birth_token = current_process_birth_token()
        with claim_path.open("xb") as claim:
            claim.write(canonical({"schema": 1, "receipt_path": str(receipt_path), "token": token,
                                   "controller": {"platform": "windows" if os.name == "nt" else "posix",
                                                  "pid": os.getpid(), "birth_token": birth_token},
                                   "created_at": utc_now()}))
            claim.flush()
            os.fsync(claim.fileno())
        remaining(deadline)
    except TimeoutError:
        raise
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": {"code": "input", "message": str(error)}}))
        return 2

    execution = run_owned(command, cwd, stdout_path, stderr_path, deadline, token)
    finish_deadline = execution.pop("finish_deadline")
    if snapshot is not None:
        snapshot["after"] = capture(snapshot_request, finish_deadline)
    if args.formal:
        formal["head_after"], formal["clean_after"] = git_candidate(cwd, finish_deadline, finish_deadline)
    logs = {"stdout": file_record(stdout_path, finish_deadline),
            "stderr": file_record(stderr_path, finish_deadline)}
    receipt = {
        "schema": 1, "receipt_id": token, "argv": command, "cwd": str(cwd),
        "started_at": started_at, "ended_at": utc_now(),
        "duration_seconds": time.monotonic() - started, "timeout_seconds": args.timeout,
        **execution,
        "logs": logs,
        "snapshot": snapshot,
        "formal": formal,
    }
    remaining(finish_deadline)
    temporary = Path(str(receipt_path) + "." + token + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(canonical(receipt) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    remaining(finish_deadline)
    os.replace(temporary, receipt_path)
    outcome, exit_code = execution["outcome"], execution["exit_code"]
    print(json.dumps({"ok": True, "receipt_path": str(receipt_path),
                      "outcome": outcome, "exit_code": exit_code}))
    if not execution["cleanup_complete"] or outcome not in {"exited", "timeout"}:
        return 2
    if outcome == "timeout":
        return 124
    return 0 if exit_code == 0 else 1


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except TimeoutError as error:
        print(json.dumps({"ok": False, "error": {"code": "timeout", "message": str(error)}}))
        return 124
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": {"code": "evidence", "message": str(error)}}))
        return 2


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in {"--bootstrap", "--bootstrap-posix"}:
        raise SystemExit(bootstrap(sys.argv[2], hold=sys.argv[1] == "--bootstrap-posix"))
    raise SystemExit(main())
