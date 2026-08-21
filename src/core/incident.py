"""The Incident object — the single contract every stage reads and writes."""
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

def _now(): return datetime.now(timezone.utc)

class IncidentStatus(str, Enum):
    OPEN = "open"
    DIAGNOSING = "diagnosing"
    IDENTIFIED = "identified"
    RESOLVED = "resolved"

class Severity(str, Enum):
    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"

class TimelineEvent(BaseModel):
    at: datetime = Field(default_factory=_now)
    stage: str
    message: str
    evidence: Optional[dict] = None

class Alert(BaseModel):
    fired_at: datetime
    kind: str
    service: str
    detail: str
    metric_value: float
    threshold: float

class SuspectCommit(BaseModel):
    sha: str
    author: str
    message: str
    committed_at: datetime
    files_changed: list[str] = Field(default_factory=list)
    rank: int
    confidence: float
    reasoning: str

class ImpactEstimate(BaseModel):
    affected_requests: int
    affected_users_estimate: int
    window_seconds: int
    note: str = "Estimate: error_rate x traffic over the incident window."

class Incident(BaseModel):
    id: str
    status: IncidentStatus = IncidentStatus.OPEN
    severity: Severity = Severity.SEV2
    started_at: datetime = Field(default_factory=_now)
    resolved_at: Optional[datetime] = None
    alert: Alert
    suspects: list[SuspectCommit] = Field(default_factory=list)
    matched_runbook: Optional[str] = None
    impact: Optional[ImpactEstimate] = None
    timeline: list[TimelineEvent] = Field(default_factory=list)

    def log(self, stage, message, evidence=None):
        self.timeline.append(TimelineEvent(stage=stage, message=message, evidence=evidence))

    def top_suspect(self):
        return self.suspects[0] if self.suspects else None

    def mark_resolved(self):
        self.status = IncidentStatus.RESOLVED
        self.resolved_at = _now()
        self.log("resolution", "Metrics returned to baseline; incident resolved.")

def new_incident(alert, incident_id=None):
    iid = incident_id or f"INC-{alert.fired_at.strftime('%Y%m%d-%H%M%S')}"
    inc = Incident(id=iid, alert=alert)
    inc.log("detection",
            f"{alert.kind} on {alert.service}: {alert.detail} "
            f"({alert.metric_value:.0%} vs {alert.threshold:.0%} threshold)",
            evidence={"metric_value": alert.metric_value, "threshold": alert.threshold})
    return inc
