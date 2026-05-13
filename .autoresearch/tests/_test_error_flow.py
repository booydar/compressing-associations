"""Smoke tests for new error-flow helpers. Run via python3.11 on gpu8."""
import sys, os, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("AUTORESEARCH_STREAM_ID", "0")

import autoresearch as A
from planner import _summarize_run_error

tmp = pathlib.Path(tempfile.mkdtemp())

# --- _read_log_tail: traceback anchoring + ANSI strip ---
log = tmp / "train.log"
log.write_text(
    "loading model...\n"
    "step 1\rstep 2\rstep 3 done\n"
    "\x1b[31msome ansi colored line\x1b[0m\n"
    "Traceback (most recent call last):\n"
    "  File \"foo.py\", line 10, in <module>\n"
    "    raise ValueError('num_heads * head_dim (32) must equal expand * hidden_size (256)')\n"
    "ValueError: num_heads * head_dim (32) must equal expand * hidden_size (256)\n"
)
tail = A._read_log_tail(log)
assert "Traceback" in tail
assert "ansi colored" not in tail
assert "\x1b[" not in tail
assert "num_heads * head_dim (32)" in tail
print("[PASS] _read_log_tail anchors on Traceback, strips ANSI, drops pre-traceback noise")

# tqdm \r collapse without traceback
log2 = tmp / "prog.log"
log2.write_text("epoch 1\rstep 50\rstep 100/100\n")
out = A._read_log_tail(log2)
assert "step 100/100" in out and "step 50" not in out
print("[PASS] _read_log_tail collapses tqdm \\r progress")

# truncation
log3 = tmp / "big.log"
log3.write_text("x" * 20000 + "\nTraceback (most recent call last):\nfinal: boom\n")
out = A._read_log_tail(log3, max_chars=200)
assert len(out) <= 260 and "boom" in out
print("[PASS] _read_log_tail truncates to tail")

# --- _summarize_run_error (planner) ---
err = "exit 1\n" + "noise\n" * 100 + "Traceback (most recent call last):\n  ...\nValueError: bad shape\n"
s = _summarize_run_error(err, max_chars=300)
assert s.startswith("Traceback") and "ValueError: bad shape" in s
print("[PASS] planner._summarize_run_error anchors on Traceback")

# --- _last_failed_run_error ---
A.STREAM_ID = "0"
mem = {"experiments": [
    {"stream_id": "0", "status": "failed", "run_error": "old failure"},
    {"stream_id": "0", "status": "completed", "run_error": None, "em_score": 0.5},
]}
assert A._last_failed_run_error(mem) is None
mem2 = {"experiments": [
    {"stream_id": "0", "status": "failed", "run_error": "X"},
    {"stream_id": "0", "status": "failed", "run_error": "latest traceback Y"},
]}
assert A._last_failed_run_error(mem2) == "latest traceback Y"
mem3 = {"experiments": [
    {"stream_id": "1", "status": "failed", "run_error": "other stream"},
]}
assert A._last_failed_run_error(mem3) is None
print("[PASS] _last_failed_run_error: latest failed, stream-scoped, reset by success")

# --- live tee capture + non-zero exit propagates tail ---
import subprocess, io
fake_script = tmp / "fake_train.sh"
fake_script.write_text(
    "#!/bin/bash\n"
    "echo loading model\n"
    "printf 'step 1\\rstep 2\\rstep 3 done\\n'\n"
    "echo 'Traceback (most recent call last):'\n"
    "echo '  File \"x.py\", line 1, in <module>'\n"
    "echo 'ValueError: num_heads * head_dim (32) must equal expand * hidden_size (256)'\n"
    "exit 1\n"
)
fake_script.chmod(0o755)

# Simulate the new run_experiment body inline so we don't depend on env vars
log_path = tmp / "iter_fake" / "train.log"
log_path.parent.mkdir(parents=True, exist_ok=True)
proc = subprocess.Popen(
    ["bash", str(fake_script)],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    bufsize=1, text=True,
)
captured_stdout = io.StringIO()
with open(log_path, "w") as logf:
    for line in proc.stdout:
        captured_stdout.write(line)
        logf.write(line)
rc = proc.wait(timeout=10)
assert rc == 1
assert "loading model" in captured_stdout.getvalue(), "live stdout should be preserved"
tail = A._read_log_tail(log_path)
assert "Traceback" in tail and "num_heads * head_dim (32)" in tail
print("[PASS] tee-style capture: live stdout preserved AND log saved AND tail extracts error")

print("\nALL TESTS PASSED")
