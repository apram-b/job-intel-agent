# V2 implementation validation — September 19, 2026

## Verified locally

- Preserved the existing MVP as baseline commit `f83c904` before v2 edits.
- Created a private SQLite backup and verified `PRAGMA integrity_check` returned `ok`.
- Repaired the local Python 3.12 interpreter link. The original 60 tests passed before implementation.
- **85 automated tests pass** after implementation, including 25 v2 cases. These cover migrations/import, identity and aliases, closure grace periods, source failure safety, cache invalidation, independent confidence refresh, concurrent monthly reservations, public export isolation, candidate evidence validation, and a populated Streamlit dashboard.
- Ruff lint/format checks, Git whitespace checks and lockfile verification pass.
- AWS CloudFormation templates pass `cfn-lint`; every deployment shell script passes Bash syntax validation.
- Migrated the real local database without changing original v1 row counts: **91 jobs, 110 observations, one profile**. V2 imported all 91 jobs and 110 observations. Database integrity remains `ok`.
- Preserved five old assessments as legacy evaluations and generated 91 explicit v2 review outcomes. Old generic web sources remain disabled/unverified; this is not a claim that they are active ATS listings.
- Live company discovery added **15 disabled ATS suggestions** for owner review, without model calls.
- In an isolated database, two live Particle41 Greenhouse scans returned **26 jobs, 26 unique job rows and 52 observations**.
- A live Plaid Lever request failed without disturbing other company state. A discovered 3pillarglobal Lever board returned a complete empty list twice. Nonempty Lever extraction/apply URLs are covered by fixtures, not a successful live nonempty-board check.
- The local Streamlit server returned HTTP 200 at `/_stcore/health`.
- The seeded public demo contains fictional sample roles and no live application links. It remains available without provider credentials.

## Not verified / not complete

- No paid model calls were made. Neither provider key is configured locally, and exact-model billing rates still need configuration. No claim is made about ranking precision on the actual candidate.
- PostgreSQL-aware tests and a PostgreSQL 16 CI service are implemented. A local PostgreSQL attempt was blocked by the desktop sandbox's shared-memory restriction, so PostgreSQL runtime tests have **not** been executed here.
- Docker is unavailable locally. Image build/start checks are defined in CI but have not been run here.
- AWS has no default credentials. The existing named profile `data-sre-agent` has not been selected for this project by the owner. No AWS resources, recurring worker, SNS subscription or public distribution have been provisioned.
- CloudFormation linting is not a deployed acceptance test. SSH, secrets, actual backups/restoration, restart, CI rollout, HTTPS and billing eligibility require live verification.
- The seven-day pilot has not occurred. No 50-posting human relevance review has occurred. `pilot-report` correctly reports that the release gate is not met.
- The new queue defaults locally, with Legacy search available. The public trial has not been launched or expanded.

See the runbook for exact setup, missing configuration and release checks. Local implementation is reviewable; public production readiness is still pending.
