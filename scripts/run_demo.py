"""One-command demo — the full bisect loop (Phases 0-8):
simulate -> detect -> diagnose -> runbook -> impact -> brief
-> propose remediation -> human approves -> resolve -> postmortem."""
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
from src.remediation.actions import propose_actions, approve
from src.postmortem.resolution import resolve_if_recovered
from src.postmortem.generator import generate_postmortem

def main():
    gt_path = ROOT / "data" / "toy_repo" / "GROUND_TRUTH.json"
    if not gt_path.exists():
        print("Toy repo missing. Run:  python3 scripts/make_toy_repo.py"); sys.exit(1)
    gt = json.loads(gt_path.read_text())
    bad = {"sha": gt["bad_commit_sha"], "author": "devuser", "message": "refactor: simplify checkout flow"}

    print("STEP 1 - simulate an incident\n" + "-"*44)
    sim = Simulator(rps=50)
    sim.run(healthy_secs=20, broken_secs=20, bad_commit=bad, recover_secs=0)

    print("\nSTEP 2 - detect\n" + "-"*44)
    inc = detect()
    if inc is None: print("No incident detected."); sys.exit(1)
    print(f"Incident {inc.id} [{inc.severity.value}] {inc.alert.service}")

    print("\nSTEP 3-5 - diagnose, runbook, impact\n" + "-"*44)
    inc = diagnose(inc, use_claude=True)
    match_runbook(inc); add_impact(inc)
    print(f"Cause: {inc.top_suspect().sha[:8]} | Runbook: {inc.matched_runbook} | "
          f"Impact: ~{inc.impact.affected_requests} reqs")

    print("\nSTEP 6 - incident brief\n" + "-"*44)
    notify(inc)

    print("\nSTEP 7 - remediation (human-approved)\n" + "-"*44)
    actions = propose_actions(inc)
    print("Proposed (pending):", ", ".join(a.label for a in actions))
    print("Simulating an authorized human approving the rollback...")
    approve(actions[0], "vaish", inc,
            rollback_fn=lambda: sim.deploy_good_build(gt["all_commits"]["init_checkout"]))
    for _ in range(12): sim._tick()
    print(f"Rollback: {actions[0].status.value}")

    print("\nSTEP 8 - resolution + postmortem\n" + "-"*44)
    inc = resolve_if_recovered(inc)
    print(f"Status: {inc.status.value}")
    md = generate_postmortem(inc, use_llm=True)
    out = ROOT / "data" / "generated" / "postmortems" / f"{inc.id}.md"
    print(f"Postmortem written to: {out.relative_to(ROOT)}")
    print("\n" + "="*44 + "\nFull loop complete. Postmortem preview:\n" + "="*44)
    print("\n".join(md.splitlines()[:8]))

if __name__ == "__main__":
    main()
