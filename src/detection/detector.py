"""Detection: read metrics, fire an alert on sustained threshold breach, create an Incident."""
from __future__ import annotations
import json, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.core.incident import Alert, Incident, Severity, new_incident

METRICS = Path(__file__).resolve().parents[2] / "data" / "generated" / "metrics.jsonl"
ERROR_RATE_THRESHOLD = 0.20
SUSTAINED_SECONDS = 3

def _load(path=METRICS):
    if not path.exists(): return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

def _severity(er):
    if er >= 0.50: return Severity.SEV1
    if er >= 0.30: return Severity.SEV2
    return Severity.SEV3

def detect(path=METRICS):
    rows = _load(path)
    if not rows: return None
    streak = 0
    for row in rows:
        streak = streak + 1 if row["error_rate"] >= ERROR_RATE_THRESHOLD else 0
        if streak >= SUSTAINED_SECONDS:
            alert = Alert(fired_at=datetime.fromisoformat(row["at"]),
                          kind="error_rate_spike", service=row["service"],
                          detail=f"error rate sustained above {ERROR_RATE_THRESHOLD:.0%} for {SUSTAINED_SECONDS}s",
                          metric_value=row["error_rate"], threshold=ERROR_RATE_THRESHOLD)
            inc = new_incident(alert)
            inc.severity = _severity(row["error_rate"])
            return inc
    return None

if __name__ == "__main__":
    inc = detect()
    if inc is None:
        print("No incident detected — service stayed healthy.")
    else:
        print(f"ALERT -> Incident {inc.id} created")
        print(f"  service:  {inc.alert.service}")
        print(f"  severity: {inc.severity.value}")
        print(f"  detail:   {inc.alert.detail}")
        print(f"  error rate at fire: {inc.alert.metric_value:.0%}")
        print("  timeline:")
        for ev in inc.timeline:
            print(f"    [{ev.stage}] {ev.message}")
