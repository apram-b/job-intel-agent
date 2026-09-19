# Why make OpenAI the initial default?

Decision: use OpenAI as the default baseline, keep Anthropic configurable, and choose the longer-term default from evaluations rather than brand preference.

This pipeline consists mostly of bounded extraction and classification. OpenAI's Responses API can parse directly into the same Pydantic models used by application validation. That simplifies schema enforcement and avoids regex-based JSON extraction in the live path. The app sets `store=False`, isolates each user's credentials and records aggregate token usage, without logging resume prompts or provider error bodies. [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

The pinned GPT-5 Mini baseline supports structured outputs. Its listed standard price, checked September 5, 2026, is $0.25 per million input tokens and $2 per million output tokens. This is a documented baseline for well-defined tasks, not a claim that it is the newest model or the best performer for this dataset. Actual availability depends on the API account. [Model documentation](https://developers.openai.com/api/docs/models/gpt-5-mini).

These are reasons to try OpenAI, not evidence that it will rank jobs more accurately than Anthropic. Anthropic remains supported using its structured tool interface with the same local validation. Model provider choice does not fix missing descriptions, bad location logic or destructive history; those are addressed in application code.

## Evaluation before changing the default

1. Freeze a reviewed candidate profile and 50–100 real job postings spanning senior DE, MLOps, ML Platform, junior roles, explicit US-only remote, India remote and ambiguous hybrid.
2. Label eligibility, interview-worthy fit and missing skills manually.
3. Run identical inputs through both providers using separate profile IDs and record model snapshot, scorer version, tokens and elapsed time.
4. Compare precision among the top ten, false India-eligibility positives, unsupported evidence, schema failures, latency and cost per useful match.
5. Select a model only after reviewing disagreements. A score is a ranking aid, not a probability of receiving an interview.

The adapters do not silently switch providers. Visitor-supplied credentials are used only with the selected provider; an invalid key results in failure rather than owner-funded retries.
