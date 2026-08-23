"""
Phase 6 — The incident brief.

Assembles the finished investigation (cause + evidence, matched runbook, impact)
into one clean summary and delivers it. Two notifiers:

  - ConsoleNotifier (default): prints a formatted brief to the terminal. Works
    immediately, nothing to configure — this is what you screenshot for a demo.
  - SlackNotifier: posts the same brief to a real channel using Block Kit, but
    only if SLACK_BOT_TOKEN is set. Falls back to console otherwise.

Both render from the SAME incident object, so the brief is identical whether it
lands in your terminal or a Slack channel. The remediation buttons (Phase 7) will
attach to the Slack version's actions block.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.core.incident import Incident

SEV_LABEL = {"sev1": "SEV1 · major outage", "sev2": "SEV2 · significant degradation",
             "sev3": "SEV3 · minor"}


def build_brief_text(incident: Incident) -> str:
    """Plain-text brief — used by the console notifier and as Slack fallback text."""
    top = incident.top_suspect()
    lines = []
    lines.append("─" * 60)
    lines.append(f"  🔴 INCIDENT {incident.id}")
    lines.append(f"  {SEV_LABEL.get(incident.severity.value, incident.severity.value)}")
    lines.append("─" * 60)
    lines.append("")
    lines.append(f"  Service    {incident.alert.service} · {incident.alert.kind}")
    lines.append(f"  Detected   {incident.alert.detail}")
    lines.append(f"             error rate {incident.alert.metric_value:.0%} "
                 f"(threshold {incident.alert.threshold:.0%})")
    lines.append("")

    if top:
        lines.append(f"  Likely cause")
        lines.append(f"    {top.sha[:8]} — {top.message}")
        lines.append(f"    by {top.author} · confidence {top.confidence:.0%}")
        lines.append(f"    {top.reasoning}")
        lines.append("")

    if incident.impact:
        imp = incident.impact
        lines.append(f"  Impact (estimate)")
        lines.append(f"    ~{imp.affected_requests} failed requests · "
                     f"~{imp.affected_users_estimate} users · {imp.window_seconds}s window")
        lines.append("")

    if incident.matched_runbook:
        lines.append(f"  Runbook    {incident.matched_runbook}")
        lines.append("")

    lines.append(f"  Recommended actions (human-approved)")
    lines.append(f"    [ Roll back now ]   [ Open revert PR ]   [ View runbook ]")
    lines.append("")
    lines.append("  bisect diagnoses and recommends. A human approves any action.")
    lines.append("─" * 60)
    return "\n".join(lines)


def build_slack_blocks(incident: Incident) -> list[dict]:
    """Block Kit layout for real Slack delivery (Phase 7 adds the action buttons)."""
    top = incident.top_suspect()
    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"🔴 {incident.id} · "
                  f"{incident.severity.value.upper()}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Service*\n{incident.alert.service}"},
            {"type": "mrkdwn", "text": f"*Error rate*\n{incident.alert.metric_value:.0%}"},
        ]},
    ]
    if top:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": f"*Likely cause*\n`{top.sha[:8]}` — {top.message}\n"
                    f"by {top.author} · confidence {top.confidence:.0%}\n_{top.reasoning}_"}})
    if incident.impact:
        imp = incident.impact
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": f"*Impact (estimate)*\n~{imp.affected_requests} failed requests · "
                    f"~{imp.affected_users_estimate} users · {imp.window_seconds}s"}})
    if incident.matched_runbook:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": f"*Runbook*\n{incident.matched_runbook}"}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
        "text": "bisect diagnoses and recommends. A human approves any action."}]})
    # Phase 7 will append an "actions" block with Roll back / Revert PR buttons here.
    return blocks


class ConsoleNotifier:
    def send(self, incident: Incident) -> None:
        print(build_brief_text(incident))


class SlackNotifier:
    """Posts to Slack if configured; otherwise defers to console."""
    def __init__(self, token: str | None = None, channel: str | None = None):
        self.token = token or os.environ.get("SLACK_BOT_TOKEN")
        self.channel = channel or os.environ.get("SLACK_CHANNEL", "#incidents")

    def send(self, incident: Incident) -> None:
        if not self.token:
            ConsoleNotifier().send(incident)
            return
        try:
            from slack_sdk import WebClient
            client = WebClient(token=self.token)
            client.chat_postMessage(
                channel=self.channel,
                text=f"Incident {incident.id} ({incident.severity.value})",
                blocks=build_slack_blocks(incident),
            )
        except Exception as e:  # network/auth/import — fall back, never crash the pipeline
            print(f"[slack] delivery failed ({e}); printing to console instead.\n")
            ConsoleNotifier().send(incident)


def notify(incident: Incident) -> None:
    """Deliver the brief via the best available channel and log it."""
    notifier = SlackNotifier() if os.environ.get("SLACK_BOT_TOKEN") else ConsoleNotifier()
    notifier.send(incident)
    incident.log("brief", f"incident brief delivered via {type(notifier).__name__}")


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from src.detection.detector import detect
    from src.diagnosis.agent import diagnose
    from src.runbooks.retriever import match_runbook
    from src.impact.estimator import add_impact

    inc = detect()
    if inc is None:
        print("No incident in current data. Run: python3 src/simulator/simulator.py")
        sys.exit(0)
    inc = diagnose(inc, use_claude=False)
    match_runbook(inc)
    inc = add_impact(inc)
    notify(inc)
