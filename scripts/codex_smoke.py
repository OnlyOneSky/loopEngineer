"""Run ONCE on the work machine to (a) confirm `codex exec` flags work and
(b) capture a real --json event stream as a test fixture.

Usage:
    python scripts/codex_smoke.py > tests/fixtures/codex_events.jsonl
Then sanity-check the last line is the final agent message, and commit the fixture.
"""
import subprocess
import sys

PROMPT = "Reply with the single word OK. Do not edit any files."

proc = subprocess.run(
    ["codex", "exec", "--sandbox", "read-only", "--json",
     "--skip-git-repo-check", PROMPT],
    capture_output=True, text=True, timeout=300)
sys.stderr.write(f"[codex_smoke] returncode={proc.returncode}\n")
sys.stderr.write(f"[codex_smoke] stderr tail:\n{proc.stderr[-500:]}\n")
sys.stdout.write(proc.stdout)
