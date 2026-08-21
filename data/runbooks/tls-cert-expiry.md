# Runbook: TLS certificate expiry

## Symptoms
- Clients fail with `certificate has expired` or TLS handshake errors
- Sudden total failure of HTTPS connections at a specific timestamp
- Health checks over TLS start failing simultaneously

## Likely cause
A TLS certificate reached its expiry date and was not renewed / rotated in time.

## Remediation
1. Check the certificate expiry date on the affected endpoint.
2. Renew and deploy the certificate immediately.
3. Reload / restart services to pick up the new certificate.
4. Add expiry monitoring and automate renewal.
