"""Repeatable CLI benchmark; independent agent/review latency is out of scope.

Fresh fixtures perform real per-example failing/passing assertions and final
formal acceptance. Review inputs are mechanical fixtures, never real reviews.
Use --single for a diagnostic trial; matched runs alternate AB/BA pairs.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import platform
import pstats
import shutil
import statistics
import subprocess
import sys
import tempfile
import time


ROLES = (
    "exploration", "architect", "test_author", "implementer", "runner",
    "integrator", "coverage_audit", "spec_reviewer", "standards_reviewer", "expert",
)
SCENARIOS = {"small": (2, 0), "history_logs": (12, 32768)}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_skill(source, destination):
    """Use identical source-only snapshots; -B alone still reads old .pyc files."""
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return {str(path.relative_to(destination)): sha256(path) for path in sorted(destination.rglob("*")) if path.is_file()}


class Trial:
    def __init__(self, skill, scenario, label, root, profile=False, mode="legacy"):
        self.skill, self.scenario, self.label = Path(skill), scenario, label
        self.root, self.profile, self.mode = root, profile, mode
        self.workspace, self.state = root / "workspace", root / "state"
        self.phases, self.receipts = [], []
        self.count, self.log_bytes = SCENARIOS[scenario]
        self.serial = 0

    def command(self, phase, argv, expected=0, cwd=None, script=False):
        self.serial += 1
        argv = list(map(str, argv))
        if self.profile and script:
            profile_path = self.root / "profiles" / f"{self.serial:03}-{phase}.pstats"
            profile_path.parent.mkdir(exist_ok=True)
            argv = [argv[0], "-B", str(Path(__file__).with_name("profile_cli.py")), str(profile_path), *argv[2:]]
        start = time.perf_counter()
        result = subprocess.run(
            argv, cwd=cwd or self.root, capture_output=True, text=True,
            encoding="utf-8", timeout=30, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        elapsed = time.perf_counter() - start
        self.phases.append({"phase": phase, "seconds": elapsed, "exit": result.returncode})
        with (self.root / "commands.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps({"phase": phase, "argv": argv, "exit": result.returncode,
                                     "seconds": elapsed, "stdout": result.stdout, "stderr": result.stderr}) + "\n")
        if result.returncode != expected:
            raise RuntimeError(f"{phase}: expected {expected}, got {result.returncode}: {result.stdout} {result.stderr}")
        return result.stdout.strip()

    def cycle(self, phase, *argv):
        output = self.command(phase, [sys.executable, "-B", self.skill / "scripts" / "cycle.py",
                                     "--state", self.state, *argv], script=True)
        return json.loads(output.splitlines()[-1])

    def apply(self, phase, op, **fields):
        event = {"schema": 1, "op_id": phase, "op": op, **fields}
        event_path = self.root / "events" / f"{phase}.json"
        write_json(event_path, event)
        return self.cycle(phase, "apply", "--event", event_path)

    def prepare(self, example, purpose, label=None):
        return self.apply(f"{example}-{label or purpose}-prepare", "prepare", example=example,
                          purpose=purpose, timeout_seconds=10)

    def execution(self, example, purpose, expected, label=None):
        prefix = f"{example}-{label or purpose}"
        if self.mode == "execute":
            request_path = self.root / "executions" / f"{prefix}.json"
            write_json(request_path, {
                "schema": 1,
                "prepare": {"schema": 1, "op_id": f"{prefix}-prepare", "op": "prepare",
                            "example": example, "purpose": purpose, "timeout_seconds": 10},
                "record_op_id": f"{prefix}-record", "argv": self.test_argv(),
            })
            result = self.cycle(f"{prefix}-execute", "execute", "--request", request_path)
            assert result["outcome"] == "exited" and result["exit_code"] == expected
            prepared = result["prepare"]
            self.check_receipt(prepared, f"{prefix}-execute", expected)
        else:
            prepared = self.prepare(example, purpose, label)
            self.run_prepared(prepared, f"{prefix}-run", expected)
            self.apply(f"{prefix}-record", "record", attempt_id=prepared["attempt_id"])
        return prepared

    @staticmethod
    def test_argv():
        return [sys.executable, "-B", "tests/run_acceptance.py"]

    def run_prepared(self, prepared, phase, expected, formal=False):
        args = [sys.executable, "-B", self.skill / "scripts" / "run_command.py",
                "--receipt", prepared["receipt_path"], "--cwd", self.workspace,
                "--timeout", "10", "--snapshot", prepared["request_path"]]
        if formal:
            args.append("--formal")
        args += ["--", *self.test_argv()]
        self.command(phase, args, expected=expected, script=True)
        return self.check_receipt(prepared, phase, expected)

    def check_receipt(self, prepared, phase, expected):
        receipt_path = Path(prepared["receipt_path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["outcome"] == "exited" and receipt["exit_code"] == expected
        assert receipt["cleanup_complete"]
        assert receipt["snapshot"]["before"] == receipt["snapshot"]["after"]
        target_log = Path(prepared["receipt_path"] + ".stderr.log").read_text(encoding="utf-8")
        target_markers = [json.loads(line) for line in target_log.splitlines()
                          if line.startswith('{"benchmark_target_seconds":')]
        assert len(target_markers) == 1
        target = target_markers[0]
        assert target["successful"] == (expected == 0) and target["tests_run"] > 0
        self.receipts.append({"phase": phase, "path": str(receipt_path),
                              "duration_seconds": receipt["duration_seconds"],
                              "target_seconds": target["benchmark_target_seconds"],
                              "tests_run": target["tests_run"],
                              "sha256": sha256(receipt_path)})
        return receipt

    def git(self, phase, *args):
        return self.command(phase, ["git", *args], cwd=self.workspace)

    def setup(self):
        self.workspace.mkdir(parents=True)
        (self.workspace / "tests").mkdir()
        (self.workspace / "src").mkdir()
        (self.workspace / "shared").mkdir()
        (self.workspace / "tests" / "run_acceptance.py").write_text(
            "import time\nstarted = time.perf_counter()\nimport json\nimport sys\nimport unittest\n"
            "suite = unittest.TestLoader().discover('tests', pattern='test_*.py')\n"
            "result = unittest.TextTestRunner(verbosity=2).run(suite)\n"
            "print(json.dumps({'benchmark_target_seconds': time.perf_counter() - started, "
            "'tests_run': result.testsRun, 'successful': result.wasSuccessful()}), file=sys.stderr)\n"
            "raise SystemExit(0 if result.wasSuccessful() else 1)\n", encoding="utf-8")
        (self.workspace / "shared" / "oracle.py").write_text(
            "EXPECTED = " + repr({i * 100 - 1: i * 10 for i in range(1, self.count + 1)}) + "\n", encoding="utf-8")
        (self.workspace / "src" / "fee.py").write_text("def fee(amount):\n    return 0\n", encoding="utf-8")
        (self.workspace / "spec.md").write_text(
            "".join(f"REQ-{i}: fee({i * 100 - 1}) must return {i * 10}.\n" for i in range(1, self.count + 1)),
            encoding="utf-8",
        )
        plan = {
            "schema": 1, "run_id": "matched-cli-benchmark", "workspace": str(self.workspace),
            "spec_sources": ["spec.md"], "models": {role: "mechanical-fixture-no-agent" for role in ROLES},
            "budget": {"max_attempts": self.count * 2 + 4, "max_formal_failures": 2, "max_seconds": 600},
            "flows": [{"id": "main", "write_paths": ["src"]}], "gates": [],
            "examples": [{
                "id": f"fee-{i}", "flow": "main", "requirement": f"REQ-{i}",
                "depends_on": [] if i == 1 else [f"fee-{i - 1}"],
                "snapshot": {"schema": 1, "root": str(self.workspace), "tests": ["tests", "shared/oracle.py"],
                             "contract": ["spec.md"], "product": ["src"], "binding": None},
            } for i in range(1, self.count + 1)],
        }
        write_json(self.root / "plan.json", plan)
        self.git("fixture-git-init", "init", "--quiet")
        self.cycle("init", "init", "--plan", self.root / "plan.json")

    def example(self, i):
        example = f"fee-{i}"
        (self.workspace / "tests" / f"test_fee_{i:02}.py").write_text(
            "import runpy\nimport unittest\n"
            f"class Fee{i}(unittest.TestCase):\n"
            f"    def test_req_{i}(self):\n"
            f"        print('trace-' + 'x' * {self.log_bytes})\n"
            f"        expected = runpy.run_path('shared/oracle.py')['EXPECTED'][{i * 100 - 1}]\n"
            f"        self.assertEqual(runpy.run_path('src/fee.py')['fee']({i * 100 - 1}), expected)\n",
            encoding="utf-8",
        )
        self.apply(f"{example}-open", "open", example=example, light_check={
            "source": f"spec.md / REQ-{i}", "observation": f"fee({i * 100 - 1}) returns {i * 10}",
            "expected_failure": f"test_req_{i} assertion observes missing result 0",
            "independent_context": "requirements-defined-mechanical-fixture-not-agent-review",
        })
        red = self.execution(example, "probe", 1)
        red_stderr = Path(red["receipt_path"] + ".stderr.log").read_text(encoding="utf-8")
        assert f"test_req_{i}" in red_stderr and f"0 != {i * 10}" in red_stderr
        assert f"Ran {i} test" in red_stderr and "FAILED (failures=1)" in red_stderr
        self.apply(f"{example}-judge", "judge", attempt_id=red["attempt_id"], classification="valid-red",
                   reason=f"Target test_req_{i} alone fails: fee({i * 100 - 1}) is 0 instead of {i * 10}.",
                   evidence=[red["receipt_path"]])
        if self.scenario == "small" and i == 2:
            self.write_product(i, wrong=True)
            failed = self.execution(example, "green", 1, label="failed-green")
            failure_log = Path(failed["receipt_path"] + ".stderr.log").read_text(encoding="utf-8")
            assert "test_req_2" in failure_log and "19 != 20" in failure_log and "FAILED (failures=1)" in failure_log
            self.apply(f"{example}-implementation-failure", "judge", attempt_id=failed["attempt_id"],
                       classification="implementation", reason="The new product branch returns 19; REQ-2 requires 20.",
                       evidence=[failed["receipt_path"]])
            self.apply(f"{example}-diagnose", "diagnose", attempt_id=failed["attempt_id"],
                       reason="The second branch contains the off-by-one value 19; the independent oracle requires 20.",
                       evidence=[failed["receipt_path"] + ".stderr.log"],
                       next_action="Correct the second branch and rerun all authored assertions, then final formal acceptance.")
        self.write_product(i)
        green = self.execution(example, "green", 0)
        green_stderr = Path(green["receipt_path"] + ".stderr.log").read_text(encoding="utf-8")
        assert f"Ran {i} test" in green_stderr and "\nOK\n" in green_stderr
        self.apply(f"{example}-close", "close", example=example, regression_attempt_id=green["attempt_id"],
                   regression_scope="All authored examples run in the same unittest discovery command.")

    def write_product(self, i, wrong=False):
        values = {j * 100 - 1: j * 10 for j in range(1, i + 1)}
        if wrong:
            values[i * 100 - 1] -= 1
        (self.workspace / "src" / "fee.py").write_text(
            "def fee(amount):\n    return " + repr(values) + ".get(amount, 0)\n", encoding="utf-8")

    @staticmethod
    def review(axis):
        return {"review_id": f"mechanical-fixture-{axis}", "source": f"spec.md / {axis} fixture",
                "independent_context": "mechanical-fixture-not-a-real-review", "verdict": "pass"}

    def dependency_refresh(self):
        self.apply("qualify-before-refresh", "qualify", scope={"final": True},
                   spec_review=self.review("spec"), standards_review=self.review("standards"))
        write_json(self.workspace / "shared" / "fees.json",
                   {str(i * 100 - 1): i * 10 for i in range(1, self.count + 1)})
        (self.workspace / "shared" / "oracle.py").write_text(
            "import json\nfrom pathlib import Path\n"
            "EXPECTED = {int(k): v for k, v in json.loads(Path('shared/fees.json').read_text()).items()}\n",
            encoding="utf-8")
        self.apply("include-shared-data", "include", source="spec.md / REQ-1 and REQ-2",
                   reason="Test-owned data refactor preserves expected answers and adds the shared fixture dependency.",
                   items=[{"example": f"fee-{i}", "tests": ["shared/fees.json"], "contract": [], "product": []}
                          for i in range(1, self.count + 1)])

    def finish(self):
        self.git("fixture-git-add", "add", "--all")
        self.git("fixture-git-commit", "-c", "user.name=Benchmark Fixture", "-c", "user.email=benchmark@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "matched fixture candidate")
        head = self.git("fixture-git-head", "rev-parse", "HEAD")
        self.apply("qualify-final", "qualify", scope={"final": True},
                   spec_review=self.review("spec"), standards_review=self.review("standards"))
        if self.mode == "execute":
            request_path = self.root / "executions" / "final.json"
            write_json(request_path, {
                "schema": 1,
                "prepare": {"schema": 1, "op_id": "prepare-final", "op": "prepare-formal",
                            "scope": {"final": True}, "timeout_seconds": 10},
                "record_op_id": "record-final", "argv": self.test_argv(),
            })
            result = self.cycle("formal-execute", "execute", "--request", request_path)
            assert result["outcome"] == "exited" and result["exit_code"] == 0
            formal = result["prepare"]
            receipt = self.check_receipt(formal, "formal-execute", 0)
        else:
            formal = self.apply("prepare-final", "prepare-formal", scope={"final": True}, timeout_seconds=10)
            receipt = self.run_prepared(formal, "formal-run", 0, formal=True)
            self.apply("record-final", "record", attempt_id=formal["attempt_id"])
        assert receipt["formal"]["head_before"] == receipt["formal"]["head_after"] == head
        assert receipt["formal"]["clean_before"] and receipt["formal"]["clean_after"]
        finished = self.apply("finish", "finish", attempt_id=formal["attempt_id"], code_reviews={
            axis: {"head": head, "review_id": f"mechanical-fixture-code-{axis}", "verdict": "pass"}
            for axis in ("spec", "standards")})
        assert finished["status"] == "ready"
        observed = self.cycle("inspect", "inspect")
        assert observed["status"] == "ready" and not observed["pending_attempts"]
        assert all(item["state"] == "closed" and item["mode"] == "red-green" for item in observed["examples"].values())
        assert all(item["classification"] in {"valid-red", "implementation"} and item["resolved"] for item in observed["failures"])
        assert observed["budget"]["attempts_used"] == self.count * 2 + 1 + (self.scenario == "small")
        assert self.cycle("verify", "verify")["valid"]
        return observed

    def run(self):
        start = time.perf_counter()
        self.setup()
        for i in range(1, self.count + 1):
            self.example(i)
        if self.scenario == "small":
            self.dependency_refresh()
        observed = self.finish()
        elapsed = time.perf_counter() - start
        state = json.loads((self.state / "state.json").read_text(encoding="utf-8"))
        work_signature = {
            "events": [[item["event"]["op_id"], item["event"]["op"]] for item in state["events"]],
            "executions": [{"example": item["example"], "purpose": item["purpose"],
                            "outcome": item["receipt"]["outcome"], "exit_code": item["receipt"]["exit_code"],
                            "argv": item["receipt"]["argv"],
                            "after": {group: item["receipt"]["snapshot"]["after"][group]["sha256"]
                                      for group in ("tests", "contract", "product")}}
                           for item in sorted(state["attempts"].values(), key=lambda item: item["request"]["binding"]["prepared_seq"])],
            "final_sources": {str(path.relative_to(self.workspace)): sha256(path)
                              for folder in ("src", "tests", "shared") for path in sorted((self.workspace / folder).rglob("*")) if path.is_file()},
        }
        groups = defaultdict(float)
        for item in self.phases:
            phase = item["phase"]
            group = ("execute" if phase.endswith("-execute") else "runner" if phase.endswith("-run")
                     else "git" if phase.startswith("fixture-git") else "ledger")
            groups[group] += item["seconds"]
        result = {"label": self.label, "scenario": self.scenario, "mode": self.mode, "root": str(self.root),
                  "skill": str(self.skill), "examples": self.count, "trace_bytes_per_test": self.log_bytes,
                  "elapsed_seconds": elapsed, "phase_totals_seconds": dict(groups),
                  "other_seconds": elapsed - sum(groups.values()), "phases": self.phases, "receipts": self.receipts,
                  "target_body_seconds": sum(item["target_seconds"] for item in self.receipts),
                  "receipt_managed_seconds": sum(item["duration_seconds"] for item in self.receipts),
                  "status": observed["status"], "attempts": observed["budget"]["attempts_used"],
                  "events": observed["last_seq"], "outer_process_invocations": len(self.phases),
                  "work_signature": work_signature,
                  "profiled": self.profile,
                  "retained_bytes": sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())}
        write_json(self.root / "result.json", result)
        if self.profile:
            stats = pstats.Stats(*map(str, (self.root / "profiles").glob("*.pstats")))
            stats.files = []
            with (self.root / "profile-summary.txt").open("w", encoding="utf-8") as output:
                stats.stream = output
                stats.strip_dirs().sort_stats("cumulative").print_stats(35)
                stats.sort_stats("tottime").print_stats(25)
        return result


def summarize(results):
    summary = {}
    for scenario in SCENARIOS:
        subset = [r for r in results if r["scenario"] == scenario and not r["profiled"] and not r.get("warmup")]
        if not subset:
            continue
        arms = {}
        for label in ("baseline", "candidate"):
            values = [r["elapsed_seconds"] for r in subset if r["label"] == label]
            if values:
                arms[label] = {"n": len(values), "median_seconds": statistics.median(values),
                               "min_seconds": min(values), "max_seconds": max(values),
                               "mean_seconds": statistics.mean(values),
                               "stdev_seconds": statistics.stdev(values) if len(values) > 1 else None}
        pairs = defaultdict(dict)
        for r in subset:
            pairs[r["pair"]][r["label"]] = r["elapsed_seconds"]
        differences = [v["baseline"] - v["candidate"] for v in pairs.values() if len(v) == 2]
        percentages = [100 * (v["baseline"] - v["candidate"]) / v["baseline"]
                       for v in pairs.values() if len(v) == 2]
        summary[scenario] = {"arms": arms, "paired_saved_seconds": differences,
                             "paired_saved_percent": percentages,
                             "median_paired_saved_seconds": statistics.median(differences) if differences else None,
                             "median_paired_saved_percent": statistics.median(percentages) if percentages else None}
    return summary


def run_trial(trial, manifest, output, pair):
    try:
        return trial.run()
    except Exception as error:
        manifest.setdefault("failed_trials", []).append({
            "label": trial.label, "scenario": trial.scenario, "pair": pair,
            "mode": trial.mode, "root": str(trial.root), "error": repr(error),
        })
        write_json(output, manifest)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pairs", type=int, default=6)
    parser.add_argument("--single", choices=SCENARIOS)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--candidate-mode", choices=("legacy", "execute"), default="execute")
    parser.add_argument("--single-mode", choices=("legacy", "execute"), default="legacy")
    parser.add_argument("--single-arm", choices=("baseline", "candidate"), default="baseline")
    args = parser.parse_args()
    if args.single_arm == "candidate" and args.candidate is None:
        parser.error("--single-arm candidate requires --candidate")
    root = Path(tempfile.mkdtemp(prefix="v3-matched-bench-"))
    results = []
    baseline = root / "baseline-skill"
    manifests = {"baseline": freeze_skill(args.baseline, baseline)}
    candidate = root / "candidate-skill"
    if args.candidate:
        manifests["candidate"] = freeze_skill(args.candidate, candidate)
    manifest = {"python": sys.version, "python_executable": sys.executable, "platform": platform.platform(),
                "cpu_count": os.cpu_count(), "root": str(root), "baseline": str(args.baseline),
                "candidate": str(args.candidate), "source_sha256": manifests, "results": results}
    if args.single:
        skill = baseline if args.single_arm == "baseline" else candidate
        trial = Trial(skill, args.single, args.single_arm, root / "single", profile=args.profile, mode=args.single_mode)
        result = run_trial(trial, manifest, args.output, 0)
        result["pair"] = 0
        results.append(result)
        print(json.dumps({"scenario": args.single, "elapsed_seconds": result["elapsed_seconds"], "root": str(root)}), flush=True)
    else:
        if args.candidate is None:
            parser.error("matched runs require --candidate")
        for scenario in SCENARIOS:
            for pair in range(-1, args.pairs):
                order = ("baseline", "candidate") if pair % 2 == 0 else ("candidate", "baseline")
                for label in order:
                    skill = baseline if label == "baseline" else candidate
                    mode = "legacy" if label == "baseline" else args.candidate_mode
                    trial = Trial(skill, scenario, label, root / f"{scenario}-{pair + 1:02}-{label}", mode=mode)
                    result = run_trial(trial, manifest, args.output, pair)
                    result.update(pair=pair, warmup=pair == -1)
                    results.append(result)
                    paired = [r for r in results if r["scenario"] == scenario and r["pair"] == pair]
                    if len(paired) == 2:
                        if paired[0]["work_signature"] != paired[1]["work_signature"]:
                            manifest.setdefault("failed_comparisons", []).append({"scenario": scenario, "pair": pair})
                            write_json(args.output, manifest)
                            raise AssertionError("Matched arms did different work")
                    manifest["summary"] = summarize(results)
                    write_json(args.output, manifest)
                    print(json.dumps({"scenario": scenario, "pair": pair, "label": label,
                                      "elapsed_seconds": result["elapsed_seconds"]}), flush=True)
    manifest["summary"] = summarize(results)
    write_json(args.output, manifest)


if __name__ == "__main__":
    main()
