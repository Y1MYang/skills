"""Event-bound resource obligations and a cooperative, metadata-only watcher.

This module never releases resources, inspects business PIDs, or sends messages.
Hooks mutate the supplied ledger; callers own its lock and persistence. Audit
findings are requests to the existing scheduler, never deletion permission.
"""

import copy
import datetime
import hashlib
import json
import os
import time
import uuid


ACTIONS = frozenset({"due", "disposition", "audit", "watch", "watch-stop"})
INTERVAL_SECONDS = 1800
_RECENT_IDS = 64
_MAX_TEXT = 4096


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _time(value):
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include their UTC offset")
    return parsed


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT:
        raise ValueError("{} must be nonempty and at most {} characters".format(label, _MAX_TEXT))
    return value


def _book(state):
    return state.setdefault("resource_audit", {"version": 1})


def _item(state, resource_id):
    if resource_id not in state["resources"]:
        raise ValueError("unknown resource: " + resource_id)
    return state["resources"][resource_id]


def _audit(item):
    return item.setdefault("resource_audit", {"usage_generation": 0})


def _seen(book, key, value, add=False):
    """Exact recent deduplication; independent checks also require time/events."""
    recent = book.get(key, [])
    result = value in recent
    if add and not result:
        book[key] = (recent + [value])[-_RECENT_IDS:]
    return result


def mark_due(state, resource_id, event_id, stage, evidence, owner=None, at=None):
    """Record a release obligation, not a claim that deletion is safe."""
    for value, label in [(event_id, "event ID"), (stage, "stage"), (evidence, "evidence")]:
        _text(value, label)
    if owner is not None:
        _text(owner, "owner")
    item = _item(state, resource_id)
    if item["status"] == "released":
        raise ValueError("released resource cannot acquire a new obligation")
    audit = _audit(item)
    old = audit.get("due")
    if old and old["event_id"] == event_id:
        if old["stage"] != stage or old["evidence"] != evidence:
            raise ValueError("event ID already identifies a different obligation")
        return copy.deepcopy(old)
    if _seen(audit, "events_seen", event_id):
        raise ValueError("old event cannot replace the current obligation")
    _seen(audit, "events_seen", event_id, add=True)
    if owner is not None:
        item["owner"] = owner
    book = _book(state)
    book["event_sequence"] = book.get("event_sequence", 0) + 1
    due = {"event_id": event_id, "sequence": book["event_sequence"], "stage": stage, "evidence": evidence,
           "at": at or _now(), "owner": item.get("owner", item.get("role"))}
    audit.setdefault("first_due_at", due["at"])
    audit["due"] = due
    for name in ["receipt", "assessment", "handoff", "retention_identity"]:
        audit.pop(name, None)
    # A later stage may replace this event before the next periodic check.
    # Latch waiting receipts at publication so that the event cannot disappear.
    for other in state["resources"].values():
        receipt = _current_receipt(other.get("resource_audit", {}))
        if receipt and receipt["kind"] == "retained" and receipt.get("recheck_event") == event_id:
            receipt.setdefault("review_due_at", due["at"])
    return copy.deepcopy(due)


def note_usage(state, resource_ids, run_id, at=None):
    """A new command invalidates previous assessment and retention assumptions."""
    for resource_id in dict.fromkeys(resource_ids):
        audit = _audit(_item(state, resource_id))
        if audit.get("last_usage", {}).get("run_id") == run_id:
            continue
        audit["usage_generation"] = audit.get("usage_generation", 0) + 1
        audit["last_usage"] = {"run_id": run_id, "at": at or _now()}
        audit.pop("assessment", None)
        # Keep the receipt as history, but its generation will no longer match.


def _event(audit, event_id, required=False):
    current = audit.get("due", {}).get("event_id")
    if required and current is None:
        raise ValueError("resource has no release obligation")
    if event_id is not None and event_id != current:
        raise ValueError("receipt event does not match the current obligation")
    return current


def record_assessment(state, resource_id, assessment, at=None, event_id=None):
    audit = _audit(_item(state, resource_id))
    current = _event(audit, event_id)
    result = copy.deepcopy(assessment)
    for key in ["machine_blockers", "owner_checks_required"]:
        if not isinstance(result.get(key), list):
            raise ValueError("assessment requires a {} list".format(key))
    if len(json.dumps(result)) > 65536:
        raise ValueError("assessment exceeds 64 KiB")
    generation = audit.get("usage_generation", 0)
    if result.get("usage_generation", generation) != generation:
        raise ValueError("assessment predates the latest resource use")
    result.update(event_id=current, checked_at=at or _now(), usage_generation=generation)
    audit["assessment"] = result
    # Keep the last observed semantics separately: invalidating a snapshot is not
    # itself progress, and new due metadata must not clear existing misses.
    audit["assessment_facts"] = [copy.deepcopy(result["machine_blockers"]),
                                 copy.deepcopy(result["owner_checks_required"])]
    return copy.deepcopy(result)


def record_release(state, resource_id, outcome, reason=None, at=None, event_id=None):
    """Record every identified attempt, including refusal before mutation."""
    if outcome not in {"released", "blocked", "error"}:
        raise ValueError("unknown release outcome")
    if reason is not None:
        _text(reason, "release reason")
    audit = _audit(_item(state, resource_id))
    current = _event(audit, event_id)
    attempt = {"event_id": current, "outcome": outcome, "reason": reason,
               "at": at or _now(), "usage_generation": audit.get("usage_generation", 0)}
    audit["last_attempt"] = attempt
    if current is not None and outcome == "released":
        audit["receipt"] = dict(attempt, kind="released")
        audit.pop("handoff", None)
    return copy.deepcopy(attempt)


def _facts(state, resource_id):
    """Only machine lifecycle facts count as progress; prose/timestamps do not."""
    item = state["resources"][resource_id]
    audit = item.get("resource_audit", {})
    runs = []
    for run in state.get("runs", {}).values():
        if resource_id in run.get("uses", []):
            runs.append([run["id"], run.get("status"), run.get("exit_code"),
                         run.get("record_sha256"), bool(run.get("summary")),
                         bool(run.get("resolution"))])
    children = sorted([other["id"], other["status"]]
                      for other in state["resources"].values()
                      if other.get("parent") == resource_id)
    assessed_facts = audit.get("assessment_facts")
    handoff = audit.get("last_handoff", {})
    accepted_owner = [handoff.get("from"), handoff.get("to")] if handoff.get("accepted_at") else None
    facts = [item["status"], audit.get("usage_generation", 0), sorted(runs), children,
             assessed_facts, accepted_owner]
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()


def _metadata_blockers(state, resource_id):
    blockers = []
    for other in state["resources"].values():
        if other.get("parent") == resource_id and other["status"] != "released":
            blockers.append({"code": "child_present", "resource": other["id"]})
    for run in state.get("runs", {}).values():
        if resource_id not in run.get("uses", []):
            continue
        code = None
        if run.get("status") != "completed":
            code = "command_outcome_unconfirmed"
        elif run.get("test") and "summary" not in run:
            code = "test_summary_missing"
        elif not run.get("record_sha256"):
            code = "compact_record_unrecorded"
        if code:
            blockers.append({"code": code, "run": run["id"]})
        # A failure can be releasable for scratch, subject to external evidence.
        # Leave that decision to the shared explicit preflight, never duplicate it.
    return blockers


def _current_receipt(audit):
    receipt = audit.get("receipt")
    if receipt and receipt.get("event_id") == audit.get("due", {}).get("event_id") and \
            receipt.get("usage_generation") == audit.get("usage_generation", 0):
        return receipt
    return None


def _retention_due(receipt, at, trigger, registered_events=()):
    return (bool(receipt.get("review_due_at")) or
            (receipt.get("recheck_at") is not None and _time(at) >= _time(receipt["recheck_at"])) or
            (receipt.get("recheck_event") is not None and
             (trigger == receipt["recheck_event"] or receipt["recheck_event"] in registered_events)))


def audit_state(state, check_id, at, trigger=None):
    """Pure ledger inspection. No file reads, process inspection, or deletion."""
    _text(check_id, "check ID")
    _time(at)
    book = _book(state)
    registered_events = {item.get("resource_audit", {}).get("due", {}).get("event_id")
                         for item in state["resources"].values()}
    trigger_sequence = max((item.get("resource_audit", {}).get("due", {}).get("sequence", 0)
                            for item in state["resources"].values()
                            if item.get("resource_audit", {}).get("due", {}).get("event_id") == trigger), default=0)
    known_trigger = trigger is not None and trigger_sequence > 0
    if trigger is not None and not known_trigger:
        raise ValueError("audit trigger must name a currently registered phase event")
    duplicate = _seen(book, "checks_seen", check_id, add=True)
    new_trigger = known_trigger and trigger_sequence > book.get("last_trigger_sequence", 0)
    if not duplicate and new_trigger:
        book["last_trigger_sequence"] = trigger_sequence
    rows = []
    for resource_id, item in state["resources"].items():
        audit = item.get("resource_audit", {})
        due = audit.get("due")
        if not due:
            if item["status"] != "released":
                rows.append({"resource": resource_id, "category": "phase_unrecorded",
                             "owner": item.get("owner"), "action": "record_phase_when_reached"})
            continue
        row = {"resource": resource_id, "event_id": due["event_id"],
               "stage": due["stage"], "evidence": due["evidence"],
               "due_at": due["at"], "first_due_at": audit.get("first_due_at", due["at"]),
               "owner": item.get("owner"), "deletion_authorized": False}
        if item["status"] == "released":
            row.update(category="released", action="none")
            rows.append(row)
            continue
        checks = audit.setdefault("checks", {"unhandled_checks": 0})
        last_at = checks.get("last_counted_at")
        independent = not duplicate and not _seen(audit, "counted_check_ids", check_id) and (last_at is None or new_trigger or
                       (_time(at) - _time(last_at)).total_seconds() >= INTERVAL_SECONDS)
        signature = _facts(state, resource_id)
        progressed = checks.get("facts") is not None and checks["facts"] != signature
        if progressed and not duplicate:
            checks["unhandled_checks"] = 0
            checks["last_progress_at"] = at
        if not duplicate:
            checks["facts"] = signature
        receipt = _current_receipt(audit)
        review_due = receipt and receipt["kind"] == "retained" and _retention_due(receipt, at, trigger, registered_events)
        if review_due and not duplicate:
            receipt.setdefault("review_due_at", at)
        if receipt and receipt["kind"] == "retained" and not review_due:
            row.update(category="retained", action="none", reason=receipt["reason"],
                       evidence=receipt["evidence"], recheck_at=receipt.get("recheck_at"),
                       recheck_event=receipt.get("recheck_event"))
            rows.append(row)
            continue
        blockers = _metadata_blockers(state, resource_id)
        assessment = audit.get("assessment")
        if assessment and (assessment.get("event_id") != due["event_id"] or
                           assessment.get("usage_generation") != audit.get("usage_generation", 0)):
            assessment = None
        if audit.get("handoff") and audit["handoff"].get("event_id") == due["event_id"]:
            category = "handoff_unaccepted"
            row["proposed_owner"] = audit["handoff"]["to"]
        elif receipt and receipt["kind"] == "retained":
            category = "retention_review_due"
        elif blockers:
            category = "blocked_needs_disposition"
        elif assessment and assessment["machine_blockers"]:
            category = "last_assessment_blocked"
        elif assessment and not assessment["owner_checks_required"]:
            category = "release_attempt_missing"
        else:
            category = "verification_required"
        if independent:
            checks["unhandled_checks"] = min(2, checks["unhandled_checks"] + 1)
            checks["last_counted_at"] = at
            checks["last_check_id"] = check_id
            _seen(audit, "counted_check_ids", check_id, add=True)
        misses = checks["unhandled_checks"]
        row.update(category=category, independent_check=independent,
                   unhandled_checks=misses, machine_metadata_blockers=blockers,
                   action="escalate_existing_merger" if misses >= 2 else "dispatch_current_owner")
        if assessment:
            row["assessment_at"] = assessment["checked_at"]
            row["owner_checks_required"] = assessment["owner_checks_required"]
            row["last_assessment_blockers"] = assessment["machine_blockers"]
        attempt = audit.get("last_attempt")
        if attempt and attempt.get("event_id") == due["event_id"]:
            row["last_attempt"] = attempt
        rows.append(row)
    result = {"invocation": state.get("invocation"),
              "check_id": check_id, "checked_at": at, "duplicate": duplicate,
              "metadata_only": True, "rows": rows,
              "delivery": "stdout_only; scheduler routing and wakeup are not guaranteed"}
    if not duplicate:
        book["last_check"] = {"id": check_id, "at": at, "trigger": trigger}
        book["last_report"] = copy.deepcopy(result)
    return result


def _disposition(state, args, at):
    item = _item(state, args.resource)
    audit = _audit(item)
    _event(audit, args.event_id, required=True)
    if item["status"] == "released":
        raise ValueError("released resource needs no further disposition")
    generation = audit.get("usage_generation", 0)
    if args.kind == "accept":
        handoff = audit.get("handoff")
        if not handoff or handoff["event_id"] != args.event_id or handoff["to"] != args.owner:
            raise ValueError("accept must match the pending handoff and proposed owner")
        if handoff["usage_generation"] != generation:
            raise ValueError("resource reused since handoff; renew handoff before accepting")
        item["owner"] = args.owner
        audit["last_handoff"] = dict(handoff, accepted_at=at)
        audit.pop("handoff")
        # Acceptance transfers responsibility; it does not close the obligation.
        return {"resource": args.resource, "owner": item["owner"], "accepted": True}
    _text(args.reason, "reason")
    _text(args.evidence, "evidence")
    receipt = {"event_id": args.event_id, "kind": args.kind, "reason": args.reason,
               "evidence": args.evidence, "at": at, "usage_generation": generation}
    if args.kind == "handoff":
        _text(args.owner, "new owner")
        if args.owner == item.get("owner"):
            raise ValueError("handoff needs a different owner")
        pending = dict(receipt, **{"from": item.get("owner"), "to": args.owner})
        audit["handoff"] = pending
        return {"resource": args.resource, "handoff_pending": True, "owner": item.get("owner"),
                "proposed_owner": args.owner}
    if bool(args.recheck_at) == bool(args.recheck_event):
        raise ValueError("retained requires exactly one recheck time or event")
    if args.recheck_at and _time(args.recheck_at) <= _time(at):
        raise ValueError("recheck time must be in the future")
    if args.recheck_event:
        _text(args.recheck_event, "recheck event")
        if args.recheck_event == args.event_id:
            raise ValueError("recheck event must be a subsequent event")
        if any(args.recheck_event in other.get("resource_audit", {}).get("events_seen", [])
               for other in state["resources"].values()):
            raise ValueError("recheck event has already occurred; choose a future event or time")
    receipt.update(recheck_at=args.recheck_at, recheck_event=args.recheck_event)
    identity = [args.evidence, generation]
    old = audit.get("receipt", {})
    if audit.get("retention_identity") == identity:
        if old.get("recheck_at") != args.recheck_at or old.get("recheck_event") != args.recheck_event:
            raise ValueError("repeated retention statement cannot postpone its review")
        return {"resource": args.resource, "retained": True, "unchanged": True}
    audit["retention_identity"] = identity
    audit["receipt"] = receipt
    audit.pop("handoff", None)
    return {"resource": args.resource, "retained": True, "receipt": receipt}


def add_commands(subparsers):
    for name in sorted(ACTIONS):
        subparsers.add_parser(name).add_argument("--state", required=True)
    command = subparsers.choices["due"]
    for name in ["resource", "event-id", "stage", "evidence"]:
        command.add_argument("--" + name, required=True)
    command.add_argument("--owner")
    command = subparsers.choices["disposition"]
    for name in ["resource", "event-id"]:
        command.add_argument("--" + name, required=True)
    command.add_argument("--kind", choices=["retained", "handoff", "accept"], required=True)
    for name in ["reason", "evidence", "owner", "recheck-at", "recheck-event"]:
        command.add_argument("--" + name)
    command = subparsers.choices["audit"]
    command.add_argument("--check-id", required=True)
    command.add_argument("--trigger")
    subparsers.choices["watch"].add_argument("--interval-seconds", type=int, default=INTERVAL_SECONDS)
    command = subparsers.choices["watch-stop"]
    command.add_argument("--stopped-confirmed", action="store_true")
    command.add_argument("--reason")


def _action_signature(report):
    """Repeated timestamps and checks are not new notifications."""
    volatile = {"at", "checked_at", "assessment_at", "independent_check", "last_check_id"}

    def stable(value):
        if isinstance(value, dict):
            return {key: stable(item) for key, item in value.items() if key not in volatile}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    capacity = report.get("capacity", {})
    capacity_actions = [{key: row.get(key) for key in ["filesystem", "action", "error"]}
                        for row in capacity.get("filesystems", [])]
    facts = [stable(report["rows"]), capacity.get("enabled"), capacity_actions]
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()


def _capacity_report(state, report, h):
    if hasattr(h, "capacity_snapshot"):
        report["capacity"] = h.capacity_snapshot(state)
        _book(state)["last_report"] = copy.deepcopy(report)
    return report


def _watch(args, h):
    if args.interval_seconds < INTERVAL_SECONDS:
        raise h.Refusal("watch interval must be at least 1800 seconds")
    watch_id = uuid.uuid4().hex
    with h.locked(args.state) as (path, state):
        if state.get("sealed_at"):
            return {"watch": "not_started", "reason": "invocation is sealed"}
        book = _book(state)
        if book.get("watch", {}).get("status") in {"running", "stop_requested"}:
            raise h.Refusal("watch already registered; request cooperative stop or explicitly confirm it stopped")
        book["watch"] = {"id": watch_id, "pid": os.getpid(), "status": "running",
                         "started_at": h.now(), "interval_seconds": args.interval_seconds,
                         "delivery": "stdout_only"}
        h.save(path, state)
    next_check = time.monotonic()
    failure = None
    stop_reason = "watch loop ended"
    try:
        while True:
            with h.locked(args.state) as (path, state):
                watcher = _book(state).get("watch", {})
                if watcher.get("id") != watch_id:
                    stop_reason = "registration replaced"
                    return {"watch": "stopped", "reason": "registration replaced"}
                if watcher.get("status") != "running" or state.get("sealed_at"):
                    stop_reason = "sealed" if state.get("sealed_at") else "stop requested"
                    return {"watch": "stopped", "reason": stop_reason}
                if time.monotonic() >= next_check:
                    at = h.now()
                    result = _capacity_report(state, audit_state(state, "watch-" + uuid.uuid4().hex, at), h)
                    watcher["last_check_at"] = at
                    signature = _action_signature(result)
                    changed = watcher.get("last_output_signature") != signature
                    if changed:
                        watcher["last_output_signature"] = signature
                    h.save(path, state)
                    if changed:
                        print(json.dumps(result, ensure_ascii=False), flush=True)
                    next_check = time.monotonic() + args.interval_seconds
            # Only the owned watcher waits; business workloads remain untouched.
            time.sleep(min(5, max(0.01, next_check - time.monotonic())))
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        with h.locked(args.state) as (path, state):
            watcher = _book(state).get("watch", {})
            if watcher.get("id") == watch_id:
                watcher.update(status="failed" if failure else "stopped", stopped_at=h.now())
                if failure:
                    watcher["failure"] = failure
                else:
                    watcher["stop_reason"] = stop_reason
                h.save(path, state)


def dispatch(action, args, h):
    if action not in ACTIONS:
        raise h.Refusal("unknown audit action: " + action)
    if action == "watch":
        return _watch(args, h)
    with h.locked(args.state) as (path, state):
        if action == "due":
            h.checked_id(args.event_id)
            h.resource(state, args.resource)
            result = mark_due(state, args.resource, args.event_id, args.stage, args.evidence,
                              owner=args.owner, at=h.now())
        elif action == "disposition":
            h.checked_id(args.event_id)
            result = _disposition(state, args, h.now())
        elif action == "audit":
            h.checked_id(args.check_id)
            result = _capacity_report(state, audit_state(state, args.check_id, h.now(), trigger=args.trigger), h)
        else:
            watcher = _book(state).get("watch")
            if not watcher or watcher.get("status") == "stopped":
                return {"watch": "stopped", "already_stopped": True}
            if args.stopped_confirmed:
                _text(args.reason, "independent stopped confirmation reason")
                watcher.update(status="stopped", stopped_at=h.now(), stopped_confirmation=args.reason)
            else:
                watcher.update(status="stop_requested", stop_requested_at=h.now())
            result = {"watch": watcher["status"], "id": watcher["id"], "business_commands_stopped": False}
        h.save(path, state)
        return result
