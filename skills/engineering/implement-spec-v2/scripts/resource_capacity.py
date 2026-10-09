"""Conservative, invocation-scoped disk admission; not a filesystem quota.

Mutating hooks are called with the resource ledger lock held. A reservation is
future growth still to come, so finishing a command never spends or drops it.
Owners reduce that estimate only after checking actual use and remaining work.
"""

import copy


PROTOCOL = "disk-reservations/1"


def initialize(state):
    state["capacity_protocol"] = PROTOCOL
    state["reservations"] = {}


def enabled(state, h):
    protocol = state.get("capacity_protocol")
    if protocol and protocol != PROTOCOL:
        raise h.Refusal("unsupported disk reservation protocol")
    return protocol == PROTOCOL


def _require_enabled(state, h):
    if not enabled(state, h):
        raise h.Refusal("historical ledger has disk reservations disabled; start a new invocation to enable admission")


def _amount(value, h):
    if type(value) is not int or value < 0:
        raise h.Refusal("space estimates must be nonnegative integer bytes")
    return value


def _owner(value, h):
    if not isinstance(value, str) or not value.strip():
        raise h.Refusal("reservation needs a concrete owner")
    return value.strip()


def _directory(value, h):
    path = h.plain_path(str(value))
    if not path.is_dir():
        raise h.Refusal("capacity path must be an existing destination directory")
    return path, h.identity(path)


def _open(state):
    return [item for item in state.get("reservations", {}).values()
            if item["status"] == "open"]


def _totals(state, filesystem, exclude=None):
    items = [item for item in _open(state)
             if item["filesystem"] == filesystem and item["id"] != exclude]
    return (sum(item["remaining_bytes"] for item in items),
            max([item["reserve_bytes"] for item in items] or [0]), items)


def _capacity(state, value, next_bytes, reserve_bytes, h, exclude=None):
    _amount(next_bytes, h)
    _amount(reserve_bytes, h)
    path, identity = _directory(value, h)
    tracked, existing_floor, items = _totals(state, identity[0], exclude)
    floor = max(existing_floor, reserve_bytes)
    free = h.shutil.disk_usage(path).free
    required = tracked + next_bytes + floor
    admission_enabled = enabled(state, h)
    return {"measured_path": str(path), "filesystem": identity[0],
            "available_bytes": free, "reserved_growth_bytes": tracked,
            "reservation_ids": [item["id"] for item in items],
            "next_bytes": next_bytes, "reserve_bytes": floor,
            "required_bytes": required, "shortfall_bytes": max(0, required - free),
            "admit": free >= required, "admission_enabled": admission_enabled,
            "budget_kind": "estimated future growth; not an OS quota",
            "scope": "this invocation; actual free space includes all disk users",
            "recommendation": ("keep normal concurrency" if free >= required else
                "release eligible owned resources or revise measured remaining growth first; "
                "defer new allocations if still short; keep existing commands"),
            "legacy_notice": None if admission_enabled else
                "historical ledger: reservations and mandatory admission are disabled"}


def _require_capacity(result, h):
    if not result["admit"]:
        raise h.Refusal("insufficient unreserved space on filesystem {}: shortfall {} bytes; "
                        "retain running commands".format(result["filesystem"], result["shortfall_bytes"]))


def report(state):
    """Cheap ledger-only status: reservations never expire or release by PID."""
    fields = ["id", "owner", "path", "filesystem", "status", "remaining_bytes",
              "reserve_bytes", "created_at", "updated_at", "claimant", "last_claim",
              "released_at", "reason", "last_transfer"]
    return {"enabled": state.get("capacity_protocol") == PROTOCOL,
            "protocol": state.get("capacity_protocol"),
            "reservations": [{key: copy.deepcopy(item[key]) for key in fields if key in item}
                             for item in state.get("reservations", {}).values()],
            "automatic_expiry": False,
            "legacy_notice": None if state.get("capacity_protocol") == PROTOCOL else
                "disk reservation admission is not enabled for this ledger"}


def claim(state, reservation_ids, paths, claimant_kind, claimant_id, h, owner=None):
    """Validate and claim atomically under the caller's ledger lock.

    Each destination filesystem needs one distinct reservation. Concurrent
    commands cannot reuse the same estimate. This deliberately includes every
    declared resource: the wrapper cannot prove which paths a command writes.
    """
    admission_enabled = enabled(state, h)
    names = list(reservation_ids or [])
    if not admission_enabled:
        if names:
            raise h.Refusal("historical ledger has disk reservations disabled")
        return []
    h.require_open(state)
    if not names:
        raise h.Refusal("this invocation requires --reservation for create and run")
    if len(names) != len(set(names)):
        raise h.Refusal("duplicate reservation IDs")
    owner = _owner(owner, h)
    targets = {}
    for value in paths:
        path, identity = _directory(value, h)
        targets.setdefault(identity[0], path)
    reservations = []
    filesystems = set()
    for name in names:
        h.checked_id(name)
        item = state["reservations"].get(name)
        if not item or item["status"] != "open":
            raise h.Refusal("unknown or released reservation: " + name)
        if item["owner"] != owner:
            raise h.Refusal("reservation owner mismatch: " + name)
        if item.get("claimant"):
            raise h.Refusal("reservation already has an active claimant: " + name)
        _, identity = _directory(item["path"], h)
        if identity != item["identity"]:
            raise h.Refusal("reservation destination identity changed: " + name)
        if item["filesystem"] in filesystems:
            raise h.Refusal("use exactly one reservation for each destination filesystem")
        filesystems.add(item["filesystem"])
        reservations.append(item)
    if filesystems != set(targets):
        raise h.Refusal("reservations must cover exactly the declared destination filesystems")
    for path in targets.values():
        _require_capacity(_capacity(state, path, 0, 0, h), h)
    timestamp = h.now()
    for item in reservations:
        item["claimant"] = {"kind": claimant_kind, "id": claimant_id, "owner": owner,
                            "started_at": timestamp}
        item["updated_at"] = timestamp
    return names


def finish(state, claimant_kind, claimant_id, h):
    """After known completion or confirmed stopped recovery, retain the budget."""
    timestamp = h.now()
    for item in _open(state):
        current = item.get("claimant")
        if current and (current["kind"], current["id"]) == (claimant_kind, claimant_id):
            item["last_claim"] = dict(current, ended_at=timestamp)
            item["claimant"] = None
            item["updated_at"] = timestamp


def _reserve(args, h):
    h.checked_id(args.id)
    owner = _owner(args.owner, h)
    with h.locked(args.state) as (state_path, state):
        _require_enabled(state, h)
        h.require_open(state)
        if args.id in state["reservations"]:
            raise h.Refusal("reservation ID already used")
        path, identity = _directory(args.path, h)
        result = _capacity(state, path, args.next_bytes, args.reserve_bytes, h)
        _require_capacity(result, h)
        timestamp = h.now()
        item = {"id": args.id, "owner": owner, "path": str(path), "identity": identity,
                "filesystem": identity[0], "status": "open", "remaining_bytes": args.next_bytes,
                "reserve_bytes": args.reserve_bytes, "created_at": timestamp,
                "updated_at": timestamp, "claimant": None}
        state["reservations"][args.id] = item
        h.save(state_path, state)
        return {"reservation": copy.deepcopy(item), "capacity": result}


def _reservation(args, h):
    h.checked_id(args.id)
    with h.locked(args.state) as (state_path, state):
        _require_enabled(state, h)
        item = state["reservations"].get(args.id)
        if not item:
            raise h.Refusal("unknown reservation")
        transfer_to = getattr(args, "transfer_to", None)
        if args.remaining_bytes is None and not args.release and transfer_to is None:
            return {"reservation": copy.deepcopy(item), "automatic_expiry": False}
        if _owner(args.owner, h) != item["owner"]:
            raise h.Refusal("reservation owner mismatch")
        if item["status"] != "open":
            raise h.Refusal("reservation is already released")
        if item.get("claimant"):
            raise h.Refusal("reservation has an active claimant; retain it until completion or confirmed recovery")
        if not args.idle_confirmed or not args.reason or not args.reason.strip():
            raise h.Refusal("reservation changes require --idle-confirmed and a concrete --reason; byte revisions must reflect measured remaining work")
        timestamp = h.now()
        if args.release:
            item.update(status="released", released_at=timestamp, remaining_bytes=0)
        elif transfer_to is not None:
            new_owner = _owner(transfer_to, h)
            if new_owner == item["owner"]:
                raise h.Refusal("reservation transfer needs a different owner")
            # Transfer existing responsibility only: no new allocation, no
            # implicit resource handoff acceptance, and no budget adjustment.
            item["last_transfer"] = {"from": item["owner"], "to": new_owner,
                                     "at": timestamp, "reason": args.reason.strip()}
            item["owner"] = new_owner
        else:
            remaining = _amount(args.remaining_bytes, h)
            if remaining > item["remaining_bytes"]:
                h.require_open(state)
                _, identity = _directory(item["path"], h)
                if identity != item["identity"]:
                    raise h.Refusal("reservation destination identity changed")
                _require_capacity(_capacity(state, item["path"], remaining,
                                            item["reserve_bytes"], h, exclude=item["id"]), h)
            item["remaining_bytes"] = remaining
        item.update(updated_at=timestamp, reason=args.reason.strip())
        h.save(state_path, state)
        return {"reservation": copy.deepcopy(item), "automatic_expiry": False}


def add_commands(commands):
    command = commands.add_parser("reserve", help="reserve future disk growth before new work")
    command.add_argument("--state", required=True)
    command.add_argument("--id", required=True)
    command.add_argument("--path", required=True, help="existing directory on the destination filesystem")
    command.add_argument("--next-bytes", type=int, required=True)
    command.add_argument("--reserve-bytes", type=int, required=True, help="filesystem safety floor; maximum across reservations")
    command.add_argument("--owner", required=True)
    command = commands.add_parser("reservation", help="inspect, revise, transfer or release a retained growth estimate")
    command.add_argument("--state", required=True)
    command.add_argument("--id", required=True)
    command.add_argument("--owner")
    changes = command.add_mutually_exclusive_group()
    changes.add_argument("--remaining-bytes", type=int)
    changes.add_argument("--release", action="store_true")
    changes.add_argument("--transfer-to", help="transfer an idle reservation to a new owner without changing its budget")
    command.add_argument("--idle-confirmed", action="store_true")
    command.add_argument("--reason")
    for name in ["create", "run"]:
        commands.choices[name].add_argument("--reservation", action="append", default=[],
                                          help="one growth reservation per destination filesystem; repeat for multiple filesystems")


def dispatch(action, args, h):
    if action == "reserve":
        return _reserve(args, h)
    if action == "reservation":
        return _reservation(args, h)
    if action == "capacity":
        with h.locked(args.state) as (state_path, state):
            return _capacity(state, args.path or state_path, args.next_bytes, args.reserve_bytes, h)
    raise h.Refusal("unknown capacity action: " + action)
