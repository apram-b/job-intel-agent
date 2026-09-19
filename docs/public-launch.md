# Public trial: three free searches, then personal API keys

The implementation is present; public authentication has not been configured or deployed. The current supported deployment is one service instance on persistent disk. It is not a claim that a public service is exploit-proof.

## Identity and allowance

Streamlit's native OIDC sign-in validates the login. The application accepts claims only from `st.user`, requires the configured issuer, a stable subject and verified email, and hashes issuer plus subject into the internal user ID. It does not trust a typed email, Host header, browser storage, IP address or a client-supplied profile ID.

The server reserves a run in SQLite using `BEGIN IMMEDIATE` before starting paid work. Three lifetime sponsored admissions are allowed. Refreshing, clearing cookies, changing tabs or restarting the service does not reset that count when the same database is retained. Repeated request IDs are rejected; only one active run is admitted per identity. Parallel requests share the same database transaction boundary.

A failed or abandoned admitted run consumes a credit. Invalid local input and missing configuration are checked before admission. Automatic refunds are intentionally absent because an attacker could repeatedly trigger failures after billable work. Interrupted runs have a one-hour lease, after which the active slot becomes available without refunding the consumed credit. An operator can reconcile exceptional cases directly after inspecting the run and admission records; no public refund endpoint exists.

After three admissions, the UI only offers a personal key. Personal-key searches never borrow the owner's key, including on authentication failures or rate limits. Keys exist in server session/run memory, are excluded from persistent state, and are cleared from the UI after a returned run or with the clear-key control. A browser disconnect can discard a personal key; users may need to enter it again. This is a server-mediated BYOK feature: the server receives the key over HTTPS, it is not a browser-to-provider direct connection.

## Bounded shared usage

- At most 20 sponsored admissions per rolling 24 hours by default (`JOB_INTEL_DAILY_FREE_RUNS`).
- At most three active searches service-wide (`JOB_INTEL_MAX_ACTIVE_RUNS`), and one per identity.
- At most 30 model requests per public run, with SDK retries disabled, 60-second request timeouts, bounded input and 4,096 output tokens per request.
- At most 20 jobs scored and two outreach drafts per public run.
- Public collection accepts only Greenhouse and Lever adapters; arbitrary generic-site fetching is disabled even for personal-key users.
- Maximum upload 5 MB / 10 pages; bounded response downloads, pagination and extraction inputs.

These are usage ceilings, not an exact currency spending limit. Set a separate API project budget/limit with the chosen provider and monitor actual billing. Usage counters can undercount provider work on ambiguous transport failures, so billing remains the authoritative cost source.

Verified sign-in cannot prove one human has only one account. Multiple verified accounts can still claim separate allowances. The shared daily ceiling limits the resulting owner-funded usage. For a larger launch, add invitation/access controls, provider abuse controls, reverse-proxy rate limits and operational monitoring. Do not attempt to identify a person solely by IP or browser fingerprint.

## Configure before sharing

1. Register an OIDC client, initially Google, with the exact public HTTPS callback `https://YOUR_DOMAIN/oauth2callback`. Follow [Streamlit authentication](https://docs.streamlit.io/develop/concepts/connections/authentication).
2. Copy `.streamlit/secrets.example.toml` to `.streamlit/secrets.toml`; set the real client ID/secret and a strong random cookie secret. Keep this file private and persistent across normal restarts.
3. Set `JOB_INTEL_MODE=public`, `JOB_INTEL_OIDC_ISSUER=https://accounts.google.com`, the owner's chosen provider/key, and `JOB_INTEL_DB` to a persistent volume path. Never put the key in source control or client-side code.
4. Start with `--server.address 0.0.0.0` only behind HTTPS. Keep XSRF protection enabled. Set proxy request/upload/rate limits and infrastructure memory/CPU limits.
5. Use a single persistent service instance. Independent replicas with separate databases multiply allowances. For horizontal scale, migrate both admission and job transactions to a shared database before adding replicas. Do not place a WAL-mode SQLite file on unsupported network storage.
6. Define user-facing retention/deletion and support procedures for parsed resumes and application notes. The UI currently stores these until an operator removes them; a self-service deletion flow is not implemented.
7. Run acceptance tests with real test accounts: three sponsored starts; fourth denied; reload/new browser; parallel tabs; service restart; missing/invalid personal key; successful personal-key run; interrupted run; budget exhaustion; and separate histories for two accounts.

The generic local HTTP fallback checks public destinations and redirects but is not a full network sandbox against DNS rebinding. It is disabled in public mode. Public outbound network policy should still restrict traffic to required APIs and identity-provider endpoints.

The access module is an internal server module, not an HTTP endpoint accepting arbitrary identity JSON. Future API routes must validate identity tokens server-side before calling it.

## Owner administration

Set `JOB_INTEL_ADMIN_IDS` to a comma-separated allowlist of verified identity hashes (the `identity` values in the admissions table after sign-in). These are issuer/subject hashes, not email addresses or browser-supplied flags. An empty allowlist enables no public administrators. The same access check guards both the Admin view toggle and its server-side data query.

The public admin view shows the last 100 runs, the last 200 source checks and trial admissions by account. It excludes API keys and resume snapshots. Ordinary visitors see neither source diagnostics nor operational details in their result downloads; incomplete runs still receive a plain-language notice. Local mode retains diagnostics for the operator.

Dark mode is the default. The sidebar Light mode toggle is per session, so one visitor cannot change another visitor's appearance. All displayed shortlisted, review and saved jobs link to the original posting with a View job / Apply action.
