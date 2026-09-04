"""Responses-compatible Grok X Search adapter for Hermes Agent."""

from __future__ import annotations

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

MAX_HANDLES = 10
HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,15}$")
REASONING_EFFORTS = {"low", "medium", "high", "xhigh"}
LOCAL_HTTP_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_MODEL = "grok-4.5"
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
STRICT_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
X_CITATION_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}


def _load_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly()
        section = config.get("grok_x_search") if isinstance(config, dict) else None
        return section if isinstance(section, dict) else {}
    except (ImportError, OSError, TypeError, ValueError):
        return {}


def _get_api_key() -> str:
    try:
        from hermes_cli.config import get_env_value

        return str(get_env_value("GROK_X_SEARCH_API_KEY") or "").strip()
    except (ImportError, OSError, TypeError, ValueError):
        return str(os.getenv("GROK_X_SEARCH_API_KEY") or "").strip()


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_request(request: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


def responses_endpoint(base_url: str) -> str:
    base_url = str(base_url or "").strip().rstrip("/")
    if any(ord(char) < 32 or ord(char) == 127 for char in base_url):
        raise ValueError("base URL must not contain control characters")
    parsed = urlparse(base_url)
    if parsed.username or parsed.password:
        raise ValueError("base URL must not contain embedded credentials")
    if "?" in base_url or "#" in base_url:
        raise ValueError("base URL must not contain a query or fragment")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("base URL must be absolute")
    if any(char.isspace() for char in parsed.netloc):
        raise ValueError("base URL host must not contain whitespace")
    if parsed.netloc.endswith(":"):
        raise ValueError("base URL must contain a valid port")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("base URL must contain a valid port") from exc
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" and not (parsed.scheme == "http" and hostname in LOCAL_HTTP_HOSTS):
        raise ValueError("base URL must use HTTPS; HTTP is allowed only for loopback")
    return base_url if base_url.endswith("/responses") else f"{base_url}/responses"


def _parse_date(value: str, field_name: str):
    if not STRICT_DATE.fullmatch(value):
        raise ValueError(f"{field_name} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc


def _validate_dates(from_date: str, to_date: str) -> None:
    start = _parse_date(from_date, "from_date") if from_date else None
    end = _parse_date(to_date, "to_date") if to_date else None
    if start and end and start > end:
        raise ValueError("from_date must be on or before to_date")
    if start and start > datetime.now(timezone.utc).date():
        raise ValueError("from_date must not be in the future")


def _normalize_handles(handles: list[str] | None, field_name: str) -> list[str]:
    if handles is not None and not isinstance(handles, list):
        raise ValueError(f"{field_name} must be an array")
    cleaned: list[str] = []
    for handle in handles or []:
        if not isinstance(handle, str):
            raise ValueError(f"{field_name} entries must be strings")
        value = handle.strip().lstrip("@")
        if not value:
            raise ValueError(f"{field_name} entries must not be blank")
        if not HANDLE_PATTERN.fullmatch(value):
            raise ValueError(f"{field_name} entries must be valid X handles")
        cleaned.append(value)
    if len(cleaned) > MAX_HANDLES:
        raise ValueError(f"{field_name} supports at most {MAX_HANDLES} handles")
    return cleaned


def build_payload(
    *,
    query: str,
    model: str,
    allowed_x_handles: list[str] | None = None,
    excluded_x_handles: list[str] | None = None,
    from_date: str = "",
    to_date: str = "",
    enable_image_understanding: bool = False,
    enable_video_understanding: bool = False,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    if not isinstance(model, str):
        raise ValueError("model must be a string")
    if not isinstance(from_date, str):
        raise ValueError("from_date must be a string")
    if not isinstance(to_date, str):
        raise ValueError("to_date must be a string")
    if not isinstance(enable_image_understanding, bool):
        raise ValueError("enable_image_understanding must be a boolean")
    if not isinstance(enable_video_understanding, bool):
        raise ValueError("enable_video_understanding must be a boolean")
    if reasoning_effort is not None and not isinstance(reasoning_effort, str):
        raise ValueError("reasoning_effort must be a string")

    query = query.strip()
    if not query:
        raise ValueError("query is required")

    allowed = _normalize_handles(allowed_x_handles, "allowed_x_handles")
    excluded = _normalize_handles(excluded_x_handles, "excluded_x_handles")
    if allowed and excluded:
        raise ValueError("allowed_x_handles and excluded_x_handles cannot be used together")

    from_date = from_date.strip()
    to_date = to_date.strip()
    _validate_dates(from_date, to_date)

    effort = (reasoning_effort or "").strip().lower()
    if effort and effort not in REASONING_EFFORTS:
        raise ValueError("reasoning_effort must be low, medium, high, or xhigh")

    tool: dict[str, Any] = {"type": "x_search"}
    if allowed:
        tool["allowed_x_handles"] = allowed
    if excluded:
        tool["excluded_x_handles"] = excluded
    if from_date:
        tool["from_date"] = from_date
    if to_date:
        tool["to_date"] = to_date
    if enable_image_understanding:
        tool["enable_image_understanding"] = True
    if enable_video_understanding:
        tool["enable_video_understanding"] = True

    prompt = query
    if allowed:
        handles = ", ".join(f"@{handle}" for handle in allowed)
        prompt += (
            f"\n\nStrict source constraint: Only cite and discuss posts authored by: {handles}. "
            "Do not include related or quoted accounts."
        )
    elif excluded:
        handles = ", ".join(f"@{handle}" for handle in excluded)
        prompt += (
            f"\n\nStrict source constraint: Do not cite or discuss posts authored by: {handles}."
        )

    payload: dict[str, Any] = {
        "model": model.strip(),
        "input": [{"role": "user", "content": prompt}],
        "tools": [tool],
        "store": False,
    }
    if effort:
        payload["reasoning"] = {"effort": effort}
    return payload


def _valid_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    url = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        return ""
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return ""
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or hostname not in X_CITATION_HOSTS
    ):
        return ""
    return url


def _array(value: Any, field_name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"upstream {field_name} is not an array")
    return value


def _optional_text(value: Any, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"upstream {field_name} is not a string")
    return value


def _optional_index(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("upstream citation index is not an integer")
    return value


def _response_text(data: dict[str, Any]) -> str:
    direct_value = data.get("output_text")
    if direct_value is not None and not isinstance(direct_value, str):
        raise TypeError("upstream output_text is not a string")
    direct = str(direct_value or "").strip()
    if direct:
        return direct
    parts: list[str] = []
    for item in _array(data.get("output"), "output"):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in _array(item.get("content"), "message content"):
            if not isinstance(content, dict):
                continue
            text_value = content.get("text")
            if text_value is not None and not isinstance(text_value, str):
                raise TypeError("upstream content text is not a string")
            text = str(text_value or "").strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def normalize_response(
    data: dict[str, Any],
    *,
    model: str,
    query: str,
    active_filters: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise TypeError("upstream response is not an object")
    if data.get("error"):
        raise ValueError("upstream returned an error envelope")
    status = data.get("status")
    if status is not None and not isinstance(status, str):
        raise TypeError("upstream status is not a string")
    if status != "completed":
        raise ValueError("upstream response is not completed")
    output = _array(data.get("output"), "output")
    citations_value = _array(data.get("citations"), "citations")

    answer = _response_text(data)
    if not answer:
        raise ValueError("upstream response contained no answer")
    if answer.lower().startswith("internal error"):
        raise ValueError("upstream returned an error response")

    citations: list[dict[str, Any]] = []
    inline: list[dict[str, Any]] = []
    urls: list[str] = []

    def add_url(value: Any) -> str:
        url = _valid_url(value)
        if url and url not in urls:
            urls.append(url)
        return url

    for citation in citations_value:
        if isinstance(citation, str):
            url = add_url(citation)
            if url:
                citations.append({"url": url, "title": ""})
        elif isinstance(citation, dict):
            url = add_url(citation.get("url"))
            if url:
                citations.append(
                    {
                        "url": url,
                        "title": _optional_text(citation.get("title"), "citation title"),
                    }
                )

    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = _optional_text(item.get("type"), "output type")
        if item_type != "message":
            continue
        for content in _array(item.get("content"), "message content"):
            if not isinstance(content, dict):
                continue
            for annotation in _array(content.get("annotations"), "annotations"):
                if not isinstance(annotation, dict) or annotation.get("type") != "url_citation":
                    continue
                url = add_url(annotation.get("url"))
                if url:
                    inline.append(
                        {
                            "url": url,
                            "title": _optional_text(annotation.get("title"), "citation title"),
                            "start_index": _optional_index(annotation.get("start_index")),
                            "end_index": _optional_index(annotation.get("end_index")),
                        }
                    )

    filters = active_filters or []
    degraded = bool(filters) and not bool(urls)
    return {
        "success": True,
        "provider": "grok-responses",
        "credential_source": "gateway",
        "tool": "grok_x_search",
        "model": model,
        "query": query,
        "answer": answer,
        "citations": citations,
        "inline_citations": inline,
        "degraded": degraded,
        "degraded_reason": (
            f"no citations returned despite filters: {', '.join(filters)}"
            if degraded
            else None
        ),
    }


def _integer_setting(
    config: dict[str, Any], name: str, default: int, minimum: int, maximum: int
) -> int:
    try:
        value = int(config.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _float_setting(
    config: dict[str, Any], name: str, default: float, minimum: float, maximum: float
) -> float:
    try:
        value = float(config.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _request_id(headers: Any) -> str | None:
    if not hasattr(headers, "get"):
        return None
    for name in ("x-request-id", "request-id", "x-openai-request-id"):
        value = headers.get(name)
        if value and SAFE_REQUEST_ID.fullmatch(str(value)):
            return str(value)
    return None


def _http_error_type(status_code: int) -> str:
    if status_code in {401, 403}:
        return "authentication"
    if status_code == 402:
        return "quota"
    if status_code == 408:
        return "timeout"
    if status_code == 429:
        return "rate_limit"
    if status_code >= 500:
        return "upstream"
    return "request"


def _failure(error_type: str, error: str, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "success": False,
        "provider": "grok-responses",
        "tool": "grok_x_search",
        "error_type": error_type,
        "error": error,
    }
    result.update({key: value for key, value in extra.items() if value is not None})
    return result


def grok_x_search(
    query: str,
    allowed_x_handles: list[str] | None = None,
    excluded_x_handles: list[str] | None = None,
    from_date: str = "",
    to_date: str = "",
    enable_image_understanding: bool = False,
    enable_video_understanding: bool = False,
) -> dict[str, Any]:
    config = _load_config()
    base_url = str(config.get("base_url") or "").strip()
    api_key = _get_api_key()
    if not base_url:
        return _failure("configuration", "grok_x_search.base_url is not set")
    if not api_key:
        return _failure("configuration", "GROK_X_SEARCH_API_KEY is not set")

    model = str(config.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    try:
        payload = build_payload(
            query=query,
            model=model,
            allowed_x_handles=allowed_x_handles,
            excluded_x_handles=excluded_x_handles,
            from_date=from_date,
            to_date=to_date,
            enable_image_understanding=enable_image_understanding,
            enable_video_understanding=enable_video_understanding,
            reasoning_effort=config.get("reasoning_effort"),
        )
        endpoint = responses_endpoint(base_url)
    except (TypeError, ValueError) as exc:
        return _failure("validation", str(exc))

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Hermes-Grok-X-Search/0.1.0",
        },
        method="POST",
    )
    timeout = _integer_setting(config, "timeout_seconds", DEFAULT_TIMEOUT_SECONDS, 30, 600)
    max_bytes = _integer_setting(
        config,
        "max_response_bytes",
        DEFAULT_MAX_RESPONSE_BYTES,
        1024,
        16 * 1024 * 1024,
    )
    retries = _integer_setting(config, "retries", 1, 0, 5)
    retry_base = _float_setting(config, "retry_base_seconds", 1.5, 0.0, 10.0)
    retry_cap = _float_setting(config, "max_retry_after_seconds", 30.0, 0.0, 60.0)

    for attempt in range(retries + 1):
        try:
            with _open_request(request, timeout=timeout) as response:
                raw = response.read(max_bytes + 1)
                request_id = _request_id(getattr(response, "headers", {}))
            if len(raw) > max_bytes:
                return _failure(
                    "response_too_large",
                    "upstream response exceeded configured size limit",
                    request_id=request_id,
                )
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return _failure(
                    "malformed_response",
                    "upstream response was not valid JSON",
                    request_id=request_id,
                )
            try:
                tool_def = payload["tools"][0]
                active_filters = [
                    name
                    for name in (
                        "allowed_x_handles",
                        "excluded_x_handles",
                        "from_date",
                        "to_date",
                    )
                    if tool_def.get(name)
                ]
                result = normalize_response(
                    data,
                    model=model,
                    query=str(query or "").strip(),
                    active_filters=active_filters,
                )
            except (TypeError, ValueError) as exc:
                return _failure("malformed_response", str(exc), request_id=request_id)
            if request_id:
                result["request_id"] = request_id
            return result
        except urllib.error.HTTPError as exc:
            status_code = int(exc.code)
            request_id = _request_id(exc.headers or {})
            transient = status_code in {408, 429} or status_code >= 500
            if transient and attempt < retries:
                retry_after = None
                try:
                    retry_after = float((exc.headers or {}).get("Retry-After", ""))
                except (TypeError, ValueError):
                    retry_after = None
                delay = retry_after if retry_after is not None else retry_base * (attempt + 1)
                time.sleep(min(retry_cap, max(0.0, delay)))
                continue
            return _failure(
                _http_error_type(status_code),
                f"upstream returned HTTP {status_code}",
                status_code=status_code,
                request_id=request_id,
            )
        except (http.client.HTTPException, urllib.error.URLError, TimeoutError):
            if attempt < retries:
                time.sleep(min(retry_cap, retry_base * (attempt + 1)))
                continue
            return _failure("network", "could not reach upstream gateway")

    return _failure("upstream", "upstream request failed")
