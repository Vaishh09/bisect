# Runbook: Disk full / no space left on device

## Symptoms
- Errors: `No space left on device`; writes and logging fail
- Service cannot write temp files, caches, or logs
- Often follows unrotated logs or a runaway file

## Likely cause
Log files or temp data filled the volume; log rotation failed or a job wrote
large files without cleanup.

## Remediation
1. Identify the largest directories on the full volume.
2. Rotate or delete old logs and temp files to free space immediately.
3. Fix or enable log rotation.
4. Add a disk-usage alert below the critical threshold.
