"""Simulator: a fake checkout service emitting logs + metrics to disk.
Healthy 200s -> deploy bad commit -> 500s + latency spike -> optional rollback."""
from __future__ import annotations
import json, random
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "generated"
LOGS, METRICS, DEPLOYS = DATA / "logs.jsonl", DATA / "metrics.jsonl", DATA / "deploys.jsonl"
SERVICE, ENDPOINT = "checkout", "/api/checkout"
HEALTHY_ERROR_RATE, BROKEN_ERROR_RATE = 0.015, 0.55
HEALTHY_LATENCY_MS, BROKEN_LATENCY_MS = (40, 120), (300, 900)
BROKEN_STACK = ('Traceback (most recent call last):\n'
    '  File "checkout/service.py", line 12, in process_checkout\n'
    '    return {"user_id": user.id, "session": user.session.id, "total": total}\n'
    "AttributeError: 'NoneType' object has no attribute 'id'")

def _now(): return datetime.now(timezone.utc).isoformat()
def _append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f: f.write(json.dumps(obj) + "\n")

class Simulator:
    def __init__(self, rps=50, seed=42):
        self.rps, self.broken, self.rng = rps, False, random.Random(seed)
    def reset(self):
        for p in (LOGS, METRICS, DEPLOYS):
            if p.exists(): p.unlink()
        DATA.mkdir(parents=True, exist_ok=True)
    def deploy_bad_commit(self, sha, author, message):
        _append(DEPLOYS, {"at": _now(), "sha": sha, "author": author,
                          "message": message, "service": SERVICE})
        self.broken = True
    def deploy_good_build(self, sha):
        _append(DEPLOYS, {"at": _now(), "sha": sha, "message": "rollback to last good build",
                          "service": SERVICE, "rollback": True})
        self.broken = False
    def _tick(self):
        er = BROKEN_ERROR_RATE if self.broken else HEALTHY_ERROR_RATE
        lo, hi = BROKEN_LATENCY_MS if self.broken else HEALTHY_LATENCY_MS
        errors = 0
        for _ in range(self.rps):
            is_err = self.rng.random() < er
            log = {"at": _now(), "service": SERVICE, "endpoint": ENDPOINT,
                   "status": 500 if is_err else 200, "latency_ms": self.rng.randint(lo, hi)}
            if is_err:
                errors += 1
                log["error"] = BROKEN_STACK
            _append(LOGS, log)
        row = {"at": _now(), "service": SERVICE, "requests": self.rps, "errors": errors,
               "error_rate": round(errors / self.rps, 4),
               "avg_latency_ms": round(self.rng.uniform(lo, hi), 1)}
        _append(METRICS, row)
        return row
    def run(self, healthy_secs, broken_secs, bad_commit, recover_secs=0, good_sha="129e553"):
        self.reset()
        print(f"[sim] {healthy_secs}s healthy...")
        for _ in range(healthy_secs): r = self._tick()
        print(f"      healthy error_rate={r['error_rate']:.1%}")
        print(f"[sim] deploying bad commit {bad_commit['sha'][:8]}")
        self.deploy_bad_commit(**bad_commit)
        print(f"[sim] {broken_secs}s broken...")
        for _ in range(broken_secs): r = self._tick()
        print(f"      broken error_rate={r['error_rate']:.1%}")
        if recover_secs:
            print(f"[sim] rolling back to {good_sha}")
            self.deploy_good_build(good_sha)
            for _ in range(recover_secs): r = self._tick()
            print(f"      recovered error_rate={r['error_rate']:.1%}")
        print("[sim] done.")

if __name__ == "__main__":
    gt = json.loads((Path(__file__).resolve().parents[2] / "data" / "toy_repo" / "GROUND_TRUTH.json").read_text())
    bad = {"sha": gt["bad_commit_sha"], "author": "devuser", "message": "refactor: simplify checkout flow"}
    Simulator(rps=50).run(healthy_secs=20, broken_secs=20, bad_commit=bad, recover_secs=10)
