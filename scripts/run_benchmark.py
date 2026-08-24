"""Benchmark: measure diagnosis accuracy across EASY and HARD scenarios.

The point: on the easy scenario a deploy marker hands the answer to the
deterministic baseline. On the hard scenarios a benign 'decoy' commit touches the
same file (and is deployed closest, or there's no deploy marker at all), so
timing + blast-radius get fooled. Only reading the diff finds the real culprit.

Deterministic accuracy should DROP on the hard set. Claude (with a key) should
hold. That gap is the headline result.

  python3 scripts/run_benchmark.py
"""
from __future__ import annotations
import json, os, sys, time
from dotenv import load_dotenv
load_dotenv()
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.simulator.simulator import run_scenario
from src.detection.detector import detect
from src.diagnosis.agent import rank_deterministic, rank_with_claude


def scenarios(gt):
    bad, decoy = gt["bad_commit_sha"], gt["decoy_commit_sha"]
    return [
        {  # EASY: only the bad commit deploys, right before the spike
            "name": "easy: clean deploy marker",
            "bad_sha": bad, "record_deploys": True,
            "deploys": [{"sha": bad, "author": "devuser",
                         "message": "refactor: simplify checkout flow",
                         "offset_s": -8, "breaks": True}],
        },
        {  # HARD: benign decoy deploys CLOSEST to the spike; bad deployed earlier
            "name": "hard: decoy deployed closest",
            "bad_sha": bad, "record_deploys": True,
            "deploys": [
                {"sha": bad, "author": "devuser",
                 "message": "refactor: simplify checkout flow",
                 "offset_s": -70, "breaks": True},
                {"sha": decoy, "author": "arjun",
                 "message": "style: add a clarifying comment to checkout",
                 "offset_s": -4, "breaks": False},
            ],
        },
        {  # HARD: no deploy marker at all — timing signal gone entirely
            "name": "hard: no deploy marker",
            "bad_sha": bad, "record_deploys": False, "deploys": [],
        },
    ]


def score(suspects, bad_sha):
    ranked = [s.sha for s in suspects]
    return (ranked[:1] == [bad_sha], bad_sha in ranked[:3])


def run_one(scn):
    bad_sha = run_scenario(scn)
    inc = detect()
    if inc is None:
        return None

    t0 = time.time(); det = rank_deterministic(inc); det_ms = (time.time()-t0)*1000
    d1, d3 = score(det, bad_sha)

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if has_key:
        t0 = time.time(); cla = rank_with_claude(inc); cla_ms = (time.time()-t0)*1000
        c1, c3 = score(cla, bad_sha)
    else:
        c1 = c3 = None; cla_ms = 0.0

    return {"name": scn["name"], "d1": d1, "d3": d3, "det_ms": det_ms,
            "c1": c1, "c3": c3, "cla_ms": cla_ms, "has_key": has_key,
            "det_top": det[0].sha[:8], "det_top_reason": det[0].reasoning}


def main():
    gt = json.loads((ROOT / "data" / "toy_repo" / "GROUND_TRUTH.json").read_text())
    scns = scenarios(gt)
    print(f"Running {len(scns)} scenarios (bad={gt['bad_commit_sha'][:8]}, "
          f"decoy={gt['decoy_commit_sha'][:8]})\n")

    results = [run_one(s) for s in scns]
    results = [r for r in results if r]

    print("PER-SCENARIO")
    print("-" * 72)
    for r in results:
        det_mark = "OK " if r["d1"] else "MISS"
        print(f"  [{det_mark}] {r['name']}")
        print(f"         deterministic top-1 = {r['det_top']}  ({r['det_top_reason']})")
    print()

    n = len(results)
    d1 = sum(r["d1"] for r in results) / n
    d3 = sum(r["d3"] for r in results) / n
    det_ms = sum(r["det_ms"] for r in results) / n

    print("SUMMARY")
    print("-" * 54)
    print(f"{'mode':<24}{'top-1':>8}{'top-3':>8}{'avg latency':>14}")
    print(f"{'deterministic':<24}{d1:>7.0%}{d3:>8.0%}{det_ms:>12.0f}ms")
    if results[0]["has_key"]:
        c1 = sum(r["c1"] for r in results) / n
        c3 = sum(r["c3"] for r in results) / n
        cla_ms = sum(r["cla_ms"] for r in results) / n
        print(f"{'claude (diff-reading)':<24}{c1:>7.0%}{c3:>8.0%}{cla_ms:>12.0f}ms")
    else:
        print(f"{'claude (diff-reading)':<24}{'--':>8}{'--':>8}{'  no API key':>14}")
        print("\nSet ANTHROPIC_API_KEY to run the model ranker and close the gap.")

if __name__ == "__main__":
    main()
