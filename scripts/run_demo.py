"""One-command demo (Phases 0-2): simulate an incident, then detect it."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.simulator.simulator import Simulator
from src.detection.detector import detect

def main():
    gt_path = ROOT / "data" / "toy_repo" / "GROUND_TRUTH.json"
    if not gt_path.exists():
        print("Toy repo missing. Run:  python3 scripts/make_toy_repo.py"); sys.exit(1)
    gt = json.loads(gt_path.read_text())
    bad = {"sha": gt["bad_commit_sha"], "author": "devuser", "message": "refactor: simplify checkout flow"}

    print("=" * 60); print("STEP 1 — simulate an incident"); print("=" * 60)
    Simulator(rps=50).run(healthy_secs=20, broken_secs=20, bad_commit=bad, recover_secs=10)

    print("\n" + "=" * 60); print("STEP 2 — detect it"); print("=" * 60)
    inc = detect()
    if inc is None: print("No incident detected (unexpected)."); sys.exit(1)
    print(f"Incident {inc.id}  [{inc.severity.value}]")
    print(f"  {inc.alert.service}: {inc.alert.detail}")
    print(f"  error rate at fire: {inc.alert.metric_value:.0%}")
    print(f"\n  Ground truth: bad commit = {gt['bad_commit_sha'][:8]} — diagnosis should rank this #1")
    print("\nNext: Phase 3 diagnosis agent ranks suspect commits with reasoning.")

if __name__ == "__main__":
    main()
