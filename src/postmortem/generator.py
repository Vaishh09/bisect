"""
Phase 8b — Postmortem generation.

Draft the writeup from the timeline the pipeline has been recording all along.
This is why every stage calls incident.log(): the postmortem writes itself from
structured facts.

Two modes, same facts:
  - Deterministic (default): assemble a clean markdown postmortem directly from
    the incident's fields and timeline. No key, no invented content.
  - LLM-polished (optional): if ANTHROPIC_API_KEY is set, the model rewrites the
    narrative to read more naturally — but it is handed ONLY the structured facts
    and instructed to narrate them, never to add a cause, number, or claim that
    isn't already in the incident. (An early ungrounded draft is exactly the
    failure mode to avoid; the guardrail is that the model can't introduce facts.)

Output: a markdown string, and optionally written to data/generated/postmortems/.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.core.incident import Incident

OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "generated" / "postmortems"


def _duration(incident: Incident) -> str:
    if not incident.resolved_at:
        return "ongoing"
    secs = int((incident.resolved_at - incident.alert.fired_at).total_seconds())
    # our simulator timestamps are compressed; fall back to a sensible label
    if secs <= 0:
        return "~tens of seconds (simulated)"
    m, s = divmod(secs, 60)
    return f"{m}m {s}s" if m else f"{s}s"


def _facts(incident: Incident) -> dict:
    """The structured facts the postmortem is built from. The LLM sees ONLY this."""
    top = incident.top_suspect()
    remediation_events = [e.message for e in incident.timeline if e.stage == "remediation"]
    return {
        "id": incident.id,
        "severity": incident.severity.value,
        "status": incident.status.value,
        "service": incident.alert.service,
        "detected": incident.alert.detail,
        "error_rate": f"{incident.alert.metric_value:.0%}",
        "root_cause_sha": top.sha[:8] if top else None,
        "root_cause_msg": top.message if top else None,
        "root_cause_author": top.author if top else None,
        "root_cause_reasoning": top.reasoning if top else None,
        "runbook": incident.matched_runbook,
        "impact": (f"~{incident.impact.affected_requests} failed requests, "
                   f"~{incident.impact.affected_users_estimate} users, "
                   f"{incident.impact.window_seconds}s window") if incident.impact else None,
        "duration": _duration(incident),
        "remediation": remediation_events,
        "timeline": [{"stage": e.stage, "message": e.message} for e in incident.timeline],
    }


def _deterministic_markdown(f: dict) -> str:
    lines = [
        f"# Postmortem — {f['id']}",
        "",
        f"**Severity:** {f['severity'].upper()}  |  **Status:** {f['status']}  "
        f"|  **Duration:** {f['duration']}",
        "",
        "## Summary",
        f"The `{f['service']}` service experienced an error-rate spike "
        f"({f['error_rate']} error rate). "
        + (f"The likely root cause was commit `{f['root_cause_sha']}` "
           f"(\"{f['root_cause_msg']}\") by {f['root_cause_author']}. " if f['root_cause_sha'] else "")
        + ("The incident was resolved after remediation." if f['status'] == "resolved"
           else "The incident is not yet resolved."),
        "",
        "## Root cause",
    ]
    if f["root_cause_sha"]:
        lines += [
            f"- **Commit:** `{f['root_cause_sha']}` — {f['root_cause_msg']}",
            f"- **Author:** {f['root_cause_author']}",
            f"- **Why:** {f['root_cause_reasoning']}",
        ]
    else:
        lines.append("- Root cause not identified.")
    lines += ["", "## Impact", f"- {f['impact'] or 'Not estimated.'}", ""]
    lines += ["## Detection", f"- {f['detected']}", ""]
    if f["runbook"]:
        lines += ["## Runbook applied", f"- `{f['runbook']}`", ""]
    lines += ["## Remediation"]
    if f["remediation"]:
        for m in f["remediation"]:
            lines.append(f"- {m}")
    else:
        lines.append("- No remediation recorded.")
    lines += ["", "## Timeline"]
    for e in f["timeline"]:
        lines.append(f"- **[{e['stage']}]** {e['message']}")
    lines += [
        "",
        "## Follow-up actions",
        "- [ ] Add a regression test covering the failure path.",
        "- [ ] Review how the change reached production without catching the regression.",
        "- [ ] Confirm the applied runbook is accurate and up to date.",
        "",
        "---",
        "*Drafted by bisect from the recorded incident timeline. "
        "bisect diagnoses and recommends; humans approve all actions.*",
    ]
    return "\n".join(lines)


def _llm_polish(markdown: str, facts: dict) -> str:
    """Optionally rewrite the narrative sections for readability. The model is
    given only `facts` and told to narrate them — never to add new claims."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return markdown
    try:
        from anthropic import Anthropic
    except ImportError:
        return markdown

    import json as _json
    prompt = (
        "You are writing the Summary and Root cause prose for a blameless "
        "postmortem. Use ONLY the facts in this JSON. Do NOT introduce any cause, "
        "number, name, or claim that is not present. Return the full markdown "
        "document, keeping every section and the timeline exactly, but improving "
        "the prose in Summary and Root cause.\n\n"
        f"FACTS:\n{_json.dumps(facts, indent=2)}\n\n"
        f"CURRENT DRAFT:\n{markdown}"
    )
    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-opus-4-20250514", max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        return text or markdown
    except Exception:
        return markdown


def generate_postmortem(incident: Incident, use_llm: bool = True, write: bool = True) -> str:
    facts = _facts(incident)
    md = _deterministic_markdown(facts)
    if use_llm and os.environ.get("ANTHROPIC_API_KEY"):
        md = _llm_polish(md, facts)
    incident.log("postmortem", "postmortem drafted from incident timeline.")
    if write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"{incident.id}.md"
        path.write_text(md)
    return md


if __name__ == "__main__":
    import json as _json
    from src.simulator.simulator import Simulator
    from src.detection.detector import detect
    from src.diagnosis.agent import diagnose
    from src.runbooks.retriever import match_runbook
    from src.impact.estimator import add_impact
    from src.remediation.actions import propose_actions, approve
    from src.postmortem.resolution import resolve_if_recovered

    gt = _json.loads((Path(__file__).resolve().parents[2] / "data" / "toy_repo" / "GROUND_TRUTH.json").read_text())
    bad = {"sha": gt["bad_commit_sha"], "author": "devuser", "message": "refactor: simplify checkout flow"}

    sim = Simulator(rps=50)
    sim.run(healthy_secs=15, broken_secs=15, bad_commit=bad, recover_secs=0)
    inc = detect()
    inc = diagnose(inc, use_claude=False)
    match_runbook(inc)
    add_impact(inc)
    actions = propose_actions(inc)
    approve(actions[0], "vaish", inc,
            rollback_fn=lambda: sim.deploy_good_build(gt["all_commits"]["init_checkout"]))
    for _ in range(10):
        sim._tick()
    inc = resolve_if_recovered(inc)

    md = generate_postmortem(inc, use_llm=False)
    print(md)
