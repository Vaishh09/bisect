# Runbook: High latency from a slow downstream dependency

## Symptoms
- p95 / p99 latency spikes but error rate stays relatively low at first
- Traces show time spent waiting on an upstream API or service call
- No obvious 5xx until timeouts start cascading

## Likely cause
A downstream dependency (payment gateway, auth service, third-party API) is
slow or degraded, and calls are blocking without a tight timeout.

## Remediation
1. Identify the slow dependency from distributed traces.
2. Check the dependency's own status / dashboards.
3. Apply or tighten timeouts and circuit breakers on the call.
4. Consider serving degraded / cached responses while the dependency recovers.
