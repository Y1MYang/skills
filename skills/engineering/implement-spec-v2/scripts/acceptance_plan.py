"""Finite checkpoint admission; lifecycle and failure history stay in resources.

All admission and registration run under the resource ledger's existing lock.
Limits charge declared command horizons, including uncertain attempts, without
refunds. They do not cap the separate final acceptance chain.
"""

import copy
import math


PROTOCOL = "implement-spec-plan/1"


def _text(value, label, h):
    if not isinstance(value, str) or not value.strip():
        raise h.Refusal(label + " must be a nonempty string")
    return value


def _positive(value, label, h, integer=False):
    valid = type(value) is int if integer else type(value) in (int, float)
    try:
        finite = valid and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value <= 0:
        raise h.Refusal(label + " must be positive and finite")
    return value


def _scope(value, h):
    if not isinstance(value, list) or not value:
        raise h.Refusal("acceptance must be a nonempty list")
    for item in value:
        _text(item, "acceptance pointer", h)
    if len(set(value)) != len(value):
        raise h.Refusal("acceptance pointers must be unique")
    return value


def _validate(value, h):
    fields = {"version", "approval", "max_parallel_checkpoints", "max_checkpoint_attempts", "checkpoints", "final"}
    if not isinstance(value, dict) or set(value) != fields or type(value.get("version")) is not int or value["version"] != 1:
        raise h.Refusal("acceptance plan requires the version-1 plan schema")
    _text(value["approval"], "plan approval pointer", h)
    for name in ("max_parallel_checkpoints", "max_checkpoint_attempts"):
        _positive(value[name], name, h, integer=True)
    final = value["final"]
    if not isinstance(final, dict) or set(final) != {"key", "acceptance"}:
        raise h.Refusal("final requires key and acceptance")
    h.checked_id(_text(final["key"], "final key", h))
    _scope(final["acceptance"], h)
    checkpoints = value["checkpoints"]
    if not isinstance(checkpoints, list):
        raise h.Refusal("checkpoints must be a finite list")
    entries = {}
    for item in checkpoints:
        fields = {"key", "acceptance", "depends_on", "repair_limit", "max_attempts", "max_total_seconds"}
        if not isinstance(item, dict) or set(item) != fields:
            raise h.Refusal("checkpoint requires key, acceptance, depends_on, repair_limit, max_attempts and max_total_seconds")
        key = h.checked_id(_text(item["key"], "checkpoint key", h))
        if key == final["key"] or key in entries:
            raise h.Refusal("plan keys must be unique and distinct from the final key")
        if not set(_scope(item["acceptance"], h)).issubset(final["acceptance"]):
            raise h.Refusal("checkpoint acceptance must belong to the final approved scope")
        dependencies = item["depends_on"]
        if not isinstance(dependencies, list) or any(not isinstance(key, str) for key in dependencies) or len(set(dependencies)) != len(dependencies):
            raise h.Refusal("depends_on must list unique checkpoint keys")
        if type(item["repair_limit"]) is not int or item["repair_limit"] not in (1, 2):
            raise h.Refusal("checkpoint repair_limit must be 1 or 2")
        _positive(item["max_attempts"], "max_attempts", h, integer=True)
        _positive(item["max_total_seconds"], "max_total_seconds", h)
        entries[key] = item
    pending = set(entries)
    done = set()
    while pending:
        ready = {key for key in pending if set(entries[key]["depends_on"]).issubset(done)}
        if not ready:
            raise h.Refusal("checkpoint dependencies contain unknown keys or a cycle")
        pending -= ready
        done |= ready
    return copy.deepcopy(value)


def _plan(state, h):
    if "acceptance_plan_protocol" in state and state["acceptance_plan_protocol"] != PROTOCOL:
        raise h.Refusal("unsupported acceptance plan protocol")
    plan = state.get("acceptance_plan", {}).get("value")
    if plan is None and state.get("acceptance_plan_protocol") == PROTOCOL:
        raise h.Refusal("register the approved acceptance plan before formal acceptance")
    return plan


def _entries(plan):
    return {item["key"]: item for item in plan["checkpoints"]}


def _runs(state, key):
    return [run for run in state.get("runs", {}).values()
            if run.get("formal_acceptance") and run.get("failure_key") == key]


def _usage(state, key):
    runs = _runs(state, key)
    return {"attempts": len(runs),
            "reserved_seconds": sum(run["execution_contract"]["value"]["budgets"]["total"]["seconds"] for run in runs),
            "active": sum(run.get("status") != "completed" for run in runs)}


def snapshot(state):
    plan = state.get("acceptance_plan", {}).get("value")
    if plan is None:
        return {"required": state.get("acceptance_plan_protocol") == PROTOCOL, "registered": False}
    checkpoints = {key: dict(_usage(state, key), limits={name: item[name] for name in
        ("max_attempts", "max_total_seconds", "repair_limit")}) for key, item in _entries(plan).items()}
    return {"required": True, "registered": True, "approval": plan["approval"],
            "revision": state["acceptance_plan"].get("revision", 1),
            "final_key": plan["final"]["key"], "checkpoints": checkpoints,
            "checkpoint_attempts": sum(item["attempts"] for item in checkpoints.values()),
            "active_checkpoints": sum(item["active"] for item in checkpoints.values()),
            "max_checkpoint_attempts": plan["max_checkpoint_attempts"],
            "max_parallel_checkpoints": plan["max_parallel_checkpoints"]}


def register(args, h):
    value = _validate(h.load_json(h.plain_path(args.plan), h.MAX_SUMMARY), h)
    with h.locked(args.state) as (path, state):
        h.require_open(state)
        if "acceptance_plan_protocol" in state and state["acceptance_plan_protocol"] != PROTOCOL:
            raise h.Refusal("unsupported acceptance plan protocol")
        old = state.get("acceptance_plan")
        if old:
            if old["value"] == value:
                return {"registered": True, "unchanged": True, "plan": snapshot(state)}
            _text(getattr(args, "amendment_evidence", None), "plan amendment evidence", h)
            previous = old["value"]
            if any(value[name] != previous[name] for name in
                   ("version", "max_parallel_checkpoints", "max_checkpoint_attempts", "final")):
                raise h.Refusal("amendment cannot change final scope or global checkpoint limits")
            before, after = _entries(previous), _entries(value)
            if any(after.get(key) != item for key, item in before.items()):
                raise h.Refusal("amendment must preserve every existing checkpoint key, scope, dependency and budget")
            added = set(after) - set(before)
            if not added:
                raise h.Refusal("plan amendment must add a checkpoint")
            old_scope = {pointer for item in before.values() for pointer in item["acceptance"]}
            if any(old_scope.intersection(after[key]["acceptance"]) for key in added):
                raise h.Refusal("new checkpoint scope overlaps an existing checkpoint; continue its existing chain")
        elif getattr(args, "amendment_evidence", None):
            raise h.Refusal("amendment requires an already registered acceptance plan")
        entries = _entries(value)
        keys = set(entries) | {value["final"]["key"]}
        historical_keys = {run.get("failure_key") for run in state.get("runs", {}).values() if run.get("formal_acceptance")}
        historical_keys.update(state.get("execution_chains", {}))
        if not historical_keys.issubset(keys):
            raise h.Refusal("plan must preserve every historical formal failure key")
        total = 0
        for key, entry in entries.items():
            chain = state.get("execution_chains", {}).get(key)
            if chain and chain.get("repair_limit", 3) != entry["repair_limit"]:
                raise h.Refusal("plan must preserve the original checkpoint repair limit")
            usage = _usage(state, key)
            total += usage["attempts"]
            if usage["attempts"] > entry["max_attempts"] or usage["reserved_seconds"] > entry["max_total_seconds"]:
                raise h.Refusal("checkpoint limits cannot erase historical execution charges")
        if total > value["max_checkpoint_attempts"]:
            raise h.Refusal("global checkpoint limit cannot erase historical attempts")
        # Do not invent snapshots or modify any existing attempt/chain history.
        state["acceptance_plan_protocol"] = PROTOCOL
        timestamp = h.now()
        history = copy.deepcopy(old.get("history", [])) if old else []
        if old and not history:
            history.append({"revision": 1, "approval": old["value"]["approval"],
                            "at": old["registered_at"], "added_keys": sorted(_entries(old["value"]))})
        history.append({"revision": len(history) + 1, "approval": value["approval"], "at": timestamp,
                        "added_keys": sorted(set(entries) - (set(_entries(old["value"])) if old else set())),
                        "amendment_evidence": getattr(args, "amendment_evidence", None)})
        state["acceptance_plan"] = {"value": value, "registered_at": old["registered_at"] if old else timestamp,
                                    "revision": len(history), "history": history}
        h.save(path, state)
        return {"registered": True, "unchanged": False, "plan": snapshot(state)}


def _qualified_predecessor(state_path, state, key, entry, h, expected=None):
    chain = state.get("execution_chains", {}).get(key)
    latest = chain.get("attempts", [])[-1] if chain and chain.get("attempts") else None
    previous = state.get("runs", {}).get(latest)
    if not previous or previous.get("failure_key") != key or (expected is not None and latest != expected):
        raise h.Refusal("checkpoint continuation/dependency requires the chain's latest attempt: " + key)
    h.check_record(state_path, previous)
    if (previous.get("status") != "completed" or not previous.get("acceptance_qualified") or
            h.execution_failed(previous) or not previous.get("summary") or
            not set(entry["acceptance"]).issubset(previous["summary"]["acceptance"])):
        raise h.Refusal("checkpoint continuation/dependency requires a recorded qualified pass covering its approved scope: " + key)
    for run in _runs(state, key):
        if run.get("status") != "completed" or (h.execution_failed(run) and not run.get("resolution")):
            raise h.Refusal("unresolved checkpoint failures require repair/recovery before continuation: " + key)
        h.check_record(state_path, run)
    return previous


def admission(state_path, state, args, contract, cwd, source, h):
    plan = _plan(state, h)
    recheck = getattr(args, "recheck_after", None)
    inputs_path = getattr(args, "checkpoint_inputs", None)
    if plan is None:
        if recheck or inputs_path:
            raise h.Refusal("register an acceptance plan before checkpoint rechecks or input snapshots")
        return {}
    key = args.failure_key
    entries = _entries(plan)
    if key == plan["final"]["key"]:
        if recheck or inputs_path:
            raise h.Refusal("final acceptance uses its existing repair/recovery chain, not checkpoint recheck")
        return {}
    if key not in entries:
        raise h.Refusal("failure key is not an approved checkpoint or final key")
    entry = entries[key]
    if getattr(args, "repair_limit", None) not in (None, entry["repair_limit"]):
        raise h.Refusal("checkpoint repair limit differs from the approved plan")
    args.repair_limit = entry["repair_limit"]
    if not inputs_path:
        raise h.Refusal("checkpoint acceptance requires --checkpoint-inputs")
    inputs = h.load_json(h.plain_path(inputs_path), h.MAX_SUMMARY)
    if not isinstance(inputs, dict) or set(inputs) != {"implementation", "tests", "contract"}:
        raise h.Refusal("checkpoint inputs require implementation, tests and contract")
    _text(inputs["contract"], "pinned contract input", h)
    for name in ("implementation", "tests"):
        h.checked_oid(_text(inputs[name], name + " commit", h))
        if h.git(cwd, "merge-base", "--is-ancestor", inputs[name], source["revision"], check=False).returncode:
            raise h.Refusal(name + " input must be a commit contained in the frozen candidate")
    usage = _usage(state, key)
    status = snapshot(state)
    if usage["attempts"] >= entry["max_attempts"] or status["checkpoint_attempts"] >= plan["max_checkpoint_attempts"]:
        raise h.Refusal("approved checkpoint attempt budget is exhausted")
    if usage["reserved_seconds"] + contract["budgets"]["total"]["seconds"] > entry["max_total_seconds"]:
        raise h.Refusal("approved checkpoint time budget is exhausted")
    if status["active_checkpoints"] >= plan["max_parallel_checkpoints"]:
        raise h.Refusal("approved checkpoint concurrency limit is occupied")
    dependency_runs = {dependency: _qualified_predecessor(
        state_path, state, dependency, entries[dependency], h)["id"] for dependency in entry["depends_on"]}
    if recheck:
        previous = _qualified_predecessor(state_path, state, key, entry, h, expected=recheck)
        _text(getattr(args, "recheck_evidence", None), "recheck evidence", h)
        changed_source = source["revision"] != previous.get("revision")
        prior_inputs = previous.get("checkpoint_inputs")
        changed_inputs = prior_inputs is not None and inputs != prior_inputs
        if not changed_source and not changed_inputs:
            raise h.Refusal("recheck requires changed dependency inputs or a changed frozen candidate")
    return {"checkpoint_inputs": inputs, "checkpoint_dependency_runs": dependency_runs}


def check_summary(state, run, summary, h):
    plan = state.get("acceptance_plan", {}).get("value")
    if not plan or not run.get("formal_acceptance"):
        return
    entry = _entries(plan).get(run["failure_key"])
    if entry is None and run["failure_key"] == plan["final"]["key"]:
        entry = plan["final"]
    if entry is None:
        raise h.Refusal("formal run is outside the registered acceptance plan")
    recorded = set(summary["acceptance"])
    required = set(entry["acceptance"])
    if not recorded.issubset(required):
        raise h.Refusal("recorded acceptance is outside the approved key scope")
    if run.get("acceptance_qualified") and not required.issubset(recorded):
        raise h.Refusal("qualified passing record must cover the full approved key scope")


def final_blockers(state, final_run, required_scope):
    if "acceptance_plan_protocol" in state and state["acceptance_plan_protocol"] != PROTOCOL:
        return [{"run": final_run, "reason": "unsupported acceptance plan protocol"}]
    plan = state.get("acceptance_plan", {}).get("value")
    if plan is None:
        if state.get("acceptance_plan_protocol") == PROTOCOL:
            return [{"run": final_run, "reason": "approved acceptance plan is missing"}]
        return []
    blockers = []
    selected = state.get("runs", {}).get(final_run, {})
    if selected.get("failure_key") != plan["final"]["key"]:
        blockers.append({"run": final_run, "reason": "final delivery requires the designated final key"})
    if required_scope is None or set(required_scope["acceptance"]) != set(plan["final"]["acceptance"]):
        blockers.append({"run": final_run, "reason": "final delivery scope must equal the approved complete plan scope"})
    return blockers
