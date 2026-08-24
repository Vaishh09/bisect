"""Hardened benchmark: measure diagnosis accuracy across many adversarial scenarios.

Corpus: 3 services x bug types, each run under 3 timing variants:
  - clean deploy marker (easy)
  - benign decoy deployed closest to the spike (hard)
  - no deploy marker at all (hard)

Every scenario has a known-bad commit AND same-file decoys, so ranking by timing
+ blast-radius alone is insufficient. Reading the diff is required.

Deterministic accuracy should be low on the hard variants; the LLM diff-reader
should recover them. Both rows are reported, plus the deterministic/LLM gap.

  python3 scripts/run_benchmark.py
"""
from __future__ import annotations
import json, os, sys, time, random
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv()

from src.detection.detector import detect
from src.diagnosis.agent import rank_deterministic, rank_with_claude

GEN = ROOT / "data" / "generated"
LOGS, METRICS, DEPLOYS = GEN / "logs.jsonl", GEN / "metrics.jsonl", GEN / "deploys.jsonl"

STACKS = {
    "checkout": ('Traceback (most recent call last):\n'
                 '  File "checkout/service.py", line 8, in process_checkout\n'
                 '    return {"user_id": user.id, "session": user.session.id, "total": total}\n'
                 "AttributeError: 'NoneType' object has no attribute 'id'"),
    "payments": ('Traceback (most recent call last):\n'
                 '  File "payments/service.py", line 8, in charge\n'
                 '    converted = amount_cents / rate\n'
                 "ZeroDivisionError: division by zero"),
    "auth":     ('Traceback (most recent call last):\n'
                 '  File "auth/service.py", line 8, in verify\n'
                 '    if token["exp"] < time.time():\n'
                 "KeyError: 'exp'"),
}


def _now(): return datetime.now(timezone.utc)
def _iso(dt): return dt.isoformat()

def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

def generate(service, deploys, rng):
    """Write logs/metrics/deploys for one scenario. deploys = list of dicts with
    sha/author/message/offset_s/breaks. Breakage begins at the earliest 'breaks' deploy."""
    endpoint = {"checkout": "/api/checkout", "payments": "/api/charge", "auth": "/api/verify"}[service]
    stack = STACKS[service]
    metrics, logs, dep_rows = [], [], []

    base = _now()
    # 20s healthy, 20s broken (per-second rows)
    for sec in range(40):
        broken = sec >= 20
        er = 0.55 if broken else 0.015
        errors = 0
        at = _iso(base + timedelta(seconds=sec))
        for _ in range(50):
            is_err = rng.random() < er
            log = {"at": at, "service": service, "endpoint": endpoint,
                   "status": 500 if is_err else 200, "latency_ms": rng.randint(40, 900)}
            if is_err:
                errors += 1; log["error"] = stack
            logs.append(log)
        metrics.append({"at": at, "service": service, "requests": 50, "errors": errors,
                        "error_rate": round(errors/50, 4), "avg_latency_ms": 120.0})

    spike = base + timedelta(seconds=20)
    for d in deploys:
        dep_rows.append({"at": _iso(spike + timedelta(seconds=d["offset_s"])),
                         "sha": d["sha"], "author": d.get("author"),
                         "message": d.get("message", ""), "service": service})

    _write(METRICS, metrics); _write(LOGS, logs); _write(DEPLOYS, dep_rows)


def score(suspects, bad_sha):
    r = [s.sha for s in suspects]
    return (r[:1] == [bad_sha], bad_sha in r[:3])


def build_scenarios(gt):
    bugs = gt["bugs"]
    scns = []
    for svc, b in bugs.items():
        bad, decoys = b["sha"], b["decoys"]
        dmsg = "refactor: simplify " + svc
        # easy: clean deploy marker
        scns.append({"name": f"{svc}: clean deploy", "service": svc, "bad": bad,
                     "deploys": [{"sha": bad, "author": "devuser", "message": dmsg,
                                  "offset_s": -8, "breaks": True}]})
        # hard: decoy deployed closest
        scns.append({"name": f"{svc}: decoy closest", "service": svc, "bad": bad,
                     "deploys": [
                         {"sha": bad, "author": "devuser", "message": dmsg, "offset_s": -70, "breaks": True},
                         {"sha": decoys[0], "author": "arjun", "message": "style: comment", "offset_s": -4, "breaks": False},
                     ]})
        # hard: no deploy marker
        scns.append({"name": f"{svc}: no deploy marker", "service": svc, "bad": bad,
                     "deploys": []})
    return scns


def run_one(scn, rng):
    generate(scn["service"], scn["deploys"], rng)
    inc = detect()
    if inc is None:
        return None
    bad = scn["bad"]
    t0 = time.time(); det = rank_deterministic(inc); det_ms = (time.time()-t0)*1000
    d1, d3 = score(det, bad)
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if has_key:
        t0 = time.time(); cla = rank_with_claude(inc); cla_ms = (time.time()-t0)*1000
        c1, c3 = score(cla, bad)
    else:
        c1 = c3 = None; cla_ms = 0.0
    return {"name": scn["name"], "d1": d1, "d3": d3, "det_ms": det_ms,
            "c1": c1, "c3": c3, "cla_ms": cla_ms, "has_key": has_key,
            "det_top": det[0].sha[:8]}


def main():
    gt = json.loads((ROOT / "data" / "toy_repo" / "GROUND_TRUTH.json").read_text())
    rng = random.Random(42)
    scns = build_scenarios(gt)
    print(f"Running {len(scns)} scenarios across {len(gt['bugs'])} services...\n")

    results = [r for r in (run_one(s, rng) for s in scns) if r]

    print("PER-SCENARIO (deterministic)")
    print("-" * 60)
    for r in results:
        print(f"  [{'OK ' if r['d1'] else 'MISS'}] {r['name']}")
    print()

    n = len(results)
    d1 = sum(r["d1"] for r in results)/n
    d3 = sum(r["d3"] for r in results)/n
    det_ms = sum(r["det_ms"] for r in results)/n
    print("SUMMARY")
    print("-" * 58)
    print(f"{'mode':<26}{'top-1':>8}{'top-3':>8}{'avg latency':>14}")
    print(f"{'deterministic':<26}{d1:>7.0%}{d3:>8.0%}{det_ms:>12.0f}ms")
    if results[0]["has_key"]:
        c1 = sum(r['c1'] for r in results)/n
        c3 = sum(r['c3'] for r in results)/n
        cla_ms = sum(r['cla_ms'] for r in results)/n
        print(f"{'claude (diff-reading)':<26}{c1:>7.0%}{c3:>8.0%}{cla_ms/1000:>11.1f}s")
        print(f"\ngap: deterministic {d1:.0%} -> claude {c1:.0%} top-1 on {n} scenarios")
    else:
        print(f"{'claude (diff-reading)':<26}{'--':>8}{'--':>8}{'  no API key':>14}")

if __name__ == "__main__":
    main()
