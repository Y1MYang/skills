"""Persist the small, version-bound implement-spec-v3 development cycle."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

from path_identity import paths_equivalent, paths_overlap, unique_paths


ROLES = {
    "exploration", "architect", "test_author", "implementer", "runner",
    "integrator", "coverage_audit", "spec_reviewer", "standards_reviewer", "expert",
}
OPERATIONS = {
    "open", "prepare", "record", "judge", "diagnose", "close", "invocation", "recover",
    "qualify", "prepare-formal", "release", "finish", "extend", "revise", "include",
    "stage", "promote",
}


class Rejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def same_oracle(left, right):
    return all(left[group] == right[group] for group in ("tests", "contract"))


def same_scoped_oracle(snapshot, current, baseline):
    """Compare an example's inputs with its portion of a possibly larger proof."""
    if same_oracle(current, baseline):
        return True
    for group in ("tests", "contract"):
        expected = current[group]["entries"]
        observed = [entry for entry in baseline[group]["entries"]
                    if any(paths_equivalent(snapshot["root"], path, entry["path"])
                           or (len(Path(entry["path"]).parts) >= len(Path(path).parts)
                               and paths_overlap(snapshot["root"], path, entry["path"]))
                           for path in snapshot[group])]
        if observed == expected:
            continue

        def matches(left, right):
            return ({key: value for key, value in left.items() if key != "path"}
                    == {key: value for key, value in right.items() if key != "path"}
                    and paths_equivalent(snapshot["root"], left["path"], right["path"]))

        if (not all(any(matches(entry, other) for other in observed) for entry in expected)
                or not all(any(matches(entry, other) for other in expected) for entry in observed)):
            return False
    return True


def relative_path(value):
    if not nonempty(value):
        raise Rejected("invalid-path", "Snapshot paths must be nonempty relative paths.")
    normalized = value.replace("\\", "/")
    if (Path(normalized).is_absolute() or ":" in normalized or ".." in normalized.split("/")
            or any(character in normalized for character in "*?[]")):
        raise Rejected("invalid-path", "Paths must stay within the declared root.")
    return Path(normalized).as_posix()


def capture(snapshot):
    root = Path(snapshot["root"]).resolve()
    groups = {}
    for group in ("tests", "contract", "product"):
        entries = {}

        def visit(path):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise Rejected("unsafe-path", "Snapshot paths cannot contain links or junctions.")
            if not path.exists():
                entries[relative] = {"path": relative, "kind": "missing"}
            elif path.is_dir():
                entries[relative] = {"path": relative, "kind": "directory"}
                for child in path.iterdir():
                    visit(child)
            elif path.is_file():
                data = path.read_bytes()
                entries[relative] = {"path": relative, "kind": "file",
                                     "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            else:
                raise Rejected("unsafe-path", "Snapshots only support ordinary files and directories.")

        for declared in snapshot[group]:
            path = root / relative_path(declared)
            for ancestor in (path, *path.parents):
                if ancestor == root:
                    break
                if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
                    raise Rejected("unsafe-path", "Snapshot paths cannot contain links or junctions.")
            visit(path)
        ordered = [entries[path] for path in sorted(entries)]
        groups[group] = {"entries": ordered, "sha256": digest(ordered)}
    return groups


def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != {
        "schema", "run_id", "workspace", "spec_sources", "models", "budget", "flows", "examples", "gates"
    } or type(plan["schema"]) is not int or plan["schema"] != 1:
        raise Rejected("invalid-plan", "Unexpected plan schema or fields.")
    if not nonempty(plan["run_id"]) or not nonempty(plan["workspace"]):
        raise Rejected("invalid-plan", "Run identity and workspace must be explicit.")
    validate_models(plan.get("models"))
    budget = plan.get("budget")
    if not isinstance(budget, dict) or set(budget) != {
        "max_attempts", "max_formal_failures", "max_seconds"
    }:
        raise Rejected("invalid-budget", "Declare all three finite execution limits.")
    for key, value in budget.items():
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise Rejected("invalid-budget", f"{key} must be finite and positive.")
        if key != "max_seconds" and type(value) is not int:
            raise Rejected("invalid-budget", f"{key} must be an integer.")
    plan["workspace"] = str(Path(plan["workspace"]).resolve())
    for field in ("spec_sources", "flows", "examples", "gates"):
        if not isinstance(plan[field], list) or (field != "gates" and not plan[field]):
            raise Rejected("invalid-plan", f"{field} must be a declared list.")
    flows, examples, gates, requirements = {}, {}, {}, set()
    for flow in plan["flows"]:
        if (not isinstance(flow, dict) or set(flow) not in ({"id", "write_paths"}, {"id", "write_paths", "root"})
                or not nonempty(flow["id"]) or flow["id"] in flows
                or not isinstance(flow["write_paths"], list) or not flow["write_paths"]):
            raise Rejected("invalid-flow", "Flows need unique IDs and nonempty write paths.")
        flow["write_paths"] = sorted({relative_path(path) for path in flow["write_paths"]})
        if "root" in flow:
            flow["root"] = str(Path(flow["root"]).resolve())
            if flow["root"] == plan["workspace"]:
                raise Rejected("invalid-flow", "A parallel flow's workcopy root must differ from the integration workspace.")
            if not Path(flow["root"]).is_dir():
                raise Rejected("invalid-flow", "The flow workcopy root must be an existing prepared worktree.")
        for old in flows.values():
            for left in flow["write_paths"]:
                for right in old["write_paths"]:
                    if paths_overlap(plan["workspace"], left, right):
                        raise Rejected("shared-write-path", "Parallel flows must own disjoint write paths.")
        flows[flow["id"]] = flow
    for example in plan["examples"]:
        if (not isinstance(example, dict) or set(example) != {"id", "flow", "requirement", "depends_on", "snapshot"}
                or not nonempty(example["id"]) or example["id"] in examples
                or not nonempty(example["requirement"]) or example["requirement"] in requirements
                or example["flow"] not in flows or not isinstance(example["depends_on"], list)
                or not all(nonempty(item) for item in example["depends_on"])):
            raise Rejected("invalid-example", "Examples require unique identities and a declared flow.")
        snapshot = example["snapshot"]
        if (not isinstance(snapshot, dict) or set(snapshot) != {"schema", "root", "tests", "contract", "product", "binding"}
                or type(snapshot["schema"]) is not int or snapshot["schema"] != 1 or snapshot["binding"] is not None):
            raise Rejected("invalid-snapshot", "Examples require an unbound snapshot declaration.")
        snapshot["root"] = str(Path(snapshot["root"]).resolve())
        if snapshot["root"] != flows[example["flow"]].get("root", plan["workspace"]):
            raise Rejected("invalid-root", "Every snapshot root must be its flow's workcopy root.")
        for group in ("tests", "contract", "product"):
            paths = snapshot[group]
            if not isinstance(paths, list) or not paths:
                raise Rejected("invalid-snapshot", "Snapshot groups cannot be empty.")
            normalized = unique_paths(plan["workspace"], [relative_path(path) for path in paths])
            snapshot[group] = sorted(normalized)
        examples[example["id"]] = example
        requirements.add(example["requirement"])
    for gate in plan["gates"]:
        if (not isinstance(gate, dict) or set(gate) != {"id", "prerequisites", "consumers"}
                or not nonempty(gate["id"]) or gate["id"] == "final" or gate["id"] in gates
                or not isinstance(gate["prerequisites"], list) or not gate["prerequisites"]
                or not isinstance(gate["consumers"], list)
                or any(identifier not in examples for identifier in gate["prerequisites"] + gate["consumers"])):
            raise Rejected("invalid-gate", "Gates need unique IDs and existing example references.")
        gates[gate["id"]] = gate
    graph = {("example", identifier): [] for identifier in examples}
    graph.update({("gate", identifier): [] for identifier in gates})
    for identifier, example in examples.items():
        for dependency in example["depends_on"]:
            if dependency not in examples:
                raise Rejected("missing-dependency", "An example dependency is absent.")
            graph[("example", dependency)].append(("example", identifier))
    for identifier, gate in gates.items():
        for dependency in gate["prerequisites"]:
            graph[("example", dependency)].append(("gate", identifier))
        for consumer in gate["consumers"]:
            graph[("gate", identifier)].append(("example", consumer))
    visiting, visited = set(), set()

    def visit(node):
        if node in visiting:
            raise Rejected("dependency-cycle", "Example and gate dependencies must be acyclic.")
        if node in visited:
            return
        visiting.add(node)
        for target in graph[node]:
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
    # Parallelism is planned, not emergent: examples that are simultaneously
    # ready must not all sit in one serial flow. Requiring distinct flows per
    # sibling would forbid legitimate capacity choices, so only the degenerate
    # all-in-one-flow plan is rejected.
    memo = {}

    def level_of(identifier):
        if identifier not in memo:
            dependencies = examples[identifier]["depends_on"]
            memo[identifier] = 0 if not dependencies else 1 + max(level_of(item) for item in dependencies)
        return memo[identifier]

    for identifier in examples:
        level_of(identifier)
    by_level = {}
    for identifier, value in memo.items():
        by_level.setdefault(value, []).append(identifier)
    for ready in by_level.values():
        assigned = {examples[identifier]["flow"] for identifier in ready}
        if len(ready) > 1 and len(assigned) == 1:
            raise Rejected("unnamed-parallelism",
                           f"Simultaneously ready examples {sorted(ready)} cannot share one flow; "
                           "plan distinct flows so they can advance in parallel.")
    plan["spec_sources"] = sorted({relative_path(path) for path in plan["spec_sources"]})


def validate_models(models):
    if not isinstance(models, dict) or set(models) != ROLES:
        raise Rejected("models-required", "All ten role models must be explicitly selected.")
    if any(not isinstance(model, str) or not model.strip() for model in models.values()):
        raise Rejected("invalid-model", "Every role model must be a nonempty string.")


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def lock_state(directory):
    """Hold an OS lock across the entire read/validate/write transaction."""
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / ".writer.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        stream.close()
        raise Rejected("busy", "Another command owns the run state; retry this operation.") from error
    return stream


def scope_anchor(plan):
    workspace = Path(plan["workspace"])
    source_paths = unique_paths(workspace, plan["spec_sources"], reject_duplicates=False)
    common = subprocess.run(["git", "-C", str(workspace), "rev-parse", "--git-common-dir"],
                            capture_output=True, text=True, timeout=10, check=False)
    if common.returncode == 0:
        directory = (workspace / common.stdout.strip()).resolve() / "implement-spec-v3"
        top = subprocess.run(["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10, check=True)
        base = Path(top.stdout.strip()).resolve()
        sources = sorted((workspace / source).resolve().relative_to(base).as_posix()
                         for source in source_paths)
    else:
        directory = workspace / ".implement-spec-v3"
        # resolve() uses the real spelling of existing Windows paths, preserving
        # distinct names in case-sensitive directories while collapsing aliases.
        sources = sorted((workspace / source).resolve(strict=True).relative_to(workspace.resolve()).as_posix()
                         for source in source_paths)
    return directory / f"{digest(sources)}.json"


def claim_scope(plan, state_path):
    path = scope_anchor(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    source_paths = sorted((Path(plan["workspace"]) / source).resolve(strict=True)
                          .relative_to(Path(plan["workspace"]).resolve()).as_posix()
                          for source in unique_paths(plan["workspace"], plan["spec_sources"], reject_duplicates=False))
    source_snapshot = {"root": plan["workspace"], **{group: source_paths for group in ("tests", "contract", "product")}}
    source_digest = capture(source_snapshot)["contract"]["sha256"]
    anchor = {"schema": 1, "run_id": plan["run_id"], "state_path": str(state_path),
              "plan_sha256": digest(plan), "spec_sha256": source_digest, "history": []}
    scope_lock = lock_state(path.parent)
    try:
        if path.exists():
            existing = read_json(path)
            for entry in [existing, *existing.get("history", [])]:
                if (entry["run_id"] == plan["run_id"] and entry["state_path"] == str(state_path)
                        and entry["plan_sha256"] == digest(plan) and state_path.is_file()):
                    return str(path)
            if (plan["run_id"] in {entry["run_id"] for entry in [existing, *existing.get("history", [])]}
                    or existing.get("spec_sha256") is None or existing["spec_sha256"] == source_digest):
                raise Rejected("scope-active", "This scope requires its original run unless completed requirements actually change.")
            old_path = Path(existing["state_path"])
            old_lock = lock_state(old_path.parent)
            try:
                old = read_json(old_path)
                audit_history(old, old_path)
                historical_completion(old)
                anchor["history"] = [*existing.get("history", []),
                                     {key: value for key, value in existing.items() if key != "history"}]
                atomic_json(path, anchor)
            finally:
                old_lock.close()
        else:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(anchor, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
    finally:
        scope_lock.close()
    return str(path)


def initial_data(plan):
    return {
        "status": "active", "active_by_flow": {flow["id"]: None for flow in plan["flows"]},
        "examples": {example["id"]: {"state": "planned", "mode": None, "attempt_ids": []}
                     for example in plan["examples"]},
        "gates": {gate["id"]: {"state": "pending", "attempt_ids": []} for gate in plan["gates"]},
        "budget": {"attempts_used": 0, "formal_failures_used": 0,
                   "seconds_used": 0, "seconds_reserved": 0},
        "pending_attempts": [], "failures": [],
        "staged": {},
    }


def inspect_state(state):
    return {
        "ok": True,
        "run_id": state["plan"]["run_id"],
        "models": state.get("models", state["plan"]["models"]),
        **state["data"],
        "staged": state["data"].get("staged", {}),
        "started_at": state["started_at"],
        "pending_attempts": [
            {"attempt_id": identifier, "example": state["attempts"][identifier]["example"],
             "gate": state["attempts"][identifier]["request"]["binding"]["gate"],
             "purpose": state["attempts"][identifier]["purpose"],
             "state": state["attempts"][identifier].get("recovery_state", "prepared"),
             "timeout_seconds": state["attempts"][identifier]["request"]["timeout_seconds"],
             "receipt_path": state["attempts"][identifier]["receipt_path"]}
            for identifier in state["data"]["pending_attempts"]
        ],
        "last_seq": len(state["events"]),
    }


def stage_test(state, event):
    """Register a blind prewritten test for one direct successor (depth 1).

    The test lives outside every snapshot's regression scope; the event only
    records its identity and digest. Promotion binds it as the successor's
    opening criterion, so prewritten bytes cannot leak into any earlier
    example's affected-regression evidence.
    """
    if set(event) != {"schema", "op_id", "op", "example", "test_digest", "light_check"}:
        raise Rejected("invalid-event", "Unexpected or missing stage fields.")
    check = event["light_check"]
    if not isinstance(check, dict) or set(check) != {
        "source", "observation", "expected_failure", "independent_context"
    } or not all(nonempty(value) for value in check.values()):
        raise Rejected("invalid-light-check", "Record all four independent oracle checks.")
    if not nonempty(event["test_digest"]):
        raise Rejected("invalid-stage", "A staged test needs its content digest.")
    example = next((item for item in state["plan"]["examples"] if item["id"] == event["example"]), None)
    if example is None:
        raise Rejected("unknown-example", "The example is not in this run.")
    data = state["data"]
    if data["examples"][example["id"]]["state"] != "planned":
        raise Rejected("invalid-stage", "Only a planned example can receive a staged prewritten test.")
    prerequisites = example["depends_on"]
    if not prerequisites or not all(data["examples"][item]["state"] in {"open", "red", "green", "existing", "closed"}
                                    for item in prerequisites):
        raise Rejected("stage-not-ready", "Stage only a successor whose prerequisites reached development.")
    staged_flows = set()
    for staged_id, staged_entry in data["staged"].items():
        staged_example = next(item for item in state["plan"]["examples"] if item["id"] == staged_id)
        if staged_example["flow"] == example["flow"]:
            staged_flows.add(staged_example["flow"])
    if staged_flows:
        raise Rejected("invalid-stage", "Depth 1 staging permits one prewritten test per flow.")
    data["staged"][example["id"]] = {
        "test_digest": event["test_digest"], "light_check": check,
        "staged_seq": len(state["events"]) + 1,
    }
    return {"ok": True, "example": example["id"], "staged": True}


def promote_test(state, event):
    """Bind the staged test as the example's opening criterion before its probe."""
    if set(event) != {"schema", "op_id", "op", "example"}:
        raise Rejected("invalid-event", "Unexpected or missing promote fields.")
    example = next((item for item in state["plan"]["examples"] if item["id"] == event["example"]), None)
    if example is None:
        raise Rejected("unknown-example", "The example is not in this run.")
    data = state["data"]
    progress = data["examples"][example["id"]]
    staged = data["staged"].get(example["id"])
    if progress["state"] != "planned":
        raise Rejected("invalid-stage", "Promotion applies to a planned example.")
    if staged is None:
        raise Rejected("invalid-stage", "Promotion requires a staged prewritten test.")
    if any(data["examples"][dependency]["state"] != "closed" for dependency in example["depends_on"]):
        raise Rejected("dependency-pending", "Promotion waits for closed prerequisite examples.")
    staged["promoted_seq"] = len(state["events"]) + 1
    return {"ok": True, "example": example["id"], "promoted": True}


def open_example(state, event):
    if set(event) not in ({"schema", "op_id", "op", "example", "light_check"},
                          {"schema", "op_id", "op", "example", "light_check", "promoted_from"}):
        raise Rejected("invalid-event", "Unexpected or missing open fields.")
    check = event["light_check"]
    if not isinstance(check, dict) or set(check) != {
        "source", "observation", "expected_failure", "independent_context"
    } or not all(nonempty(value) for value in check.values()):
        raise Rejected("invalid-light-check", "Record all four independent oracle checks.")
    example = next((item for item in state["plan"]["examples"] if item["id"] == event["example"]), None)
    if example is None:
        raise Rejected("unknown-example", "The example is not in this run.")
    data = state["data"]
    progress = data["examples"][example["id"]]
    if progress["state"] != "planned" or data["active_by_flow"][example["flow"]] is not None:
        raise Rejected("flow-active", "Finish the current example before opening another in this flow.")
    if any(data["examples"][dependency]["state"] != "closed" for dependency in example["depends_on"]):
        raise Rejected("dependency-pending", "Prerequisite examples must be closed.")
    for gate in state["plan"]["gates"]:
        if example["id"] in gate["consumers"]:
            released = data["gates"][gate["id"]]
            if released["state"] != "released":
                raise Rejected("gate-pending", "The critical contract gate has not released this consumer.")
            check_formal(state, released["release_attempt_id"], gate["id"], require_clean=False)
    progress.update(state="open", opening=capture(example["snapshot"]), light_check=check)
    data["active_by_flow"][example["flow"]] = example["id"]
    return {"ok": True, "example": example["id"], "state": "open"}


def prepare(state, event, state_dir):
    if set(event) != {"schema", "op_id", "op", "example", "purpose", "timeout_seconds"}:
        raise Rejected("invalid-event", "Unexpected or missing prepare fields.")
    timeout = event["timeout_seconds"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise Rejected("invalid-timeout", "Timeout must be finite and positive.")
    example = next((item for item in state["plan"]["examples"] if item["id"] == event["example"]), None)
    if example is None:
        raise Rejected("unknown-example", "The example is not in this run.")
    data = state["data"]
    progress = data["examples"][example["id"]]
    purpose = event["purpose"]
    if progress["state"] != "closed" and data["active_by_flow"][example["flow"]] != example["id"]:
        raise Rejected("flow-active", "Only the current flow example may prepare development work.")
    if purpose == "probe":
        if progress["state"] != "open":
            raise Rejected("invalid-stage", "A probe requires an open example.")
    elif purpose == "green":
        if progress["state"] != "red" or not progress.get("red_attempt_id"):
            raise Rejected("invalid-stage", "Green requires a recorded valid Red.")
    elif purpose == "regression":
        if progress["state"] not in {"green", "existing", "closed"}:
            raise Rejected("invalid-stage", "Regression requires Green, existing capability, or historical completion.")
        active = data["active_by_flow"][example["flow"]]
        if active is not None and active != example["id"]:
            raise Rejected("flow-active", "Finish the active example before refreshing historical regressions.")
    else:
        raise Rejected("invalid-purpose", "Unsupported attempt purpose.")
    attempts = state.setdefault("attempts", {})
    if any(attempts[identifier]["flow"] == example["flow"] for identifier in data["pending_attempts"]):
        raise Rejected("attempt-pending", "This flow already has an unsettled attempt.")
    current = capture(example["snapshot"])
    if purpose == "probe" and current != progress["opening"]:
        raise Rejected("stale-opening", "The first probe must use the opening snapshot.")
    if purpose == "green" and not same_oracle(current, attempts[progress["red_attempt_id"]]["receipt"]["snapshot"]["after"]):
        raise Rejected("stale-red", "Green must retain the independent Red test and contract snapshots.")
    result = reserve_attempt(state, event, state_dir, example["snapshot"], current,
                             example["id"], example["flow"], None, purpose)
    progress["attempt_ids"].append(result["attempt_id"])
    return result


def reserve_attempt(state, event, state_dir, snapshot, current, example, flow, gate, purpose):
    timeout = event["timeout_seconds"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise Rejected("invalid-timeout", "Timeout must be finite and positive.")
    data = state["data"]
    for failure in data["failures"]:
        failed = state["attempts"][failure["attempt_id"]]
        if failure["resolved"] or (flow is not None and failed["flow"] not in {flow, None}):
            continue
        if failure["classification"] in {"unknown", "business-decision"} or not failure["diagnoses"]:
            raise Rejected("diagnosis-required", "Classify the failure and record new diagnostic evidence before retrying.")
    limits, used = state["plan"]["budget"], data["budget"]
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(state["started_at"])).total_seconds()
    if (used["attempts_used"] >= limits["max_attempts"]
            or used["formal_failures_used"] >= limits["max_formal_failures"]
            or elapsed > limits["max_seconds"]):
        raise Rejected("budget-exhausted", "The declared run budget cannot admit this attempt.")
    identifier = "attempt-" + digest([state["plan"]["run_id"], event["op_id"]])[:24]
    directory = state_dir / "attempts"
    request_path, receipt_path = directory / f"{identifier}.request.json", directory / f"{identifier}.receipt.json"
    binding = {"run_id": state["plan"]["run_id"], "example": example, "gate": gate,
               "attempt_id": identifier, "purpose": purpose, "prepared_seq": len(state["events"]) + 1,
               "prepared_at": datetime.now(timezone.utc).isoformat()}
    request = {**snapshot, "binding": binding, "timeout_seconds": timeout}
    atomic_json(request_path, request)
    state.setdefault("attempts", {})[identifier] = {
        "id": identifier, "example": example, "flow": flow, "purpose": purpose,
        "request_path": str(request_path), "receipt_path": str(receipt_path), "request": request,
        "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(), "state": "prepared",
        "prepared_snapshot": current,
    }
    used["attempts_used"] += 1
    used["seconds_reserved"] += timeout
    data["status"] = "active"
    data["pending_attempts"].append(identifier)
    return {"ok": True, "attempt_id": identifier, "request_path": str(request_path),
            "receipt_path": str(receipt_path)}


def check_receipt(state, attempt):
    request_path = Path(attempt["request_path"])
    if hashlib.sha256(request_path.read_bytes()).hexdigest() != attempt["request_sha256"]:
        raise Rejected("request-changed", "The prepared request has changed.")
    receipt_path = Path(attempt["receipt_path"])
    raw = receipt_path.read_bytes()
    receipt = json.loads(raw.decode("utf-8"))
    if set(receipt) != {"schema", "receipt_id", "argv", "cwd", "started_at", "ended_at",
                       "duration_seconds", "timeout_seconds", "outcome", "exit_code", "owner",
                       "cleanup_complete", "logs", "snapshot", "formal"} or type(receipt["schema"]) is not int or receipt["schema"] != 1:
        raise Rejected("invalid-receipt", "Unexpected receipt schema.")
    request = attempt["request"]
    prepared_event = state["events"][request["binding"]["prepared_seq"] - 1]["event"]
    execution = state.get("executions", {}).get(prepared_event["op_id"])
    if execution is not None and receipt["argv"] != execution["request"]["argv"]:
        raise Rejected("wrong-command", "The actual command differs from this preparation's bound execution.")
    if receipt["timeout_seconds"] != request["timeout_seconds"] or receipt["cleanup_complete"] is not True:
        raise Rejected("invalid-receipt", "Execution bounds and completed cleanup are required.")
    duration = receipt["duration_seconds"]
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
        raise Rejected("invalid-receipt", "Invalid execution duration.")
    if datetime.fromisoformat(receipt["started_at"]) < datetime.fromisoformat(request["binding"]["prepared_at"]):
        raise Rejected("out-of-order", "Execution predates its durable preparation.")
    if datetime.fromisoformat(receipt["ended_at"]) < datetime.fromisoformat(receipt["started_at"]):
        raise Rejected("invalid-receipt", "Execution ended before it started.")
    if Path(receipt["cwd"]).resolve() != Path(request["root"]).resolve():
        raise Rejected("wrong-workspace", "The receipt was executed in another workspace.")
    snapshot = receipt["snapshot"]
    if not isinstance(snapshot, dict) or set(snapshot) != {"request_sha256", "binding", "before", "after"}:
        raise Rejected("invalid-snapshot", "A bound snapshot is required.")
    if snapshot["request_sha256"] != attempt["request_sha256"] or snapshot["binding"] != request["binding"]:
        raise Rejected("wrong-binding", "The receipt does not belong to this preparation.")
    for captures in (snapshot["before"], snapshot["after"]):
        if set(captures) != {"tests", "contract", "product"}:
            raise Rejected("invalid-snapshot", "All three capture groups are required.")
        for group in captures.values():
            if set(group) != {"entries", "sha256"} or digest(group["entries"]) != group["sha256"]:
                raise Rejected("invalid-snapshot", "A capture digest does not match its entries.")
    if snapshot["before"] != attempt["prepared_snapshot"]:
        raise Rejected("wrong-snapshot", "Execution must begin from its prepared snapshot.")
    if set(receipt["logs"]) != {"stdout", "stderr"}:
        raise Rejected("invalid-logs", "Both raw execution logs are required.")
    for log in receipt["logs"].values():
        if set(log) != {"path", "sha256", "size"}:
            raise Rejected("invalid-logs", "Unexpected log descriptor.")
        content = Path(log["path"]).read_bytes()
        if len(content) != log["size"] or hashlib.sha256(content).hexdigest() != log["sha256"]:
            raise Rejected("log-changed", "An execution log does not match its recorded bytes.")
    if receipt["outcome"] not in {"exited", "timeout", "launch_error", "ownership_error", "interrupted"}:
        raise Rejected("invalid-receipt", "Unknown execution outcome.")
    if receipt["outcome"] == "exited":
        if type(receipt["exit_code"]) is not int:
            raise Rejected("invalid-receipt", "Exited executions require an integer exit code.")
    elif receipt["exit_code"] is not None:
        raise Rejected("invalid-receipt", "Only exited executions have an exit code.")
    return receipt, hashlib.sha256(raw).hexdigest()


def record(state, event):
    if set(event) != {"schema", "op_id", "op", "attempt_id"}:
        raise Rejected("invalid-event", "A record names only its prepared attempt.")
    attempt = state.get("attempts", {}).get(event["attempt_id"])
    if attempt is None or attempt["state"] != "prepared":
        raise Rejected("unknown-attempt", "The attempt is absent or already settled.")
    receipt, receipt_digest = check_receipt(state, attempt)
    attempt.update(state="recorded", receipt=receipt, receipt_sha256=receipt_digest)
    data = state["data"]
    data["pending_attempts"].remove(attempt["id"])
    data["budget"]["seconds_reserved"] -= attempt["request"]["timeout_seconds"]
    data["budget"]["seconds_used"] += receipt["duration_seconds"]
    if receipt["snapshot"]["before"] != receipt["snapshot"]["after"]:
        attempt["eligible"] = False
        data["failures"].append({"attempt_id": attempt["id"], "classification": "ineligible",
                                 "reason": "snapshot-changed", "resolved": False, "diagnoses": []})
        if attempt["purpose"] == "formal":
            data["budget"]["formal_failures_used"] += 1
        return {"ok": True, "attempt_id": attempt["id"], "eligible": False, "reason": "snapshot-changed"}
    if receipt["outcome"] != "exited" or receipt["exit_code"] != 0:
        data["failures"].append({"attempt_id": attempt["id"], "classification": "unclassified",
                                 "resolved": False, "diagnoses": []})
        if attempt["purpose"] == "formal":
            data["budget"]["formal_failures_used"] += 1
    elif attempt["purpose"] == "green":
        progress = data["examples"][attempt["example"]]
        red = state["attempts"][progress["red_attempt_id"]]
        if not same_oracle(receipt["snapshot"]["after"], red["receipt"]["snapshot"]["after"]):
            raise Rejected("stale-red", "The Green receipt uses another independent criterion.")
        progress.update(state="green", mode="red-green", green_attempt_id=attempt["id"])
    elif attempt["purpose"] == "regression":
        data["examples"][attempt["example"]]["regression_attempt_id"] = attempt["id"]
    elif attempt["purpose"] == "formal":
        _, examples, _ = scope_details(state, {"final": True} if attempt["request"]["binding"]["gate"] == "final"
                                       else {"gate": attempt["request"]["binding"]["gate"]})
        for identifier in examples:
            data["examples"][identifier]["regression_attempt_id"] = attempt["id"]
        try:
            check_formal(state, attempt["id"], attempt["request"]["binding"]["gate"])
        except Rejected:
            pass
        else:
            for failure in data["failures"]:
                if failure["classification"] == "valid-red" or not failure["diagnoses"]:
                    continue
                failed = state["attempts"][failure["attempt_id"]]
                failed_scope = failed.get("scope_examples")
                if failed_scope is None:
                    if failed["example"] is not None:
                        failed_scope = [failed["example"]]
                    else:
                        failed_key = failed["request"]["binding"]["gate"]
                        _, failed_scope, _ = scope_details(state, {"final": True} if failed_key == "final" else {"gate": failed_key})
                diagnosis_seq = last_diagnosis_sequence(state, failure["attempt_id"])
                if (diagnosis_seq and attempt["request"]["binding"]["prepared_seq"] > diagnosis_seq
                        and set(failed_scope).issubset(examples)):
                    failure.update(resolved=True, resolution_attempt_id=attempt["id"])
    return {"ok": True, "attempt_id": attempt["id"], "outcome": receipt["outcome"],
            "exit_code": receipt["exit_code"]}


def judge(state, event):
    if set(event) != {"schema", "op_id", "op", "attempt_id", "classification", "reason", "evidence"}:
        raise Rejected("invalid-event", "Unexpected or missing judgment fields.")
    if not nonempty(event["reason"]) or not isinstance(event["evidence"], list) or not event["evidence"] or not all(nonempty(item) for item in event["evidence"]):
        raise Rejected("invalid-judgment", "Record a reason and nonempty evidence identifiers.")
    attempt = state.get("attempts", {}).get(event["attempt_id"])
    if attempt is None or attempt["state"] != "recorded":
        raise Rejected("unknown-attempt", "Record the execution before judging it.")
    if attempt.get("eligible") is False:
        raise Rejected("ineligible-execution", "A changing execution cannot qualify the example.")
    if attempt.get("judgment", {}).get("classification") in {"valid-red", "existing"}:
        raise Rejected("already-judged", "A settled capability judgment is immutable; replay its original op_id.")
    if (attempt["example"] is not None and attempt["request"]["binding"]["prepared_seq"] <=
            state["data"]["examples"][attempt["example"]].get("revision_seq", 0)):
        raise Rejected("old-revision", "A historical attempt cannot qualify a revised behavior.")
    if attempt["example"] is not None and state["data"]["examples"][attempt["example"]]["state"] == "closed":
        raise Rejected("historical-completion", "Judging an old attempt cannot reopen a completed example.")
    receipt = attempt["receipt"]
    classification = event["classification"]
    if classification in {"implementation", "test-defect", "environment", "business-decision", "unknown"}:
        if receipt["outcome"] == "exited" and receipt["exit_code"] == 0:
            raise Rejected("not-a-failure", "A successful command cannot be classified as a failure.")
        failure = next(item for item in state["data"]["failures"] if item["attempt_id"] == attempt["id"])
        failure["classification"] = classification
        attempt["judgment"] = event
        return {"ok": True, "attempt_id": attempt["id"], "classification": classification}
    if classification not in {"valid-red", "existing"} or attempt["purpose"] != "probe" or receipt["outcome"] != "exited":
        raise Rejected("invalid-judgment", "Capability judgments require an exited probe.")
    if (classification == "valid-red") != (receipt["exit_code"] != 0):
        raise Rejected("invalid-judgment", "Valid Red requires failure; existing capability requires success.")
    example = next(item for item in state["plan"]["examples"] if item["id"] == attempt["example"])
    if not same_oracle(capture(example["snapshot"]), receipt["snapshot"]["after"]):
        raise Rejected("stale-red", "The current test or contract differs from the probe.")
    attempt["judgment"] = event
    progress = state["data"]["examples"][example["id"]]
    if classification == "valid-red":
        progress.update(state="red", red_attempt_id=attempt["id"])
        failure = next(item for item in state["data"]["failures"] if item["attempt_id"] == attempt["id"])
        failure.update(classification="valid-red", resolved=True)
    else:
        if progress["state"] != "open" or progress.get("red_attempt_id"):
            raise Rejected("not-initial-green", "Existing capability cannot erase recorded Red history.")
        progress.update(state="existing", mode="existing", existing_attempt_id=attempt["id"])
    return {"ok": True, "attempt_id": attempt["id"], "classification": classification}


def diagnose(state, event):
    if set(event) != {"schema", "op_id", "op", "attempt_id", "reason", "evidence", "next_action"}:
        raise Rejected("invalid-event", "A diagnosis requires the failed attempt, reason, evidence, and next action.")
    if (not nonempty(event["reason"]) or not nonempty(event["next_action"])
            or not isinstance(event["evidence"], list) or not event["evidence"]
            or not all(nonempty(item) for item in event["evidence"])):
        raise Rejected("invalid-diagnosis", "Supply a reason, evidence identifiers, and a discriminating next action.")
    failure = next((item for item in state["data"]["failures"] if item["attempt_id"] == event["attempt_id"]), None)
    if failure is None or failure["classification"] == "valid-red":
        raise Rejected("not-a-failure", "A diagnosis applies to a non-normal failure or interruption.")
    previous = {identifier for diagnosis in failure["diagnoses"] for identifier in diagnosis["evidence"]}
    if not set(event["evidence"]) - previous:
        raise Rejected("evidence-repeated", "A new diagnosis needs at least one new evidence identifier.")
    failure["diagnoses"].append({key: event[key] for key in ("reason", "evidence", "next_action")})
    failure["resolved"] = False
    return {"ok": True, "attempt_id": event["attempt_id"], "diagnosed": True}


def last_diagnosis_sequence(state, attempt_id):
    return max((entry["seq"] for entry in state["events"]
                if entry["event"]["op"] == "diagnose" and entry["event"]["attempt_id"] == attempt_id), default=0)


def close_example(state, event):
    required = {"schema", "op_id", "op", "example", "regression_attempt_id"}
    if set(event) not in (required, required | {"regression_scope"}):
        raise Rejected("invalid-event", "Unexpected or missing close fields.")
    example = next((item for item in state["plan"]["examples"] if item["id"] == event["example"]), None)
    if example is None:
        raise Rejected("unknown-example", "The example is not in this run.")
    data = state["data"]
    progress = data["examples"][example["id"]]
    if progress["state"] not in {"green", "existing"}:
        raise Rejected("no-green", "Closing requires current Green or verified existing capability.")
    current = capture(example["snapshot"])
    capability_id = progress.get("green_attempt_id") or progress.get("existing_attempt_id")
    capability = state["attempts"][capability_id]["receipt"]["snapshot"]["after"]
    if not same_oracle(current, capability):
        raise Rejected("stale-capability", "A new regression cannot replace the current example's independent Green criterion.")
    if any(state["attempts"][identifier]["flow"] == example["flow"] for identifier in data["pending_attempts"]):
        raise Rejected("attempt-pending", "Settle the current execution before closing.")
    attempt = state.get("attempts", {}).get(event["regression_attempt_id"])
    if attempt is None or attempt["example"] != example["id"] or attempt["state"] != "recorded":
        raise Rejected("invalid-regression", "Use a recorded regression for this example.")
    if attempt.get("eligible") is False:
        raise Rejected("ineligible-regression", "An execution with changing inputs cannot close a behavior.")
    if attempt["purpose"] == "green":
        if not nonempty(event.get("regression_scope")):
            raise Rejected("regression-scope-required", "Describe the regressions covered by this Green command.")
    elif attempt["purpose"] != "regression":
        raise Rejected("invalid-regression", "A probe cannot double as affected regression evidence.")
    receipt, receipt_digest = check_receipt(state, attempt)
    if receipt_digest != attempt["receipt_sha256"]:
        raise Rejected("receipt-changed", "The recorded execution receipt changed.")
    if receipt["outcome"] != "exited" or receipt["exit_code"] != 0 or current != receipt["snapshot"]["after"]:
        raise Rejected("stale-regression", "Passing affected regressions must match current files.")
    progress.update(state="closed", regression_attempt_id=attempt["id"])
    data["active_by_flow"][example["flow"]] = None
    return {"ok": True, "example": example["id"], "state": "closed", "mode": progress["mode"]}


def invocation(state, event):
    if set(event) != {"schema", "op_id", "op", "kind", "models"} or event["kind"] != "resume":
        raise Rejected("invalid-event", "A new resume invocation requires its explicit role choices.")
    validate_models(event["models"])
    state["models"] = event["models"]
    state["latest_invocation"] = event["op_id"]
    return {"ok": True, "invocation_id": event["op_id"]}


def scope_details(state, scope):
    if scope == {"final": True} and type(scope.get("final")) is bool:
        key = "final"
        identifiers = [example["id"] for example in state["plan"]["examples"]]
    elif isinstance(scope, dict) and set(scope) == {"gate"}:
        key = scope["gate"]
        gate = next((item for item in state["plan"]["gates"] if item["id"] == key), None)
        if gate is None:
            raise Rejected("unknown-gate", "The gate is not in this run.")
        identifiers = gate["prerequisites"]
    else:
        raise Rejected("invalid-scope", "Use one gate or the complete final scope.")
    snapshots = [example["snapshot"] for example in state["plan"]["examples"] if example["id"] in identifiers]
    snapshot = {"schema": 1, "root": state["plan"]["workspace"], "binding": None}
    for group in ("tests", "contract", "product"):
        snapshot[group] = sorted(unique_paths(snapshot["root"],
            [path for item in snapshots for path in item[group]], reject_duplicates=False))
    return key, identifiers, snapshot


def qualify(state, event):
    if set(event) != {"schema", "op_id", "op", "scope", "spec_review", "standards_review"}:
        raise Rejected("invalid-event", "Qualification requires both independent review axes.")
    for name in ("spec_review", "standards_review"):
        review = event[name]
        if (not isinstance(review, dict) or set(review) != {"review_id", "source", "independent_context", "verdict"}
                or not all(nonempty(value) for value in review.values()) or review["verdict"] != "pass"):
            raise Rejected("review-required", "Both independent review axes must pass with provenance.")
    key, identifiers, snapshot = scope_details(state, event["scope"])
    for failure in state["data"]["failures"]:
        attempt = state["attempts"][failure["attempt_id"]]
        if (failure["classification"] == "unclassified" and not failure["diagnoses"]
                and attempt["purpose"] == "formal" and attempt.get("scope_examples")
                and set(identifiers).issubset(attempt["scope_examples"])):
            raise Rejected("diagnosis-required",
                           "Judge and diagnose the failed formal attempt before new qualification of its scope.")
    current = capture(snapshot)
    state.setdefault("qualifications", {})[key] = {
        "examples": identifiers, "snapshot": current, "event": event, "seq": len(state["events"]) + 1,
    }
    return {"ok": True, "scope": event["scope"], "qualified": True}


def check_qualification(state, key, identifiers, snapshot):
    qualification = state.get("qualifications", {}).get(key)
    if qualification is None or qualification["examples"] != identifiers:
        raise Rejected("qualification-stale", "Obtain both current test review axes for the full scope.")
    current = capture(snapshot)
    if (not same_oracle(qualification["snapshot"], current)
            or qualification["seq"] <= state.get("scope_versions", {}).get(key, 0)
            or (key == "final" and qualification["seq"] <= state.get("latest_extend_seq", 0))):
        raise Rejected("qualification-stale", "Obtain both current test review axes for the full scope.")
    return current


def prepare_formal(state, event, state_dir):
    if set(event) != {"schema", "op_id", "op", "scope", "timeout_seconds"}:
        raise Rejected("invalid-event", "Unexpected or missing formal preparation fields.")
    key, identifiers, snapshot = scope_details(state, event["scope"])
    if state["data"]["pending_attempts"]:
        raise Rejected("attempt-pending", "Formal execution requires settled development attempts.")
    if any(state["data"]["examples"][identifier]["state"] != "closed" for identifier in identifiers):
        raise Rejected("scope-incomplete", "Close every prerequisite example before formal execution.")
    current = check_qualification(state, key, identifiers, snapshot)
    result = reserve_attempt(state, event, state_dir, snapshot, current, None, None, key, "formal")
    state["attempts"][result["attempt_id"]]["scope_examples"] = identifiers
    if key != "final":
        state["data"]["gates"][key]["attempt_ids"].append(result["attempt_id"])
    return result


def git_candidate(workspace, require_clean=True):
    head = subprocess.run(["git", "-C", workspace, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    status = subprocess.run(["git", "-C", workspace, "status", "--porcelain", "--untracked-files=all"],
                            capture_output=True, text=True, check=True, timeout=10).stdout
    if require_clean and status.strip():
        raise Rejected("dirty-candidate", "The formal candidate must remain clean.")
    return head


def check_formal(state, identifier, key, require_clean=True):
    attempt = state.get("attempts", {}).get(identifier)
    if (attempt is None or attempt["state"] != "recorded" or attempt.get("eligible") is False or attempt["purpose"] != "formal"
            or attempt["request"]["binding"]["gate"] != key):
        raise Rejected("formal-required", "Use the recorded formal execution for this scope.")
    if key == "final" and attempt["request"]["binding"]["prepared_seq"] <= state.get("latest_extend_seq", 0):
        raise Rejected("formal-stale", "The final execution must cover the latest appended examples.")
    if attempt["request"]["binding"]["prepared_seq"] <= state.get("scope_versions", {}).get(key, 0):
        raise Rejected("formal-stale", "The formal execution predates an explicit behavior revision.")
    scope = {"final": True} if key == "final" else {"gate": key}
    _, identifiers, snapshot = scope_details(state, scope)
    current = check_qualification(state, key, identifiers, snapshot)
    if any(state["data"]["examples"][item]["state"] != "closed" for item in identifiers):
        raise Rejected("scope-incomplete", "The formal scope contains unfinished examples.")
    receipt, checksum = check_receipt(state, attempt)
    formal = receipt["formal"]
    if (checksum != attempt["receipt_sha256"] or receipt["outcome"] != "exited" or receipt["exit_code"] != 0
            or formal.get("requested") is not True or formal.get("clean_before") is not True
            or formal.get("clean_after") is not True or not nonempty(formal.get("head_before"))
            or formal["head_before"] != formal.get("head_after")
            or current != receipt["snapshot"]["after"]
            or git_candidate(state["plan"]["workspace"], require_clean=require_clean) != formal["head_after"]):
        raise Rejected("formal-stale", "Formal success must match the current clean, committed candidate.")
    return formal["head_after"]


def release(state, event):
    if set(event) != {"schema", "op_id", "op", "gate", "attempt_id"}:
        raise Rejected("invalid-event", "Release names a gate and its formal attempt.")
    check_formal(state, event["attempt_id"], event["gate"])
    state["data"]["gates"][event["gate"]].update(state="released", release_attempt_id=event["attempt_id"])
    return {"ok": True, "gate": event["gate"], "state": "released"}


def finish(state, event):
    if set(event) != {"schema", "op_id", "op", "attempt_id", "code_reviews"}:
        raise Rejected("invalid-event", "Finish requires the final attempt and both code review axes.")
    if state["data"]["pending_attempts"]:
        raise Rejected("attempt-pending", "Settle every prepared execution before declaring the candidate ready.")
    selected = state.get("attempts", {}).get(event["attempt_id"])
    if selected is None:
        raise Rejected("formal-required", "Select an existing formal attempt.")
    for failure in state["data"]["failures"]:
        if failure["classification"] == "valid-red":
            continue
        if (not failure["resolved"] or not failure["diagnoses"]
                or selected["request"]["binding"]["prepared_seq"] <= last_diagnosis_sequence(state, failure["attempt_id"])):
            raise Rejected("failure-unresolved", "Diagnose each failure and obtain subsequent formal proof before finishing.")
    head = check_formal(state, event["attempt_id"], "final")
    reviews = event["code_reviews"]
    if not isinstance(reviews, dict) or set(reviews) != {"spec", "standards"}:
        raise Rejected("review-required", "Both code review axes must pass on the final candidate.")
    for review in reviews.values():
        if (not isinstance(review, dict) or set(review) != {"head", "review_id", "verdict"}
                or not nonempty(review["review_id"]) or review["verdict"] != "pass" or review["head"] != head):
            raise Rejected("review-head-mismatch", "Both code reviews must pass on the actual final execution HEAD.")
    state["data"]["status"] = "ready"
    state["finished"] = {"attempt_id": event["attempt_id"], "head": head,
                         "code_reviews": reviews, "seq": len(state["events"]) + 1}
    return {"ok": True, "status": "ready", "head": head}


def affected_closure(plan, identifiers):
    affected = set(identifiers)
    while True:
        previous = set(affected)
        for example in plan["examples"]:
            if affected.intersection(example["depends_on"]):
                affected.add(example["id"])
        for gate in plan["gates"]:
            if affected.intersection(gate["prerequisites"]):
                affected.update(gate["consumers"])
        if affected == previous:
            return affected


def require_local_boundary(state, plan, affected, revised=()):
    flows = {example["flow"] for example in plan["examples"] if example["id"] in affected}
    for identifier in state["data"]["pending_attempts"]:
        attempt = state["attempts"][identifier]
        gate = attempt["request"]["binding"]["gate"]
        if (gate == "final" or attempt["flow"] in flows or attempt["example"] in affected
                or affected.intersection(attempt.get("scope_examples", []))):
            raise Rejected("attempt-pending", "Settle attempts in the affected scope before changing its plan.")
    for flow, active in state["data"]["active_by_flow"].items():
        if flow in flows and active is not None and active not in revised:
            raise Rejected("active-work", "Affected flows must reach a safe boundary before changing their plan.")


def extend(state, event):
    if set(event) != {"schema", "op_id", "op", "source", "reason", "examples", "flows", "gates"}:
        raise Rejected("invalid-event", "Extension requires source, reason, and all three append lists.")
    if not nonempty(event["source"]) or not nonempty(event["reason"]):
        raise Rejected("source-required", "An extension needs authoritative scope and reasoning.")
    for name in ("examples", "flows", "gates"):
        if not isinstance(event[name], list) or (name == "examples" and not event[name]):
            raise Rejected("invalid-extension", "Append at least one example and declare all lists.")
    data = state["data"]
    candidate = copy.deepcopy(state["plan"])
    for name in ("examples", "flows", "gates"):
        candidate[name].extend(copy.deepcopy(event[name]))
    validate_plan(candidate)
    for gate in event["gates"]:
        if any(identifier in data["examples"] and data["examples"][identifier]["state"] != "planned"
               for identifier in gate["consumers"]):
            raise Rejected("consumer-started", "A new gate cannot retroactively block an opened consumer.")
    affected = affected_closure(candidate, {
        *[example["id"] for example in event["examples"]],
        *[identifier for gate in event["gates"] for identifier in gate["consumers"]],
    })
    require_local_boundary(state, candidate, affected)
    state.setdefault("initial_plan", copy.deepcopy(state["plan"]))
    state["plan"] = candidate
    for example in event["examples"]:
        data["examples"][example["id"]] = {"state": "planned", "mode": None, "attempt_ids": []}
        data.setdefault("staged", {}).pop(example["id"], None)
    for flow in event["flows"]:
        data["active_by_flow"][flow["id"]] = None
    for gate in event["gates"]:
        data["gates"][gate["id"]] = {"state": "pending", "attempt_ids": []}
    state["latest_extend_seq"] = len(state["events"]) + 1
    state.get("qualifications", {}).pop("final", None)
    for gate in candidate["gates"]:
        if affected.intersection(gate["prerequisites"]):
            state.get("qualifications", {}).pop(gate["id"], None)
            state.setdefault("scope_versions", {})[gate["id"]] = state["latest_extend_seq"]
            data["gates"][gate["id"]]["state"] = "pending"
    data["status"] = "active"
    return {"ok": True, "op_id": event["op_id"], "status": "active",
            "added": {name: [item["id"] for item in event[name]] for name in ("examples", "flows", "gates")}}


def revise(state, event):
    if (set(event) != {"schema", "op_id", "op", "examples", "source", "reason"}
            or not nonempty(event["source"]) or not nonempty(event["reason"])
            or not isinstance(event["examples"], list) or not event["examples"]
            or len(set(event["examples"])) != len(event["examples"])):
        raise Rejected("invalid-event", "A revision requires affected examples and authoritative reasoning.")
    data = state["data"]
    if any(identifier not in data["examples"] for identifier in event["examples"]):
        raise Rejected("unknown-example", "Only existing examples can be revised.")
    for identifier in data["pending_attempts"]:
        attempt = state["attempts"][identifier]
        if (attempt["purpose"] == "formal"
                and not same_oracle(capture(attempt["request"]), attempt["prepared_snapshot"])):
            raise Rejected("attempt-pending", "A pending formal criterion changed; settle its affected scope before revision.")
    sequence = len(state["events"]) + 1
    affected = set(event["examples"])
    captures = {}
    for example in state["plan"]["examples"]:
        progress = data["examples"][example["id"]]
        current = captures[example["id"]] = capture(example["snapshot"])
        source = progress.get("green_attempt_id") or progress.get("existing_attempt_id") or progress.get("red_attempt_id")
        regression = state.get("attempts", {}).get(progress.get("regression_attempt_id"))
        if (progress["state"] == "closed" and regression is not None
                and regression["state"] == "recorded" and regression.get("eligible") is not False):
            receipt = regression["receipt"]
            formal = receipt["formal"]
            formal_success = (regression["purpose"] == "formal" and formal.get("requested") is True
                              and formal.get("clean_before") is True and formal.get("clean_after") is True
                              and nonempty(formal.get("head_before")) and formal["head_before"] == formal.get("head_after"))
            if (receipt["outcome"] == "exited" and receipt["exit_code"] == 0
                    and (regression["purpose"] == "regression" or formal_success)):
                source = regression["id"]
        baseline = (state["attempts"][source]["receipt"]["snapshot"]["after"] if source
                    else progress.get("opening", progress.get("revision_snapshot")))
        if baseline is not None and not same_scoped_oracle(example["snapshot"], current, baseline):
            affected.add(example["id"])
        for identifier in data["pending_attempts"]:
            attempt = state["attempts"][identifier]
            if attempt["example"] == example["id"] and not same_oracle(current, attempt["prepared_snapshot"]):
                affected.add(example["id"])
    affected = affected_closure(state["plan"], affected)
    require_local_boundary(state, state["plan"], affected, revised=event["examples"])
    for example in state["plan"]["examples"]:
        progress = data["examples"][example["id"]]
        if example["id"] in event["examples"]:
            attempts = progress["attempt_ids"]
            progress.clear()
            progress.update(state="planned", mode=None, attempt_ids=attempts, revision_seq=sequence,
                            revision_snapshot=captures[example["id"]])
            if data["active_by_flow"][example["flow"]] == example["id"]:
                data["active_by_flow"][example["flow"]] = None
            data.setdefault("staged", {}).pop(example["id"], None)
        elif example["id"] in affected:
            progress["evidence_stale"] = True
    invalidated = {"final"}
    for gate in state["plan"]["gates"]:
        if affected.intersection(gate["prerequisites"]):
            invalidated.add(gate["id"])
            data["gates"][gate["id"]]["state"] = "pending"
    for key, qualification in list(state.get("qualifications", {}).items()):
        _, identifiers, snapshot = scope_details(state, {"final": True} if key == "final" else {"gate": key})
        if affected.intersection(identifiers) or not same_oracle(qualification["snapshot"], capture(snapshot)):
            invalidated.add(key)
    for key in invalidated:
        state.get("qualifications", {}).pop(key, None)
        state.setdefault("scope_versions", {})[key] = sequence
    data["status"] = "active"
    return {"ok": True, "examples": event["examples"], "status": "active"}


def include(state, event):
    if (set(event) != {"schema", "op_id", "op", "source", "reason", "items"}
            or not nonempty(event["source"]) or not nonempty(event["reason"])
            or not isinstance(event["items"], list) or not event["items"]):
        raise Rejected("invalid-event", "Dependency inclusion requires authoritative source, reason, and items.")
    data = state["data"]
    candidate = copy.deepcopy(state["plan"])
    examples = {example["id"]: example for example in candidate["examples"]}
    included = []
    added_paths = []
    for item in event["items"]:
        if (not isinstance(item, dict) or set(item) != {"example", "tests", "contract", "product"}
                or not nonempty(item["example"]) or item["example"] not in examples or item["example"] in included):
            raise Rejected("invalid-inclusion", "Each included example must occur once and already exist.")
        snapshot = examples[item["example"]]["snapshot"]
        additions = 0
        for group in ("tests", "contract", "product"):
            if not isinstance(item[group], list):
                raise Rejected("invalid-inclusion", "All three additional dependency lists are required.")
            normalized = [relative_path(path) for path in item[group]]
            combined = unique_paths(state["plan"]["workspace"], [*snapshot[group], *normalized])
            additions += len(normalized)
            added_paths.extend(normalized)
            snapshot[group] = sorted(combined)
        if not additions:
            raise Rejected("no-new-dependency", "Each item must append at least one new dependency path.")
        capture(snapshot)
        included.append(item["example"])
    validate_plan(candidate)
    affected = set(included)
    for example in state["plan"]["examples"]:
        if any(paths_overlap(candidate["workspace"], added, path)
               for added in added_paths for group in ("tests", "contract", "product")
               for path in example["snapshot"][group]):
            affected.add(example["id"])
    affected = affected_closure(candidate, affected)
    require_local_boundary(state, candidate, affected)
    state.setdefault("initial_plan", copy.deepcopy(state["plan"]))
    state["plan"] = candidate
    sequence = len(state["events"]) + 1
    invalidated = {"final"}
    for identifier in included:
        data["examples"][identifier]["evidence_stale"] = True
    for gate in candidate["gates"]:
        if affected.intersection(gate["prerequisites"]):
            invalidated.add(gate["id"])
            data["gates"][gate["id"]]["state"] = "pending"
    for key in invalidated:
        state.get("qualifications", {}).pop(key, None)
        state.setdefault("scope_versions", {})[key] = sequence
    data["status"] = "active"
    return {"ok": True, "op_id": event["op_id"], "included_examples": included, "status": "active"}


def audit_history(state, state_path):
    checksum = state.get("sha256")
    if checksum != digest({key: value for key, value in state.items() if key != "sha256"}):
        raise Rejected("state-changed", "The durable state checksum is invalid.")
    anchor = read_json(Path(state["anchor_path"]))
    def matches(entry):
        return (entry["run_id"] == state["plan"]["run_id"] and entry["state_path"] == str(state_path)
                and entry["plan_sha256"] == digest(state.get("initial_plan", state["plan"])))

    if not any(matches(entry) for entry in [anchor, *anchor.get("history", [])]):
        raise Rejected("anchor-changed", "The run no longer matches its scope anchor.")
    previous, identifiers = None, set()
    for sequence, entry in enumerate(state["events"], 1):
        if (entry["seq"] != sequence or entry["previous_sha256"] != previous
                or entry["sha256"] != digest({key: value for key, value in entry.items() if key != "sha256"})
                or entry["event"]["op_id"] in identifiers):
            raise Rejected("history-changed", "The operation history is missing, reordered, or changed.")
        previous = entry["sha256"]
        identifiers.add(entry["event"]["op_id"])
    for attempt in state.get("attempts", {}).values():
        if (attempt["state"] != "recorded"
                and hashlib.sha256(Path(attempt["request_path"]).read_bytes()).hexdigest() != attempt["request_sha256"]):
            raise Rejected("request-changed", "A historical request has changed.")
        if attempt["state"] == "recorded":
            _, checksum = check_receipt(state, attempt)
            if checksum != attempt["receipt_sha256"]:
                raise Rejected("receipt-changed", "A historical receipt has changed.")
        elif attempt["state"] == "interrupted" and attempt.get("claim_sha256"):
            claim_path = Path(attempt["receipt_path"] + ".claim.json")
            if hashlib.sha256(claim_path.read_bytes()).hexdigest() != attempt["claim_sha256"]:
                raise Rejected("claim-changed", "The interruption ownership evidence has changed.")
    return matches(anchor)


def historical_completion(state):
    finished = state.get("finished")
    if (state["data"]["status"] != "ready" or not finished or state["data"]["pending_attempts"]
            or any(not item["resolved"] for item in state["data"]["failures"])):
        raise Rejected("scope-active", "The prior run must have a complete, auditable historical finish.")
    entry = state["events"][finished["seq"] - 1]
    attempt = state["attempts"][finished["attempt_id"]]
    receipt = attempt["receipt"]
    formal = receipt["formal"]
    if (entry["event"]["op"] != "finish" or entry["result"].get("status") != "ready"
            or entry["event"]["attempt_id"] != finished["attempt_id"]
            or receipt["outcome"] != "exited" or receipt["exit_code"] != 0
            or attempt.get("eligible") is False or formal["requested"] is not True
            or formal["clean_before"] is not True or formal["clean_after"] is not True
            or formal["head_before"] != finished["head"] or formal["head_after"] != finished["head"]
            or any(review["head"] != finished["head"] or review["verdict"] != "pass"
                   for review in finished["code_reviews"].values())):
        raise Rejected("historical-finish-invalid", "The prior finish does not match its fixed execution and review evidence.")


def verify_current(state):
    # Earlier gates remain auditable history after their consumers advance HEAD.
    # Their freshness is checked when a new consumer attempts to use them.
    if state["data"]["status"] == "ready":
        check_formal(state, state["finished"]["attempt_id"], "final")


def save_state(path, state):
    state["sha256"] = digest({key: value for key, value in state.items() if key != "sha256"})
    atomic_json(path, state)


def controller_status(claim, receipt_path):
    if (not isinstance(claim, dict) or set(claim) != {"schema", "receipt_path", "token", "controller", "created_at"}
            or type(claim["schema"]) is not int or claim["schema"] != 1
            or claim["receipt_path"] != str(receipt_path) or not nonempty(claim["token"])):
        return "ownership-unknown"
    controller = claim["controller"]
    if (not isinstance(controller, dict) or set(controller) != {"platform", "pid", "birth_token"}
            or type(controller["pid"]) is not int or controller["pid"] <= 0):
        return "ownership-unknown"
    if os.name != "nt" or controller["platform"] != "windows":
        return "ownership-unknown"
    birth = controller["birth_token"]
    if not isinstance(birth, str) or not birth.isdecimal():
        return "ownership-unknown"
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000 | 0x1000, False, controller["pid"])
    if not handle:
        return "dead" if ctypes.get_last_error() == 87 else "ownership-unknown"
    try:
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
            return "ownership-unknown"
        actual_birth = (created.dwHighDateTime << 32) | created.dwLowDateTime
        if str(actual_birth) != birth:
            return "dead"
        wait = kernel.WaitForSingleObject(handle, 0)
        return "running" if wait == 258 else "dead" if wait == 0 else "ownership-unknown"
    finally:
        kernel.CloseHandle(handle)


def recover(state, event):
    if set(event) != {"schema", "op_id", "op", "invocation_id"} or event["invocation_id"] != state.get("latest_invocation"):
        raise Rejected("invocation-required", "Recover must reference the latest explicit resume invocation.")
    reconciled, blocked, reasons = [], [], []
    data = state["data"]
    for identifier in list(data["pending_attempts"]):
        attempt = state["attempts"][identifier]
        receipt_path = Path(attempt["receipt_path"])
        if receipt_path.exists():
            record(state, {"schema": 1, "op_id": event["op_id"], "op": "record", "attempt_id": identifier})
            reconciled.append(identifier)
            continue
        claim_path = Path(str(receipt_path) + ".claim.json")
        cancellation = {"schema": 1, "receipt_path": str(receipt_path), "cancelled_attempt": identifier,
                        "created_at": datetime.now(timezone.utc).isoformat()}
        try:
            with claim_path.open("x", encoding="utf-8") as stream:
                json.dump(cancellation, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            pass
        try:
            claim = read_json(claim_path)
        except (OSError, ValueError):
            claim = {}
        cancelled = (set(claim) == {"schema", "receipt_path", "cancelled_attempt", "created_at"}
                     and type(claim.get("schema")) is int and claim["schema"] == 1
                     and claim.get("receipt_path") == str(receipt_path)
                     and claim.get("cancelled_attempt") == identifier)
        ownership = "dead" if cancelled else controller_status(claim, receipt_path)
        if ownership != "dead":
            attempt["recovery_state"] = ownership
            blocked.append(identifier)
            reasons.append(ownership)
            continue
        timeout = attempt["request"]["timeout_seconds"]
        attempt["state"] = "interrupted"
        attempt["claim_sha256"] = hashlib.sha256(claim_path.read_bytes()).hexdigest()
        data["pending_attempts"].remove(identifier)
        data["budget"]["seconds_reserved"] -= timeout
        data["budget"]["seconds_used"] += timeout
        if attempt["purpose"] == "formal":
            data["budget"]["formal_failures_used"] += 1
        data["failures"].append({"attempt_id": identifier, "classification": "interrupted",
                                 "resolved": False, "diagnoses": []})
        reconciled.append(identifier)
    if blocked:
        data["status"] = "blocked"
        reason = "ownership-unknown" if "ownership-unknown" in reasons else "running"
        return {"ok": True, "status": "blocked", "reason": reason, "attempt_ids": blocked}
    if data["status"] != "ready":
        data["status"] = "active"
    return {"ok": True, "status": data["status"], "reconciled_attempts": reconciled}


def validate_event_header(event):
    if (not isinstance(event, dict) or type(event.get("schema")) is not int
            or event["schema"] != 1 or not nonempty(event.get("op_id")) or not nonempty(event.get("op"))):
        raise Rejected("invalid-event", "Events require schema 1 and a nonempty op_id.")
    if event["op"] not in OPERATIONS:
        raise Rejected("unknown-operation", "Unsupported operation.")


def apply_event(state, event, state_dir):
    validate_event_header(event)
    for execution in state.get("executions", {}).values():
        record_id = execution["request"]["record_op_id"]
        if event["op_id"] == record_id and event != {
            "schema": 1, "op_id": record_id, "op": "record", "attempt_id": execution["attempt_id"]
        }:
            raise Rejected("op-id-conflict", "This operation ID is reserved for its bound execution record.")
    for previous_event in state["events"]:
        if previous_event["event"]["op_id"] == event["op_id"]:
            if previous_event["event"] != event:
                raise Rejected("op-id-conflict", "An op_id cannot be reused with different content.")
            return previous_event["result"]
    if event.get("op") == "open":
        result = open_example(state, event)
    elif event.get("op") == "stage":
        result = stage_test(state, event)
    elif event.get("op") == "promote":
        result = promote_test(state, event)
    elif event.get("op") == "prepare":
        result = prepare(state, event, state_dir)
    elif event.get("op") == "record":
        result = record(state, event)
    elif event.get("op") == "judge":
        result = judge(state, event)
    elif event.get("op") == "diagnose":
        result = diagnose(state, event)
    elif event.get("op") == "close":
        result = close_example(state, event)
    elif event.get("op") == "invocation":
        result = invocation(state, event)
    elif event.get("op") == "recover":
        result = recover(state, event)
    elif event.get("op") == "qualify":
        result = qualify(state, event)
    elif event.get("op") == "prepare-formal":
        result = prepare_formal(state, event, state_dir)
    elif event.get("op") == "release":
        result = release(state, event)
    elif event.get("op") == "finish":
        result = finish(state, event)
    elif event.get("op") == "extend":
        result = extend(state, event)
    elif event.get("op") == "revise":
        result = revise(state, event)
    elif event.get("op") == "include":
        result = include(state, event)
    else:
        raise Rejected("unknown-operation", "Unsupported operation.")
    sequence = len(state["events"]) + 1
    result["seq"] = sequence
    previous = state["events"][-1]["sha256"] if state["events"] else None
    entry = {"seq": sequence, "previous_sha256": previous, "event": event, "result": result}
    entry["sha256"] = digest(entry)
    state["events"].append(entry)
    return result


def apply_batch(state_path, envelope):
    results = []
    try:
        if (not isinstance(envelope, dict) or set(envelope) != {"schema", "events"}
                or type(envelope["schema"]) is not int or envelope["schema"] != 1
                or not isinstance(envelope["events"], list) or not envelope["events"]):
            raise Rejected("invalid-batch", "A schema-1 batch requires a nonempty events list.")
        identifiers = set()
        for event in envelope["events"]:
            validate_event_header(event)
            if event["op_id"] in identifiers:
                raise Rejected("op-id-conflict", "Each batch item requires a distinct operation ID.")
            identifiers.add(event["op_id"])
    except (Rejected, OSError, ValueError, KeyError, TypeError) as error:
        return {"ok": False, "results": [], "failed_index": None,
                "error": {"code": getattr(error, "code", "invalid-input"), "message": str(error)}}
    for index, event in enumerate(envelope["events"]):
        state_lock = None
        try:
            state_lock = lock_state(state_path.parent)
            state = read_json(state_path)
            if not audit_history(state, state_path):
                raise Rejected("historical-run", "A completed historical run is preserved read-only after new requirements start.")
            result = apply_event(state, event, state_path.parent)
            save_state(state_path, state)
            results.append(result)
        except (Rejected, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            return {"ok": False, "results": results, "failed_index": index,
                    "error": {"code": getattr(error, "code", "invalid-input"), "message": str(error)}}
        finally:
            if state_lock is not None:
                state_lock.close()
    return {"ok": True, "results": results}


def execution_result(attempt, execution_digest, prepared, recorded):
    receipt = attempt["receipt"]
    return {"ok": True, "attempt_id": attempt["id"], "execution_sha256": execution_digest,
            "prepare": prepared, "record": recorded,
            "outcome": receipt["outcome"], "exit_code": receipt["exit_code"]}


def execute_request(state_path, request):
    if (not isinstance(request, dict) or set(request) != {"schema", "prepare", "record_op_id", "argv"}
            or type(request["schema"]) is not int or request["schema"] != 1
            or not nonempty(request["record_op_id"])
            or not isinstance(request["argv"], list) or not request["argv"]
            or not all(nonempty(argument) for argument in request["argv"])):
        raise Rejected("invalid-execution", "An execution requires its preparation, distinct record ID, and argument array.")
    preparation = request["prepare"]
    validate_event_header(preparation)
    if preparation["op"] not in {"prepare", "prepare-formal"} or preparation["op_id"] == request["record_op_id"]:
        raise Rejected("invalid-execution", "Use a preparation event and a separate record operation ID.")
    execution_digest = digest(request)
    with lock_state(state_path.parent):
        state = read_json(state_path)
        if not audit_history(state, state_path):
            raise Rejected("historical-run", "A completed historical run is preserved read-only after new requirements start.")
        executions = state.setdefault("executions", {})
        binding = executions.get(preparation["op_id"])
        if binding is not None:
            if binding["sha256"] != execution_digest:
                raise Rejected("execution-conflict", "An execution preparation is bound to its original request.")
            recorded = next((entry for entry in state["events"]
                             if entry["event"]["op_id"] == request["record_op_id"]), None)
            attempt = state["attempts"][binding["attempt_id"]]
            if recorded is not None and recorded["event"] == {
                "schema": 1, "op_id": request["record_op_id"], "op": "record", "attempt_id": attempt["id"]
            }:
                prepared = state["events"][attempt["request"]["binding"]["prepared_seq"] - 1]["result"]
                return execution_result(attempt, execution_digest, prepared, recorded["result"])
            if attempt["state"] != "prepared":
                raise Rejected("execution-settled", "Another event already settled this execution; use its original evidence.")
            if Path(attempt["receipt_path"]).is_file():
                prepared = state["events"][attempt["request"]["binding"]["prepared_seq"] - 1]["result"]
                recorded = apply_event(state, {"schema": 1, "op_id": request["record_op_id"],
                                              "op": "record", "attempt_id": attempt["id"]}, state_path.parent)
                save_state(state_path, state)
                return execution_result(attempt, execution_digest, prepared, recorded)
            raise Rejected("recovery-required", "An earlier preparation cannot launch another command.")
        reserved_records = {item["request"]["record_op_id"] for item in executions.values()}
        if reserved_records.intersection({preparation["op_id"], request["record_op_id"]}):
            raise Rejected("op-id-conflict", "This operation ID is reserved for another execution record.")
        identifiers = {entry["event"]["op_id"] for entry in state["events"]}
        if preparation["op_id"] in identifiers:
            raise Rejected("execution-unbound", "An ordinary preparation cannot be adopted for execution.")
        if (request["record_op_id"] in identifiers
                or any({preparation["op_id"], request["record_op_id"]}.intersection(
                    {item["request"]["prepare"]["op_id"], item["request"]["record_op_id"]})
                       for item in executions.values())):
            raise Rejected("execution-conflict", "Execution operation IDs already belong to other work.")
        prepared = apply_event(state, preparation, state_path.parent)
        attempt = state["attempts"][prepared["attempt_id"]]
        executions[preparation["op_id"]] = {
            "request": request, "sha256": execution_digest, "attempt_id": attempt["id"],
        }
        save_state(state_path, state)

    from run_command import main as run_command

    arguments = ["--receipt", attempt["receipt_path"], "--cwd", attempt["request"]["root"],
                 "--timeout", str(attempt["request"]["timeout_seconds"]),
                 "--snapshot", attempt["request_path"]]
    if attempt["purpose"] == "formal":
        arguments.append("--formal")
    run_command([*arguments, "--", *request["argv"]])

    with lock_state(state_path.parent):
        state = read_json(state_path)
        if not audit_history(state, state_path):
            raise Rejected("historical-run", "The execution no longer owns the current scope.")
        attempt = state["attempts"][prepared["attempt_id"]]
        if not Path(attempt["receipt_path"]).is_file():
            raise Rejected("execution-incomplete", "The execution has no complete receipt; preserve its reservation for recovery.")
        recorded = apply_event(state, {"schema": 1, "op_id": request["record_op_id"],
                                      "op": "record", "attempt_id": attempt["id"]}, state_path.parent)
        save_state(state_path, state)
        return execution_result(attempt, execution_digest, prepared, recorded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init")
    initialize.add_argument("--plan", required=True, type=Path)
    commands.add_parser("inspect")
    commands.add_parser("verify")
    apply = commands.add_parser("apply")
    apply.add_argument("--event", required=True, type=Path)
    batch = commands.add_parser("batch")
    batch.add_argument("--events", required=True, type=Path)
    execute = commands.add_parser("execute")
    execute.add_argument("--request", required=True, type=Path)
    args = parser.parse_args(argv)
    state_lock = None
    try:
        state_path = args.state.resolve() / "state.json"
        if args.command == "batch":
            result = apply_batch(state_path, read_json(args.events))
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["ok"] else 2
        if args.command == "execute":
            result = execute_request(state_path, read_json(args.request))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        state_lock = lock_state(state_path.parent)
        if args.command == "init":
            plan = read_json(args.plan)
            validate_plan(plan)
            created = not state_path.exists()
            if not created:
                state = read_json(state_path)
                audit_history(state, state_path)
                if state.get("initial_plan", state["plan"]) != plan:
                    raise Rejected("already-initialized", "The run exists with a different plan.")
                claim_scope(plan, state_path)
            else:
                anchor_path = claim_scope(plan, state_path)
                state = {"schema": 1, "plan": plan, "events": [], "data": initial_data(plan),
                         "anchor_path": anchor_path,
                         "started_at": datetime.now(timezone.utc).isoformat()}
                save_state(state_path, state)
            result = {"ok": True, "run_id": plan["run_id"],
                      "state_dir": str(state_path.parent), "created": created}
        else:
            state = read_json(state_path)
            current_run = audit_history(state, state_path)
            if args.command == "apply":
                if not current_run:
                    raise Rejected("historical-run", "A completed historical run is preserved read-only after new requirements start.")
                result = apply_event(state, read_json(args.event), state_path.parent)
                save_state(state_path, state)
            elif args.command == "verify":
                if current_run:
                    verify_current(state)
                else:
                    historical_completion(state)
                result = {"ok": True, "valid": True, "last_seq": len(state["events"])}
            else:
                result = inspect_state(state)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (Rejected, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        failure = {"ok": False, "error": {
            "code": getattr(error, "code", "invalid-input"), "message": str(error)
        }}
        if args.command == "batch":
            failure.update(results=[], failed_index=None)
        print(json.dumps(failure, ensure_ascii=False))
        return 2
    finally:
        if state_lock is not None:
            state_lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
