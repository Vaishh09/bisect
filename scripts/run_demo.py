"""One-command demo (Phases 0-3): simulate -> detect -> diagnose."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.simulator.simulator import Simulator
from src.detection.detector import detect
from src.diagnosis.agent import diagnose

def main():
    gt_path = ROOT / "data" / "toy_repo" / "GROUND_TRUTH.json"
    if not gt_path.exists():
        print("Toy repo missing. Run:  python3 scripts/make_toy_repo.py"); sys.exit(1)
    gt = json.loads(gt_path.read_text())
    bad = {"sha": gt["bad_commit_sha"], "author": "devuser", "message": "refactor: simplify checkout flow"}

    print("=" * 60); print("STEP 1 - simulate an incident"); print("=" * 60)
    Simulator(rps=50).run(healthy_secs=20, broken_secs=20, bad_commit=bad, recover_secs=10)

    print("\n" + "=" * 60); print("STEP 2 - detect it"); print("=" * 60)
    inc = detect()
    if inc is None: print("No incident detected (unexpected)."); sys.exit(1)
    print(f"Incident {inc.id}  [{inc.severity.value}]  {inc.alert.service}: {inc.alert.detail}")

    print("\n" + "=" * 60); print("STEP 3 - diagnose it"); print("=" * 60)
    inc = diagnose(inc, use_claude=True)  # uses Claude if ANTHROPIC_API_KEY set, else deterministic
    bad_sha = gt["bad_commit_sha"]
    print("Ranked suspects:")
    for s in inc.suspects:
        mark = "  <-- ground-truth bad commit" if s.sha == bad_sha else ""
        print(f"  #{s.rank}  {s.sha[:8]}  {s.author:8} conf={s.confidence:.2f}  {s.reasoning}{mark}")
    top = inc.top_suspect()
    print(f"\nTOP-1 correct: {top.sha == bad_sha}")

if __name__ == "__main__":
    main()
