"""Hermes plugin registration for gateway-backed Grok X Search."""

from __future__ import annotations

import json

from .provider import _get_api_key, _load_config, grok_x_search, responses_endpoint

GROK_X_SEARCH_SCHEMA = {
    "name": "grok_x_search",
    "description": (
        "Search public X posts, profiles, and threads through a pooled Grok "
        "Responses gateway. Returns a synthesized answer plus citations and "
        "inline_citations. Treat the result as X-grounded when degraded is false "
        "and either citation field contains valid X post URLs. Read-only discovery "
        "only; never use for posting, replies, likes, DMs, or other authenticated "
        "X actions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to research on X.",
            },
            "allowed_x_handles": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 10,
                "description": (
                    "Only consider posts from these X handles. Cannot be combined "
                    "with excluded_x_handles."
                ),
            },
            "excluded_x_handles": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 10,
                "description": (
                    "Exclude posts from these X handles. Cannot be combined with allowed_x_handles."
                ),
            },
            "from_date": {
                "type": "string",
                "description": "Optional inclusive start date in YYYY-MM-DD format.",
            },
            "to_date": {
                "type": "string",
                "description": "Optional inclusive end date in YYYY-MM-DD format.",
            },
            "enable_image_understanding": {
                "type": "boolean",
                "description": "Analyze images attached to matching X posts.",
                "default": False,
            },
            "enable_video_understanding": {
                "type": "boolean",
                "description": "Analyze videos attached to matching X posts.",
                "default": False,
            },
        },
        "required": ["query"],
    },
}


def is_available() -> bool:
    config = _load_config()
    try:
        responses_endpoint(config.get("base_url"))
    except ValueError:
        return False
    return bool(_get_api_key())


def _handle_grok_x_search(args, **_kwargs):
    if not isinstance(args, dict):
        return json.dumps(
            {
                "success": False,
                "provider": "grok-responses",
                "tool": "grok_x_search",
                "error_type": "validation",
                "error": "tool arguments must be an object",
            }
        )
    result = grok_x_search(
        query=args.get("query", ""),
        allowed_x_handles=args.get("allowed_x_handles"),
        excluded_x_handles=args.get("excluded_x_handles"),
        from_date=args.get("from_date", ""),
        to_date=args.get("to_date", ""),
        enable_image_understanding=args.get("enable_image_understanding", False),
        enable_video_understanding=args.get("enable_video_understanding", False),
    )
    return json.dumps(result, ensure_ascii=False)


def register(ctx):
    ctx.register_tool(
        name="grok_x_search",
        toolset="grok_x_search",
        schema=GROK_X_SEARCH_SCHEMA,
        handler=_handle_grok_x_search,
        check_fn=is_available,
        requires_env=["GROK_X_SEARCH_API_KEY"],
        emoji="🐦",
    )
