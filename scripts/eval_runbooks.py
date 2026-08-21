"""Phase 4 eval: runbook retrieval accuracy across known failure types.

  python3 scripts/eval_runbooks.py

Verifies that each seeded failure signature retrieves its intended runbook. This
is the roadmap's 'verify by asking known failure types and checking you get the
right runbook back'.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.runbooks.retriever import TfidfRetriever

# (query, expected runbook id) — realistic error signatures, not the runbook text
PROBES = [
    ("AttributeError 'NoneType' object has no attribute 'id' checkout/service.py", "null-session-checkout"),
    ("TimeoutError QueuePool limit reached could not acquire connection", "db-connection-pool"),
    ("p99 latency spike waiting on downstream payment API timeout", "high-latency-dependency"),
    ("container OOMKilled memory climbs pods restarting", "out-of-memory"),
    ("HTTP 429 Too Many Requests rate limit exceeded upstream", "upstream-rate-limit"),
    ("No space left on device cannot write logs", "disk-full"),
    ("SSL certificate has expired TLS handshake failed", "tls-cert-expiry"),
]


def main():
    r = TfidfRetriever()
    print(f"Corpus: {len(r.runbooks)} runbooks\n")
    correct = 0
    for query, expected in PROBES:
        top = r.retrieve(query, k=3)
        hit = top[0].runbook.id == expected
        in_top3 = expected in [m.runbook.id for m in top]
        correct += hit
        mark = "OK " if hit else "MISS"
        print(f"  [{mark}] -> {top[0].runbook.id:24} (score {top[0].score:.2f})"
              f"{'' if hit else '   expected: ' + expected}")
    print(f"\nTop-1 retrieval accuracy: {correct}/{len(PROBES)} ({correct/len(PROBES):.0%})")


if __name__ == "__main__":
    main()
