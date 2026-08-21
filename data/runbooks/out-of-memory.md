# Runbook: Out of memory / OOMKilled

## Symptoms
- Pods restart repeatedly; `OOMKilled` in the container events
- Memory usage climbs steadily until the process is killed
- 5xx errors coincide with restarts

## Likely cause
A memory leak, an unbounded cache or buffer, or a workload increase past the
configured memory limit.

## Remediation
1. Check memory graphs for a steady climb vs a sudden jump.
2. Look for a recent change introducing an unbounded structure or large payloads.
3. Raise the memory limit as a stopgap; fix the leak as the real remedy.
4. Capture a heap profile if the leak is not obvious.
