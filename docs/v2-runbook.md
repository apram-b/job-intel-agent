# Job Intel v2 operator runbook

The personal dashboard remains local. A daily AWS worker writes to PostgreSQL; a separate public site serves sanitized snapshots. Existing authenticated public-trial functionality is retained under Legacy search but is not part of this release.

## Local use and migration

Use Python 3.12+ and the locked environment:

```sh
uv sync --locked
uv run python main.py --v2 migrate
uv run python main.py --v2 import-legacy data/job_intel.db
uv run streamlit run app.py
```

Back up an existing database with SQLite's backup API before the first migration. The importer preserves original IDs, first/last observations, application notes and statuses. It copies old 0–12 scores into explicitly legacy evaluations; it does not convert them to v2 percentages. Existing v1 tables remain intact. Repeating import does not overwrite new v2 records.

The migrated generic web sources start disabled and their jobs are unverified. Supply validated Greenhouse/Lever URLs in the Companies tab or import an explicit sources file:

```sh
uv run python main.py --v2 watchlist --import-sources config/my-sources.json
uv run python main.py --v2 discover
uv run python main.py --v2 watchlist
uv run python main.py --v2 scan
uv run python main.py --v2 evaluate
```

Discovery suggestions remain disabled until reviewed. No company is endorsed by the smoke-test configuration. Edit the candidate independently from YAML preferences in the local dashboard. The `--profile` legacy JSON format remains supported by legacy commands; v2 configure accepts YAML or JSON:

```sh
uv run python main.py --v2 configure --candidate config/candidate.json --preferences config/search_profile.yaml
```

Real candidate and preference files are ignored by Git. Copy the supplied example preferences, then review the candidate parsed by the previous workflow. The paid worker uses this saved profile; it does not repeatedly parse the résumé.

## Exact model prices and the monthly limit

Put your API key only in `.env` locally or `/opt/job-intel/worker.env` on the worker. Set the exact priced-model identity and current input/output USD per million token rates shown by that provider. V2 refuses paid calls when a matching price configuration is missing. Do not guess prices or use a cheaper model's rates for a different model.

Every attempted v2 model call reserves its worst-case cost transactionally from the shared monthly US$3 ledger before the provider request. Reservations use a conservative 62,000-input-token bound and 4,096-output-token bound, are not refunded on ambiguous failures, and cannot exceed US$3 even if the environment requests a higher limit. This intentionally favors staying under budget over maximizing calls. It may leave many jobs pending. Cached fit/strategy remain usable; confidence refreshes independently.

The monthly guard covers the v2 worker and demo evaluations. The preserved legacy interface still has its original per-run controls, not this monthly ledger; use v2 for the budgeted scheduled release. Provider invoices remain authoritative. Configure provider-level limits in addition to the application ledger.

## AWS provisioning

Nothing in the repository automatically provisions resources on startup. Confirm the intended AWS profile before using it. The read-only preflight requires your current public IPv4 /32:

```sh
uv run python deploy/preflight.py --profile YOUR_PROFILE --owner-cidr YOUR_IPV4/32
```

The checked templates are:

- `deploy/edge-stack.yaml` in **us-east-1**: private S3, origin access control, HTTPS CloudFront, WAF rate limit and an explicit **FREE** flat-rate subscription. The distribution starts disabled; leave it disabled through the pilot.
- `deploy/worker-stack.yaml` in **ap-south-1**: 2 GB Lightsail, static IP, owner-only SSH, private backup bucket with seven-day retention, SNS topic and a scoped worker IAM user. The database and worker have no public HTTP ports.

Example provisioning after preflight and account verification:

```sh
aws --profile YOUR_PROFILE cloudformation deploy --region us-east-1 --stack-name job-intel-demo --template-file deploy/edge-stack.yaml
# Read DemoBucketArn from the first stack's outputs.
aws --profile YOUR_PROFILE cloudformation deploy --region ap-south-1 --stack-name job-intel-worker --template-file deploy/worker-stack.yaml --capabilities CAPABILITY_IAM --parameter-overrides OwnerCidr=YOUR_IPV4/32 DemoBucketArn=DEMO_BUCKET_ARN
```

Check that the free subscription is active. AWS Free Tier account plans cannot use CloudFront flat-rate subscriptions; do not silently fall back to pay-as-you-go. Stack creation may temporarily create WAF resources before subscription activation; inspect rollback if subscription creation fails.

Budget envelope: US$12 compute, about US$1 storage/backups, at most US$3 reserved model usage, US$4 taxes/contingency. Validate current account prices and billing eligibility first. Create AWS budget alerts at US$15 and US$18; alerts do not impose a hard billing cap. Do not add a load balancer, managed database, extra instance, paid CloudFront plan, or new recurring services without revisiting the budget. Retained worker/bucket resources continue existing after stack deletion and require explicit cleanup.

References checked September 19, 2026: [Lightsail prices](https://aws.amazon.com/lightsail/pricing/), [CloudFront prices](https://aws.amazon.com/cloudfront/pricing/), [subscription resource](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-pricingplanmanager-subscription.html), [account eligibility](https://docs.aws.amazon.com/PricingPlanManager/latest/UserGuide/plans.html).

## Bootstrap, schedules and credentials

1. Publish the tested image through the Release workflow. Use the full commit SHA; no floating application image tag. Ensure the worker can pull the package, using read-only registry credentials if it is private.
2. Upload that commit's source archive to `/opt/job-intel/releases/COMMIT_SHA` and point `/opt/job-intel/current` there.
3. Copy the worker environment example to `/opt/job-intel/worker.env`, mode 600. Generate a random hexadecimal database password. Set the exact image, model configuration and stack output bucket/topic names. Configure the scoped worker user's AWS access separately; do not place administrator credentials in the container or repository.
4. Generate an **age** identity locally, save its private key outside the repository, and put only its public recipient on the worker. Subscribe and confirm only the owner's chosen destination to the alert topic.
5. Start the database with `docker compose --env-file /opt/job-intel/worker.env -f /opt/job-intel/current/deploy/compose.yaml up -d db`, then run `deploy/run.sh migrate`.
6. Import a private copy of the SQLite database through the shared volume, configure/review the personal profile and watchlist, then remove the transferred database after verifying counts. No résumé PDF is required on AWS.
7. Install the supplied systemd units and enable `job-intel-scan.timer`, `job-intel-discover.timer`, `job-intel-backup.timer` and `job-intel-health.timer`.

Daily scans run at 02:30 UTC / 08:00 IST. Discovery runs Sundays at 03:30 UTC. Daily encrypted backups run at 04:00 UTC and freshness checks at 05:00 UTC. The worker timeout is 45 minutes; its lease is 60 minutes. An interrupted run may need its lease to expire before manual retry. The process is safe to restart: committed companies remain intact, incomplete sources cannot close jobs, and scoring reads versioned caches.

## Local dashboard connected to AWS

Run `deploy/connect-local.sh WORKER_IP SSH_KEY_FILE`, verify the SSH host fingerprint, and keep the tunnel open. Set the local `JOB_INTEL_DATABASE_URL` to `postgresql+psycopg://job_intel:PASSWORD@127.0.0.1:15432/job_intel`. Then launch Streamlit locally. PostgreSQL binds only to worker loopback and is not exposed publicly. If the tunnel is down, reconnect it; do not create an independent hosted copy of the database.

## Backups, restore and rollback

`deploy/backup.sh` streams `pg_dump -Fc` directly through age encryption, uploads only the encrypted file, and removes its temporary file. The bucket expires backups after seven days. Keep the age private key off the worker.

Before publishing, download a backup and restore into a **separate test database**, not production:

```sh
age -d -i /PRIVATE/PATH/backup-key.txt backup.dump.age > /PRIVATE/TEMP/restored.dump
createdb RESTORE_TEST_DATABASE
pg_restore --no-owner --dbname RESTORE_TEST_DATABASE /PRIVATE/TEMP/restored.dump
```

Compare job/application/observation counts and run the queue against the restored database. Remove the temporary plaintext dump afterward. This restore must be exercised on the deployed database; template validation is not a restore test.

`deploy/deploy-release.sh COMMIT_SHA` backs up before migration, keeps the previous source/image settings and restores them if migration fails. Initial bootstrap precedes this update workflow. After a successful additive migration, roll the app back by restoring `worker.env.previous` and the `previous` release symlink; restore a database backup only when the migration itself requires it, accounting for subsequent writes. No destructive Alembic downgrade is provided.

## Public demo and release gates

`export-demo` requires the separately marked fictional `demo` candidate and evaluations made for its current version. Personal assessments and notes are never copied. The export maps an explicit field allowlist; unsupported raw payloads cannot leak through. Fictional seed cards have no active application links. A failed refresh keeps the existing snapshot and its timestamp. The public `/health.json` exposes only demo readiness and snapshot freshness.

```sh
uv run python main.py --v2 export-demo --seed-profile
uv run python main.py --v2 evaluate --profile demo
uv run python main.py --v2 export-demo
uv run python main.py --v2 review-packet
# After manually labeling 50 actual postings:
uv run python main.py --v2 pilot-report --labels data/relevance-review.json
```

The gate requires seven calendar days of complete scans for enabled companies, at least 50 genuine human labels and 8/10 worthwhile top-ranked roles with no known hard-exclusion violation. It does not pretend to verify hosting, backups or billing. Separately verify a cold HTTPS visit, worker restart, backup restoration and redeploy. Then update `PublishAfterPilot=true` on the edge stack. The default CloudFront HTTPS hostname avoids purchasing a domain.

## Known operational limits

A single worker is not highly available. The static demo remains available during worker failure, but new scans wait for recovery. Legacy web records stay unverified until matched to a supported ATS source. Source coverage and model relevance need real evaluation; passing fixtures is not proof of useful search results. Infrastructure templates, CI and scripts need account-specific live acceptance before claiming this service is deployed.
