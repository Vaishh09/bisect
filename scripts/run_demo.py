"""One-command demo — the full bisect pipeline (Phases 0-6):
simulate -> detect -> diagnose -> runbook -> impact -> brief."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.simulator.simulator import Simulator
from src.detection.detector import detect
from src.diagnosis.agent import diagnose
from src.runbooks.retriever import match_runbook
from src.impact.estimator import add_impact
from src.slack.notifier import notify

def main():
    gt_path = ROOT / "data" / "toy_repo" / "GROUND_TRUTH.json"
    if not gt_path.exists():
        print("Toy repo missing. Run:  python3 scripts/make_toy_repo.py"); sys.exit(1)
    gt = json.loads(gt_path.read_text())
    bad = {"sha": gt["bad_commit_sha"], "author": "devuser", "message": "refactor: simplify checkout flow"}

    print("STEP 1 - simulate an incident\n" + "-"*40)
    Simulator(rps=50).run(healthy_secs=20, broken_secs=20, bad_commit=bad, recover_secs=0)

    print("\nSTEP 2 - detect\n" + "-"*40)
    inc = detect()
    if inc is None: print("No incident detected."); sys.exit(1)
    print(f"Incident {inc.id} [{inc.severity.value}] {inc.alert.service}: {inc.alert.detail}")

    print("\nSTEP 3 - diagnose\n" + "-"*40)
    inc = diagnose(inc, use_claude=True)
    print(f"Top suspect: {inc.top_suspect().sha[:8]} ({inc.top_suspect().confidence:.0%}) — {inc.top_suspect().reasoning}")

    print("\nSTEP 4 - match runbook\n" + "-"*40)
    match_runbook(inc)
    print(f"Runbook: {inc.matched_runbook}")

    print("\nSTEP 5 - estimate impact\n" + "-"*40)
    add_impact(inc)
    print(f"Impact: ~{inc.impact.affected_requests} reqs, ~{inc.impact.affected_users_estimate} users, {inc.impact.window_seconds}s")

    print("\nSTEP 6 - incident brief\n" + "-"*40)
    notify(inc)

if __name__ == "__main__":
    main()
