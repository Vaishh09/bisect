"""
Signal gathering for diagnosis: pull the raw material the ranker reasons over.

Three signals, all from REAL data (real git, the simulator's deploy markers, the
error logs):

  1. recent commits     — real `git log` in a window before the incident
  2. deploy markers     — from deploys.jsonl (time correlation: which deploy is
                          closest-before the spike)
  3. error signature    — the stack trace pulled from the 500 logs (blast radius:
                          which file/endpoint is failing)

This module does NO ranking and NO LLM. It just assembles evidence. The rankers
(deterministic + Claude) consume what this returns.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
TOY_REPO = ROOT / "data" / "toy_repo"
GEN = ROOT / "data" / "generated"


class CommitInfo(BaseModel):
    sha: str
    author: str
    message: str
    committed_at: datetime
    files_changed: list[str] = Field(default_factory=list)
    diff: str = ""


class DeployMarker(BaseModel):
    at: datetime
    sha: str
    author: Optional[str] = None
    message: str = ""


class ErrorSignature(BaseModel):
    endpoint: str
    file_hint: Optional[str] = None      # file named in the stack trace
    exception: Optional[str] = None      # e.g. "AttributeError: 'NoneType' ..."
    sample_count: int = 0


def _git(*args: str, repo: Path = TOY_REPO) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def recent_commits(limit: int = 10, repo: Path = TOY_REPO) -> list[CommitInfo]:
    """Real `git log` — the candidate pool. Each with files changed + full diff."""
    fmt = "%H%x1f%an%x1f%cI%x1f%s"
    raw = _git("log", f"-{limit}", f"--pretty=format:{fmt}", repo=repo)
    commits: list[CommitInfo] = []
    for line in raw.splitlines():
        sha, author, iso, msg = line.split("\x1f")
        files = _git("show", "--name-only", "--pretty=format:", sha, repo=repo).split("\n")
        files = [f for f in files if f.strip()]
        diff = _git("show", sha, "--pretty=format:%b", repo=repo)
        commits.append(CommitInfo(
            sha=sha, author=author, message=msg,
            committed_at=datetime.fromisoformat(iso),
            files_changed=files, diff=diff,
        ))
    return commits


def deploy_markers(path: Path = GEN / "deploys.jsonl") -> list[DeployMarker]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("rollback"):
            continue  # rollbacks aren't suspects
        out.append(DeployMarker(at=datetime.fromisoformat(d["at"]), sha=d["sha"],
                                author=d.get("author"), message=d.get("message", "")))
    return out


def error_signature(path: Path = GEN / "logs.jsonl") -> Optional[ErrorSignature]:
    """Read the 500 logs, extract the failing endpoint + file + exception."""
    if not path.exists():
        return None
    endpoint = None
    file_hint = None
    exception = None
    count = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        log = json.loads(line)
        if log.get("status") != 500:
            continue
        count += 1
        endpoint = log.get("endpoint")
        err = log.get("error", "")
        if err and file_hint is None:
            # pull 'File "checkout/service.py"' and the exception line
            for ln in err.splitlines():
                ln = ln.strip()
                if ln.startswith('File "') and file_hint is None:
                    file_hint = ln.split('"')[1]
                if ln and (ln.split(":")[0].endswith("Error") or "Error:" in ln):
                    exception = ln
    if count == 0:
        return None
    return ErrorSignature(endpoint=endpoint, file_hint=file_hint,
                          exception=exception, sample_count=count)


if __name__ == "__main__":
    print("Recent commits:")
    for c in recent_commits():
        print(f"  {c.sha[:8]} {c.author:8} {c.message}  files={c.files_changed}")
    print("\nDeploy markers (suspects):")
    for d in deploy_markers():
        print(f"  {d.sha[:8]} at {d.at}  {d.message}")
    print("\nError signature:")
    sig = error_signature()
    if sig:
        print(f"  endpoint={sig.endpoint}  file={sig.file_hint}")
        print(f"  exception={sig.exception}  samples={sig.sample_count}")
