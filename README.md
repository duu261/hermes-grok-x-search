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
hermes config set grok_x_search.model grok-4.5
```

Optional settings:

```yaml
grok_x_search:
  base_url: https://gateway.example/v1
  model: grok-4.5
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
- `allowed_x_handles` - exclusively include up to 20 handles
- `excluded_x_handles` - exclude up to 20 handles
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
  "tool": "grok_x_search",
  "model": "grok-4.5",
  "answer": "...",
  "citations": [],
  "inline_citations": [],
  "citation_urls": ["https://x.com/example/status/123"],
  "output_types": ["reasoning", "message"],
  "search_call_detected": false,
  "degraded": false,
  "degraded_reason": null
}
```

Some gateways preserve citations but omit the upstream `x_search_call` output item. `search_call_detected: false` therefore does not invalidate a citation-backed answer.

Only HTTPS citation URLs on `x.com` or `twitter.com` are retained. Userinfo, nonstandard ports, and unrelated hosts are dropped.

An HTTP 200 answer with no citations is returned with `degraded: true`. Treat it as unsourced model synthesis, not proof that X Search ran.

## Trust boundary

This plugin sends requests to the configured gateway. The gateway operator controls upstream accounts, authentication, routing, logs, retention, billing, request rewriting, and availability. Installing this plugin does not grant an xAI entitlement or bypass provider controls.

Domain and handle filters constrain the requested search but are not security boundaries. Verify returned URLs before fetching or acting on them.

The plugin refuses redirects, caps response bodies and retry delays, and returns sanitized error categories instead of raw upstream bodies.

## Development

```bash
python -m unittest discover -s tests -v
python -m py_compile provider.py __init__.py tests/test_provider.py tests/test_live.py
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
