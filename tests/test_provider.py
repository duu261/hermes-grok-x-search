import http.client
import importlib.util
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_provider():
    spec = importlib.util.spec_from_file_location("grok_x_search_provider", ROOT / "provider.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "grok_x_search_plugin",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload, *, headers=None):
        self.payload = json.dumps(payload).encode()
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit=None):
        if limit is None:
            return self.payload
        return self.payload[:limit]


class PayloadTests(unittest.TestCase):
    def test_build_payload_normalizes_handles_and_uses_x_search(self):
        provider = load_provider()

        payload = provider.build_payload(
            query="Find recent Grok posts",
            model="grok-4.6",
            allowed_x_handles=["@xai", "  grok  "],
            enable_image_understanding=True,
        )

        self.assertEqual(payload["model"], "grok-4.6")
        self.assertEqual(payload["input"], [{"role": "user", "content": "Find recent Grok posts"}])
        self.assertEqual(
            payload["tools"],
            [
                {
                    "type": "x_search",
                    "allowed_x_handles": ["xai", "grok"],
                    "enable_image_understanding": True,
                }
            ],
        )
        self.assertIs(payload["store"], False)
        self.assertNotIn("api_key", json.dumps(payload).lower())

    def test_build_payload_rejects_conflicting_handle_filters(self):
        provider = load_provider()
        with self.assertRaisesRegex(ValueError, "cannot be used together"):
            provider.build_payload(
                query="test",
                model="grok-4.6",
                allowed_x_handles=["xai"],
                excluded_x_handles=["spam"],
            )

    def test_build_payload_rejects_more_than_twenty_handles(self):
        provider = load_provider()
        with self.assertRaisesRegex(ValueError, "at most 20"):
            provider.build_payload(
                query="test",
                model="grok-4.6",
                allowed_x_handles=[f"user{i}" for i in range(21)],
            )

    def test_build_payload_rejects_non_array_handles(self):
        provider = load_provider()
        with self.assertRaisesRegex(ValueError, "must be an array"):
            provider.build_payload(
                query="test",
                model="grok-4.6",
                allowed_x_handles=7,
            )
        with self.assertRaisesRegex(ValueError, "must not be blank"):
            provider.build_payload(
                query="test",
                model="grok-4.6",
                allowed_x_handles=["  "],
            )

    def test_build_payload_rejects_coerced_argument_types(self):
        provider = load_provider()
        invalid_cases = [
            {"query": ["not", "text"]},
            {"query": "test", "allowed_x_handles": [["nested"]]},
            {"query": "test", "from_date": []},
            {"query": "test", "enable_image_understanding": "false"},
        ]
        for values in invalid_cases:
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "must be"):
                provider.build_payload(model="grok-4.6", **values)

    def test_build_payload_validates_dates_and_reasoning(self):
        provider = load_provider()
        with self.assertRaisesRegex(ValueError, "on or before"):
            provider.build_payload(
                query="test",
                model="grok-4.6",
                from_date="2026-09-05",
                to_date="2026-09-04",
            )
        for invalid_date in ("09/04/2026", "20260904", "2026-W36-5"):
            with (
                self.subTest(invalid_date=invalid_date),
                self.assertRaisesRegex(ValueError, "YYYY-MM-DD"),
            ):
                provider.build_payload(
                    query="test",
                    model="grok-4.6",
                    from_date=invalid_date,
                )
        with self.assertRaisesRegex(ValueError, "reasoning_effort"):
            provider.build_payload(
                query="test",
                model="grok-4.6",
                reasoning_effort="maximum",
            )


class EndpointTests(unittest.TestCase):
    def test_endpoint_requires_https_except_loopback(self):
        provider = load_provider()
        self.assertEqual(
            provider.responses_endpoint("https://gateway.example/v1"),
            "https://gateway.example/v1/responses",
        )
        self.assertEqual(
            provider.responses_endpoint("http://127.0.0.1:8080/v1/responses"),
            "http://127.0.0.1:8080/v1/responses",
        )
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            provider.responses_endpoint("http://gateway.example/v1")
        with self.assertRaisesRegex(ValueError, "embedded credentials"):
            provider.responses_endpoint("https://user:pass@gateway.example/v1")
        with self.assertRaisesRegex(ValueError, "query or fragment"):
            provider.responses_endpoint("https://gateway.example/v1?target=other")
        with self.assertRaisesRegex(ValueError, "query or fragment"):
            provider.responses_endpoint("https://gateway.example/v1?")
        with self.assertRaisesRegex(ValueError, "query or fragment"):
            provider.responses_endpoint("https://gateway.example/v1#")
        with self.assertRaisesRegex(ValueError, "absolute"):
            provider.responses_endpoint("https://:443/v1")
        with self.assertRaisesRegex(ValueError, "valid port"):
            provider.responses_endpoint("https://gateway.example:bad/v1")
        with self.assertRaisesRegex(ValueError, "valid port"):
            provider.responses_endpoint("https://gateway.example:/v1")
        with self.assertRaisesRegex(ValueError, "control characters"):
            provider.responses_endpoint("https://gateway.example/v1\nX-Leak: yes")

    def test_request_id_accepts_only_safe_identifiers(self):
        provider = load_provider()
        self.assertEqual(provider._request_id({"x-request-id": "req_123-abc"}), "req_123-abc")
        self.assertIsNone(provider._request_id({"x-request-id": "secret\nheader"}))


class ResponseTests(unittest.TestCase):
    def test_normalize_response_accepts_citations_without_search_call_item(self):
        provider = load_provider()
        data = {
            "status": "completed",
            "citations": [
                "https://x.com/xai/status/1",
                {"url": "https://x.com/grok/status/2", "title": "Grok"},
            ],
            "output": [
                {"type": "reasoning"},
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Found posts.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://x.com/xai/status/1",
                                    "title": "xAI",
                                    "start_index": 0,
                                    "end_index": 5,
                                }
                            ],
                        }
                    ],
                },
            ],
        }

        result = provider.normalize_response(data, model="grok-4.6", query="test")

        self.assertTrue(result["success"])
        self.assertEqual(result["answer"], "Found posts.")
        self.assertEqual(
            result["citation_urls"],
            [
                "https://x.com/xai/status/1",
                "https://x.com/grok/status/2",
            ],
        )
        self.assertFalse(result["search_call_detected"])
        self.assertFalse(result["degraded"])

    def test_normalize_response_marks_uncited_answer_degraded(self):
        provider = load_provider()
        data = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Unsourced answer"}],
                }
            ],
        }

        result = provider.normalize_response(data, model="grok-4.6", query="test")

        self.assertTrue(result["success"])
        self.assertTrue(result["degraded"])
        self.assertEqual(result["degraded_reason"], "no citations returned")

    def test_normalize_response_rejects_non_string_text(self):
        provider = load_provider()
        with self.assertRaisesRegex(TypeError, "output_text"):
            provider.normalize_response(
                {"status": "completed", "output_text": {"private": "detail"}},
                model="grok-4.6",
                query="test",
            )
        with self.assertRaisesRegex(TypeError, "content text"):
            provider.normalize_response(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": {"private": "detail"}}],
                        }
                    ],
                },
                model="grok-4.6",
                query="test",
            )
        with self.assertRaisesRegex(TypeError, "citation title"):
            provider.normalize_response(
                {
                    "status": "completed",
                    "output_text": "ok",
                    "citations": [
                        {
                            "url": "https://x.com/xai/status/1",
                            "title": {"private": "detail"},
                        }
                    ],
                },
                model="grok-4.6",
                query="test",
            )
        with self.assertRaisesRegex(TypeError, "citation index"):
            provider.normalize_response(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "ok",
                                    "annotations": [
                                        {
                                            "type": "url_citation",
                                            "url": "https://x.com/xai/status/1",
                                            "start_index": {"private": "detail"},
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                model="grok-4.6",
                query="test",
            )

    def test_normalize_response_keeps_only_safe_x_citations(self):
        provider = load_provider()
        result = provider.normalize_response(
            {
                "status": "completed",
                "output_text": "Found one post",
                "citations": [
                    "https://x.com/xai/status/1",
                    "https://user:pass@x.com/xai/status/2",
                    "http://x.com/xai/status/3",
                    "https://169.254.169.254/latest/meta-data",
                    "https://example.com/not-x",
                ],
            },
            model="grok-4.6",
            query="test",
        )
        self.assertEqual(result["citation_urls"], ["https://x.com/xai/status/1"])
        self.assertFalse(result["degraded"])

    def test_normalize_response_rejects_error_envelope_and_empty_answer(self):
        provider = load_provider()
        with self.assertRaisesRegex(ValueError, "error envelope"):
            provider.normalize_response(
                {"error": {"message": "internal detail"}},
                model="grok-4.6",
                query="test",
            )
        with self.assertRaisesRegex(ValueError, "no answer"):
            provider.normalize_response(
                {"status": "completed", "output": []},
                model="grok-4.6",
                query="test",
            )
        with self.assertRaisesRegex(ValueError, "error response"):
            provider.normalize_response(
                {"status": "completed", "output_text": "Internal Error"},
                model="grok-4.6",
                query="test",
            )
        with self.assertRaisesRegex(TypeError, "citations"):
            provider.normalize_response(
                {"status": "completed", "output_text": "ok", "citations": 1},
                model="grok-4.6",
                query="test",
            )
        with self.assertRaisesRegex(TypeError, "message content"):
            provider.normalize_response(
                {
                    "status": "completed",
                    "output": [{"type": "message", "content": 1}],
                },
                model="grok-4.6",
                query="test",
            )
        for status in ("failed", "incomplete", "in_progress"):
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "not completed"):
                provider.normalize_response(
                    {"status": status, "output_text": "partial"},
                    model="grok-4.6",
                    query="test",
                )
        for missing_status in (
            {"output_text": "partial"},
            {"status": "", "output_text": "partial"},
        ):
            with (
                self.subTest(missing_status=missing_status),
                self.assertRaisesRegex(ValueError, "not completed"),
            ):
                provider.normalize_response(
                    missing_status,
                    model="grok-4.6",
                    query="test",
                )


class RegistrationTests(unittest.TestCase):
    def test_plugin_registers_narrow_grok_x_search_schema(self):
        plugin = load_plugin()
        calls = []

        class Context:
            def register_tool(
                self,
                *,
                name,
                toolset,
                schema,
                handler,
                check_fn=None,
                requires_env=None,
                emoji=None,
            ):
                calls.append(
                    {
                        "name": name,
                        "toolset": toolset,
                        "schema": schema,
                        "handler": handler,
                        "check_fn": check_fn,
                        "requires_env": requires_env,
                        "emoji": emoji,
                    }
                )

        plugin.register(Context())

        self.assertEqual(len(calls), 1)
        registered = calls[0]
        self.assertEqual(registered["name"], "grok_x_search")
        properties = registered["schema"]["parameters"]["properties"]
        self.assertEqual(
            set(properties),
            {
                "query",
                "allowed_x_handles",
                "excluded_x_handles",
                "from_date",
                "to_date",
                "enable_image_understanding",
                "enable_video_understanding",
            },
        )
        self.assertEqual(registered["schema"]["parameters"]["required"], ["query"])
        self.assertNotIn("tools", properties)
        self.assertNotIn("input", properties)
        self.assertNotIn("reasoning", properties)

        with patch.object(plugin, "grok_x_search", return_value={"success": True}):
            handled = registered["handler"]({"query": "test"})
        self.assertIsInstance(handled, str)
        self.assertEqual(json.loads(handled), {"success": True})

        with patch.object(plugin, "grok_x_search", return_value={"success": True}) as search:
            registered["handler"]({"query": "test", "enable_image_understanding": "false"})
        self.assertEqual(search.call_args.kwargs["enable_image_understanding"], "false")


class TransportTests(unittest.TestCase):
    def test_grok_x_search_mirrors_native_defaults(self):
        provider = load_provider()
        upstream = {
            "status": "completed",
            "citations": ["https://x.com/xai/status/1"],
            "output_text": "Result",
        }
        config = {
            "base_url": "https://gateway.example/v1",
            "retries": 0,
        }

        with (
            patch.object(provider, "_load_config", return_value=config),
            patch.object(provider, "_get_api_key", return_value="secret-key"),
            patch.object(provider, "_open_request", return_value=FakeResponse(upstream)) as opened,
        ):
            result = provider.grok_x_search("find posts")

        self.assertTrue(result["success"])
        body = json.loads(opened.call_args.args[0].data)
        self.assertEqual(body["model"], "grok-4.5")
        self.assertNotIn("reasoning", body)

    def test_grok_x_search_sends_responses_request_and_normalizes_result(self):
        provider = load_provider()
        upstream = {
            "status": "completed",
            "citations": ["https://x.com/xai/status/1"],
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Result"}],
                }
            ],
        }
        config = {
            "base_url": "https://gateway.example/v1",
            "model": "grok-4.6",
            "reasoning_effort": "low",
            "timeout_seconds": 90,
            "retries": 0,
        }

        with (
            patch.object(provider, "_load_config", return_value=config),
            patch.object(provider, "_get_api_key", return_value="secret-key"),
            patch.object(provider, "_open_request", return_value=FakeResponse(upstream)) as opened,
        ):
            result = provider.grok_x_search("find posts", allowed_x_handles=["@xai"])

        self.assertTrue(result["success"])
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://gateway.example/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key")
        body = json.loads(request.data)
        self.assertEqual(body["tools"], [{"type": "x_search", "allowed_x_handles": ["xai"]}])
        self.assertEqual(body["reasoning"], {"effort": "low"})
        self.assertNotIn("secret-key", json.dumps(result))

    def test_grok_x_search_retries_rate_limit_with_capped_delay(self):
        provider = load_provider()
        config = {
            "base_url": "https://gateway.example/v1",
            "model": "grok-4.6",
            "retries": 1,
            "max_retry_after_seconds": 7,
        }
        error = urllib.error.HTTPError(
            "https://gateway.example/v1/responses",
            429,
            "rate limited",
            {"Retry-After": "999", "x-request-id": "request-1"},
            io.BytesIO(b'{"error":{"message":"secret backend detail"}}'),
        )
        upstream = {
            "status": "completed",
            "citations": ["https://x.com/xai/status/1"],
            "output_text": "Recovered",
        }

        with (
            patch.object(provider, "_load_config", return_value=config),
            patch.object(provider, "_get_api_key", return_value="secret-key"),
            patch.object(provider, "_open_request", side_effect=[error, FakeResponse(upstream)]),
            patch.object(provider.time, "sleep") as sleep,
        ):
            result = provider.grok_x_search("find posts")

        self.assertTrue(result["success"])
        sleep.assert_called_once_with(7.0)

    def test_grok_x_search_sanitizes_http_errors(self):
        provider = load_provider()
        config = {
            "base_url": "https://gateway.example/v1",
            "model": "grok-4.6",
            "retries": 0,
        }
        error = urllib.error.HTTPError(
            "https://gateway.example/v1/responses",
            403,
            "forbidden",
            {"x-request-id": "request-2"},
            io.BytesIO(b'{"error":{"message":"secret backend detail"}}'),
        )

        with (
            patch.object(provider, "_load_config", return_value=config),
            patch.object(provider, "_get_api_key", return_value="secret-key"),
            patch.object(provider, "_open_request", side_effect=error),
        ):
            result = provider.grok_x_search("find posts")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "authentication")
        self.assertEqual(result["status_code"], 403)
        self.assertEqual(result["request_id"], "request-2")
        serialized = json.dumps(result)
        self.assertNotIn("secret backend detail", serialized)
        self.assertNotIn("secret-key", serialized)

    def test_grok_x_search_sanitizes_malformed_http(self):
        provider = load_provider()
        config = {
            "base_url": "https://gateway.example/v1",
            "model": "grok-4.6",
            "retries": 0,
        }
        with (
            patch.object(provider, "_load_config", return_value=config),
            patch.object(provider, "_get_api_key", return_value="secret-key"),
            patch.object(
                provider,
                "_open_request",
                side_effect=http.client.BadStatusLine("secret malformed status"),
            ),
        ):
            result = provider.grok_x_search("find posts")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "network")
        self.assertNotIn("secret malformed status", json.dumps(result))

    def test_grok_x_search_rejects_oversized_and_malformed_responses(self):
        provider = load_provider()
        config = {
            "base_url": "https://gateway.example/v1",
            "model": "grok-4.6",
            "retries": 0,
            "max_response_bytes": 1024,
        }
        oversized = FakeResponse({"output_text": "x" * 2000})
        malformed = FakeResponse({"output_text": "ok"})
        malformed.payload = b"not-json"
        wrong_shape = FakeResponse({"output_text": "ok"})
        wrong_shape.payload = b"[]"

        with (
            patch.object(provider, "_load_config", return_value=config),
            patch.object(provider, "_get_api_key", return_value="secret-key"),
            patch.object(provider, "_open_request", return_value=oversized),
        ):
            too_large = provider.grok_x_search("find posts")
        with (
            patch.object(provider, "_load_config", return_value=config),
            patch.object(provider, "_get_api_key", return_value="secret-key"),
            patch.object(provider, "_open_request", return_value=malformed),
        ):
            bad_json = provider.grok_x_search("find posts")
        with (
            patch.object(provider, "_load_config", return_value=config),
            patch.object(provider, "_get_api_key", return_value="secret-key"),
            patch.object(provider, "_open_request", return_value=wrong_shape),
        ):
            bad_shape = provider.grok_x_search("find posts")

        self.assertEqual(too_large["error_type"], "response_too_large")
        self.assertEqual(bad_json["error_type"], "malformed_response")
        self.assertEqual(bad_shape["error_type"], "malformed_response")


if __name__ == "__main__":
    unittest.main()
