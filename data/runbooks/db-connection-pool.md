# Runbook: Database connection pool exhaustion

## Symptoms
- Latency climbs then requests fail with `TimeoutError: QueuePool limit reached`
- Errors mention `could not acquire connection` or `pool timeout`
- Database CPU normal but app cannot get a connection

## Likely cause
A leak of unreleased connections, a spike in traffic, or a lowered pool size.

## Remediation
1. Check current pool usage and max pool size.
2. Restart the affected app pods to reclaim leaked connections (temporary).
3. Look for a recent change to connection handling or pool configuration.
4. Increase pool size only if the database can handle more connections.
