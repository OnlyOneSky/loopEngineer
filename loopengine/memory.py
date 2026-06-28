"""Memory — durable run state outside any single conversation.

The loop's spine: every iteration's verdicts and last_error are flushed to disk
so a run is auditable and resumable. The agent forgets; the file does not.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Caps


@dataclass
class Memory:
    path: Path
    run_dir: Path
    state: dict = field(default_factory=dict)

    @classmethod
    def create(cls, runs_dir: Path, run_id: str, spec_path: str,
               repo: str, branch: str, caps: Caps) -> "Memory":
        run_dir = Path(runs_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "run_id": run_id,
            "spec_path": spec_path,
            "repo": repo,
            "branch": branch,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "caps": {"max_iterations": caps.max_iterations,
                     "max_wall_seconds": caps.max_wall_seconds},
            "status": "running",
            "iterations": [],
            "result": None,
        }
        m = cls(path=run_dir / "state.json", run_dir=run_dir, state=state)
        m._flush()
        return m

    def add_iteration(self, n: int, elapsed_s: int) -> dict:
        record = {"n": n, "elapsed_s": elapsed_s, "enforce": None,
                  "tests": None, "qa": None, "security": None, "last_error": None}
        self.state["iterations"].append(record)
        self._flush()
        return record

    def update_iteration(self, **fields) -> None:
        self.state["iterations"][-1].update(fields)
        self._flush()

    def finish(self, status: str, outcome: str, artifact: str | None = None) -> None:
        self.state["status"] = status
        self.state["result"] = {"outcome": outcome, "artifact": artifact}
        self._flush()

    def _flush(self) -> None:
        self.path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False))
