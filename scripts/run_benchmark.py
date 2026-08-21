"""
Benchmark: measure diagnosis accuracy against ground truth.

Runs the diagnosis agent on the current generated incident and checks whether it
ranked the known bad commit #1 (top-1) and in the top 3 (top-3). Reports both the
deterministic baseline and (if a key is set) the Claude ranker, so you can SHOW
the gap between service-matching and diff-reading.

  python3 scripts/run_benchmark.py

This is the seed of the real benchmark. To make it meaningful (Krishna-style),
add HARDER scenarios where the deterministic baseline fails and diff-reading is
required — e.g. two deploys close in time, or a benign commit touching the same
file with no deploy marker. Each scenario carries its own known bad commit.
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.simulator.simulator import Simulator
from src.detection.detector import detect
from src.diagnosis.agent import rank_deterministic, rank_with_claude


def score(suspects, bad_sha):
    ranked = [s.sha for s in suspects]
    top1 = ranked[:1] == [bad_sha]
    top3 = bad_sha in ranked[:3]
    return top1, top3


def run_one(bad, label):
    Simulator(rps=50).run(healthy_secs=20, broken_secs=20, bad_commit=bad, recover_secs=0)
    inc = detect()
    bad_sha = bad["sha"]

    t0 = time.time()
    det = rank_deterministic(inc)
    det_ms = (time.time() - t0) * 1000
    d1, d3 = score(det, bad_sha)

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if has_key:
        t0 = time.time()
        cla = rank_with_claude(inc)
        cla_ms = (time.time() - t0) * 1000
        c1, c3 = score(cla, bad_sha)
    else:
        c1 = c3 = None
        cla_ms = 0.0

    return {"label": label, "det_top1": d1, "det_top3": d3, "det_ms": det_ms,
            "claude_top1": c1, "claude_top3": c3, "claude_ms": cla_ms, "has_key": has_key}


def main():
    gt = json.loads((ROOT / "data" / "toy_repo" / "GROUND_TRUTH.json").read_text())
    scenarios = [
        {"sha": gt["bad_commit_sha"], "author": "devuser",
         "message": "refactor: simplify checkout flow", "_label": "checkout-null-session"},
    ]

    print("Running benchmark on", len(scenarios), "scenario(s)...\n")
    results = [run_one({k: v for k, v in s.items() if not k.startswith("_")}, s["_label"])
               for s in scenarios]

    n = len(results)
    det_t1 = sum(r["det_top1"] for r in results) / n
    det_t3 = sum(r["det_top3"] for r in results) / n
    det_ms = sum(r["det_ms"] for r in results) / n

    print(f"{'mode':<24}{'top-1':>8}{'top-3':>8}{'avg latency':>14}")
    print("-" * 54)
    print(f"{'deterministic':<24}{det_t1:>7.0%}{det_t3:>8.0%}{det_ms:>12.0f}ms")

    if results[0]["has_key"]:
        c_t1 = sum(r["claude_top1"] for r in results) / n
        c_t3 = sum(r["claude_top3"] for r in results) / n
        c_ms = sum(r["claude_ms"] for r in results) / n
        print(f"{'claude (diff-reading)':<24}{c_t1:>7.0%}{c_t3:>8.0%}{c_ms:>12.0f}ms")
    else:
        print(f"{'claude (diff-reading)':<24}{'--':>8}{'--':>8}{'  no API key':>14}")
        print("\nSet ANTHROPIC_API_KEY to run the model ranker and compare.")


if __name__ == "__main__":
    main()
