# Hermes Grok X Search

A standalone Hermes Agent plugin that exposes xAI's server-side X Search as one model-facing tool, `grok_x_search`, through an operator-configured Responses-compatible gateway.

```text
Hermes model
  -> grok_x_search
  -> gateway /v1/responses
  -> pooled Grok accounts
  -> xAI x_search
  -> answer and X citations
```

The plugin is designed for gateways that manage account pooling, OAuth refresh, routing, limits, and failover. Hermes stores one gateway credential instead of owning each upstream Grok account.

## Scope

Version 0.1 provides only X Search:

- public X post, profile, and thread research
- allowed or excluded handle filters
- date filters
- image understanding for matched posts
- video understanding for matched posts
- citation extraction and degraded-result detection

It does not provide general web search, posting or liking on X, code execution, file search, MCP, arbitrary function calling, or a generic Responses API client.

## Install

```bash
hermes plugins install https://github.com/duu261/hermes-grok-x-search.git --enable
```

Restart the Hermes surface that should load the plugin. Gateway restarts remain an operator action.

## Configure

Store the gateway API key in Hermes' private environment file:

```text
GROK_X_SEARCH_API_KEY=replace-me
```

Set non-secret behavior through Hermes config:

```bash
hermes config set grok_x_search.base_url https://gateway.example/v1
hermes config set grok_x_search.model grok-4.6
```

Optional settings:

```yaml
grok_x_search:
  base_url: https://gateway.example/v1
  model: grok-4.6
  reasoning_effort: null
  timeout_seconds: 180
  retries: 1
  retry_base_seconds: 1.5
  max_retry_after_seconds: 30
  max_response_bytes: 4194304
```

Remote endpoints must use HTTPS. Plain HTTP is accepted only for `localhost`, `127.0.0.1`, or `::1` development endpoints. The plugin appends `/responses` unless the configured URL already ends with `/responses`.

## Tool inputs

`grok_x_search` accepts:

- `query` - required research request
- `allowed_x_handles` - exclusively include up to 10 handles
- `excluded_x_handles` - exclude up to 10 handles
- `from_date` - optional `YYYY-MM-DD` start date
- `to_date` - optional `YYYY-MM-DD` end date
- `enable_image_understanding` - analyze images attached to matching posts
- `enable_video_understanding` - analyze videos attached to matching posts

Allowed and excluded handles cannot be combined.

## Result

Successful calls return JSON containing:

```json
{
  "success": true,
  "provider": "grok-responses",
  "credential_source": "gateway",
  "tool": "grok_x_search",
  "model": "grok-4.6",
  "answer": "...",
  "citations": [],
  "inline_citations": [],
  "degraded": false,
  "degraded_reason": null
}
```

The result intentionally mirrors native Hermes `x_search`. Treat it as citation-backed when `degraded` is false and either `citations` or `inline_citations` contains valid X post URLs. Gateway-internal output types are not exposed because they are transport diagnostics, not grounding status.

Only HTTPS citation URLs on `x.com` or `twitter.com` are retained. Userinfo, nonstandard ports, and unrelated hosts are dropped.

Like native Hermes `x_search`, a filtered HTTP 200 answer with no citations is returned with `degraded: true`. Treat it as unsourced model synthesis, not proof that X Search ran. An unfiltered answer follows native behavior and is not marked degraded solely because citations are absent. If a canonical X URL in the returned citations or answer text identifies an author that conflicts with `allowed_x_handles` or `excluded_x_handles`, the plugin fails closed with `error_type: "filter_violation"`.

## Trust boundary

This plugin sends requests to the configured gateway. The gateway operator controls upstream accounts, authentication, routing, logs, retention, billing, request rewriting, and availability. Installing this plugin does not grant an xAI entitlement or bypass provider controls.

Domain and handle filters constrain the requested search but are not security boundaries. Verify returned URLs before fetching or acting on them.

The plugin refuses redirects, caps response bodies and retry delays, and returns sanitized error categories instead of raw upstream bodies.

The normalized tool result is capped at 100,000 characters, matching native Hermes tool-result limits. An upstream response without `status` is accepted, while an explicit non-`completed` status is rejected. Filter constraints are reinforced in the request instructions and checked against identifiable returned X URLs.

## Development

```bash
python -m unittest discover -s tests -v
python -m py_compile provider.py __init__.py tests/test_provider.py tests/test_live.py tests/test_hermes_e2e.py tests/hermes_e2e_runner.py
hermes plugins doctor . --ci
git diff --check
```

Authenticated live test:

```bash
GROK_X_SEARCH_LIVE_TESTS=1 \
GROK_X_SEARCH_LIVE_BASE_URL=https://gateway.example/v1 \
python -m unittest tests.test_live -v
```

The live test consumes upstream quota and never prints credentials or raw responses.

## Future work

A separate larger plugin may later expose other Grok Responses capabilities such as web search, image search, code interpreter, collections, MCP, and mixed server-side tool workflows. Those capabilities are intentionally outside this plugin's initial scope.

## License

MIT
