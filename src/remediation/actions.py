"""
Phase 7 — Remediation, human-approved.

The defining rule of bisect: it SUGGESTS, it never acts on its own. Every
recommended action sits PENDING until a human explicitly approves it. Only then
does it execute — and bisect records who approved, what ran, and when.

Flow:
  1. bisect proposes actions (roll back / open revert PR) on the incident.
  2. They sit as PENDING approvals. Nothing happens.
  3. A human calls approve(action_id, approver) or reject(action_id, approver).
  4. On approval — and only then — the action executes (here, against the
     simulator: a rollback deploys the last known-good build and the errors stop).
  5. The decision and its result are written to the incident timeline.

The `_authorize()` check is real logic, not a stub, even though it runs against a
fake user list here. When this touches anything real (Phase 9), that check is the
thing standing between a helpful tool and an AI that changed production. It exists
now so it's already there when it matters.

This is driven from the CLI today. A Slack interactivity payload handler plugs in
at the SAME approve()/reject() functions later — see the seam at the bottom.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pydantic import BaseModel, Field
from src.core.incident import Incident


# --- who is allowed to approve a production-affecting action ---
# Real logic against a fake roster for now. In Phase 9 this reads your real
# identity/on-call source. The point: approval is gated, not open.
AUTHORIZED_APPROVERS = {"vaish", "oncall-lead", "sre-admin"}


class ActionKind(str, Enum):
    ROLLBACK = "rollback"          # redeploy last known-good; stops the bleeding now
    REVERT_PR = "revert_pr"        # open a revert PR; permanent code cleanup


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class RemediationAction(BaseModel):
    id: str
    kind: ActionKind
    label: str
    description: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    proposed_for_sha: Optional[str] = None
    approver: Optional[str] = None
    decided_at: Optional[datetime] = None
    result: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _authorize(approver: str) -> bool:
    """Real authorization check. Only known approvers may execute actions."""
    return approver in AUTHORIZED_APPROVERS


def propose_actions(incident: Incident) -> list[RemediationAction]:
    """bisect proposes remediation for the incident's top suspect. These are
    SUGGESTIONS — they sit pending until a human approves. Nothing executes here."""
    top = incident.top_suspect()
    sha = top.sha if top else None
    actions = [
        RemediationAction(
            id=f"{incident.id}-rollback",
            kind=ActionKind.ROLLBACK,
            label="Roll back now",
            description="Redeploy the last known-good build. Stops errors immediately.",
            proposed_for_sha=sha,
        ),
        RemediationAction(
            id=f"{incident.id}-revert",
            kind=ActionKind.REVERT_PR,
            label="Open revert PR",
            description=f"Open a PR reverting {sha[:8] if sha else 'the bad commit'}. "
                        "Permanent code-level cleanup.",
            proposed_for_sha=sha,
        ),
    ]
    # store on the incident (as plain dicts in the timeline evidence for now)
    incident.log("remediation",
                 "proposed 2 actions (pending human approval): Roll back now, Open revert PR",
                 evidence={"actions": [a.id for a in actions]})
    return actions


def _execute(action: RemediationAction, incident: Incident,
             rollback_fn: Optional[Callable[[], None]] = None) -> str:
    """Run the approved action. In the demo, ROLLBACK acts on the simulator."""
    if action.kind == ActionKind.ROLLBACK:
        if rollback_fn:
            rollback_fn()
            return "Rolled back to last known-good build; error rate returning to baseline."
        return "Rollback issued (no simulator bound; recorded only)."
    if action.kind == ActionKind.REVERT_PR:
        # Demo: we don't open a real PR (that's Phase 9 / real GitHub API).
        sha = action.proposed_for_sha or "unknown"
        return f"Revert PR drafted for {sha[:8]} (demo: not opened against a real repo)."
    return "No-op."


def approve(action: RemediationAction, approver: str, incident: Incident,
            rollback_fn: Optional[Callable[[], None]] = None) -> RemediationAction:
    """A human approves the action. This is the ONLY path that leads to execution."""
    if action.status != ApprovalStatus.PENDING:
        raise ValueError(f"action {action.id} is {action.status.value}, not pending")

    if not _authorize(approver):
        action.status = ApprovalStatus.REJECTED
        action.approver = approver
        action.decided_at = _now()
        action.result = "not authorized"
        incident.log("remediation",
                     f"BLOCKED: {approver} attempted to approve '{action.label}' "
                     f"but is not an authorized approver.",
                     evidence={"action": action.id, "approver": approver})
        return action

    action.status = ApprovalStatus.APPROVED
    action.approver = approver
    action.decided_at = _now()
    incident.log("remediation",
                 f"{approver} APPROVED '{action.label}' for "
                 f"{action.proposed_for_sha[:8] if action.proposed_for_sha else '—'}",
                 evidence={"action": action.id, "approver": approver})

    # execute — only reachable after an authorized human approval
    try:
        result = _execute(action, incident, rollback_fn)
        action.status = ApprovalStatus.EXECUTED
        action.result = result
        incident.log("remediation", f"executed '{action.label}': {result}",
                     evidence={"action": action.id, "result": result})
    except Exception as e:
        action.status = ApprovalStatus.FAILED
        action.result = str(e)
        incident.log("remediation", f"execution FAILED for '{action.label}': {e}",
                     evidence={"action": action.id})
    return action


def reject(action: RemediationAction, approver: str, incident: Incident) -> RemediationAction:
    """A human declines the suggestion. Nothing executes. The decision is recorded."""
    action.status = ApprovalStatus.REJECTED
    action.approver = approver
    action.decided_at = _now()
    action.result = "declined by human"
    incident.log("remediation", f"{approver} REJECTED '{action.label}'. No action taken.",
                 evidence={"action": action.id, "approver": approver})
    return action


# --- Slack seam (Phase 9): a Slack interactivity payload maps to the same calls ---
# def handle_slack_action(payload):
#     verify_slack_signature(payload)              # security: confirm it's really Slack
#     approver = payload["user"]["username"]       # who clicked
#     action = lookup_action(payload["actions"][0]["value"])
#     if payload["actions"][0]["action_id"] == "approve":
#         approve(action, approver, incident, rollback_fn=...)
#     else:
#         reject(action, approver, incident)
# The approve()/reject() logic above does not change — only the trigger does.


if __name__ == "__main__":
    from src.simulator.simulator import Simulator
    from src.detection.detector import detect
    from src.diagnosis.agent import diagnose
    import json

    gt = json.loads((Path(__file__).resolve().parents[2] / "data" / "toy_repo" / "GROUND_TRUTH.json").read_text())
    bad = {"sha": gt["bad_commit_sha"], "author": "devuser", "message": "refactor: simplify checkout flow"}

    sim = Simulator(rps=50)
    sim.run(healthy_secs=20, broken_secs=20, bad_commit=bad, recover_secs=0)
    inc = detect()
    inc = diagnose(inc, use_claude=False)

    print("\n=== bisect proposes remediation (nothing runs yet) ===")
    actions = propose_actions(inc)
    for a in actions:
        print(f"  [{a.status.value}] {a.label} — {a.description}")

    rollback = actions[0]

    print("\n=== an UNAUTHORIZED person tries to approve ===")
    approve(rollback, "random-intern", inc)
    print(f"  status: {rollback.status.value} ({rollback.result})")

    # fresh action (the previous one was rejected by the auth check)
    actions = propose_actions(inc)
    rollback = actions[0]

    print("\n=== an AUTHORIZED human approves the rollback ===")
    approve(rollback, "vaish", inc, rollback_fn=lambda: sim.deploy_good_build(gt["all_commits"]["init_checkout"]))
    print(f"  status: {rollback.status.value}")
    print(f"  result: {rollback.result}")
    print(f"  approver: {rollback.approver}")

    print("\n=== incident timeline (the audit trail) ===")
    for ev in inc.timeline:
        print(f"  [{ev.stage:11}] {ev.message}")
