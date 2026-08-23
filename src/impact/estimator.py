"""
Phase 5 — Impact estimation.

Answer "how bad is it?" from the metrics: count the failed requests during the
incident window and estimate affected users. Deliberately simple and clearly
labeled as an estimate — bisect never presents a modeled number as an exact count.

Method (all deterministic, inspectable):
  - The incident window runs from when the alert fired to the last broken metric
    row (or the rollback, whichever comes first).
  - affected_requests = sum of `errors` across the window's metric rows.
  - affected_users = affected_requests / avg_requests_per_user, a stated
    assumption (default 1.8 requests/user) — not a measured value.

The assumption is explicit in the estimate's `note` so nobody mistakes it for
telemetry. When real user-session data is available (Phase 9), this is where it
plugs in; the interface (an ImpactEstimate on the Incident) does not change.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.core.incident import Incident, ImpactEstimate

GEN = Path(__file__).resolve().parents[2] / "data" / "generated"
METRICS = GEN / "metrics.jsonl"

# Stated assumption, not a measurement. Kept visible so the estimate is honest.
DEFAULT_REQUESTS_PER_USER = 1.8


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def estimate_impact(incident: Incident, requests_per_user: float = DEFAULT_REQUESTS_PER_USER,
                    metrics_path: Path = METRICS) -> ImpactEstimate | None:
    """Compute impact for the window from alert-fire to the last elevated row."""
    rows = _load(metrics_path)
    if not rows:
        return None

    fired = incident.alert.fired_at
    threshold = incident.alert.threshold

    # window = rows from the alert onward that are still elevated (contiguous).
    window_rows: list[dict] = []
    started = False
    for r in rows:
        at = datetime.fromisoformat(r["at"])
        if at < fired:
            continue
        started = True
        if r["error_rate"] >= threshold or (window_rows and r["errors"] > 0):
            window_rows.append(r)
        elif started and window_rows and r["error_rate"] < threshold:
            # recovered — window closed
            break

    if not window_rows:
        window_rows = [r for r in rows if datetime.fromisoformat(r["at"]) >= fired]

    affected_requests = sum(r["errors"] for r in window_rows)
    total_requests = sum(r["requests"] for r in window_rows)
    affected_users = int(round(affected_requests / requests_per_user)) if requests_per_user else 0

    start = datetime.fromisoformat(window_rows[0]["at"])
    end = datetime.fromisoformat(window_rows[-1]["at"])
    elapsed = (end - start).total_seconds()
    # Each metric row represents one second of traffic. If the simulator wrote
    # rows faster than real time (compressed timestamps), fall back to counting
    # rows rather than wall-clock, so the window reflects intended duration.
    window_seconds = max(len(window_rows), int(round(elapsed)) + 1)

    pct = (affected_requests / total_requests) if total_requests else 0.0
    est = ImpactEstimate(
        affected_requests=affected_requests,
        affected_users_estimate=affected_users,
        window_seconds=window_seconds,
        note=(f"Estimate: {affected_requests} failed of {total_requests} requests "
              f"({pct:.0%}) over ~{window_seconds}s. Users approximated at "
              f"{requests_per_user} req/user (stated assumption, not measured)."),
    )
    return est


def add_impact(incident: Incident, **kwargs) -> Incident:
    """Attach the impact estimate to the incident and log it."""
    est = estimate_impact(incident, **kwargs)
    if est:
        incident.impact = est
        incident.log("impact",
                     f"~{est.affected_requests} failed requests, "
                     f"~{est.affected_users_estimate} users affected over {est.window_seconds}s",
                     evidence={"affected_requests": est.affected_requests,
                               "affected_users": est.affected_users_estimate,
                               "window_seconds": est.window_seconds})
    return incident


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from src.detection.detector import detect

    inc = detect()
    if inc is None:
        print("No incident in current data. Run the simulator first.")
        sys.exit(0)
    inc = add_impact(inc)
    if inc.impact:
        print("Impact estimate:")
        print(f"  affected requests : {inc.impact.affected_requests}")
        print(f"  affected users    : ~{inc.impact.affected_users_estimate} (estimate)")
        print(f"  window            : {inc.impact.window_seconds}s")
        print(f"  note              : {inc.impact.note}")
