"""
Phase 8a — Resolution detection.

Detection in reverse: after remediation, keep reading the metric stream and mark
the incident resolved once the error rate returns to baseline and STAYS there for
a sustained window (so a single lucky second doesn't declare victory early).

Returns the resolution timestamp, or None if the service hasn't recovered yet.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.core.incident import Incident

GEN = Path(__file__).resolve().parents[2] / "data" / "generated"
METRICS = GEN / "metrics.jsonl"

BASELINE_THRESHOLD = 0.05     # error rate at/below this counts as healthy
SUSTAINED_SECONDS = 3         # must stay healthy this many consecutive rows


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def detect_resolution(incident: Incident, metrics_path: Path = METRICS) -> Optional[datetime]:
    """Scan metrics AFTER the incident started; return the time it recovered."""
    rows = _load(metrics_path)
    if not rows:
        return None

    fired = incident.alert.fired_at
    saw_breach = False
    streak = 0
    for r in rows:
        at = datetime.fromisoformat(r["at"])
        if at < fired:
            continue
        if r["error_rate"] >= incident.alert.threshold:
            saw_breach = True
            streak = 0
        elif r["error_rate"] <= BASELINE_THRESHOLD:
            streak += 1
            if saw_breach and streak >= SUSTAINED_SECONDS:
                return at
        else:
            streak = 0
    return None


def resolve_if_recovered(incident: Incident, metrics_path: Path = METRICS) -> Incident:
    """If the metrics show recovery, mark the incident resolved and log it."""
    resolved_at = detect_resolution(incident, metrics_path)
    if resolved_at:
        incident.status = incident.status.__class__.RESOLVED
        incident.resolved_at = resolved_at
        incident.log("resolution",
                     "error rate returned to baseline and held; incident resolved.",
                     evidence={"resolved_at": resolved_at.isoformat()})
    return incident


if __name__ == "__main__":
    import json as _json
    from src.simulator.simulator import Simulator
    from src.detection.detector import detect
    from src.diagnosis.agent import diagnose

    gt = _json.loads((Path(__file__).resolve().parents[2] / "data" / "toy_repo" / "GROUND_TRUTH.json").read_text())
    bad = {"sha": gt["bad_commit_sha"], "author": "devuser", "message": "refactor: simplify checkout flow"}
    # run WITH recovery so there's a resolution to detect
    Simulator(rps=50).run(healthy_secs=15, broken_secs=15, bad_commit=bad, recover_secs=12)

    inc = detect()
    inc = diagnose(inc, use_claude=False)
    inc = resolve_if_recovered(inc)
    print(f"status: {inc.status.value}")
    print(f"resolved_at: {inc.resolved_at}")
