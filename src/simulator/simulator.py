"""
The simulator: a fake 'checkout service' that emits a stream of request logs and
per-second metrics to disk.

- Normal mode: ~1-2% baseline errors, low latency, mostly 200s.
- After deploy_bad_commit(): error rate jumps, latency spikes, 500s pour in with a
  real-looking stack trace referencing the code the bad commit broke (user.session).

Why write to disk (jsonl): the detector and diagnosis agent read these files exactly
the way a real system reads Datadog/Loki. It's inspectable (just open the file), works
across separate processes, and keeps the Incident object as the real interface.

Deploy markers are logged with timestamps so Phase 3 can line up 'spike started at T'
against 'deploy landed at T-epsilon' — the single strongest diagnosis signal.

Run standalone to generate a full incident dataset:
    python3 src/simulator/simulator.py
"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "generated"
LOGS = DATA / "logs.jsonl"
METRICS = DATA / "metrics.jsonl"
DEPLOYS = DATA / "deploys.jsonl"

SERVICE = "checkout"
ENDPOINT = "/api/checkout"

HEALTHY_ERROR_RATE = 0.015
BROKEN_ERROR_RATE = 0.55
HEALTHY_LATENCY_MS = (40, 120)
BROKEN_LATENCY_MS = (300, 900)

# A realistic stack trace matching what the planted bad commit actually breaks.
BROKEN_STACK = (
    "Traceback (most recent call last):\n"
    '  File "checkout/service.py", line 12, in process_checkout\n'
    '    return {"user_id": user.id, "session": user.session.id, "total": total}\n'
    "AttributeError: 'NoneType' object has no attribute 'id'"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(obj) + "\n")


class Simulator:
    def __init__(self, rps: int = 50, seed: int | None = 42):
        self.rps = rps
        self.broken = False
        self.rng = random.Random(seed)

    def reset(self) -> None:
        for p in (LOGS, METRICS, DEPLOYS):
            if p.exists():
                p.unlink()
        DATA.mkdir(parents=True, exist_ok=True)

    def deploy_bad_commit(self, sha: str, author: str, message: str) -> None:
        """Record a deploy marker AND flip the service into the broken state."""
        marker = {
            "at": _now_iso(),
            "sha": sha,
            "author": author,
            "message": message,
            "service": SERVICE,
        }
        _append(DEPLOYS, marker)
        self.broken = True

    def deploy_good_build(self, sha: str) -> None:
        """Rollback: redeploy last known-good, service recovers."""
        _append(DEPLOYS, {"at": _now_iso(), "sha": sha, "message": "rollback to last good build",
                          "service": SERVICE, "rollback": True})
        self.broken = False

    def _tick(self) -> dict:
        """Simulate one second of traffic; emit logs + one metrics row."""
        error_rate = BROKEN_ERROR_RATE if self.broken else HEALTHY_ERROR_RATE
        lat_lo, lat_hi = BROKEN_LATENCY_MS if self.broken else HEALTHY_LATENCY_MS

        errors = 0
        for _ in range(self.rps):
            is_error = self.rng.random() < error_rate
            latency = self.rng.randint(lat_lo, lat_hi)
            status = 500 if is_error else 200
            if is_error:
                errors += 1
            log = {
                "at": _now_iso(),
                "service": SERVICE,
                "endpoint": ENDPOINT,
                "status": status,
                "latency_ms": latency,
            }
            if is_error:
                log["error"] = BROKEN_STACK
            _append(LOGS, log)

        row = {
            "at": _now_iso(),
            "service": SERVICE,
            "requests": self.rps,
            "errors": errors,
            "error_rate": round(errors / self.rps, 4),
            "avg_latency_ms": round(self.rng.uniform(lat_lo, lat_hi), 1),
        }
        _append(METRICS, row)
        return row

    def run(self, healthy_secs: int, broken_secs: int,
            bad_commit: dict, recover_secs: int = 0, good_sha: str = "129e553") -> None:
        """Generate a full incident: healthy -> deploy bad -> broken -> (optional recover)."""
        self.reset()
        print(f"[sim] {healthy_secs}s healthy traffic...")
        for _ in range(healthy_secs):
            r = self._tick()
        print(f"      last healthy error_rate={r['error_rate']:.1%}")

        print(f"[sim] deploying bad commit {bad_commit['sha'][:8]} by {bad_commit['author']}")
        self.deploy_bad_commit(**bad_commit)

        print(f"[sim] {broken_secs}s broken traffic...")
        for _ in range(broken_secs):
            r = self._tick()
        print(f"      broken error_rate={r['error_rate']:.1%}")

        if recover_secs:
            print(f"[sim] rolling back to {good_sha}")
            self.deploy_good_build(good_sha)
            for _ in range(recover_secs):
                r = self._tick()
            print(f"      recovered error_rate={r['error_rate']:.1%}")

        print(f"[sim] done. logs={LOGS.name} metrics={METRICS.name} deploys={DEPLOYS.name}")


if __name__ == "__main__":
    import json as _json
    # Load the real bad commit sha from the toy repo's ground truth.
    gt_path = Path(__file__).resolve().parents[2] / "data" / "toy_repo" / "GROUND_TRUTH.json"
    gt = _json.loads(gt_path.read_text())
    bad = {
        "sha": gt["bad_commit_sha"],
        "author": "vaish",
        "message": "refactor: simplify checkout flow",
    }
    Simulator(rps=50).run(healthy_secs=20, broken_secs=20, bad_commit=bad, recover_secs=10)


# ----------------------------- scenario support (Phase 3+) -----------------------------
# Added for the hard benchmark scenarios. Lets a scenario record multiple deploy
# markers (a decoy deployed closest to the spike) or NO deploy marker at all,
# while a chosen commit is the one that actually breaks the service.

from datetime import timedelta

def run_scenario(scenario: dict, rps: int = 50, seed: int = 42):
    """Generate an incident from a scenario spec.

    scenario = {
      "name": str,
      "bad_sha": str,                 # the commit that actually breaks things
      "deploys": [                    # markers to record, with offsets in seconds
        {"sha": ..., "author": ..., "message": ..., "offset_s": -80, "breaks": True},
        {"sha": ..., "author": ..., "message": ..., "offset_s": -5,  "breaks": False},
      ],
      "record_deploys": True,         # if False, no deploy markers written at all
    }
    Offsets are relative to the moment breakage begins (0). Negative = before.
    """
    sim = Simulator(rps=rps, seed=seed)
    sim.reset()

    # healthy warmup
    for _ in range(20):
        sim._tick()

    record = scenario.get("record_deploys", True)
    now = datetime.now(timezone.utc)

    # write deploy markers (unless suppressed) at their offset times
    if record:
        for d in scenario.get("deploys", []):
            at = (now + timedelta(seconds=d["offset_s"])).isoformat()
            _append(DEPLOYS, {"at": at, "sha": d["sha"], "author": d.get("author"),
                              "message": d.get("message", ""), "service": SERVICE})

    # flip broken and emit the incident traffic
    sim.broken = True
    for _ in range(20):
        sim._tick()

    return scenario["bad_sha"]
