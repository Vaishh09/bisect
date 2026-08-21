"""
Phase 4 — Runbook retrieval (RAG).

Given an incident's error signature, find the runbook that matches this failure
type. This is the retrieval half of RAG.

Default backend: a pure-Python TF-IDF cosine retriever. No API key, no model
download, no heavy dependencies. For a small corpus of distinctive runbooks this
is reliable — the error signature ("NoneType ... session", "429", "OOMKilled")
carries strong, discriminating tokens that lexical matching handles well.

Upgrade path (Phase 9): swap `TfidfRetriever` for an embedding-backed store
(Chroma with a local sentence-transformers model, or pgvector with a hosted
embedding API). The interface — `retrieve(query) -> list[Match]` — stays the same,
so nothing downstream changes. That's why this is a clean boundary, not a hack.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

RUNBOOKS_DIR = Path(__file__).resolve().parents[2] / "data" / "runbooks"

_TOKEN = re.compile(r"[a-z0-9]+")
# very common words that carry no signal for matching failure types
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "is", "are",
    "it", "its", "with", "for", "as", "by", "from", "that", "this", "then",
    "runbook", "symptoms", "cause", "likely", "remediation", "prevention",
    "service", "error", "errors", "check", "add", "fix",
}


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class Runbook(BaseModel):
    id: str            # filename stem, e.g. "null-session-checkout"
    title: str
    path: str
    text: str


class Match(BaseModel):
    runbook: Runbook
    score: float       # cosine similarity 0-1


class TfidfRetriever:
    def __init__(self, runbooks_dir: Path = RUNBOOKS_DIR):
        self.runbooks: list[Runbook] = []
        self._doc_vecs: list[dict[str, float]] = []
        self._idf: dict[str, float] = {}
        self._load(runbooks_dir)
        self._build_index()

    def _load(self, d: Path) -> None:
        for p in sorted(d.glob("*.md")):
            text = p.read_text()
            first = next((ln for ln in text.splitlines() if ln.strip()), p.stem)
            title = first.lstrip("# ").strip()
            self.runbooks.append(Runbook(id=p.stem, title=title, path=str(p), text=text))

    def _build_index(self) -> None:
        docs_tokens = [_tokenize(rb.text) for rb in self.runbooks]
        n = len(docs_tokens)
        # document frequency
        df: Counter[str] = Counter()
        for toks in docs_tokens:
            for term in set(toks):
                df[term] += 1
        # smoothed idf
        self._idf = {term: math.log((1 + n) / (1 + dfi)) + 1.0 for term, dfi in df.items()}
        # tf-idf vectors per doc
        for toks in docs_tokens:
            self._doc_vecs.append(self._vectorize(toks))

    def _vectorize(self, tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        total = sum(tf.values()) or 1
        vec = {term: (count / total) * self._idf.get(term, math.log(1) + 1.0)
               for term, count in tf.items()}
        return vec

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        common = set(a) & set(b)
        dot = sum(a[t] * b[t] for t in common)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    def retrieve(self, query: str, k: int = 3) -> list[Match]:
        qvec = self._vectorize(_tokenize(query))
        scored = [Match(runbook=rb, score=round(self._cosine(qvec, dv), 4))
                  for rb, dv in zip(self.runbooks, self._doc_vecs)]
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:k]


# ---- integration with the Incident pipeline ----

def query_from_signature(exception: str | None, file_hint: str | None,
                         endpoint: str | None) -> str:
    """Build a retrieval query from an incident's error signature."""
    return " ".join(x for x in [exception, file_hint, endpoint] if x)


def match_runbook(incident, retriever: TfidfRetriever | None = None):
    """Retrieve the best runbook for an incident and record it. Reads the error
    signature the diagnosis stage already gathered."""
    from src.diagnosis.signals import error_signature
    retriever = retriever or TfidfRetriever()
    sig = error_signature()
    query = query_from_signature(
        sig.exception if sig else None,
        sig.file_hint if sig else None,
        sig.endpoint if sig else None,
    )
    matches = retriever.retrieve(query, k=3)
    if matches and matches[0].score > 0:
        best = matches[0]
        incident.matched_runbook = best.runbook.id
        incident.log("runbook",
                     f"matched runbook '{best.runbook.title}' (score {best.score:.2f})",
                     evidence={"runbook_id": best.runbook.id, "score": best.score,
                               "query": query})
    return matches


if __name__ == "__main__":
    r = TfidfRetriever()
    print(f"Loaded {len(r.runbooks)} runbooks.\n")
    # Sanity: known failure types should retrieve their own runbook.
    probes = {
        "AttributeError NoneType session checkout": "null-session-checkout",
        "QueuePool limit reached could not acquire connection": "db-connection-pool",
        "p99 latency slow downstream dependency timeout": "high-latency-dependency",
        "OOMKilled memory climbs pods restart": "out-of-memory",
        "HTTP 429 rate limit exceeded third-party": "upstream-rate-limit",
        "No space left on device logs": "disk-full",
        "certificate has expired TLS handshake": "tls-cert-expiry",
    }
    correct = 0
    for q, expected in probes.items():
        top = r.retrieve(q, k=1)[0]
        ok = top.runbook.id == expected
        correct += ok
        print(f"  [{'OK ' if ok else 'MISS'}] {q[:45]:45} -> {top.runbook.id} ({top.score:.2f})")
    print(f"\nRetrieval accuracy: {correct}/{len(probes)}")
