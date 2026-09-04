# Hermes Grok X Search - Agent Instructions

## Scope

This repository is a standalone Hermes Agent plugin. It registers one model-facing tool, `grok_x_search`, which sends a constrained xAI Responses request through an operator-configured OpenAI-compatible gateway.

Version 0.1 scope is locked to xAI server-side `x_search` only. Do not add general web search, code interpreter, file search, MCP, image generation, arbitrary tools, continuation state, or a generic Responses client without an explicit product decision.

## Repository map

- `provider.py` - validation, payload construction, HTTP transport, retries, and response normalization
- `__init__.py` - Hermes tool registration
- `plugin.yaml` - plugin metadata and credential declaration
- `tests/test_provider.py` - deterministic unit and transport tests
- `tests/test_live.py` - opt-in authenticated gateway test
- `README.md` - public installation, configuration, behavior, and trust boundaries

## Contracts

- Public tool inputs mirror xAI X Search controls: query, handle filters, date range, image understanding, and video understanding.
- Maximum 10 allowed or excluded handles, matching native Hermes `x_search`. The two filters are mutually exclusive.
- Non-secret settings live under `grok_x_search` in Hermes config. Only `GROK_X_SEARCH_API_KEY` belongs in the private environment.
- Remote endpoints require HTTPS. Loopback HTTP is allowed for development.
- Refuse redirects so bearer credentials cannot cross origins.
- Never return credentials, authorization headers, request bodies, endpoint URLs, raw upstream bodies, or backend traces.
- Cap response size and retry delay. Retry only transient HTTP failures.
- Keep the model-facing result aligned with native Hermes `x_search`; do not expose gateway-internal output types or search-call detector flags.
- A citation-backed answer is valid when `degraded` is false and either `citations` or `inline_citations` contains validated X URLs.
- Validate identifiable authors in citation fields and answer URLs against handle filters and fail closed with `filter_violation` when the gateway returns conflicting evidence.
- Retain only HTTPS citation URLs on `x.com` or `twitter.com`; never return userinfo or arbitrary hosts.
- Match native degraded semantics: only filtered answers without citations are marked `degraded: true`.
- HTTP 200 error envelopes and empty answers are failures.
- Accept omitted upstream `status` like native Hermes; reject explicit non-completed statuses.
- Keep normalized results at or below native's 100,000-character limit.
- Keep tool name `grok_x_search` to avoid overriding Hermes core `x_search`.

## Development

Use strict test-driven development. Run:

```bash
python -m unittest discover -s tests -v
python -m py_compile provider.py __init__.py tests/test_provider.py tests/test_live.py tests/test_hermes_e2e.py tests/hermes_e2e_runner.py
hermes plugins doctor . --ci
git diff --check
```

Authenticated testing consumes upstream quota and runs only when explicitly enabled:

```bash
GROK_X_SEARCH_LIVE_TESTS=1 \
GROK_X_SEARCH_LIVE_BASE_URL=https://gateway.example/v1 \
python -m unittest tests.test_live -v
```

Live tests may retry one transient failure. Never print secrets, prompts, raw responses, or private endpoint details.

## Operations

Do not mutate gateways, production services, databases, credentials, DNS, firewall, or Hermes core. Do not restart Hermes gateway. Installation and gateway restart are separate operator actions.

Use Conventional Commits with an imperative subject no longer than 50 characters. Keep repository publish-safe and free of private infrastructure names.
