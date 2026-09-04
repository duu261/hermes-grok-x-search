"""Real Hermes runtime probe used by test_hermes_e2e."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
EXPECTED_KEYS = {
    "success",
    "provider",
    "credential_source",
    "tool",
    "model",
    "query",
    "answer",
    "citations",
    "inline_citations",
    "degraded",
    "degraded_reason",
}


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        home = root / "hermes"
        shutil.copytree(REPO, home / "plugins" / "grok-x-search")
        (home / "logs").mkdir()
        (home / "config.yaml").write_text(
            "plugins:\n  enabled:\n    - grok-x-search\n"
            "grok_x_search:\n"
            "  base_url: https://gateway.example/v1\n"
            "  model: grok-4.5\n",
            encoding="utf-8",
        )
        bundled = root / "bundled"
        bundled.mkdir()
        os.environ.update(
            {
                "HERMES_HOME": str(home),
                "HERMES_BUNDLED_PLUGINS": str(bundled),
                "GROK_X_SEARCH_API_KEY": "test-only-key",
            }
        )

        from hermes_cli.plugins import PluginManager

        manager = PluginManager()
        manager.discover_and_load()
        loaded = manager._plugins["grok-x-search"]
        assert loaded.enabled and loaded.error is None

        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, limit=None):
                payload = {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "Found one post.",
                                    "annotations": [
                                        {
                                            "type": "url_citation",
                                            "url": "https://x.com/OpenAI/status/1",
                                            "title": "OpenAI",
                                            "start_index": 0,
                                            "end_index": 5,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
                raw = json.dumps(payload).encode("utf-8")
                return raw if limit is None else raw[:limit]

        from run_agent import AIAgent
        from tools.registry import registry

        agent = AIAgent(
            base_url="https://model.example/v1",
            api_key="k",
            provider="openai",
            model="gpt-5.4-mini",
            quiet_mode=True,
            skip_memory=True,
            skip_background_review=True,
            skip_context_files=True,
            platform="cli",
        )
        entry = registry.get_entry("grok_x_search")
        assert entry is not None
        search_function = entry.handler.__globals__["grok_x_search"]
        provider_globals = search_function.__globals__
        original_open_request = provider_globals["_open_request"]
        try:
            provider_globals["_open_request"] = lambda *_args, **_kwargs: Response()

            function = SimpleNamespace(
                name="grok_x_search",
                arguments=json.dumps(
                    {
                        "query": "Find official OpenAI posts",
                        "allowed_x_handles": ["OpenAI"],
                    }
                ),
            )
            tool_call = SimpleNamespace(id="call-1", function=function)
            messages: list[dict] = []
            agent._execute_tool_calls_sequential(
                SimpleNamespace(tool_calls=[tool_call]), messages, "e2e"
            )
            result = json.loads(messages[-1]["content"])

            assert set(result) == EXPECTED_KEYS, result
            assert result["success"] is True
            assert result["degraded"] is False
            assert result["inline_citations"][0]["url"] == "https://x.com/OpenAI/status/1"
            assert "search_call_detected" not in result
            assert "output_types" not in result
            assert "citation_urls" not in result
        finally:
            provider_globals["_open_request"] = original_open_request


if __name__ == "__main__":
    main()
