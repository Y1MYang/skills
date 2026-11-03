"""Audit retained paired evidence without executing either target again."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def normalized_events(run):
    root = Path(run["root"])
    state = json.loads((root / "state" / "state.json").read_text(encoding="utf-8"))
    attempts = sorted(state["attempts"].values(), key=lambda item: item["request"]["binding"]["prepared_seq"])
    replacements = [(str(root), "<TRIAL_ROOT>"), (state["finished"]["head"], "<CANDIDATE_HEAD>")]
    replacements += [(item["id"], f"<ATTEMPT_{i}>") for i, item in enumerate(attempts, 1)]

    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, str):
            for old, new in replacements:
                value = value.replace(old, new)
        return value

    commands = [json.loads(line) for line in (root / "commands.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(commands) == run["outer_process_invocations"] == len(run["phases"])
    assert len(attempts) == run["attempts"] == len(run["receipts"])
    for receipt in run["receipts"]:
        assert hashlib.sha256(Path(receipt["path"]).read_bytes()).hexdigest() == receipt["sha256"]
    return [normalize(item["event"]) for item in state["events"]]


source = Path(sys.argv[1])
data = json.loads(source.read_text(encoding="utf-8"))
pairs = defaultdict(dict)
for run in data["results"]:
    pairs[(run["scenario"], run["pair"])][run["label"]] = run
results = []
for (scenario, pair), arms in pairs.items():
    assert set(arms) == {"baseline", "candidate"}
    left, right = (normalized_events(arms[label]) for label in ("baseline", "candidate"))
    assert left == right
    assert arms["baseline"]["work_signature"] == arms["candidate"]["work_signature"]
    results.append({"scenario": scenario, "pair": pair, "warmup": pair == -1,
                    "normalized_full_event_payload_sha256": digest(left), "events": len(left)})
output = {
    "valid": True, "paired_trials": len(results), "individual_trials": len(data["results"]),
    "normalized_fields": ["Absolute per-trial root path", "Final Git commit SHA", "Generated attempt IDs, replaced in preparation order"],
    "normalization_reason": "Fresh isolated directories, commit metadata, and generated identity are expected to differ; all other full event payload fields are retained and compared.",
    "runtime_signature": "Actual argv, outcomes, exit codes, test/contract/product byte hashes at each execution, and final fixture source hashes are compared. Each receipt independently proved stable before/after snapshots and cleanup. Timing, PID/ownership tokens, and log hashes are not cross-arm equality criteria; each original receipt SHA is verified against its saved bytes.",
    "process_count_evidence": "outer_process_invocations agrees with actual commands.jsonl launches and phase records; descendant counts are not inferred.",
    "pairs": results,
}
destination = source.with_name("equivalence-audit.json")
destination.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"valid": True, "pairs": len(results), "trials": len(data["results"]), "path": str(destination)}))
