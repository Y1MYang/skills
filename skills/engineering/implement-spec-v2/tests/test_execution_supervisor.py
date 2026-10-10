"""Black-box acceptance-supervision checks using isolated real subprocesses.

These tests derive their oracle from the published execution contract. They do
not import implementation helpers or mock clocks, process identity, or pipes.
The outer timeout only protects this test runner: hitting it is always failure.
"""

from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SUPERVISOR = SCRIPTS / "execution_supervisor.py"
OUTER_TIMEOUT = 6.0
# Ten sequential gate proofs have separate declared hard horizons. Their
# synthetic caps total at most 14.4s plus two actual 1.15s fixture horizons;
# this independent wall cap includes cold CLI startup without replacing them.
GATE_OUTER_TIMEOUT = 20.0


# An adapter is deliberately separate from the supervisor. It writes only the
# documented event protocol and can block inside any acceptance phase.
ADAPTER = r"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

mode = sys.argv[1]
attempt = os.environ["IMPLEMENT_SPEC_ATTEMPT_ID"]
events = Path(os.environ["IMPLEMENT_SPEC_EVENTS_PATH"])

def identity(pid):
    fields = Path("/proc/%s/stat" % pid).read_text().rsplit(")", 1)[1].split()
    return {"pid": pid, "start_ticks": int(fields[19])}

(Path(__file__).resolve().parent / ("adapter-%s.identity.json" % os.getpid())).write_text(json.dumps(identity(os.getpid())))

def emit(kind, worker="worker-a", attempt_id=None, **fields):
    if mode == "omit_setup" and fields.get("phase") == "setup":
        return
    if mode == "omit_run" and fields.get("phase") == "run":
        return
    if mode == "omit_case" and kind in ("case_start", "case_end"):
        return
    record = dict(version=1, attempt_id=attempt_id or attempt,
                  worker_id=worker, kind=kind, **fields)
    with events.open("a") as stream:
        stream.write(json.dumps(record) + "\n")
        stream.flush()

def begin(worker="worker-a", phase="run", case="case-a"):
    emit("worker_start", worker, pid=os.getpid())
    emit("phase_start", worker, phase="setup")
    if phase == "setup":
        return
    emit("phase_end", worker, phase="setup")
    emit("phase_start", worker, phase="run")
    extra = {"profile": "slow-browser"} if mode == "slow_profile" else {}
    emit("case_start", worker, case_id=case or "case-a", **extra)
    if phase == "cleanup":
        emit("case_end", worker, case_id=case or "case-a")
        emit("phase_end", worker, phase="run")
        emit("phase_start", worker, phase="cleanup")

def end(worker="worker-a", phase="run", case="case-a"):
    if phase == "run":
        emit("case_end", worker, case_id=case)
        emit("phase_end", worker, phase="run")
        emit("phase_start", worker, phase="cleanup")
    emit("phase_end", worker, phase="cleanup")
    emit("worker_end", worker)

if os.environ.get("IMPLEMENT_SPEC_EXECUTION_GATE") == "1":
    begin()
    if mode != "no_gate_ready":
        nonce = "incorrect-fixture-nonce" if mode == "bad_nonce" else os.environ["IMPLEMENT_SPEC_GATE_NONCE"]
        emit("gate_ready", nonce=nonce)
    if os.environ.get("IMPLEMENT_SPEC_GATE_SCENARIO") == "blocked_callback" and mode != "healthy_only":
        time.sleep(60)  # The adapter's actual acceptance callback seam.
    if mode != "no_gate_cleanup":
        end()
    sys.exit(0)

if mode == "missing":
    print("normal exit without acceptance boundaries", flush=True)
elif mode == "malformed":
    events.write_text("this is not JSON\n")
elif mode == "fifo_events":
    events.unlink(missing_ok=True)
    os.mkfifo(events)
    time.sleep(60)
elif mode in ("setup", "cleanup"):
    begin(phase=mode, case=None)
    while True:
        time.sleep(0.03)
elif mode in ("complete", "incomplete", "omit_setup", "omit_run", "omit_case"):
    begin()
    emit("progress", case_id="case-a", evidence="assertion-1", progress_kind="assertion")
    if mode != "incomplete":
        end()
    else:
        emit("case_end", case_id="case-a")
        emit("phase_end", phase="run")
elif mode in ("slow_complete", "slow_profile"):
    begin()
    for index in range(5):
        emit("progress", case_id="case-a", evidence="step-" + str(index), progress_kind="assertion")
        time.sleep(0.055)
    end()
elif mode == "cross_worker_deadlines":
    begin(worker="worker-a", case="late-case")
    begin(worker="worker-b", case="early-case")
    while True:
        time.sleep(0.025)
elif mode == "end_while_observer_paused":
    begin()
    time.sleep(.8)
    end()
elif mode in ("modal", "heartbeat", "duplicate", "stale", "parallel", "progress", "no_progress", "flood"):
    begin()
    if mode != "no_progress":
        emit("progress", case_id="case-a", evidence="initial-step", progress_kind="assertion")
    if mode == "parallel":
        begin(worker="worker-b", case="case-b")
    index = 0
    while True:
        if mode in ("heartbeat", "flood"):
            emit("heartbeat")
            print("X" * 65536 if mode == "flood" else "noisy log has no semantic progress", flush=True)
            # CPU and log activity are not acceptance progress.
            sum(number * number for number in range(2500))
        elif mode == "duplicate":
            emit("progress", case_id="case-a", evidence="initial-step", progress_kind="assertion")
        elif mode == "stale":
            emit("progress", case_id="case-a", evidence="stale-" + str(index),
                 attempt_id="previous-attempt", progress_kind="assertion")
        elif mode == "parallel":
            emit("progress", worker="worker-b", case_id="case-b",
                 evidence="neighbor-" + str(index), progress_kind="assertion")
        elif mode == "progress":
            emit("progress", case_id="case-a", evidence="step-" + str(index), progress_kind="assertion")
        index += 1
        time.sleep(0.025)
elif mode in ("child_pipe", "escaped_child"):
    begin()
    child = subprocess.Popen([sys.executable, "-c",
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"],
        start_new_session=(mode == "escaped_child"))
    (Path(__file__).resolve().parent / "owned-child.pid").write_text(str(child.pid))
    (Path(__file__).resolve().parent / "child.identity.json").write_text(json.dumps(identity(child.pid)))
    emit("progress", case_id="case-a", evidence="child-launched", progress_kind="assertion")
    end()
    print("runner exited; child still owns stdout and stderr", flush=True)
elif mode == "borrowed_worker":
    borrowed = int((Path(__file__).resolve().parent / "borrowed.pid").read_text())
    emit("worker_start", pid=borrowed)
    emit("phase_start", phase="run")
    emit("case_start", case_id="case-a")
    while True:
        time.sleep(0.03)
else:
    raise ValueError(mode)
"""


HARNESS = r"""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, sys.argv[1])
from execution_supervisor import read_contract, supervise, validate_gate
config = json.loads(Path(sys.argv[2]).read_text())
contract = read_contract(config["contract"])
if config["action"] == "validate":
    result = validate_gate(config["receipt"], config["command"], config["cwd"], contract)
else:
    def blocked_start(*args, **kwargs):
        time.sleep(60)
    result = supervise(config["command"], config["cwd"], config["logs"],
                       contract, config["attempt_id"],
                       events_path=config["events"], alerts_path=config["alerts"],
                       on_start=blocked_start if config.get("blocking_start") else None)
Path(config["result"]).write_text(json.dumps(result))
"""


def budget(seconds, source="fixture acceptance specification"):
    return {"seconds": seconds, "source": source}


def contract_for(adapter, total=1.15, case=0.42, phase=0.7, stall=0.14):
    return {
        "version": 1,
        "budgets": {
            "total": budget(total),
            "shutdown": budget(0.3),
            "case": budget(case),
            "phase": {name: budget(phase) for name in ("setup", "run", "cleanup")},
            "stall": budget(stall),
        },
        "long_cases": {},
        "case_profiles": {},
        "progress_kinds": ["assertion"],
        "adapter": {"files": [str(adapter)], "environment": ["SUPERVISOR_TEST_CONFIG"]},
    }


def retain_failed_terminal_evidence(test):
    """Keep neutral receipts before disposable fixtures disappear on failure."""
    outcome = getattr(test, "_outcome", None)
    result = getattr(outcome, "result", None)
    if result is None:
        return
    failures = list(getattr(result, "failures", ())) + list(getattr(result, "errors", ()))
    if not any(case is test or getattr(case, "test_case", None) is test for case, _ in failures):
        return
    saved = Path(tempfile.mkdtemp(prefix="execution-test-failure-evidence-"))
    manifest = []
    for index, path in enumerate(sorted(test.root.rglob("*.terminal.json"))):
        entry = {"original": str(path)}
        try:
            target = saved / (str(index) + ".terminal.json")
            target.write_bytes(path.read_bytes())
            entry["saved"] = str(target)
        except OSError as error:
            entry["read_error"] = str(error)
        manifest.append(entry)
    (saved / "manifest.json").write_text(json.dumps({"test": test.id(), "terminals": manifest}, indent=2))
    print("Preserved public terminal evidence: " + str(saved / "manifest.json"), file=sys.stderr)


class ExecutionSupervisorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="execution-supervisor-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.adapter = self.root / "acceptance_adapter.py"
        self.adapter.write_text(ADAPTER)
        self.harness = self.root / "harness.py"
        self.harness.write_text(HARNESS)
        self.contract_path = self.root / "contract.json"
        self.receipt_path = self.root / "gate.json"
        self.env = dict(os.environ, SUPERVISOR_TEST_CONFIG="fixture-v1")
        self.run_number = 0
        self.addCleanup(self.cleanup_fixture_processes)

    def tearDown(self):
        retain_failed_terminal_evidence(self)

    @staticmethod
    def process_identity(pid):
        try:
            fields = Path("/proc/%s/stat" % pid).read_text().rsplit(")", 1)[1].split()
            return {"pid": pid, "start_ticks": int(fields[19]), "state": fields[0]}
        except (OSError, ValueError, IndexError):
            return None

    def cleanup_fixture_processes(self):
        # These files are written by this test's adapter, not by the supervisor.
        # Only the original exact identity is eligible for emergency cleanup.
        for path in self.root.glob("*.identity.json"):
            saved = json.loads(path.read_text())
            live = self.process_identity(saved["pid"])
            if live and live["start_ticks"] == saved["start_ticks"] and live["state"] != "Z":
                try:
                    os.kill(saved["pid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def process_is_running(self, pid):
        state = self.process_identity(pid)
        return bool(state and state["state"] != "Z")

    def write_contract(self, contract=None):
        contract = contract or contract_for(self.adapter)
        self.contract_path.write_text(json.dumps(contract))
        return contract

    def command(self, mode):
        return [sys.executable, str(self.adapter), mode]

    def run_outer(self, command, *, timeout=OUTER_TIMEOUT):
        """A failure here means the supervisor did not prove finite completion."""
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=self.root, env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=1)
            self.fail("outer safety timeout fired; supervisor did not finish: " + stderr[-1500:])
        self.assertLess(time.monotonic() - started, timeout,
                        "completion must precede the independent outer timeout")
        return process.returncode, stdout, stderr, time.monotonic() - started

    def supervise(self, mode, contract=None, *, blocking_start=False):
        contract = self.write_contract(contract)
        self.run_number += 1
        attempt_root = self.root / ("attempt-" + str(self.run_number))
        attempt_root.mkdir()
        result_path = attempt_root / "result.json"
        config = {
            "action": "supervise", "contract": str(self.contract_path),
            "command": self.command(mode), "cwd": str(self.root),
            "logs": {"stdout": str(attempt_root / "stdout.gz"),
                     "stderr": str(attempt_root / "stderr.gz")},
            "attempt_id": "attempt-" + str(self.run_number),
            "events": str(attempt_root / "events.jsonl"),
            "alerts": str(attempt_root / "alerts.jsonl"), "result": str(result_path),
            "blocking_start": blocking_start,
        }
        config_path = self.root / "harness-config.json"
        config_path.write_text(json.dumps(config))
        code, stdout, stderr, elapsed = self.run_outer(
            [sys.executable, str(self.harness), str(SCRIPTS), str(config_path)])
        self.assertEqual(code, 0, stderr or stdout)
        self.assertTrue(result_path.is_file(), "a terminal result is required")
        result = json.loads(result_path.read_text())
        self.assertLessEqual(elapsed, contract["budgets"]["total"]["seconds"] + 0.65,
                             "shutdown and log draining share the original total horizon")
        self.assert_terminal_evidence(result, config["logs"])
        return result

    def assert_terminal_evidence(self, result, logs):
        for name in ("exit_code", "outcome", "stopped", "capture_complete", "capture_errors",
                     "log_sha256", "process_identity", "coverage_verified", "elapsed_seconds",
                     "evidence_paths"):
            self.assertIn(name, result, "terminal evidence is missing " + name)
        self.assertIsInstance(result["capture_errors"], list)
        self.assertTrue(result["process_identity"], "termination must retain the verified process identity")
        self.assertTrue(result["evidence_paths"], "terminal evidence must be persisted")
        self.assertIn("terminal", result["evidence_paths"])
        terminal = Path(result["evidence_paths"]["terminal"])
        self.assertTrue(terminal.is_file(), "the completed supervisor must persist its terminal receipt")
        receipt = json.loads(terminal.read_text())
        self.assertEqual(receipt["outcome"], result["outcome"])
        self.assertEqual(receipt["process_identity"], result["process_identity"])
        for stream, log_path in logs.items():
            archive = Path(log_path)
            self.assertTrue(archive.is_file(), "terminal result requires its captured " + stream)
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),
                             result["log_sha256"][stream], "receipt digest must cover the full closed gzip archive")
            with gzip.open(archive, "rb") as captured:
                captured.read()  # Reading through EOF validates gzip footer/CRC.

    def alerts(self, result):
        path = Path(result["evidence_paths"]["alerts"])
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def supervise_with_observer_pause(self, mode, contract, *, worker, pause_seconds=1.15,
                                      require_end_while_paused=False, case_must_precede_total=False):
        """Delay only this test's observer after a public case diagnosis.

        The original command, case, phase and whole-attempt clocks continue.
        SIGSTOP/SIGCONT target the exact child PID/start_ticks we created.
        """
        self.write_contract(contract)
        self.run_number += 1
        attempt_root = self.root / ("paused-attempt-" + str(self.run_number))
        attempt_root.mkdir()
        config = {
            "action": "supervise", "contract": str(self.contract_path),
            "command": self.command(mode), "cwd": str(self.root),
            "logs": {"stdout": str(attempt_root / "stdout.gz"), "stderr": str(attempt_root / "stderr.gz")},
            "attempt_id": "paused-attempt-" + str(self.run_number),
            "events": str(attempt_root / "events.jsonl"), "alerts": str(attempt_root / "alerts.jsonl"),
            "result": str(attempt_root / "result.json"),
        }
        config_path = attempt_root / "config.json"
        config_path.write_text(json.dumps(config))
        started = time.monotonic()
        process = subprocess.Popen([sys.executable, str(self.harness), str(SCRIPTS), str(config_path)],
            cwd=self.root, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True)
        identity = self.process_identity(process.pid)
        paused = False
        try:
            self.assertTrue(identity, "the test must verify its own observer before pausing it")
            deadline = started + 3
            diagnosed = False
            diagnosis = None
            while time.monotonic() < deadline:
                alerts = Path(config["alerts"])
                for line in alerts.read_text().splitlines() if alerts.exists() else ():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (event.get("attempt_id") == config["attempt_id"]
                            and event.get("worker_id") == worker and event.get("case_id")
                            and event.get("action") == "owner_diagnosis"):
                        diagnosed = True
                        diagnosis = event
                        break
                if diagnosed or process.poll() is not None:
                    break
                time.sleep(.01)
            self.assertTrue(diagnosed, "pause requires a public alert proving this case was observed")
            if case_must_precede_total:
                payload = contract["budgets"]["total"]["seconds"] - contract["budgets"]["shutdown"]["seconds"]
                self.assertLess(diagnosis["elapsed_seconds"] + contract["budgets"]["case"]["seconds"], payload,
                    "the public diagnosis must establish that this case's fixed deadline precedes total")
            live = self.process_identity(process.pid)
            self.assertTrue(live and live["start_ticks"] == identity["start_ticks"],
                            "a reused PID cannot authorize the scheduling pause")
            os.kill(process.pid, signal.SIGSTOP)
            paused = True
            stopped_by = time.monotonic() + .3
            while time.monotonic() < stopped_by:
                live = self.process_identity(process.pid)
                if live and live["state"] == "T":
                    break
                time.sleep(.005)
            self.assertTrue(live and live["state"] == "T", "the controlled observer was not paused")
            time.sleep(pause_seconds)
            if require_end_while_paused:
                records = [json.loads(line) for line in Path(config["events"]).read_text().splitlines() if line.strip()]
                self.assertTrue([event for event in records if event.get("attempt_id") == config["attempt_id"]
                                 and event.get("worker_id") == worker and event.get("kind") == "worker_end"],
                                "the child must finish its lifecycle while the observer is paused")
            live = self.process_identity(process.pid)
            self.assertTrue(live and live["start_ticks"] == identity["start_ticks"])
            os.kill(process.pid, signal.SIGCONT)
            paused = False
            try:
                stdout, stderr = process.communicate(timeout=max(.01, OUTER_TIMEOUT - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                self.fail("outer safety timeout fired after the observer resumed")
            self.assertEqual(process.returncode, 0, stdout + stderr)
            self.assertLess(time.monotonic() - started, OUTER_TIMEOUT)
            result = json.loads(Path(config["result"]).read_text())
            self.assert_terminal_evidence(result, config["logs"])
            self.assertLessEqual(result["elapsed_seconds"], contract["budgets"]["total"]["seconds"] + .15,
                                 "the controlled scheduling pause must not renew the original hard horizon")
            return result
        finally:
            live = self.process_identity(process.pid)
            if paused and identity and live and live["start_ticks"] == identity["start_ticks"]:
                os.kill(process.pid, signal.SIGCONT)
            if process.poll() is None:
                process.kill()  # Exact isolated observer process created above.
            process.communicate(timeout=1)

    def gate(self, mode="modal", contract=None):
        self.write_contract(contract)
        command = [sys.executable, str(SUPERVISOR), "gate", "--contract", str(self.contract_path),
                   "--cwd", str(self.root), "--output", str(self.receipt_path), "--", *self.command(mode)]
        return self.run_outer(command, timeout=GATE_OUTER_TIMEOUT)

    def validate(self, mode="modal"):
        config = {
            "action": "validate", "contract": str(self.contract_path),
            "command": self.command(mode), "cwd": str(self.root),
            "receipt": str(self.receipt_path), "result": str(self.root / "validated.json"),
        }
        path = self.root / "validate-config.json"
        path.write_text(json.dumps(config))
        return self.run_outer([sys.executable, str(self.harness), str(SCRIPTS), str(path)])

    def test_normal_complete_has_full_terminal_evidence(self):
        result = self.supervise("complete")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["coverage_verified"])
        self.assertTrue(result["capture_complete"])
        self.assertFalse(result["capture_errors"])

    def test_stale_gate_environment_cannot_turn_a_formal_run_into_a_probe(self):
        self.env.update(IMPLEMENT_SPEC_EXECUTION_GATE="1", IMPLEMENT_SPEC_GATE_NONCE="stale-external-nonce",
                        IMPLEMENT_SPEC_GATE_SCENARIO="blocked_callback")
        result = self.supervise("modal")
        self.assertEqual(result["outcome"], "case_timeout",
                         "normal supervision must execute the actual blocked acceptance path")
        events = Path(result["evidence_paths"]["events"])
        records = [json.loads(line) for line in events.read_text().splitlines() if line.strip()]
        self.assertFalse([record for record in records if record["kind"] == "gate_ready"],
                         "an inherited gate flag cannot claim probe readiness in a real run")

    def test_blocking_registration_callback_cannot_escape_the_outer_supervisor(self):
        result = self.supervise("complete", blocking_start=True)
        self.assertFalse(result["coverage_verified"])
        self.assertEqual(result["outcome"], "unknown")

    def test_setup_and_cleanup_are_under_external_phase_deadlines(self):
        for phase in ("setup", "cleanup"):
            with self.subTest(phase=phase):
                result = self.supervise(phase, contract_for(self.adapter, phase=0.3))
                self.assertEqual(result["outcome"], "phase_timeout")
                self.assertTrue(result["stopped"])
                self.assertTrue(result["capture_complete"])

    def test_blocked_callback_and_activity_do_not_extend_case_deadline(self):
        for mode in ("modal", "heartbeat", "flood", "duplicate", "stale", "parallel"):
            with self.subTest(mode=mode):
                result = self.supervise(mode)
                self.assertEqual(result["outcome"], "case_timeout")
                self.assertTrue(result["stopped"])
                self.assertTrue(result["capture_complete"])
                worker = result["diagnostics"]["workers"]["worker-a"]
                self.assertEqual(worker["case_id"], "case-a")
                self.assertEqual(worker["last_progress_evidence"], "initial-step")
                self.assertGreaterEqual(result["elapsed_seconds"], 0.38,
                                        "idle diagnoses a case; it cannot replace its fixed deadline")
                alerts = [event for event in self.alerts(result)
                          if event.get("reason") == "stall_suspected" and event.get("worker_id") == "worker-a"]
                self.assertTrue(alerts, "activity from logs or another worker cannot mask idle diagnosis")
                self.assertEqual(alerts[0]["case_id"], "case-a")
                self.assertEqual(alerts[0]["phase"], "run")
                self.assertEqual(alerts[0]["action"], "owner_diagnosis")
                self.assertLess(alerts[0]["elapsed_seconds"], 0.42,
                                "stall must be diagnosed independently before the hard deadline")

    def test_real_progress_can_be_slow_but_does_not_extend_fixed_budgets(self):
        complete = self.supervise("slow_complete")
        self.assertEqual(complete["exit_code"], 0)
        self.assertTrue(complete["coverage_verified"])
        self.assertFalse([event for event in self.alerts(complete)
                          if event.get("reason") == "stall_suspected"],
                         "measured semantic progress must not be misclassified as a stall")
        for case, phase, outcome in ((0.32, 0.7, "case_timeout"),
                                     (10, 0.32, "phase_timeout"),
                                     (10, 10, "total_timeout")):
            with self.subTest(outcome=outcome):
                result = self.supervise("progress", contract_for(self.adapter, case=case, phase=phase))
                self.assertEqual(result["outcome"], outcome)
                self.assertTrue(result["stopped"])

    def test_delayed_observer_reports_the_earliest_expired_absolute_deadline(self):
        for scenario in ("case_before_phase", "earlier_other_worker", "total_before_case",
                         "phase_before_case", "case_before_total", "late_end"):
            with self.subTest(scenario=scenario):
                contract = contract_for(self.adapter, total=2.5, case=.6, phase=.9, stall=.12)
                contract["budgets"]["shutdown"] = budget(1.0,
                    "predeclared ordering fixture: controlled 1.15s observer pause with fixed deadlines and bounded capture window")
                mode, worker, outcome, deadline_worker = "modal", "worker-a", "case_timeout", "worker-a"
                if scenario == "earlier_other_worker":
                    contract["long_cases"]["late-case"] = budget(1.0, "predeclared later first worker also expires during the ordering pause")
                    mode, worker, deadline_worker = "cross_worker_deadlines", "worker-b", "worker-b"
                elif scenario == "total_before_case":
                    contract["budgets"]["shutdown"] = budget(1.5,
                        "controlled 1.15s pause crosses the .7s payload; extra .5s capture headroom preserves that payload")
                    contract["budgets"]["total"] = budget(2.2, "fixed .7s payload deadline precedes this fixture's 1.0s case")
                    contract["budgets"]["case"] = budget(1.0)
                    contract["budgets"]["phase"] = {name: budget(1.1) for name in ("setup", "run", "cleanup")}
                    outcome, deadline_worker = "total_timeout", None
                elif scenario == "phase_before_case":
                    contract["budgets"]["case"] = budget(.9)
                    contract["budgets"]["phase"] = {name: budget(.5) for name in ("setup", "run", "cleanup")}
                    outcome = "phase_timeout"
                elif scenario == "case_before_total":
                    contract["budgets"]["shutdown"] = budget(1.3,
                        "controlled 1.5s pause expires case and total; fixed 1.2s payload plus bounded capture headroom")
                    contract["budgets"]["total"] = budget(2.5, "fixed 1.2s payload expires during this fixture's 1.5s pause")
                elif scenario == "late_end":
                    mode = "end_while_observer_paused"
                result = self.supervise_with_observer_pause(mode, contract, worker=worker,
                    pause_seconds=1.5 if scenario == "case_before_total" else 1.15,
                    require_end_while_paused=(scenario == "late_end"),
                    case_must_precede_total=(scenario == "case_before_total"))
                self.assertEqual(result["outcome"], outcome, json.dumps(result))
                self.assertEqual(result["diagnostics"]["deadline_worker"], deadline_worker, json.dumps(result))
                self.assertTrue(result["stopped"], json.dumps(result))
                self.assertTrue(result["capture_complete"], json.dumps(result))
                deadlines = [event for event in self.alerts(result) if event.get("action") == "capture_and_classify"]
                self.assertTrue(deadlines, "the first expired boundary needs persisted diagnosis evidence")
                self.assertEqual(deadlines[0]["reason"], outcome, json.dumps(deadlines))
                if deadline_worker is not None:
                    self.assertEqual(deadlines[0]["worker_id"], deadline_worker)
                    self.assertEqual(deadlines[0]["case_id"], "early-case" if scenario == "earlier_other_worker" else "case-a")
                    self.assertEqual(deadlines[0]["phase"], "run")

    def test_only_predeclared_case_or_profile_budgets_extend_a_short_case(self):
        for mode, custom in (("slow_complete", "long_cases"), ("slow_profile", "case_profiles")):
            with self.subTest(custom=custom):
                contract = contract_for(self.adapter, case=0.14)
                key = "case-a" if custom == "long_cases" else "slow-browser"
                contract[custom][key] = budget(0.4, "documented browser acceptance fixture")
                result = self.supervise(mode, contract)
                self.assertEqual(result["exit_code"], 0)
                self.assertTrue(result["coverage_verified"])

    def test_missing_or_malformed_events_never_claim_formal_coverage(self):
        for mode in ("missing", "malformed", "incomplete", "omit_setup", "omit_run", "omit_case"):
            with self.subTest(mode=mode):
                result = self.supervise(mode)
                self.assertFalse(result["coverage_verified"])
                self.assertEqual(result["outcome"], "coverage_unverified")

    def test_replaced_fifo_event_channel_cannot_block_the_external_supervisor(self):
        result = self.supervise("fifo_events")
        self.assertFalse(result["coverage_verified"])
        self.assertTrue(result["diagnostics"]["event_errors"],
                        "a non-regular event channel must retain a visible protocol error")

    def test_no_internal_progress_uses_fixed_caps_and_reports_unknown(self):
        contract = contract_for(self.adapter)
        contract["progress_kinds"] = []
        result = self.supervise("no_progress", contract)
        self.assertEqual(result["outcome"], "case_timeout")
        self.assertEqual(result["diagnostics"]["workers"]["worker-a"]["progress_status"], "unknown")
        self.assertTrue(result["stopped"])
        self.assertGreaterEqual(result["elapsed_seconds"], 0.38)

    def test_inherited_pipes_and_term_resistant_owned_children_finish_within_horizon(self):
        result = self.supervise("child_pipe")
        child_pid = int((self.root / "owned-child.pid").read_text())
        self.assertFalse(self.process_is_running(child_pid), "owned child survived terminal receipt")
        self.assertTrue(result["capture_complete"], "an inherited pipe cannot defer terminal capture indefinitely")
        self.assertFalse(result["capture_errors"])
        self.assertTrue(result["owned_processes"], "child cleanup requires verified ownership evidence")

    def test_neighbor_process_is_preserved_while_owned_child_is_stopped(self):
        neighbor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                    start_new_session=True, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        def cleanup_neighbor():
            if neighbor.poll() is None:
                neighbor.kill()
            neighbor.wait(timeout=1)
        self.addCleanup(cleanup_neighbor)
        contract = contract_for(self.adapter, total=1.85)
        contract["budgets"]["shutdown"] = budget(1.0,
            "owned pipe capture measured 1.12321s with original .85s payload; threefold .27321s shutdown margin rounded to 1.0s")
        result = self.supervise("child_pipe", contract)
        self.assertTrue(result["capture_complete"])
        self.assertIsNone(neighbor.poll(), "an independent neighboring worker was stopped")

    def test_worker_reported_pid_cannot_authorize_stopping_a_neighbor(self):
        neighbor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                    start_new_session=True, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        def cleanup_neighbor():
            if neighbor.poll() is None:
                neighbor.kill()
            neighbor.wait(timeout=1)
        self.addCleanup(cleanup_neighbor)
        (self.root / "borrowed.pid").write_text(str(neighbor.pid))
        result = self.supervise("borrowed_worker")
        self.assertTrue(result["stopped"])
        self.assertIsNone(neighbor.poll(), "semantic worker PID must not replace OS ownership proof")

    def test_an_escaped_session_stays_unverified_and_is_not_blindly_stopped(self):
        result = self.supervise("escaped_child")
        child_pid = int((self.root / "owned-child.pid").read_text())
        self.assertFalse(result["coverage_verified"])
        self.assertEqual(result["outcome"], "unknown")
        self.assertTrue(self.process_is_running(child_pid), "unknown process scope must be preserved")

    def test_contract_requires_sources_and_finite_hierarchical_deadlines(self):
        good = contract_for(self.adapter)
        invalid = []
        boolean_version = deepcopy(good)
        boolean_version["version"] = True
        invalid.append(boolean_version)
        huge_integer = deepcopy(good)
        huge_integer["budgets"]["total"]["seconds"] = 10 ** 400
        invalid.append(huge_integer)
        missing_source = deepcopy(good)
        missing_source["budgets"]["case"]["source"] = ""
        invalid.append(missing_source)
        nonfinite = deepcopy(good)
        nonfinite["budgets"]["total"]["seconds"] = float("inf")
        invalid.append(nonfinite)
        no_shutdown_room = deepcopy(good)
        no_shutdown_room["budgets"]["shutdown"]["seconds"] = good["budgets"]["total"]["seconds"]
        invalid.append(no_shutdown_room)
        absent_phase = deepcopy(good)
        del absent_phase["budgets"]["phase"]["cleanup"]
        invalid.append(absent_phase)
        for contract in invalid:
            with self.subTest(contract=contract):
                code, _, stderr, _ = self.gate(contract=contract)
                self.assertNotEqual(code, 0)
                self.assertIn("error", json.loads(stderr), "invalid contracts require a structured refusal")

    def test_gate_requires_ready_nonce_and_complete_actual_runner_lifecycle(self):
        for mode in ("no_gate_ready", "bad_nonce", "no_gate_cleanup", "healthy_only"):
            with self.subTest(mode=mode):
                code, _, _, _ = self.gate(mode)
                self.assertNotEqual(code, 0, "generic canaries cannot replace actual adapter coverage")

    def test_gate_exercises_same_real_adapter_and_configuration_is_bound(self):
        code, stdout, stderr, _ = self.gate()
        self.assertEqual(code, 0, stderr or stdout)
        receipt = json.loads(self.receipt_path.read_text())
        for key in ("version", "binding", "checks", "evidence_files", "signature"):
            self.assertIn(key, receipt)
        checks = receipt["checks"]
        required = {"adapter", "adapter_blocked", "callback_block", "heartbeat_block", "setup_block", "cleanup_block",
                    "pipe_descendant", "parallel_progress", "bounded_progress", "noisy_events"}
        self.assertTrue(required.issubset(checks), "the launch gate requires each independent blocking probe")
        files = {record["path"]: record["sha256"] for record in receipt["evidence_files"]}
        identities = set()
        for name in required:
            with self.subTest(probe=name):
                check = checks[name]
                self.assertTrue(check["stopped"], "gate evidence requires actual finite termination")
                self.assertTrue(check["capture_complete"])
                budgets = check["budgets"]
                if name in ("adapter", "adapter_blocked"):
                    self.assertEqual(budgets, contract_for(self.adapter)["budgets"],
                                     "the actual adapter proof must use the unchanged actual contract")
                    self.assertEqual(check["long_cases"], {})
                else:
                    self.assertEqual(budgets["total"]["seconds"], 1.8)
                    self.assertEqual(budgets["shutdown"]["seconds"], 1.0)
                    self.assertAlmostEqual(budgets["total"]["seconds"] - budgets["shutdown"]["seconds"], .8,
                                           msg="synthetic workload window must remain fixed")
                    self.assertEqual(budgets["case"]["seconds"], 2 if name == "bounded_progress" else .25)
                    self.assertEqual(set(budgets["phase"]), {"setup", "run", "cleanup"})
                    for phase, limit in budgets["phase"].items():
                        self.assertEqual(limit["seconds"], 2 if name == "bounded_progress" and phase == "run" else .35)
                    self.assertEqual(budgets["stall"]["seconds"], .08)
                    if name == "parallel_progress":
                        self.assertEqual(set(check["long_cases"]), {"othercase"})
                        self.assertEqual(check["long_cases"]["othercase"]["seconds"], 2)
                    else:
                        self.assertEqual(check["long_cases"], {})
                self.assertLessEqual(check["elapsed_seconds"], budgets["total"]["seconds"] + .15)
                path = Path(check["terminal"])
                self.assertIn(str(path), files)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), files[str(path)])
                terminal = json.loads(path.read_text())
                self.assertEqual(terminal["total_horizon_seconds"], budgets["total"]["seconds"])
                self.assertAlmostEqual(terminal["payload_seconds"],
                                       budgets["total"]["seconds"] - budgets["shutdown"]["seconds"])
                for field in ("outcome", "stopped", "capture_complete", "coverage_verified", "elapsed_seconds"):
                    self.assertEqual(terminal[field], check[field])
                if name in ("adapter", "adapter_blocked"):
                    self.assertEqual(check["nonce"], receipt["nonces"][name])
                    self.assertIn(check["nonce"], terminal["gate_nonces"])
                    self.assertFalse(terminal["diagnostics"]["event_errors"])
                identity = terminal["process_identity"]
                identities.add((identity["pid"], identity["start_ticks"]))
                if name == "adapter":
                    self.assertEqual(check["outcome"], "completed")
                    self.assertTrue(check["coverage_verified"])
                elif name == "adapter_blocked":
                    self.assertIn(check["outcome"], ("case_timeout", "phase_timeout", "total_timeout"),
                                  "the real adapter uses whichever original fixed deadline expires first")
                    worker = terminal["diagnostics"]["workers"]["worker-a"]
                    self.assertEqual(worker["phase"], "run")
                    self.assertEqual(worker["case_id"], "case-a")
                    self.assertIn("setup", worker["completed_phases"])
                else:
                    expected = {"callback_block": "case_timeout", "heartbeat_block": "case_timeout",
                                "setup_block": "phase_timeout", "cleanup_block": "phase_timeout",
                                "pipe_descendant": "total_timeout", "parallel_progress": "case_timeout",
                                "bounded_progress": "total_timeout", "noisy_events": "case_timeout"}
                    self.assertEqual(check["outcome"], expected[name],
                                     "the probe must terminate at its declared fixed deadline")
                    if name == "parallel_progress":
                        self.assertEqual(terminal["diagnostics"]["deadline_worker"], "main",
                                         "other worker progress cannot mask the blocked worker")
                    if name == "bounded_progress":
                        self.assertEqual(terminal["diagnostics"]["workers"]["main"]["progress_status"], "observed",
                                         "real semantic progress cannot renew the original total horizon")
        self.assertEqual(len(identities), len(required), "each canary needs a separate real process identity")
        code, stdout, stderr, _ = self.validate()
        self.assertEqual(code, 0, stderr or stdout)
        self.env["SUPERVISOR_TEST_CONFIG"] = "fixture-v2"
        code, _, _, _ = self.validate()
        self.assertNotEqual(code, 0, "declared environment configuration is part of the gate binding")
        self.env["SUPERVISOR_TEST_CONFIG"] = "fixture-v1"
        self.adapter.write_text(ADAPTER + "\n# changed adapter configuration\n")
        code, _, _, _ = self.validate()
        self.assertNotEqual(code, 0, "an adapter change must invalidate the launch gate")

    def test_gate_rejects_a_boolean_receipt_and_changed_contract(self):
        self.write_contract()
        self.receipt_path.write_text(json.dumps({"version": 1, "passed": True}))
        code, _, _, _ = self.validate()
        self.assertNotEqual(code, 0)
        self.receipt_path.unlink()
        code, stdout, stderr, _ = self.gate()
        self.assertEqual(code, 0, stderr or stdout)
        changed = json.loads(self.contract_path.read_text())
        changed["budgets"]["case"]["seconds"] += 0.1
        self.write_contract(changed)
        code, _, _, _ = self.validate()
        self.assertNotEqual(code, 0, "deadlines are part of the gate binding")


if __name__ == "__main__":
    unittest.main()
