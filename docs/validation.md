# Validation notes

Checked locally on September 5, 2026.

- 56 automated tests passed on Python 3.12.13.
- Ruff checks and formatting passed.
- Streamlit's local form and public-mode configuration gate passed app tests.
- The real local server returned HTTP 200 on its health endpoint; its search form was inspected in the browser.
- The offline CLI example succeeded. Its first run returned two fictional new matches; repeating the run returned zero duplicate new matches. Demo records are stored separately from real job history.
- A read-only live Greenhouse request against the observed [Particle41 board](https://job-boards.greenhouse.io/particle41llc) returned 27 jobs, including 26 descriptions longer than 1,000 characters and 16 India-labeled locations. Counts are a point-in-time smoke test, not a recommendation or coverage guarantee.
- Lever pagination was verified with mocked API fixtures. No live Lever board or generic HTML fallback was exercised end to end.
- No paid OpenAI or Anthropic calls were made. Both adapters were tested with mocked SDK responses, including concurrent credential isolation, schema handling and sanitized errors.
- No personal resume was processed. Ranking precision and resume extraction accuracy remain to be evaluated with reviewed real inputs.
- Real OIDC login, personal API-key billing and public hosting remain unconfigured. Public admission is tested at the internal server boundary, including races, replay, exhausted allowances and persistent database records.
- No GitHub push, public deployment, recurring schedule, application submission or outreach sending was performed.

The tests demonstrate the implemented boundaries; they are not a penetration test or a claim that all possible abuse has been eliminated. See public-launch.md for the remaining deployment requirements.

## Source-coverage regression fix

A real user run exposed aggregator selection and generic extraction consuming the shared model budget. Automatic discovery now admits only observed Greenhouse/Lever boards without a model-selection call. Explicit aggregator sources are skipped before fetching. Six new tests cover site-filter enforcement, board deduplication, unsupported aggregators, empty discovery, extraction-budget isolation across threads and actionable HTTP/budget errors. The affected paid search was not automatically rerun; its historical output remains a snapshot.
