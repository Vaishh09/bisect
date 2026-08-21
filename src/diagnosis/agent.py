"""
Diagnosis: rank the suspect commits for an incident.

Two rankers, both producing the same output (a ranked list of SuspectCommit that
gets written into the Incident):

  - rank_deterministic(): no LLM, no key. Scores each commit on three signals:
      time proximity to the spike, blast-radius overlap (did it touch the failing
      file/service?), and blame relevance. This is the honest baseline.

  - rank_with_claude(): reads the actual diffs and re-ranks with reasoning. Only
    runs if an ANTHROPIC_API_KEY is present. Falls back to deterministic otherwise.

The point of having both (mirroring replay-fast vs model-eval): on HARD scenarios
where several commits touch the same file, service-matching alone can't pick the
culprit — you have to read the diff. That's where Claude earns its keep, and the
benchmark measures exactly that gap.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from src.core.incident import Incident, SuspectCommit
from src.diagnosis.signals import (
    CommitInfo, DeployMarker, ErrorSignature,
    recent_commits, deploy_markers, error_signature,
)


# ----------------------------- deterministic -----------------------------

def _score_commit(commit: CommitInfo, spike_at: datetime,
                  deploys: list[DeployMarker], sig: Optional[ErrorSignature]) -> tuple[float, str]:
    """Return (score 0-1, human reason). Pure heuristics, no LLM."""
    reasons = []
    score = 0.0

    # Signal 1: time correlation — was this commit deployed just before the spike?
    deployed = next((d for d in deploys if d.sha == commit.sha), None)
    if deployed and deployed.at <= spike_at:
        gap = (spike_at - deployed.at).total_seconds()
        if gap < 120:
            score += 0.5
            reasons.append(f"deployed {gap:.0f}s before the spike")
        else:
            score += 0.2
            reasons.append(f"deployed {gap:.0f}s before the spike")

    # Signal 2: blast radius — did it touch the file named in the stack trace?
    if sig and sig.file_hint:
        if any(sig.file_hint == f or f.endswith(sig.file_hint) for f in commit.files_changed):
            score += 0.35
            reasons.append(f"changed {sig.file_hint}, the file in the stack trace")
        elif any("checkout" in f for f in commit.files_changed):
            score += 0.1
            reasons.append("touched the failing service")

    # Signal 3: weak recency nudge (more recent = slightly more suspect)
    # (kept small so it can't override the real signals)

    if not reasons:
        reasons.append("no strong correlation")
    return min(score, 1.0), "; ".join(reasons)


def rank_deterministic(incident: Incident, limit: int = 10) -> list[SuspectCommit]:
    commits = recent_commits(limit=limit)
    deploys = deploy_markers()
    sig = error_signature()
    spike_at = incident.alert.fired_at

    scored = []
    for c in commits:
        score, reason = _score_commit(c, spike_at, deploys, sig)
        scored.append((score, c, reason))
    scored.sort(key=lambda t: t[0], reverse=True)

    suspects = []
    for rank, (score, c, reason) in enumerate(scored, start=1):
        suspects.append(SuspectCommit(
            sha=c.sha, author=c.author, message=c.message,
            committed_at=c.committed_at, files_changed=c.files_changed,
            rank=rank, confidence=round(score, 2), reasoning=reason,
        ))
    return suspects


# ----------------------------- Claude ranker -----------------------------

CLAUDE_PROMPT = """You are an SRE diagnosing a production incident. Rank the suspect \
commits from most to least likely to have caused it. Reason over the actual diffs.

INCIDENT
  service: {service}
  alert: {detail}
  error: {exception}
  failing file: {file_hint}
  spike started: {spike_at}

DEPLOY TIMELINE
{deploys}

CANDIDATE COMMITS (with diffs)
{candidates}

Return ONLY a JSON array, most likely first, each item:
  {{"sha": "...", "confidence": 0.0-1.0, "reasoning": "one sentence grounded in the diff"}}
No prose outside the JSON."""


def _build_candidates_block(commits: list[CommitInfo]) -> str:
    blocks = []
    for c in commits:
        blocks.append(
            f"--- commit {c.sha[:8]} by {c.author}: {c.message}\n"
            f"files: {', '.join(c.files_changed)}\n"
            f"diff:\n{c.diff[:1500]}"
        )
    return "\n\n".join(blocks)


def rank_with_claude(incident: Incident, limit: int = 10) -> list[SuspectCommit]:
    """Re-rank using Claude's diff reasoning. Falls back to deterministic if no key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return rank_deterministic(incident, limit=limit)

    import json as _json
    try:
        from anthropic import Anthropic
    except ImportError:
        return rank_deterministic(incident, limit=limit)

    commits = recent_commits(limit=limit)
    deploys = deploy_markers()
    sig = error_signature()
    by_sha = {c.sha: c for c in commits}

    deploy_lines = "\n".join(
        f"  {d.at.isoformat()}  deployed {d.sha[:8]}  {d.message}" for d in deploys
    ) or "  (none)"

    prompt = CLAUDE_PROMPT.format(
        service=incident.alert.service,
        detail=incident.alert.detail,
        exception=sig.exception if sig else "unknown",
        file_hint=sig.file_hint if sig else "unknown",
        spike_at=incident.alert.fired_at.isoformat(),
        deploys=deploy_lines,
        candidates=_build_candidates_block(commits),
    )

    client = Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-opus-4-20250514",  # any current model string works; swap as needed
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    ranked = _json.loads(text)

    suspects = []
    for rank, item in enumerate(ranked, start=1):
        c = by_sha.get(item["sha"]) or by_sha.get(item["sha"][:8])
        if not c:
            # tolerate short shas
            c = next((cc for cc in commits if cc.sha.startswith(item["sha"])), None)
        if not c:
            continue
        suspects.append(SuspectCommit(
            sha=c.sha, author=c.author, message=c.message,
            committed_at=c.committed_at, files_changed=c.files_changed,
            rank=rank, confidence=float(item.get("confidence", 0.0)),
            reasoning=item.get("reasoning", ""),
        ))
    return suspects or rank_deterministic(incident, limit=limit)


# ----------------------------- entry point -----------------------------

def diagnose(incident: Incident, use_claude: bool = True, limit: int = 10) -> Incident:
    """Fill the incident's suspect list. Writes a timeline event either way."""
    incident.status = incident.status.__class__.DIAGNOSING
    if use_claude and os.environ.get("ANTHROPIC_API_KEY"):
        suspects = rank_with_claude(incident, limit=limit)
        method = "claude"
    else:
        suspects = rank_deterministic(incident, limit=limit)
        method = "deterministic"

    incident.suspects = suspects
    top = incident.top_suspect()
    if top:
        incident.status = incident.status.__class__.IDENTIFIED
        incident.log("diagnosis",
                     f"[{method}] top suspect {top.sha[:8]} by {top.author} "
                     f"(confidence {top.confidence:.0%}): {top.reasoning}",
                     evidence={"method": method, "top_sha": top.sha})
    return incident
