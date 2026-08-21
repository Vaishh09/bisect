# Runbook: NoneType / missing session in checkout

## Symptoms
- 5xx spike on the checkout service (`/api/checkout`)
- Error logs show `AttributeError: 'NoneType' object has no attribute 'id'`
- Stack trace points at `checkout/service.py` accessing `user.session`

## Likely cause
A recent code change removed or bypassed the null-session guard, so requests
from users without an active session dereference `user.session.id` on None.

## Remediation
1. Identify the commit that changed `checkout/service.py` around the spike.
2. Roll back the deploy to the last known-good build to stop the bleeding.
3. Open a revert PR that restores the `if user.session is None` guard.
4. Add a regression test for the no-session path.

## Prevention
Require a test covering unauthenticated / expired-session checkout attempts.
