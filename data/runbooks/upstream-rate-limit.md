# Runbook: Upstream rate limiting (429s)

## Symptoms
- Requests fail with HTTP 429 Too Many Requests
- Errors reference `rate limit exceeded` from a third-party API
- Failures correlate with traffic bursts

## Likely cause
The service is exceeding a third-party API quota, often after a traffic increase
or a retry storm amplifying request volume.

## Remediation
1. Confirm which upstream is returning 429 and the quota limit.
2. Add exponential backoff and jitter to retries to stop the storm.
3. Add client-side rate limiting / request queuing.
4. Request a higher quota if the traffic is legitimate.
